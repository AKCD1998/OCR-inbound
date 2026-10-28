"""CLI and exact-source synthetic demo checks; no real documents or model calls."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
import zlib

from ocr_inbound.document_ai.__main__ import load_processor, main, parser
from ocr_inbound.document_ai.core import PrototypeError, PrototypeStore, image_dimensions
from ocr_inbound.document_ai.demo import (
    DEMO_MARKER, WIDTH, HEIGHT, demo_processor, prepare_demo_store,
    sample_pdf, sample_png, seed_demo,
)


class DocumentAICLITests(unittest.TestCase):
    def test_serve_defaults_and_required_reviewer_store(self):
        args=parser().parse_args(['serve','--store','private-demo','--reviewer','qa.person','--demo'])
        self.assertEqual(('127.0.0.1',8877,True,None),(args.host,args.port,args.demo,args.processor))
        for command in [['serve'],['serve','--store','x'],['serve','--reviewer','qa'],['serve','--store','x','--reviewer','qa']]:
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):parser().parse_args(command)

    def test_no_nonloopback_or_two_processors(self):
        for options in [['--host','0.0.0.0','--demo'],['--demo','--processor','json:loads'],['--demo','--hq-config','private.json']]:
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                parser().parse_args(['serve','--store','x','--reviewer','qa',*options])

    def test_invalid_port_or_empty_identity_rejected_before_store(self):
        for options in [['--port','65536'],['--port','-1'],['--reviewer','  ']]:
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                main(['serve','--store','unused-test-store','--reviewer','qa','--demo',*options])
        self.assertFalse(Path('unused-test-store').exists())

    def test_explicit_processor_import_without_eval(self):
        self.assertEqual({'a':1},load_processor('json:loads')('{"a":1}'))
        for spec in ['json','json:loads()','json:loads;print(1)','../json:loads','json:__name__']:
            with self.assertRaises((ValueError,AttributeError)):load_processor(spec)

    def test_import_failure_returns_explanatory_error(self):
        output=io.StringIO()
        with redirect_stderr(output):
            result=main(['serve','--store','unused-test-store','--reviewer','qa','--processor','nonexistent_document_ai_test_module:read'])
        self.assertEqual(2,result)
        self.assertIn('could not start',output.getvalue())
        self.assertFalse(Path('unused-test-store').exists())

    def test_graceful_cli_closes_server_and_store(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('ocr_inbound.document_ai.__main__.make_server') as server_factory:
                server=server_factory.return_value;server.server_port=8877
                server.serve_forever.side_effect=KeyboardInterrupt
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(0,main(['serve','--store',directory,'--reviewer','qa','--processor','json:loads']))
                server.server_close.assert_called_once()
                self.assertIn('Document final review',output.getvalue())
                self.assertTrue((Path(directory)/'review.sqlite3').is_file())

    def test_hq_profile_injects_transport_without_model_or_callback_call(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('ocr_inbound.document_ai.__main__.make_server') as server_factory,patch('ocr_inbound.document_ai.hq_transport.HQProcessor') as hq:
                server=server_factory.return_value;server.server_port=8877
                server.serve_forever.side_effect=KeyboardInterrupt
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(0,main(['serve','--store',directory,'--reviewer','qa','--hq-config','private-profile.json']))
                hq.assert_called_once_with(Path('private-profile.json'))
                hq.return_value.assert_not_called()
                self.assertIn('HQ transport configured',output.getvalue())


class DocumentAIDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'demo'
        prepare_demo_store(self.root);self.store=PrototypeStore(self.root,processor=demo_processor)

    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def wait_for_results(self):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            documents=self.store.list_documents()
            if documents and all(d['status']!='processing' for d in documents):return documents
            time.sleep(.01)
        self.fail('synthetic background callback did not finish')

    def test_png_crc_pixels_and_pdf_xref_are_real_and_deterministic(self):
        png=sample_png();self.assertEqual((WIDTH,HEIGHT),image_dimensions(png))
        cursor=8;compressed=[]
        while cursor<len(png):
            length=struct.unpack('>I',png[cursor:cursor+4])[0]
            kind=png[cursor+4:cursor+8];payload=png[cursor+8:cursor+8+length]
            crc=struct.unpack('>I',png[cursor+8+length:cursor+12+length])[0]
            self.assertEqual(zlib.crc32(kind+payload)&0xffffffff,crc)
            if kind==b'IDAT':compressed.append(payload)
            cursor+=12+length
        self.assertEqual(HEIGHT*(1+3*WIDTH),len(zlib.decompress(b''.join(compressed))))
        pdf=sample_pdf();self.assertTrue(pdf.startswith(b'%PDF-1.4'))
        xref=int(pdf.split(b'startxref\n')[1].splitlines()[0]);self.assertTrue(pdf[xref:].startswith(b'xref\n'))
        self.assertIn(b'/Count 1',pdf);self.assertEqual(pdf,sample_pdf());self.assertEqual(png,sample_png())

    def test_demo_requires_isolated_store_marker(self):
        self.assertEqual(DEMO_MARKER,(self.root/'.synthetic-demo-store').read_text(encoding='utf-8'))
        prepare_demo_store(self.root)
        real=self.root.parent/'real';real.mkdir();(real/'evidence.txt').write_text('private',encoding='utf-8')
        with self.assertRaises(ValueError):prepare_demo_store(real)
        self.assertEqual('private',(real/'evidence.txt').read_text(encoding='utf-8'))

    def test_seeded_pdf_and_png_have_source_bound_pending_proposals(self):
        seed_demo(self.store,'qa.reviewer');documents=self.wait_for_results()
        self.assertEqual(2,len(documents))
        for document in documents:
            self.assertEqual('review',document['status'])
            self.assertFalse(document['summary']['exportable'])
            self.assertEqual((2,2),(len(document['rows']),document['summary']['pending']))
            self.assertEqual('demo-page-1',document['pages'][0]['id'])
            for row in document['rows']:
                self.assertEqual(document['source_sha256'],row['source_sha256'])
                self.assertEqual('pending',row['decision'])
                self.assertNotIn('receiving_date',row['fields'])
            second=document['rows'][1]['fields']['product_code']
            self.assertEqual('DEMO-002',second['raw']);self.assertIsNone(second['normalized'])
            self.assertEqual('DEMO-002',second['catalogue'])
            events=self.store.history(document['id'])
            details=next(e['payload']['processing'] for e in events if e['event_type']=='proposals_prepared')
            self.assertFalse(details['recognition_performed']);self.assertEqual(0,details['model_calls'])
        seed_demo(self.store,'qa.reviewer')
        self.assertEqual(2,len(self.store.list_documents()))

    def test_demo_rejects_other_documents_instead_of_reusing_fixture_answers(self):
        self.store.ingest_source('not-a-fixture.pdf',b'%PDF-1.4\n% unrelated synthetic test','application/pdf','qa')
        document=self.wait_for_results()[0]
        self.assertEqual('failed',document['status']);self.assertEqual([],document['rows'])
        self.assertIn('HQ',document['error'])
        source=self.root/'changed.png';source.write_bytes(sample_png()+b'tamper')
        with self.assertRaises(ValueError):
            demo_processor({'source_path':str(source),'source_sha256':hashlib.sha256(sample_png()).hexdigest(),'id':'x'})

    def test_full_demo_final_review_then_completeness_export(self):
        seed_demo(self.store,'qa');document=self.wait_for_results()[0];identity=document['id']
        with self.assertRaises(PrototypeError):
            self.store.review_row(identity,'demo-row-2','approve',{},'checked','qa',document['revision'])
        document=self.store.review_row(identity,'demo-row-1','approve',{},'checked synthetic page','qa',document['revision'])
        document=self.store.review_row(identity,'demo-row-2','correct',{'product_code':'DEMO-002'},'confirmed from synthetic page','qa',document['revision'])
        with self.assertRaises(PrototypeError):
            self.store.export_document(identity,'qa',False,document['revision'],document['source_sha256'])
        export=self.store.export_document(identity,'qa',True,document['revision'],document['source_sha256'])
        self.assertFalse(export['posting_authorized']);self.assertFalse(export['physical_receipt_automatically_inferred'])
        self.assertEqual('DEMO-002',export['rows'][1]['fields']['product_code']['raw'])
        self.assertEqual('DEMO-002',export['rows'][1]['fields']['product_code']['final'])
        self.assertTrue(self.store.verify_audit())


if __name__=='__main__':unittest.main()
