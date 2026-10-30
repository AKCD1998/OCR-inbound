"""Invented GLM/Tess source cases; no model, images or private data."""
from copy import deepcopy
from pathlib import Path
import sys
import re
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import glm_evidence as glm
from tests.test_document_ai_correction_bridge import fixture,HELPERS,SourceRules
from tests.correction_source_fixture import parse_literal_unit

PIN={'path':'synthetic.json','sha256':'a'*64}
IDENTITY={k:{'path':k+'.json','sha256':c*64} for k,c in zip(('model','backend','prompt','config'),'bcde')}
class Rules(SourceRules):
    COUNT=re.compile(r'^\+?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$')


def data(raw=None):
    page,cache,_=fixture()
    source={'page_number':2,'source_sha256':'a'*64,'source_image':{'path':'NEVER_OPEN.png','sha256':'a'*64},
            'geometry':deepcopy(cache['geometry']),'source_inputs':{k:deepcopy(PIN) for k in ('canonical','cache','native')}}
    request=glm.build_plan([source],PIN,PIN)['requests'][0]
    raw=raw if raw is not None else ('<table><tr><th>Product Description</th><th>QTY</th><th>UOM</th></tr>'
        '<tr><td>Synthetic Product1</td><td>10</td><td>Box</td></tr>'
        '<tr><td>Synthetic Product2</td><td>20</td><td>Box</td></tr></table>')
    response={'choices':[{'message':{'content':raw},'finish_reason':'stop'}],
              'usage':{'prompt_tokens':400,'completion_tokens':120,'total_tokens':520}}
    observation=glm.wrap_response(request,IDENTITY,response,PIN)
    helpers={**HELPERS,'rules':Rules,'glm_identity':IDENTITY,'grammar':SimpleNamespace(parse_literal_unit=parse_literal_unit),
             'row_eligible':lambda row:not HELPERS['rules']._protected(row)}
    return page,cache,request,observation,helpers


class GlmEvidenceTests(unittest.TestCase):
    def test_resource_profiles_are_explicit_bounded_and_default_remains_unchanged(self):
        _,cache,request,_,_=data()
        source={'page_number':3,'source_sha256':'a'*64,'source_image':{'path':'source.png','sha256':'a'*64},
                'geometry':cache['geometry'],'source_inputs':request['source_inputs']}
        plan=glm.build_plan([source],PIN,PIN,resource_profile='tight1024')
        self.assertEqual((1024,512),tuple(plan['requests'][0]['limits'][k] for k in ('context_tokens','maximum_new_tokens')))
        self.assertEqual((2048,1024),tuple(request['limits'][k] for k in ('context_tokens','maximum_new_tokens')))
        for bad in ({**glm.LIMITS,'context_tokens':1024},{**glm.LIMITS,'maximum_long_side':2048}):
            with self.assertRaises(ValueError):glm.validate_limits(bad)
    def test_pre_gate_intake_keeps_empty_and_legacy_header_failed_pages(self):
        _,cache,request,_,_=data()
        pages=[]
        for n in (439,3,21):
            pages.append({'page_number':n,'source_sha256':'a'*64,'source_image':{'path':'source-%d.png'%n,'sha256':'a'*64},
              'geometry':cache['geometry'],'source_inputs':request['source_inputs']})
        plan=glm.build_plan(pages,PIN,PIN)
        self.assertEqual([3,21,439],[r['page_number'] for r in plan['requests']])
        self.assertEqual(['glm-page-0003-table'],plan['canary_request_ids'])
        self.assertTrue(all(r['roi_upright']==[0,0,1000,800] and r['prompt']=='Table Recognition:' for r in plan['requests']))
        self.assertTrue(all(not r['legacy_context_eligibility_required'] for r in plan['requests']))

    def test_exact_raw_html_spans_without_image_boxes_or_confidence(self):
        _,_,request,observation,_=data();result=glm.intake(request,observation,IDENTITY)
        self.assertEqual('COMPLETE',result['status'])
        raw=result['printed_transcription']['raw_text'];cell=result['tables'][0]['rows'][1]['cells'][1]
        self.assertEqual('<td>10</td>',raw[slice(*cell['raw_markup_span'])])
        self.assertIsNone(cell['source_bbox']);self.assertFalse(cell['character_boxes_available'])
        self.assertFalse(result['printed_transcription']['coverage_of_every_printed_character_confirmed'])

    def test_HTML_cells_keep_exact_markup_case_whitespace_and_reject_mismatched_closes(self):
        raw='<TABLE>\n<TR><TD>A &amp; B</TD ></TR></TABLE>'
        _,_,request,observation,_=data(raw)
        result=glm.intake(request,observation,IDENTITY);cell=result['tables'][0]['rows'][0]['cells'][0]
        self.assertEqual('<TD>A &amp; B</TD >',raw[slice(*cell['raw_markup_span'])])
        self.assertEqual('A & B',cell['raw_text'])
        observation['raw_response']['choices'][0]['message']['content']=raw.replace('</TD >','</TH>')
        self.assertEqual('INCOMPLETE',glm.intake(request,observation,IDENTITY)['status'])

    def test_length_context_cap_empty_or_unclosed_html_never_complete(self):
        _,_,request,observation,_=data()
        for mode in ('length','cap','empty','unclosed','no-table'):
            value=deepcopy(observation)
            if mode=='length':value['raw_response']['choices'][0]['finish_reason']='length'
            elif mode=='cap':value['raw_response']['usage']['completion_tokens']=request['limits']['maximum_new_tokens']
            elif mode=='empty':value['raw_response']['choices'][0]['message']['content']=''
            elif mode=='unclosed':value['raw_response']['choices'][0]['message']['content']='<table><tr><td>partial'
            else:value['raw_response']['choices'][0]['message']['content']='plain output'
            with self.subTest(mode=mode):self.assertNotEqual('COMPLETE',glm.intake(request,value,IDENTITY)['status'])

    def test_identity_source_or_selfconfidence_cannot_replace_proof(self):
        _,_,request,observation,_=data()
        for mode in ('identity','request','confidence','business'):
            value=deepcopy(observation)
            if mode=='identity':value['identity']['model']['sha256']='f'*64
            elif mode=='request':value['request']['source_image']['sha256']='f'*64
            elif mode=='confidence':value['model_confidence']=.999
            else:value['business_corrections']=[{'value':'not printed'}]
            with self.subTest(mode=mode),self.assertRaises(ValueError):glm.intake(request,value,IDENTITY)

    def test_backend_errors_explicit_truncation_and_all_token_caps_hold(self):
        _,_,request,observation,_=data()
        for mode in ('top-truncated','choice-truncated','error','choice-error','no-usage','bad-counts','context-cap','bad-message'):
            value=deepcopy(observation);raw=value['raw_response']
            if mode=='top-truncated':raw['truncated']=True
            elif mode=='choice-truncated':raw['choices'][0]['truncated']=True
            elif mode=='error':raw['error']={'message':'partial'}
            elif mode=='choice-error':raw['choices'][0]['error']='interrupted'
            elif mode=='no-usage':raw['usage']=None
            elif mode=='bad-counts':raw['usage']['total_tokens']=521
            elif mode=='context-cap':raw['usage'].update(prompt_tokens=1928,total_tokens=2048)
            else:raw['choices'][0]['message']='malformed backend response'
            with self.subTest(mode=mode):self.assertEqual('INCOMPLETE',glm.intake(request,value,IDENTITY)['status'])

    def test_actual_source_negative_row_and_competing_column_cannot_be_hidden_by_GLM(self):
        for marker in ('SET 2','free goods','grand total','QTY-PRICE'):
            page,cache,_,observation,helpers=data()
            word=deepcopy(cache['working_tokens'][0]);word.update(text=marker,token_id='p:negative')
            word['box']=[500,220,590,240]
            if marker=='QTY-PRICE':word.update(text='Price',box=[532,180,572,200])
            cache['working_tokens'].append(word)
            result=glm.propose(page,cache,observation,helpers,PIN)
            with self.subTest(marker=marker):
                self.assertNotIn((0,'quantity'),[(e['row_index'],e['field']) for e in result['changes']])

    def test_existing_nonempty_fields_have_before_after_and_actual_Tess_geometry(self):
        page,cache,request,observation,helpers=data();before=deepcopy((page,cache,observation))
        result=glm.propose(page,cache,observation,helpers,PIN)
        self.assertEqual(4,len(result['changes']),result['unconfirmed'])
        event=result['changes'][0];self.assertEqual('99',event['before']['raw_value']);self.assertEqual('10',event['candidate']['raw_value'])
        self.assertIsNone(event['candidate']['confidence']);self.assertIsNone(event['candidate']['model_confidence'])
        self.assertEqual([532,221,572,239],event['candidate']['bbox'])
        self.assertEqual(before,(page,cache,observation))
        actual=glm.verify(page,cache,observation,helpers,PIN,event['row_index'],event['field'],event['evidence'])
        self.assertEqual(event['candidate']['bbox'],actual['token']['bbox'])
        self.assertFalse(actual['evidence']['old_context_prerequisite'])

    def test_missing_legacy_headers_does_not_prevent_GLM_proposal(self):
        page,cache,_,observation,helpers=data()
        cache['working_tokens']=[t for t in cache['working_tokens'] if not t['token_id'].startswith('p:h')]
        page['document']['document_type']='unclassified'
        self.assertEqual(4,len(glm.propose(page,cache,observation,helpers,PIN)['changes']))

    def test_low_confidence_or_same_family_or_foreign_geometry_is_not_admitted(self):
        for mode in ('low','family','lot','duplicate-tess','wrong-column'):
            page,cache,_,observation,helpers=data()
            if mode=='low':cache['tesseract_working_tokens'][0]['confidence']=.69
            elif mode=='family':cache['tesseract_working_tokens'][0]['engine']='PADDLE_PRETENDING_TESS'
            elif mode=='lot':page['product_rows'][0]['fields']['lot']['bbox']=[532.1,221,572.1,239]
            elif mode=='duplicate-tess':cache['tesseract_working_tokens'].append({**deepcopy(cache['tesseract_working_tokens'][0]),'token_id':'tesseract:duplicate'})
            else:
                cache['tesseract_working_tokens'][0]['box']=[850,221,890,239]
                cache['tesseract_working_tokens'][0]['original_source_bbox']=[850,221,890,239]
            result=glm.propose(page,cache,observation,helpers,PIN)
            with self.subTest(mode=mode):self.assertNotIn((0,'quantity'),[(e['row_index'],e['field']) for e in result['changes']])

    def test_unmatched_and_duplicate_model_rows_remain_unconfirmed(self):
        for row in ('Unseen Product','Synthetic Product1'):
            page,cache,request,observation,helpers=data()
            raw=observation['raw_response']['choices'][0]['message']['content']
            raw=raw.replace('</table>','<tr><td>'+row+'</td><td>10</td><td>Box</td></tr></table>')
            observation['raw_response']['choices'][0]['message']['content']=raw
            result=glm.propose(page,cache,observation,helpers,PIN)
            with self.subTest(row=row):
                self.assertTrue(result['unconfirmed'])
                self.assertEqual([],result['business_corrections'])
                if row=='Synthetic Product1':self.assertNotIn((0,'quantity'),[(x['row_index'],x['field']) for x in result['changes']])

    def test_tall_or_shared_independent_read_cannot_fill_two_null_neighbour_rows(self):
        for box in ([532,210,572,350],[532,230,572,295]):
            page,cache,_,observation,helpers=data()
            for row in page['product_rows']:row['fields']['quantity']=None
            words=cache['tesseract_working_tokens'];number=deepcopy(words[0])
            number.update(text='10',box=box,original_source_bbox=box)
            cache['tesseract_working_tokens']=[number]+[w for w in words if not re.fullmatch(r'\d+',w['text'])]
            observation['raw_response']['choices'][0]['message']['content']=observation['raw_response']['choices'][0]['message']['content'].replace('<td>20</td>','<td>10</td>')
            result=glm.propose(page,cache,observation,helpers,PIN)
            with self.subTest(box=box):self.assertFalse([x for x in result['changes'] if x['field']=='quantity'])

    def test_unmodeled_dual_source_name_is_negative_barrier_not_a_goods_anchor(self):
        page,cache,_,observation,helpers=data();page['product_rows'][0]['fields']['quantity']=None
        number=cache['tesseract_working_tokens'][0];number['box']=[532,230,572,253];number['original_source_bbox']=number['box']
        p=deepcopy(cache['working_tokens'][0]);p.update(text='Unmodelled Product Extra',token_id='p:unknown-name',box=[200,245,430,265],confidence=.99)
        t=deepcopy(number);t.update(text=p['text'],token_id='tesseract:unknown-name',box=p['box'],original_source_bbox=p['box'],confidence=.99)
        cache['working_tokens'].append(p);cache['tesseract_working_tokens'].append(t)
        result=glm.propose(page,cache,observation,helpers,PIN)
        self.assertNotIn((0,'quantity'),[(x['row_index'],x['field']) for x in result['changes']])
        self.assertEqual(2,len(page['product_rows']))

    def test_explicit_non_receiving_title_or_protected_row_is_not_receiving_approval(self):
        page,cache,_,observation,helpers=data()
        observation['raw_response']['choices'][0]['message']['content']='CREDIT NOTE'+observation['raw_response']['choices'][0]['message']['content']
        self.assertFalse(glm.propose(page,cache,observation,helpers,PIN)['changes'])
        page,cache,_,observation,helpers=data();page['product_rows'][0]['counted_in_receiving']=False
        self.assertNotIn((0,'quantity'),[(x['row_index'],x['field']) for x in glm.propose(page,cache,observation,helpers,PIN)['changes']])


if __name__=='__main__':unittest.main()
