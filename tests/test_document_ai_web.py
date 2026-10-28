"""HTTP contract/security tests with synthetic document facts, no OCR/model calls."""
from __future__ import annotations

import http.client
import hashlib
import json
import select
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

from ocr_inbound.document_ai.web import CLIENT_HEADER, make_server, sniff_source


class DomainError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class FakeStore:
    def __init__(self, root):
        self.root = Path(root)
        self.source = self.root / 'source.pdf'
        self.source.write_bytes(b'%PDF-1.4\nsynthetic test only\n%%EOF')
        self.document = {'id':'doc-1', 'filename':'synthetic.pdf', 'media_type':'application/pdf',
                         'source_sha256':hashlib.sha256(self.source.read_bytes()).hexdigest(),
                         'revision':1, 'status':'review',
                         'pages':[{'id':'page-1', 'number':1, 'width':100, 'height':100,
                                   'media_type':'application/pdf', 'source_asset_id':'source'}],
                         'rows':[{'id':'row-1', 'page_id':'page-1', 'decision':'pending',
                                  'line_kind':'purchase', 'issues':[],
                                  'fields':{'product_code':{'raw':'A', 'normalized':'A',
                                                            'catalogue':'A', 'final':'A',
                                                            'bbox':[1,2,20,10], 'bbox_frame':'original_image'}}}]}
        self.calls = []

    def list_documents(self):
        self.calls.append(('list',))
        return [self.document]

    def get_document(self, document_id):
        if document_id != 'doc-1':
            raise DomainError('NOT_FOUND', 'ไม่พบเอกสาร', 404)
        self.calls.append(('get', document_id))
        return self.document

    def ingest_source(self, filename, content, media_type, reviewer):
        self.calls.append(('ingest', filename, content, media_type, reviewer))
        return self.document

    def review_row(self, document_id, row_id, decision, corrections, note, reviewer, expected_revision):
        self.calls.append(('review', document_id, row_id, decision, corrections, note, reviewer, expected_revision))
        if expected_revision != self.document['revision']:
            raise DomainError('REVISION_CONFLICT', 'มีผลตรวจใหม่ กรุณาเปิดข้อมูลล่าสุด', 409)
        if document_id != 'doc-1' or row_id != 'row-1':
            raise DomainError('NOT_FOUND', 'ไม่พบรายการ', 404)
        row = self.document['rows'][0]
        row['decision'] = {'approve':'approved','correct':'corrected','hold':'held'}[decision]
        row['note'] = note
        for key, value in corrections.items():
            row['fields'][key]['final'] = value
        self.document['revision'] += 1
        return self.document

    def history(self, document_id):
        self.calls.append(('history', document_id))
        return [{'action':'ingested', 'reviewer':'test.reviewer', 'created_at':'2026-10-28T00:00:00Z'}]

    def export_document(self, document_id, reviewer, completeness_confirmed=False, expected_revision=None, source_sha256=None):
        self.calls.append(('export', document_id, reviewer, completeness_confirmed, expected_revision, source_sha256))
        if expected_revision != self.document['revision']:
            raise DomainError('REVISION_CONFLICT','revision',409)
        if source_sha256 != self.document['source_sha256']:
            raise DomainError('SOURCE_BINDING','source',409)
        if self.document['rows'][0]['decision'] not in {'approved', 'corrected'}:
            raise DomainError('UNRESOLVED_ROWS', 'ยังมีรายการที่ไม่ได้ยืนยัน', 409)
        return {'contract':'document-ai-erp-handoff.v1', 'human_reviewed':True,
                'posting_authorized':False, 'live_erp_writes':False, 'rows':self.document['rows']}

    def add_review_row(self, document_id, fields, note, reviewer, expected_revision, page_id):
        self.calls.append(('add', document_id, fields, note, reviewer, expected_revision, page_id))
        return self.document

    def get_asset(self, document_id, asset_id):
        self.calls.append(('asset', document_id, asset_id))
        if document_id != 'doc-1' or asset_id != 'source':
            raise DomainError('NOT_FOUND', 'ไม่พบหลักฐาน', 404)
        return self.source, 'application/pdf'


class DocumentAIWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FakeStore(self.temp.name)
        self.server = make_server(self.store, port=0, reviewer='test.reviewer', max_upload_bytes=128)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.origin = f'http://127.0.0.1:{self.port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None, *, client=True):
        prepared = dict(headers or {})
        if method == 'POST' and client:
            prepared.setdefault('X-Document-AI-Client', CLIENT_HEADER)
        if isinstance(body, dict):
            body = json.dumps(body).encode('utf-8')
            prepared.setdefault('Content-Type', 'application/json')
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=prepared)
            reply = connection.getresponse()
            payload = reply.read()
            return reply.status, dict(reply.getheaders()), payload
        finally:
            connection.close()

    def review(self, decision='approve', **overrides):
        value = {'decision':decision, 'corrections':{}, 'note':'checked synthetic evidence', 'expected_revision':1}
        value.update(overrides)
        return self.request('POST', '/api/documents/doc-1/rows/row-1/review', value)

    def export_body(self, **overrides):
        return {'completeness_confirmed':True,'expected_revision':self.store.document['revision'],
                'source_sha256':self.store.document['source_sha256'],**overrides}

    def test_root_serves_local_static_with_no_inline_script_or_remote_dependencies(self):
        status, headers, body = self.request('GET', '/')
        self.assertEqual(200, status)
        self.assertIn('ตรวจครั้งสุดท้าย'.encode(), body)
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertNotIn(b'https://', body)
        self.assertIn(b'<script src="/static/app.js" defer>', body)

    def test_static_only_exposes_allowlisted_assets(self):
        for name in ['app.js', 'app.css']:
            self.assertEqual(200, self.request('GET', '/static/' + name)[0])
        self.assertEqual(404, self.request('GET', '/static/../../../AGENTS.md')[0])
        self.assertEqual(404, self.request('GET', '/static/web.py')[0])

    def test_config_named_reviewer_and_no_live_write_flag(self):
        status, _, body = self.request('GET', '/api/config')
        value = json.loads(body)
        self.assertEqual(200, status)
        self.assertEqual('test.reviewer', value['reviewer'])
        self.assertFalse(value['live_erp_writes'])
        self.assertEqual(128, value['max_upload_bytes'])

    def test_lists_and_gets_store_documents_without_reinterpreting_rows(self):
        self.assertEqual([self.store.document], json.loads(self.request('GET', '/api/documents')[2])['documents'])
        self.assertEqual(self.store.document, json.loads(self.request('GET', '/api/documents/doc-1')[2]))

    def test_missing_document_preserves_domain_not_found(self):
        status, _, body = self.request('GET', '/api/documents/missing')
        self.assertEqual(404, status)
        self.assertEqual('NOT_FOUND', json.loads(body)['error']['code'])

    def test_host_rebinding_is_denied(self):
        self.assertEqual(403, self.request('GET', '/', headers={'Host':f'evil.invalid:{self.port}'})[0])
        self.assertEqual(403, self.request('GET', '/', headers={'Host':'127.0.0.1:1'})[0])
        self.assertEqual(403, self.request('GET', '/', headers={'Host':f'127.0.0.1:{self.port}/bad'})[0])

    def test_cross_origin_and_null_origin_denied_before_store_mutation(self):
        for origin in ['https://example.com', 'null', f'http://localhost:{self.port}', self.origin+'/bad']:
            self.assertEqual(403, self.request('POST', '/api/documents?filename=a.pdf', b'%PDF-1.4', {'Origin':origin})[0])
        self.assertFalse(any(c[0] == 'ingest' for c in self.store.calls))

    def test_browser_cross_site_get_is_denied(self):
        self.assertEqual(403, self.request('GET', '/api/documents', headers={'Sec-Fetch-Site':'cross-site'})[0])

    def test_mutation_requires_non_simple_client_header(self):
        status, _, _ = self.request('POST', '/api/documents?filename=a.pdf', b'%PDF-1.4', client=False)
        self.assertEqual(403, status)
        self.assertFalse(self.store.calls)

    def test_upload_accepts_passive_pdf_and_uses_sniffed_mime(self):
        pdf = b'%PDF-1.4\nsynthetic\n%%EOF'
        status, _, _ = self.request('POST', '/api/documents?filename='+quote('ใบรับ.pdf'), pdf,
                                    {'Origin':self.origin, 'Content-Type':'text/html'})
        self.assertEqual(202, status)
        self.assertEqual(('ingest','ใบรับ.pdf',pdf,'application/pdf','test.reviewer'), self.store.calls[-1])

    def test_upload_accepts_png_and_jpeg_magic(self):
        for name, data, media in [('a.png',b'\x89PNG\r\n\x1a\n123','image/png'),('b.jpg',b'\xff\xd8\xff123','image/jpeg')]:
            self.assertEqual(202, self.request('POST','/api/documents?filename='+name,data)[0])
            self.assertEqual(media,self.store.calls[-1][3])

    def test_html_svg_and_extension_disguise_are_rejected(self):
        for data in [b'<html>x</html>',b'<svg onload="x"/>',b'not a PDF',b'']:
            self.assertEqual(415,self.request('POST','/api/documents?filename=a.pdf',data)[0])
        self.assertFalse(self.store.calls)

    def test_upload_size_is_bounded_before_store(self):
        self.assertEqual(413,self.request('POST','/api/documents?filename=a.pdf',b'%PDF-'+b'x'*128)[0])
        self.assertFalse(self.store.calls)

    def test_filename_paths_and_multiple_names_rejected(self):
        for path in ['/api/documents?filename=..%2Fa.pdf','/api/documents?filename=C%3A%5Ca.pdf',
                     '/api/documents?filename=..','/api/documents?filename=a.pdf&filename=b.pdf',
                     '/api/documents']:
            self.assertEqual(400,self.request('POST',path,b'%PDF-1.4')[0])
        self.assertFalse(self.store.calls)

    def test_invalid_filename_waits_for_bounded_upload_then_returns_complete_json(self):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        content=b'%PDF-1.4\nsynthetic'
        try:
            connection.putrequest('POST','/api/documents?filename=..%2Fa.pdf')
            connection.putheader('X-Document-AI-Client',CLIENT_HEADER)
            connection.putheader('Content-Length',str(len(content)))
            connection.endheaders()
            connection.send(content[:4])
            # A semantic filename error must not close the socket while the
            # admitted body is still arriving. No retry conceals an early reset.
            self.assertFalse(select.select([connection.sock],[],[],.2)[0])
            connection.send(content[4:])
            response=connection.getresponse()
            self.assertEqual(400,response.status)
            self.assertEqual('close',response.getheader('Connection'))
            self.assertEqual('INVALID_FILENAME',json.loads(response.read())['error']['code'])
            self.assertFalse(self.store.calls)
            # The client knows closure is intentional and can issue its next
            # explicit request without reusing a dead HTTP/1.1 socket.
            connection.request('GET','/api/config')
            response=connection.getresponse()
            self.assertEqual(200,response.status)
            self.assertEqual('test.reviewer',json.loads(response.read())['reviewer'])
        finally:connection.close()

    def test_named_review_reaches_core_with_revision_and_raw_corrections(self):
        status, _, body = self.review('correct',corrections={'product_code':'00007'})
        self.assertEqual(200,status)
        call=self.store.calls[-1]
        self.assertEqual(('review','doc-1','row-1','correct',{'product_code':'00007'},'checked synthetic evidence','test.reviewer',1),call)
        self.assertEqual('00007',json.loads(body)['rows'][0]['fields']['product_code']['final'])
        self.assertEqual('A',json.loads(body)['rows'][0]['fields']['product_code']['raw'])

    def test_revision_conflict_remains_409(self):
        status,_,body=self.review(expected_revision=0)
        self.assertEqual(409,status)
        self.assertEqual('REVISION_CONFLICT',json.loads(body)['error']['code'])

    def test_invalid_reviews_are_not_forwarded(self):
        variants=[{'decision':'auto-approve'},{'corrections':[]},{'note':4},
                  {'expected_revision':True},{'expected_revision':-1}]
        for overrides in variants:
            self.assertEqual(400,self.review(**overrides)[0])
        self.assertFalse(self.store.calls)

    def test_json_mime_shape_and_nonfinite_values_rejected(self):
        url='/api/documents/doc-1/rows/row-1/review'
        for body in [b'{bad',b'[]',b'{"expected_revision":NaN}']:
            self.assertEqual(400,self.request('POST',url,body,{'Content-Type':'application/json'})[0])
        self.assertEqual(415,self.request('POST',url,b'{}',{'Content-Type':'text/plain'})[0])

    def test_asset_opaque_ids_and_passive_content_type(self):
        status,headers,body=self.request('GET','/api/documents/doc-1/assets/source')
        self.assertEqual(200,status)
        self.assertEqual('application/pdf',headers['Content-Type'])
        self.assertEqual('same-origin',headers['Cross-Origin-Resource-Policy'])
        self.assertIn("frame-ancestors 'self'",headers['Content-Security-Policy'])
        self.assertEqual(self.store.source.read_bytes(),body)
        self.assertEqual(400,self.request('GET','/api/documents/doc-1/assets/..%2Fsource')[0])
        self.assertEqual(404,self.request('GET','/api/documents/doc-1/assets/unknown')[0])

    def test_asset_html_is_not_rendered_even_if_store_mislabels_it(self):
        self.store.get_asset=lambda *_args:(self.store.source,'text/html')
        self.assertEqual(415,self.request('GET','/api/documents/doc-1/assets/source')[0])

    def test_history_is_read_only_and_comes_from_store(self):
        status,_,body=self.request('GET','/api/documents/doc-1/history')
        self.assertEqual(200,status)
        self.assertEqual('ingested',json.loads(body)['events'][0]['action'])

    def test_export_cannot_bypass_unresolved_core_gate(self):
        status,_,body=self.request('POST','/api/documents/doc-1/export',self.export_body())
        self.assertEqual(409,status)
        self.assertEqual('UNRESOLVED_ROWS',json.loads(body)['error']['code'])

    def test_reviewed_export_retains_no_posting_authority(self):
        self.assertEqual(200,self.review()[0])
        status,headers,body=self.request('POST','/api/documents/doc-1/export',self.export_body())
        self.assertEqual(200,status)
        self.assertIn('attachment;',headers['Content-Disposition'])
        value=json.loads(body)
        self.assertTrue(value['human_reviewed'])
        self.assertFalse(value['posting_authorized'])
        self.assertFalse(value['live_erp_writes'])

    def test_export_requires_explicit_boolean_completeness_attestation(self):
        for value in [{},{'completeness_confirmed':False},{'completeness_confirmed':1},{'completeness_confirmed':'true'}]:
            status,_,body=self.request('POST','/api/documents/doc-1/export',value)
            self.assertEqual(400,status)
            self.assertEqual('COMPLETENESS_REQUIRED',json.loads(body)['error']['code'])
        self.assertFalse(any(c[0]=='export' for c in self.store.calls))

    def test_missing_row_requires_page_fields_note_and_revision(self):
        value={'fields':{'product_code':'0008','quantity':'3','unit':'box'},'note':'source row 8','page_id':'page-1','expected_revision':1}
        status,_,_=self.request('POST','/api/documents/doc-1/rows',value)
        self.assertEqual(201,status)
        self.assertEqual(('add','doc-1',value['fields'],'source row 8','test.reviewer',1,'page-1'),self.store.calls[-1])
        for bad in [{'note':''},{'fields':[]},{'page_id':'../x'},{'expected_revision':True}]:
            payload={**value,**bad}
            self.assertEqual(400,self.request('POST','/api/documents/doc-1/rows',payload)[0])

    def test_export_attestation_is_bound_to_displayed_revision_and_source(self):
        self.assertEqual(200,self.review()[0])
        self.assertEqual(400,self.request('POST','/api/documents/doc-1/export',{'completeness_confirmed':True})[0])
        self.assertEqual(409,self.request('POST','/api/documents/doc-1/export',self.export_body(expected_revision=1))[0])
        self.assertEqual(409,self.request('POST','/api/documents/doc-1/export',self.export_body(source_sha256='0'*64))[0])

    def test_non_loopback_bind_and_anonymous_reviewer_are_rejected(self):
        with self.assertRaises(ValueError):
            make_server(self.store,host='0.0.0.0',port=0,reviewer='test.reviewer')
        with self.assertRaises(ValueError):
            make_server(self.store,port=0,reviewer=' ')


if __name__ == '__main__':
    unittest.main()
