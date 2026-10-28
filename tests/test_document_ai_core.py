"""Real store/HTTP boundary tests using generated synthetic PNGs only."""
from __future__ import annotations

import copy
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import threading
import unittest
import zlib

from ocr_inbound.document_ai.core import PrototypeError, PrototypeStore
from ocr_inbound.document_ai.web import CLIENT_HEADER, make_server


def png(width=120, height=180):
    def chunk(kind, content):
        return struct.pack('>I',len(content))+kind+content+struct.pack('>I',zlib.crc32(kind+content)&0xffffffff)
    pixels=(b'\x00'+b'\xf8\xfa\xff'*width)*height
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')


class DocumentAICoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.store=PrototypeStore(self.root/'store')
        self.image=png()
        self.image_path=self.root/'rendered'/'page.png'
        self.image_path.parent.mkdir()
        self.image_path.write_bytes(self.image)
        self.doc=self.store.ingest_source('synthetic.png',self.image,'image/png','qa.reviewer')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def result(self):
        return {'contract':'document-ai-proposals.v1','document_id':self.doc['id'],
                'source_sha256':self.doc['source_sha256'],'artifacts_root':str(self.image_path.parent),
                'pages':[{'id':'original-page-1','number':1,'width':120,'height':180,
                          'image_path':str(self.image_path),'sha256':hashlib.sha256(self.image).hexdigest()}],
                'rows':[{'id':'r-1','page_id':'original-page-1','line_kind':'purchase','issues':[],
                         'fields':{'product_code':{'raw':'TEST-001','normalized':'TEST-001','catalogue':'TEST-001','bbox':[5,5,70,20],'bbox_frame':'original_image'},
                                   'quantity':{'raw':'2','normalized':'2','bbox':[75,5,90,20],'bbox_frame':'original_image'},
                                   'unit':{'raw':'box','normalized':'box','bbox':[90,5,115,20],'bbox_frame':'original_image'},
                                   'invoice_date':{'raw':'2026-10-28','normalized':'2026-10-28'}}}]}

    def prepare(self):
        self.doc=self.store.install_result(self.doc['id'],self.result())
        return self.doc

    def review(self,decision='approve',corrections=None,note='checked synthetic source'):
        current=self.store.get_document(self.doc['id'])
        self.doc=self.store.review_row(self.doc['id'],'r-1',decision,corrections or {},note,'qa.reviewer',current['revision'])
        return self.doc

    def export(self,**overrides):
        current=self.store.get_document(self.doc['id'])
        kwargs={'reviewer':'qa.reviewer','completeness_confirmed':True,
                'expected_revision':current['revision'],'source_sha256':current['source_sha256'],**overrides}
        return self.store.export_document(self.doc['id'],**kwargs)

    def test_original_sha_mime_copy_and_duplicate_intake(self):
        source,mime=self.store.get_asset(self.doc['id'],'source')
        self.assertEqual('image/png',mime)
        self.assertEqual(self.image,source.read_bytes())
        self.assertEqual(hashlib.sha256(self.image).hexdigest(),self.doc['source_sha256'])
        repeat=self.store.ingest_source('different-name.png',self.image,'image/png','other.reviewer')
        self.assertEqual(self.doc['id'],repeat['id'])
        self.assertEqual(1,len(self.store.list_documents()))
        self.assertEqual(1,len(self.store.history(self.doc['id'])))

    def test_source_and_document_result_bindings_are_required(self):
        for key,value in [('source_sha256','0'*64),('document_id','different-doc')]:
            result=self.result();result[key]=value
            with self.assertRaises(PrototypeError):self.store.install_result(self.doc['id'],result)
        self.assertEqual([],self.store.get_document(self.doc['id'])['rows'])

    def test_page_asset_ids_original_frame_and_idempotent_result(self):
        first=self.prepare()
        self.assertEqual('original-page-1',first['pages'][0]['id'])
        self.assertEqual(120,first['pages'][0]['width'])
        self.assertEqual('original_image',first['rows'][0]['fields']['quantity']['bbox_frame'])
        repeat=self.store.install_result(self.doc['id'],self.result())
        self.assertEqual(first['revision'],repeat['revision'])
        path,mime=self.store.get_asset(self.doc['id'],first['pages'][0]['image_asset_id'])
        self.assertEqual(self.image,path.read_bytes());self.assertEqual('image/png',mime)
        result=self.result();result['rows'][0]['fields']['quantity']['normalized']='3'
        with self.assertRaisesRegex(PrototypeError,'ตรึง'):self.store.install_result(self.doc['id'],result)

    def test_zero_row_page_id_is_preserved_without_guessing(self):
        result=self.result();result['rows']=[]
        doc=self.store.install_result(self.doc['id'],result)
        self.assertEqual('original-page-1',doc['pages'][0]['id'])

    def test_proposals_cannot_import_approval_or_override_normalized_final(self):
        result=self.result();row=result['rows'][0]
        row['decision']='approved';row['fields']['quantity']['final']='999'
        doc=self.store.install_result(self.doc['id'],result)
        self.assertEqual('pending',doc['rows'][0]['decision'])
        self.assertEqual('2',doc['rows'][0]['fields']['quantity']['final'])
        self.assertFalse(doc['summary']['exportable'])

    def test_source_bound_human_correction_keeps_raw_and_dates_distinct(self):
        self.prepare()
        doc=self.review('correct',{'quantity':{'value':'3','evidence_ids':['source']},'receiving_date':'2026-10-29'})
        row=doc['rows'][0]
        self.assertEqual('corrected',row['decision'])
        self.assertEqual('2',row['fields']['quantity']['raw'])
        self.assertEqual('2',row['fields']['quantity']['normalized'])
        self.assertEqual('3',row['fields']['quantity']['final'])
        self.assertEqual('human_attestation',row['fields']['quantity']['final_authority'])
        self.assertEqual('2026-10-28',row['fields']['invoice_date']['final'])
        self.assertEqual('2026-10-29',row['fields']['receiving_date']['final'])

    def test_required_fields_and_invalid_quantity_do_not_approve(self):
        self.prepare()
        for corrections in [{'product_code':None},{'unit':''},{'quantity':'not-number'},{'quantity':'0'},{'quantity':'-2'},{'quantity':'NaN'}]:
            with self.assertRaises(PrototypeError):self.review('correct',corrections)
        row=self.store.get_document(self.doc['id'])['rows'][0]
        self.assertEqual('pending',row['decision'])
        self.assertEqual('2',row['fields']['quantity']['final'])

    def test_stale_review_revision_is_rejected(self):
        prepared=self.prepare();self.review()
        with self.assertRaises(PrototypeError) as raised:
            self.store.review_row(self.doc['id'],'r-1','hold',{},'stale','qa.reviewer',prepared['revision'])
        self.assertEqual('REVISION_CONFLICT',raised.exception.code)

    def test_context_only_document_cannot_be_exported_as_goods_handoff(self):
        result=self.result();result['rows'][0]['line_kind']='context';result['rows'][0]['fields']={}
        self.doc=self.store.install_result(self.doc['id'],result)
        # Rejecting at approval or at export is safe; a header-only payload must
        # never become an ERP goods handoff merely because its one row was read.
        with self.assertRaises(PrototypeError):
            self.review('approve');self.export()
        self.assertFalse(any(e['event_type']=='reviewed_document_exported' for e in self.store.history(self.doc['id'])))

    def test_code_unit_and_quantity_reject_booleans_and_wrong_identity_types(self):
        self.prepare()
        for corrections in [{'product_code':True},{'product_code':42},{'product_code':'   '},
                            {'unit':False},{'unit':5},{'unit':'   '},{'quantity':True},{'quantity':False}]:
            with self.subTest(corrections=corrections):
                with self.assertRaises(PrototypeError):self.review('correct',corrections)
        self.assertEqual('pending',self.store.get_document(self.doc['id'])['rows'][0]['decision'])

    def test_supplied_dates_require_real_iso_calendar_dates(self):
        self.prepare()
        for field in ['invoice_date','receiving_date','receive_date','receipt_date','mfg_date','exp_date','transfer_date']:
            for value in ['2026-02-31','2026-2-03','2026/10/28',20261028]:
                with self.subTest(field=field,value=value):
                    with self.assertRaises(PrototypeError):self.review('correct',{field:value})
        # Unknown dates are still unknown. The gate must not invent one.
        document=self.review('correct',{'exp_date':None,'mfg_date':'2028-02-29'})
        self.assertIsNone(document['rows'][0]['fields']['exp_date']['final'])
        self.assertEqual('2028-02-29',document['rows'][0]['fields']['mfg_date']['final'])

    def test_correction_evidence_must_resolve_to_same_document_assets(self):
        self.prepare()
        for evidence in [['OTHER-DOCUMENT-PAGE-999'],['page-999'],['r-1'],['../page-1'],
                         'source',[None],[7]]:
            with self.subTest(evidence=evidence):
                with self.assertRaises(PrototypeError):
                    self.review('correct',{'quantity':{'value':'3','evidence_ids':evidence}})
        document=self.review('correct',{'quantity':{'value':'3','evidence_ids':['source','page-1']}})
        self.assertEqual(['source','page-1'],document['rows'][0]['fields']['quantity']['evidence_ids'])
        # A plain UI correction is an explicit human attestation to this source.
        document=self.review('correct',{'quantity':'4'})
        self.assertEqual(['source'],document['rows'][0]['fields']['quantity']['evidence_ids'])

    def test_pending_held_and_empty_documents_cannot_export(self):
        self.prepare()
        with self.assertRaises(PrototypeError):self.export()
        self.review('hold',note='not enough source evidence')
        with self.assertRaises(PrototypeError):self.export()
        self.assertEqual('held',self.store.get_document(self.doc['id'])['rows'][0]['decision'])

    def test_exclusion_preserves_raw_proposal_and_does_not_attest_bogus_fields(self):
        result=self.result();result['rows'][0]['fields']['quantity']['normalized']=None
        result['rows'][0]['fields']['invoice_date']={'raw':'footer 2026-02-31','normalized':'2026-02-31'}
        self.doc=self.store.install_result(self.doc['id'],result)
        with closing(sqlite3.connect(self.store.db_path)) as db:
            before=db.execute('SELECT proposal,corrections FROM rows WHERE id=?',('r-1',)).fetchone()
        document=self.store.review_row(self.doc['id'],'r-1','exclude',{},'ยอดรวมท้ายใบ ไม่ใช่สินค้า',
                                      'qa.reviewer',self.doc['revision'],exclusion_confirmed=True)
        row=document['rows'][0]
        self.assertEqual(('excluded','non_product','purchase','excluded_non_product'),
                         (row['decision'],row['line_kind'],row['original_line_kind'],row['disposition']))
        self.assertFalse(row['field_values_attested_correct'])
        self.assertEqual('2',row['fields']['quantity']['raw']);self.assertIsNone(row['fields']['quantity']['final'])
        self.assertEqual('2026-02-31',row['fields']['invoice_date']['final'])
        self.assertEqual((0,1,1,0),(document['summary']['goods_rows'],document['summary']['excluded'],
                                  document['summary']['decided'],document['summary']['approved']))
        with closing(sqlite3.connect(self.store.db_path)) as db:
            after=db.execute('SELECT proposal,corrections FROM rows WHERE id=?',('r-1',)).fetchone()
        self.assertEqual(before,after)
        event=self.store.history(self.doc['id'])[-1]
        self.assertEqual('row_reviewed',event['event_type']);self.assertTrue(event['payload']['exclusion_confirmed'])
        self.assertFalse(event['payload']['printed_OCR_modified']);self.assertTrue(self.store.verify_audit())

    def test_exclusion_requires_real_checkbox_reason_reviewer_and_current_revision(self):
        self.prepare();original_revision=self.doc['revision']
        for confirmation in [False,None,1,'true']:
            with self.subTest(confirmation=confirmation):
                with self.assertRaises(PrototypeError):
                    self.store.review_row(self.doc['id'],'r-1','exclude',{},'not a product','qa',original_revision,
                                          exclusion_confirmed=confirmation)
        for note,actor in [('   ','qa'),(None,'qa'),([],'qa'),('not a product',''),('not a product',None),('not a product',True)]:
            with self.assertRaises(PrototypeError):
                self.store.review_row(self.doc['id'],'r-1','exclude',{},note,actor,original_revision,True)
        with self.assertRaises(PrototypeError) as rejected:
            self.store.review_row(self.doc['id'],'r-1','exclude',{'quantity':'999'},'not a product','qa',original_revision,True)
        self.assertEqual('EXCLUSION_CORRECTIONS',rejected.exception.code)
        self.doc=self.store.review_row(self.doc['id'],'r-1','exclude',{},'not a product','qa',original_revision,True)
        with self.assertRaises(PrototypeError) as stale:
            self.store.review_row(self.doc['id'],'r-1','exclude',{},'old revision','qa',original_revision,True)
        self.assertEqual('REVISION_CONFLICT',stale.exception.code)

    def test_restoring_excluded_goods_revalidates_original_goods_fields(self):
        result=self.result();result['rows'][0]['fields']['quantity']['normalized']=None
        self.doc=self.store.install_result(self.doc['id'],result)
        self.doc=self.store.review_row(self.doc['id'],'r-1','exclude',{},'mistaken footer candidate','qa',self.doc['revision'],True)
        with self.assertRaises(PrototypeError) as missing:self.review('approve')
        self.assertEqual('REQUIRED_FIELDS',missing.exception.code)
        document=self.review('correct',{'quantity':'3'},'source shows an actual product')
        row=document['rows'][0]
        self.assertEqual(('corrected','purchase'),(row['decision'],row['line_kind']))
        self.assertNotIn('disposition',row);self.assertNotIn('original_line_kind',row)
        self.assertEqual(1,document['summary']['approved_goods'])

    def test_exclude_footer_add_missing_goods_and_export_only_confirmed_goods(self):
        result=self.result()
        footer=copy.deepcopy(result['rows'][0]);footer['id']='footer';footer['fields']['quantity']['normalized']=None
        footer['fields']['invoice_date']={'raw':'TOTAL 2026-02-31','normalized':'2026-02-31'}
        context={'id':'context','page_id':'original-page-1','line_kind':'context','fields':{'description':{'raw':'INVOICE HEADER','normalized':'INVOICE HEADER'}}}
        result['rows'] += [footer,context]
        self.doc=self.store.install_result(self.doc['id'],result)
        self.review('approve')
        self.doc=self.store.review_row(self.doc['id'],'footer','exclude',{},'ยอดรวมท้ายใบ ไม่ใช่สินค้า','qa',self.doc['revision'],True)
        self.doc=self.store.review_row(self.doc['id'],'context','approve',{},'checked source header and lines','qa',self.doc['revision'])
        self.doc=self.store.add_review_row(self.doc['id'],{'product_code':'TEST-002','quantity':'4','unit':'box'},
                                            'missed product line below TEST-001','qa',self.doc['revision'],'original-page-1')
        with self.assertRaises(PrototypeError):self.export()
        manual=self.doc['rows'][-1]
        self.doc=self.store.review_row(self.doc['id'],manual['id'],'approve',{},'checked missing source line','qa',self.doc['revision'])
        summary=self.doc['summary']
        self.assertEqual((4,2,1,1,4,2),(summary['rows'],summary['goods_rows'],summary['context_rows'],
                                      summary['excluded'],summary['decided'],summary['approved_goods']))
        bundle=self.export()
        self.assertEqual([self.doc['rows'][0]['id'],manual['id']],[r['id'] for r in bundle['goods_rows']])
        self.assertEqual(['footer'],[r['id'] for r in bundle['excluded_rows']])
        self.assertEqual(['context'],[r['id'] for r in bundle['context_rows']])
        self.assertEqual(4,len(bundle['rows']))
        self.assertEqual('TOTAL 2026-02-31',bundle['excluded_rows'][0]['fields']['invoice_date']['raw'])
        self.assertFalse(bundle['excluded_rows'][0]['field_values_attested_correct'])
        self.assertTrue(self.store.verify_audit());self.assertFalse(bundle['posting_authorized'])

    def test_excluding_every_goods_row_does_not_make_context_exportable(self):
        result=self.result();result['rows'].append({'id':'context','page_id':'original-page-1','line_kind':'context','fields':{}})
        self.doc=self.store.install_result(self.doc['id'],result)
        self.doc=self.store.review_row(self.doc['id'],'r-1','exclude',{},'only a footer','qa',self.doc['revision'],True)
        self.doc=self.store.review_row(self.doc['id'],'context','approve',{},'header checked','qa',self.doc['revision'])
        self.assertEqual((2,0),(self.doc['summary']['decided'],self.doc['summary']['goods_rows']))
        self.assertFalse(self.doc['summary']['exportable'])
        with self.assertRaises(PrototypeError):self.export()

    def test_completeness_requires_explicit_boolean_and_current_source_revision(self):
        self.prepare();self.review()
        for value in [False,None,1,'true']:
            with self.assertRaises(PrototypeError):self.export(completeness_confirmed=value)
        current=self.store.get_document(self.doc['id'])
        with self.assertRaises(PrototypeError):self.export(expected_revision=current['revision']-1)
        with self.assertRaises(PrototypeError):self.export(source_sha256='0'*64)

    def test_export_is_idempotent_traceable_and_not_a_physical_receipt(self):
        self.prepare();self.review()
        first=self.export();events=len(self.store.history(self.doc['id']));second=self.export()
        self.assertEqual(first,second)
        self.assertEqual(events,len(self.store.history(self.doc['id'])))
        self.assertEqual('document-ai-erp-handoff.v1',first['contract'])
        self.assertEqual('reviewed_supplier_document',first['event_type'])
        self.assertFalse(first['posting_authorized'])
        self.assertFalse(first['physical_receipt_automatically_inferred'])
        self.assertTrue(first['human_reviewed'])
        self.assertEqual(first['source_sha256'],first['completeness_attestation']['source_sha256'])
        self.assertEqual(first['document_revision'],first['completeness_attestation']['revision'])
        self.assertTrue(self.store.verify_audit())

    def test_manual_missing_row_has_human_authority_without_fabricated_ocr(self):
        self.prepare()
        document=self.store.add_review_row(self.doc['id'],{'product_code':'TEST-002','quantity':'4','unit':'bottle'},
                                            'Second source line missed by machine','qa.reviewer',self.doc['revision'],'original-page-1')
        self.assertEqual(2,len(document['rows']))
        row=document['rows'][1]
        self.assertEqual('pending',row['decision'])
        self.assertEqual(self.doc['source_sha256'],row['source_sha256'])
        self.assertEqual('original-page-1',row['page_id'])
        for value in row['fields'].values():
            self.assertIsNone(value['raw']);self.assertIsNone(value['normalized']);self.assertIsNone(value['bbox'])
            self.assertEqual('human_attestation',value['final_authority'])
        self.assertEqual('4',row['fields']['quantity']['final'])
        self.assertFalse(document['summary']['exportable'])

    def test_tampered_source_or_page_asset_blocks_export(self):
        self.prepare();self.review()
        page=self.doc['pages'][0]
        path,_=self.store.get_asset(self.doc['id'],page['image_asset_id']);path.write_bytes(self.image+b'changed')
        with self.assertRaises(PrototypeError) as raised:self.export()
        self.assertEqual('ASSET_INTEGRITY',raised.exception.code)

    def test_original_asset_tampering_is_detected(self):
        path,_=self.store.get_asset(self.doc['id'],'source');path.write_bytes(self.image+b'changed')
        with self.assertRaises(PrototypeError) as raised:self.store.get_asset(self.doc['id'],'source')
        self.assertEqual('ASSET_INTEGRITY',raised.exception.code)

    def test_invalid_boxes_are_not_clipped_or_invented(self):
        result=self.result();field=result['rows'][0]['fields']['quantity'];field['bbox']=[-1,2,50,20]
        doc=self.store.install_result(self.doc['id'],result)
        self.assertIsNone(doc['rows'][0]['fields']['quantity']['bbox'])
        self.assertEqual('2',doc['rows'][0]['fields']['quantity']['raw'])

    def test_page_numbers_paths_and_dimensions_cannot_forge_assets(self):
        variants=[{'number':'../../outside'},{'number':True},{'number':0},{'number':-1},{'width':119}, {'height':181}]
        for variant in variants:
            result=self.result();result['pages'][0].update(variant)
            with self.subTest(variant=variant):
                with self.assertRaises(PrototypeError):self.store.install_result(self.doc['id'],result)
        self.assertFalse((self.root/'outside.png').exists())

    def test_duplicate_page_numbers_and_unsafe_row_or_page_ids_rejected(self):
        result=self.result();result['pages'].append({**result['pages'][0],'id':'another-page'})
        with self.assertRaises(PrototypeError):self.store.install_result(self.doc['id'],result)
        for subject in ['page','row']:
            result=self.result()
            if subject=='page':result['pages'][0]['id']='../../p'
            else:result['rows'][0]['id']='../../r'
            with self.subTest(subject=subject):
                with self.assertRaises(PrototypeError):self.store.install_result(self.doc['id'],result)

    def test_audit_chain_detects_modified_history(self):
        self.prepare();self.review();self.export()
        self.assertTrue(self.store.verify_audit())
        with closing(sqlite3.connect(self.store.db_path)) as db:
            with db:db.execute("UPDATE audit SET payload='{}' WHERE sequence=1")
        self.assertFalse(self.store.verify_audit())

    def test_two_store_duplicate_intake_is_idempotent_without_orphan_source(self):
        peer=PrototypeStore(self.store.root);gate=threading.Barrier(2);image=png(121,180)
        try:
            def upload(store):
                gate.wait(timeout=3)
                return store.ingest_source('concurrent-synthetic.png',image,'image/png','qa.reviewer')
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(upload,store) for store in [self.store,peer]]
                results=[f.result(timeout=5) for f in futures]
            self.assertEqual(results[0]['id'],results[1]['id'])
            self.assertEqual(2,len(self.store.list_documents()))
            self.assertEqual(2,len(list((self.store.root/'documents').iterdir())))
            self.assertEqual(1,len(self.store.history(results[0]['id'])))
            self.assertTrue(self.store.verify_audit())
        finally:peer.close()

    def test_two_store_same_revision_allows_one_review_and_one_conflict(self):
        document=self.prepare();peer=PrototypeStore(self.store.root);gate=threading.Barrier(2)
        try:
            def review(store,value):
                gate.wait(timeout=3)
                try:
                    return ('ok',store.review_row(document['id'],'r-1','correct',{'quantity':value},
                                                 'concurrent synthetic review','qa.reviewer',document['revision']))
                except PrototypeError as exc:return ('error',exc.code)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(review,store,value) for store,value in [(self.store,'3'),(peer,'4')]]
                results=[f.result(timeout=5) for f in futures]
            self.assertEqual(['error','ok'],sorted(r[0] for r in results))
            self.assertEqual('REVISION_CONFLICT',next(r[1] for r in results if r[0]=='error'))
            current=self.store.get_document(document['id'])
            self.assertEqual(document['revision']+1,current['revision'])
            self.assertEqual('2',current['rows'][0]['fields']['quantity']['raw'])
            self.assertIn(current['rows'][0]['fields']['quantity']['final'],['3','4'])
            self.assertEqual(1,sum(e['event_type']=='row_reviewed' for e in self.store.history(document['id'])))
            self.assertTrue(self.store.verify_audit())
        finally:peer.close()


class DocumentAIRealHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=PrototypeStore(Path(self.temp.name)/'store')
        self.server=make_server(self.store,port=0,reviewer='qa.reviewer')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
        self.store.close();self.temp.cleanup()

    def call(self,method,path,value=None,content_type='application/json'):
        headers={'X-Document-AI-Client':CLIENT_HEADER,'Content-Type':content_type}
        body=json.dumps(value).encode() if isinstance(value,dict) else value
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            connection.request(method,path,body=body,headers=headers);reply=connection.getresponse();payload=reply.read()
            return reply.status,json.loads(payload) if reply.headers.get_content_type()=='application/json' else payload
        finally:connection.close()

    def test_real_upload_processing_review_and_export_gate(self):
        status,document=self.call('POST','/api/documents?filename=synthetic.png',png(),'image/png')
        self.assertEqual(202,status)
        doc_id=document['id'];image_path=Path(self.temp.name)/'render.png';image_path.write_bytes(png())
        result={'contract':'document-ai-proposals.v1','source_sha256':document['source_sha256'],
                'artifacts_root':str(image_path.parent),'pages':[{'id':'p1','number':1,'width':120,'height':180,'image_path':str(image_path),'sha256':hashlib.sha256(png()).hexdigest()}],
                'rows':[{'id':'r1','page_id':'p1','fields':{k:{'raw':v,'normalized':v} for k,v in {'product_code':'TEST-1','quantity':'2','unit':'box'}.items()}}]}
        current=self.store.install_result(doc_id,result)
        body={'completeness_confirmed':True,'expected_revision':current['revision'],'source_sha256':current['source_sha256']}
        self.assertEqual(409,self.call('POST',f'/api/documents/{doc_id}/export',body)[0])
        status,current=self.call('POST',f'/api/documents/{doc_id}/rows/r1/review',{'decision':'correct','corrections':{'quantity':'3'},'note':'synthetic source checked','expected_revision':current['revision']})
        self.assertEqual(200,status)
        self.assertEqual('2',current['rows'][0]['fields']['quantity']['raw'])
        self.assertEqual('3',current['rows'][0]['fields']['quantity']['final'])
        self.assertEqual(400,self.call('POST',f'/api/documents/{doc_id}/export',{})[0])
        self.assertEqual(409,self.call('POST',f'/api/documents/{doc_id}/export',body)[0])
        body['expected_revision']=current['revision']
        status,bundle=self.call('POST',f'/api/documents/{doc_id}/export',body)
        self.assertEqual(200,status)
        self.assertTrue(bundle['human_reviewed']);self.assertFalse(bundle['posting_authorized'])
        self.assertTrue(self.store.verify_audit())


if __name__=='__main__':unittest.main()
