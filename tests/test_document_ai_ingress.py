"""Synthetic metadata only: no image decoding, reader or model fitting here."""
import unittest
from pathlib import Path
from ocr_inbound.document_ai.hq_ingress import tsv_tokens,adapt_page,merge_retry,needs_retry
from ocr_inbound.document_ai.hq_transport import translate_asset
from ocr_inbound.batch_supplier_extraction import extract_batch_page

HEADER='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'

class IngressTests(unittest.TestCase):
    def test_whole_word_geometry_no_clipping(self):
        tokens,rejected=tsv_tokens(HEADER+'5\t1\t1\t1\t1\t1\t5\t7\t30\t10\t92\tLOT-A\n'+
            '5\t1\t1\t1\t1\t2\t95\t7\t30\t10\t92\tOUTSIDE\n',100,100)
        self.assertEqual(len(tokens),1);self.assertEqual(len(rejected),1)
        self.assertEqual(tokens[0]['text'],'LOT-A')
        self.assertEqual(tokens[0]['box'],[[5,7],[35,7],[35,17],[5,17]])

    def test_real_parser_accepts_machine_tsv_without_other_engines(self):
        tokens,_=tsv_tokens(HEADER+'5\t1\t1\t1\t1\t1\t5\t7\t50\t10\t92\tUNKNOWN\n',100,100)
        parsed=extract_batch_page(1,tokens,(100,100))
        result=adapt_page(parsed,tokens,'p1')
        self.assertEqual(result[0]['line_kind'],'context')
        self.assertIn('UNKNOWN',result[0]['fields']['description']['raw'])
        self.assertTrue(any('ไม่พบแถว' in issue for issue in result[0]['issues']))

    def test_catalogue_sku_is_not_literal_ocr(self):
        class Matcher:
            def match(self,query):
                self.query=query;return {'proposed_code':'TEST-1','candidates':[]}
        m=Matcher();p={'product_rows':[{'fields':{'description':{'raw_value':'Printed name','normalized_value':'Printed name','bbox':[1,2,30,10]},
                  'supplier_code':{'raw_value':'SUP123','normalized_value':'SUP123'}},'review_flags':[]}],
                  'document':{},'review_flags':[]}
        rows=adapt_page(p,[],'p1',m);sku=rows[0]['fields']['product_code']
        self.assertIsNone(sku['raw']);self.assertEqual(sku['catalogue'],'TEST-1')
        self.assertNotIn('company_code',m.query)
        self.assertEqual(m.query['supplier_code'],'SUP123')
        self.assertEqual(rows[0]['fields']['description']['raw'],'Printed name')

    def test_asset_paths_bound_to_exact_job(self):
        self.assertEqual(translate_asset(r'D:\runs\job1\processing\p1.png',r'D:\runs\job1\processing',Path('share')),
                         Path('share')/'p1.png')
        for bad in (r'D:\runs\job2\p1.png',r'D:\runs\job1\processing\..\secret',r'C:\Windows\secret'):
            with self.assertRaises(ValueError):translate_asset(bad,r'D:\runs\job1\processing',Path('share'))

    def test_retry_requires_unique_exact_row_owner_and_preserves_conflicts(self):
        def row(code,qty,unit='BOX'):
            return {'fields':{'supplier_code':{'normalized_value':code},
                'description':{'normalized_value':'SYNTHETIC'},
                'quantity':{'normalized_value':qty} if qty else None,
                'unit':{'normalized_value':unit} if unit else None},'review_flags':[]}
        a={'product_rows':[row('SUP1',None)],'review_flags':[]}
        self.assertTrue(needs_retry(a))
        b={'product_rows':[row('SUP1','2')],'review_flags':[]}
        fixed=merge_retry(a,b)
        self.assertEqual(fixed['product_rows'][0]['fields']['quantity']['normalized_value'],'2')
        self.assertIsNone(a['product_rows'][0]['fields']['quantity'])
        b['product_rows'].append(row('SUP1','9'))
        self.assertIsNone(merge_retry(a,b)['product_rows'][0]['fields']['quantity'])
        original={'product_rows':[row('SUP1','5')],'review_flags':[]}
        conflict=merge_retry(original,{'product_rows':[row('SUP1','2')],'review_flags':[]})
        self.assertEqual(conflict['product_rows'][0]['fields']['quantity']['normalized_value'],'5')
        self.assertIn('two_readings_disagree_quantity',conflict['product_rows'][0]['review_flags'])

if __name__=='__main__':unittest.main()
