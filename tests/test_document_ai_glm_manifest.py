"""Synthetic closed native receipts. No image files, model calls or labels."""
from copy import deepcopy
from pathlib import Path
import base64
import hashlib
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import component_common as c
import glm_evidence as evidence
import glm_read_manifest as manifest


class GlmReadManifest(unittest.TestCase):
    def fixture(self,folder,mode=None):
        def put(name,value):
            path=folder/name;c.save(path,value);return c.pin(path)
        def source(name):
            p=folder/name;p.write_text('# synthetic source only\n',encoding='utf8');return c.pin(p)
        worker=source('native.py');backend=source('backend.py');component=source('evidence.py')
        model=put('model.json',{'decoder':{'path':'FORBIDDEN_MODEL','sha256':'a'*64}})
        binary=put('binary.json',{'server':{'path':'FORBIDDEN_BINARY','sha256':'a'*64}})
        prompt=put('prompt.json',{'prompt':'Table Recognition:'})
        inventory=put('inventory.json',{'files':[{'path':'FORBIDDEN_IMAGE','sha256':'a'*64} for _ in range(484)]})
        panel=put('panel.json',{'contract':'document-ai-correction-pilot-panel.v1','source_inventory':inventory,
                              'pages':[{'page_number':n,'source_sha256':'a'*64} for n in range(3,41)]})
        pages=[{'page_number':n,'source_sha256':'a'*64,'source_image':{'path':'FORBIDDEN_IMAGE','sha256':'a'*64},
                'geometry':{'original_size':[1000,800],'upright_size':[1000,800],'orientation_ccw':0},
                'source_inputs':{k:inventory for k in ('canonical','cache','native')}} for n in range(3,41)]
        plan=evidence.build_plan(pages,panel,inventory,resource_profile='tight1024');plan_pin=put('plan.json',plan)
        recipe={'contract':manifest.RECIPE,'model_binding':model,'backend_binding':binary,'prompt_binding':prompt,
                'source_plan38':plan_pin,'master_source_inventory':inventory,'native_worker':worker,
                'backend_source':backend,'limits':deepcopy(plan['requests'][0]['limits'])}
        request=plan['requests'][0];rid=request['request_id'];native=folder/'native';native.mkdir()
        cfg={'contract':'document-ai-glm-native-config.v1','resource_policy':c.RESOURCES,'optimizer_updates_allowed':False,
             'production_activation':False,'sources':{'evidence':component,'backend':backend},'model_binding':model,
             'backend_binding':binary,'prompt_binding':prompt,'plan':plan_pin,'request_ids':[rid],
             'context_tokens':1024,'max_output_tokens':512}
        if mode=='foreign-model':cfg['model_binding']=inventory
        cfg_pin=put('native-config.json',cfg)
        identity={'model':model,'backend':binary,'prompt':prompt,'config':cfg_pin}
        raw={'choices':[{'message':{'content':'<table><tr><td>Invented</td></tr></table>'},'finish_reason':'stop'}],
             'usage':{'prompt_tokens':100,'completion_tokens':30,'total_tokens':130}}
        if mode=='incomplete-output':raw['choices'][0]['finish_reason']='length'
        raw_pin=put('native/raw.json',raw)
        image_bytes=b'synthetic bytes only; not an image or pixel fixture'
        prepared={'path':str(native/'NEVER_OPEN_PREPARED.png'),'sha256':hashlib.sha256(image_bytes).hexdigest()}
        image={'source':request['source_image'],'prepared':prepared,'source_geometry':request['geometry'],
               'roi_upright':request['roi_upright'],'actual_source_bytes_consumed_sha256':'a'*64,
               'actual_prepared_size':[896,717],'source_context_clipped':False,'EXIF_reinterpreted':False,
               'glyph_or_cell_boxes_invented':False}
        if mode=='foreign-image':image['actual_source_bytes_consumed_sha256']='b'*64
        image_pin=put('native/image-proof.json',image)
        payload={'model':'glm-ocr-isolated','messages':[{'role':'user','content':[{'type':'text','text':'Table Recognition:'},
                  {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image_bytes).decode()}}]}],
                 'temperature':0,'seed':0,'stream':False,'max_tokens':512,'cache_prompt':False}
        if mode=='foreign-http-bytes':payload['messages'][0]['content'][1]['image_url']['url']='data:image/png;base64,Zm9yZWlnbg=='
        if mode=='extra-answer-hints':payload['messages'][0]['content'].append({'type':'text','text':'synthetic forbidden answer hint'})
        http_pin=put('native/http.json',payload)
        observation=evidence.wrap_response(request,identity,raw,raw_pin)
        observation['native_input_proof']={'prepared_image':prepared,'image_proof':image_pin,'actual_HTTP_request':http_pin,'plan':plan_pin}
        if mode=='raw-object-mismatch':observation['raw_response']={**raw,'modified':True}
        obs_pin=put('native/observation.json',observation)
        generation=put('native/generation.json',{'generation_complete':mode!='incomplete-output'})
        structure=put('native/structure.json',{'status':'INCOMPLETE' if mode=='incomplete-output' else 'COMPLETE'})
        result={'request_id':rid,'page_number':3,'observation':obs_pin,'raw_response':raw_pin,
                'generation':generation,'structure':structure,'printed_content_coverage_verified':False}
        summary={'contract':'document-ai-glm-native-batch.v1','status':'EXECUTION_FINISHED','component':'glm-ocr',
                 'failure':None,'server_closed':True,'executed':True,'worker':worker,'config':cfg_pin,
                 'plan':plan_pin,'identity':identity,'assistant_image_reads':0,'optimizer_updates':0,
                 'baseline_cache_modified':False,'production_activation':False,'request_ids':[rid],
                 'requests_prepared':1,'requests_started':1,'responses_returned':1,'completed_record_count':1,'request_results':[result]}
        if mode=='failed-native':summary['status']='FAILED'
        summary_pin=put('native/SUMMARY.json',summary)
        serial=put('serial.json',{'source':{'path':'original-serial.py','sha256':manifest.SERIAL},'resource_policy':c.RESOURCES})
        resource={'actual_exit_code':0,'failure':None,'stop_reason':None,'cleanup':{'confirmed_all_known_owned_exited':True},
                  'logs_finalized_after_owned_cleanup':True,'peak_owned_process_tree_RSS_bytes':1000,'minimum_free_RAM_bytes':2*1024**3,
                  'child_started':True,'worker_optimizer_updates_permission':False,'worker_summary':summary_pin,
                  'actual_argv':['python',worker['path'],'--config',cfg_pin['path'],'--config-sha256',cfg_pin['sha256'],'--output',str(native)]}
        if mode=='failed-resource':resource['actual_exit_code']=15
        closed=put('closed.json',{'status':'COMPLETE','failure':None,'shared_lock_released_after_owned_closure':True,
               'cleanup':{'confirmed_all_known_owned_exited':True},'config':serial,'resources':[resource]})
        entry={'request_id':rid,'observation':obs_pin,'summary':summary_pin,'closed_source':closed}
        rows=[entry] if mode!='duplicate' else [entry,deepcopy(entry)]
        record=put('reads.json',{'contract':manifest.MANIFEST,'recipe':recipe,'request_results':rows})
        return recipe,component,record,panel,observation

    def test_real_receipt_chain_loads_without_following_any_image_model_or_binary_path(self):
        with tempfile.TemporaryDirectory() as d:
            recipe,component,record,panel,_=self.fixture(Path(d).resolve())
            paths=[]
            def check(p):
                paths.append(p['path']);self.assertNotIn('FORBIDDEN',p['path']);self.assertNotIn('NEVER_OPEN',p['path'])
                return c.checked(p)
            loaded=manifest.load_reads(recipe,component,record,{3},check,panel)
            self.assertEqual({3},set(loaded['records']));self.assertEqual(0,loaded['parser_model_calls'])
            self.assertTrue(manifest.continuation(loaded['request_records'],loaded['request_records']))

    def test_each_resealed_wrong_source_closure_raw_or_prepared_payload_is_refused(self):
        for mode in ('foreign-model','foreign-image','foreign-http-bytes','extra-answer-hints','raw-object-mismatch','failed-native','failed-resource','duplicate'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                recipe,component,record,panel,_=self.fixture(Path(d).resolve(),mode)
                with self.assertRaises(ValueError):manifest.load_reads(recipe,component,record,{3},panel_pin=panel)

    def test_valid_native_but_truncated_read_stays_available_for_incomplete_audit(self):
        with tempfile.TemporaryDirectory() as d:
            recipe,component,record,panel,obs=self.fixture(Path(d).resolve(),'incomplete-output')
            loaded=manifest.load_reads(recipe,component,record,{3},panel_pin=panel)
            self.assertEqual('INCOMPLETE',evidence.intake(obs['request'],obs,loaded['records'][3]['identity'])['status'])

    def test_scope_expansion_retains_original_request_records_verbatim(self):
        previous={'3':{'observation':{'path':'original','sha256':'a'*64}}}
        self.assertTrue(manifest.continuation(previous,{**previous,'7':{'observation':{'path':'new','sha256':'b'*64}}}))
        for bad in ({},{'3':{'observation':{'path':'reread','sha256':'a'*64}}}):
            with self.assertRaises(ValueError):manifest.continuation(previous,bad)

if __name__=='__main__':unittest.main()
