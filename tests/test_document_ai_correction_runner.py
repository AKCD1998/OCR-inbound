"""Correction-arm contracts and synthetic writer path; no document/model calls."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

CODE=Path(__file__).resolve().parents[1]/'experiments/document_ai'
sys.path.insert(0,str(CODE))
import component_common as c
import correction_runner as runner


class CorrectionRunner(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();self.counter=0
    def put(self,value):
        self.counter+=1;p=self.root/(str(self.counter)+'.json');c.save(p,value);return c.pin(p)

    def test_runtime_panel_has_source_ids_only_and_no_answer_leakage(self):
        sources={n:{'sha256':str(n).zfill(64)} for n in range(1,485)}
        panel={'contract':'document-ai-correction-pilot-panel.v1','source_inventory':self.put({}),
          'pages':[{'page_number':n,'source_sha256':sources[n]['sha256']} for n in range(1,21)]}
        self.assertEqual(set(range(1,21)),set(runner.panel_pages(panel,sources)))
        extended={**panel,'pages':[{'page_number':n,'source_sha256':sources[n]['sha256']} for n in range(1,65)]}
        self.assertEqual(set(range(1,65)),set(runner.panel_pages(extended,sources)))
        for scenario in ('expected','extra','duplicate','unbound','bool','short','too-long'):
            v=deepcopy(panel)
            if scenario=='expected':v['expected_values']={'quantity':10}
            elif scenario=='extra':v['pages'][0]['status']='wrong'
            elif scenario=='duplicate':v['pages'][1]=deepcopy(v['pages'][0])
            elif scenario=='unbound':v['pages'][0]['source_sha256']='f'*64
            elif scenario=='bool':v['pages'][0]['page_number']=True
            elif scenario=='short':v['pages']=v['pages'][:2]
            else:v['pages']=[{'page_number':n,'source_sha256':sources[n]['sha256']} for n in range(1,66)]
            with self.subTest(scenario=scenario),self.assertRaises(ValueError):runner.panel_pages(v,sources)

    def test_parse_preflight_never_opens_reference_prior_metrics_or_mapping(self):
        records={};data={};reads=[]
        def add(name,value,sha='a'*64):
            actual=self.put(value);record={'path':name,'sha256':sha};records[name]=actual['path'];data[name]=record;return record
        inventory=add('source-inventory',{'files':[{'sha256':'a'*64} for _ in range(484)]})
        pins={k:{'path':'FORBIDDEN-'+k,'sha256':v} for k,v in runner.EXPECTED.items()}
        pins.update(sources=inventory,cache=add('cache',{},runner.EXPECTED['cache']),frame_io=add('frame-io',{}))
        profile=add('profile',{'expected_scope':runner.SCOPE,'pins':pins,'parser_sources':[],'final164_source_files':[],
          'dependencies':[],'bridge_sources':[]},runner.PROFILE_SHA)
        panel=add('panel',{'contract':'document-ai-correction-pilot-panel.v1','source_inventory':inventory,
          'pages':[{'page_number':n,'source_sha256':'a'*64} for n in range(1,13)]})
        resource={'actual_exit_code':0,'failure':None,'stop_reason':None,'cleanup':{'confirmed_all_known_owned_exited':True},
          'logs_finalized_after_owned_cleanup':True,'peak_owned_process_tree_RSS_bytes':1000,'minimum_free_RAM_bytes':2*1024**3}
        closed=add('native-root',{'status':'COMPLETE','failure':None,'shared_lock_released_after_owned_closure':True,
          'cleanup':{'confirmed_all_known_owned_exited':True},'resources':[resource for _ in range(16)]},runner.CLOSED_SHA)
        native=add('native',{'status':'COMPLETE','pages_completed':484,'complete_full_inventory':True,'selected_pages':list(range(1,485)),
          'page_results':[{} for _ in range(484)],'actual_closed_supervision_receipts':[closed]},runner.NATIVE_SHA)
        prediction=add('baseline-prediction',{},runner.PREDICTION_SHA)
        run=add('baseline-run',{'profile':profile,'native_summary':native})
        done=add('baseline-complete',{'status':'COMPLETE','scope':'full484','variant':'control','pages':484,'prediction':prediction,'run_manifest':run},runner.CONTROL_SHA)
        sources={'runner':add('new-runner',{},c.sha(runner.__file__)),'bridge':add('bridge',{},runner.LEGACY_CORRECTION_SOURCES['bridge']),
          'guard':add('guard',{},runner.LEGACY_CORRECTION_SOURCES['guard']),
          'frozen_eval_runner':add('old-code',{},'1538e7b5ba42cf178c24b70abf6081c5c39d02161afce2fe44b5802ef39eb5f9')}
        spec=add('experiment',{'contract':'document-ai-source-correction-experiment.v1','approved_by':'root','production_activation':False,
          'parser_reference_access':False,'new_OCR_calls':0,'new_model_calls':0,'profile':profile,'native_summary':native,
          'native_closed_source':closed,'baseline_complete':done,'baseline_prediction':prediction,'panel':panel,'sources':sources})
        def check(record):
            reads.append(record['path'])
            if record['path'].startswith('FORBIDDEN'):raise AssertionError('Parser attempted evaluator-only read')
            return records[record['path']]
        result=runner.preflight(spec,check)
        self.assertEqual(12,len(result[3]));self.assertFalse(any(p.startswith('FORBIDDEN') for p in reads))
        v2=c.read(records['experiment']);eligibility=add('eligibility-policy',{'source':'synthetic'})
        v2['sources']['eligibility']=eligibility;v2['eligibility_policy']=eligibility
        v2_record=add('experiment-v2',v2);runner.preflight(v2_record,check)
        self.assertIn('eligibility-policy',reads)
        for scenario in ('missing-policy','different-policy','unexpected-module','missing-pin-with-new-import'):
            bad=deepcopy(v2)
            if scenario=='missing-policy':bad.pop('eligibility_policy')
            elif scenario=='different-policy':bad['eligibility_policy']=prediction
            elif scenario=='unexpected-module':bad['sources']['unreviewed_dependency']=eligibility
            else:
                bad['sources'].pop('eligibility');bad.pop('eligibility_policy')
                module=self.root/'new-bridge.py';module.write_text('from correction_eligibility import assess_row\n',encoding='utf8')
                bad['sources']['bridge']=c.pin(module)
            record=add('bad-'+scenario,bad)
            with self.subTest(scenario=scenario),self.assertRaises(ValueError):runner.preflight(record,check)
        component=add('source-component',{})
        # Additional components require an exact selected source closure; a
        # pinned but disabled module may not silently alter the parser.
        valid=deepcopy(v2)
        valid['active_components']=['document_admission']
        valid['sources']['document_admission']=component
        result=runner.preflight(add('with-component',valid),check)
        self.assertEqual(12,len(result[3]))
        for scenario in ('missing-source','disabled-source','duplicate','unknown','not-a-name'):
            bad=deepcopy(valid)
            if scenario=='missing-source':bad['sources'].pop('document_admission')
            elif scenario=='disabled-source':bad['active_components']=[]
            elif scenario=='duplicate':bad['active_components']*=2
            elif scenario=='unknown':bad['active_components']=['unreviewed_component']
            else:bad['active_components']=[{}]
            with self.subTest(component=scenario),self.assertRaises(ValueError):
                runner.preflight(add('invalid-component-'+scenario,bad),check)

    def test_eligibility_dependency_is_exact_pinned_import_and_rejects_preloaded_foreign_source(self):
        path=self.root/'correction_eligibility.py';path.write_text('def assess_row(row, rules):\n    return {"eligible": False}\n',encoding='utf8')
        record=c.pin(path);spec={'sources':{'eligibility':record}}
        with patch.dict(sys.modules):
            sys.modules.pop('correction_eligibility',None)
            module=runner.load_eligibility(spec)
            self.assertIs(module,sys.modules['correction_eligibility'])
            self.assertEqual(path.resolve(),Path(module.__file__).resolve())
            self.assertFalse(module.assess_row({},None)['eligible'])
            self.assertIs(module,runner.load_eligibility(spec))
            sys.modules['correction_eligibility']=types.SimpleNamespace(__file__=str(self.root/'foreign.py'))
            with self.assertRaises(ValueError):runner.load_eligibility(spec)
        path.write_text('raise RuntimeError("unapproved changed module")\n',encoding='utf8')
        with self.assertRaises(ValueError):runner.load_eligibility(spec)
        self.assertIsNone(runner.load_eligibility({'sources':{}}))

    def test_eligibility_import_final_origin_and_bytes_are_checked_after_loader(self):
        path=self.root/'correction_eligibility.py';path.write_text('VALUE = 1\n',encoding='utf8')
        record=c.pin(path);spec={'sources':{'eligibility':record}}
        def changed(name,actual):
            actual.write_text('VALUE = 2\n',encoding='utf8')
            module=types.SimpleNamespace(__file__=str(actual));sys.modules[name]=module;return module
        with patch.dict(sys.modules),patch.object(runner,'load',side_effect=changed):
            sys.modules.pop('correction_eligibility',None)
            with self.assertRaises(ValueError):runner.load_eligibility(spec)

    def test_component_imports_are_explicit_and_origin_hash_bound(self):
        for role,name in runner.COMPONENT_MODULES.items():
            path=self.root/(name+'.py');path.write_text('MARKER = "synthetic"\n',encoding='utf8')
            spec={'sources':{role:c.pin(path)},'active_components':[role]}
            if role=='fresh_source_cells':
                for dependency,module_name in runner.FRESH_DEPENDENCIES.items():
                    dep=self.root/(module_name+'.py');dep.write_text('MARKER = "synthetic dependency"\n',encoding='utf8')
                    spec['sources'][dependency]=c.pin(dep)
            with self.subTest(role=role),patch.dict(sys.modules):
                sys.modules.pop(name,None)
                if role=='fresh_source_cells':
                    for module_name in runner.FRESH_DEPENDENCIES.values():sys.modules.pop(module_name,None)
                modules=runner.load_components(spec)
                self.assertEqual('synthetic',modules[role].MARKER)
                self.assertEqual(path.resolve(),Path(modules[role].__file__).resolve())
                self.assertIs(modules[role],runner.load_components(spec)[role])
                sys.modules[name]=types.SimpleNamespace(__file__=str(self.root/'foreign.py'))
                with self.assertRaises(ValueError):runner.load_components(spec)
        self.assertEqual({},runner.load_components({'sources':{}}))

    def test_component_source_cannot_change_during_import(self):
        path=self.root/'document_source_admission.py';path.write_text('VALUE=1\n',encoding='utf8')
        spec={'sources':{'document_admission':c.pin(path)},'active_components':['document_admission']}
        def changed(name,actual):
            actual.write_text('VALUE=2\n',encoding='utf8')
            module=types.SimpleNamespace(__file__=str(actual));sys.modules[name]=module;return module
        with patch.dict(sys.modules),patch.object(runner,'load',side_effect=changed):
            sys.modules.pop('document_source_admission',None)
            with self.assertRaises(ValueError):runner.load_components(spec)

    def test_nonempty_replacements_are_distinct_from_fills_and_provenance_updates(self):
        before={'product_rows':[{'fields':{'quantity':{'raw_value':'1','normalized_value':1},'unit':None}},
                                {'fields':{'unit':{'raw_value':'box','normalized_value':'box'}}}]}
        after=deepcopy(before);after['product_rows'][0]['fields']['quantity']={'raw_value':'2','normalized_value':2}
        after['product_rows'][0]['fields']['unit']={'raw_value':'box','normalized_value':'box'}
        after['product_rows'][1]['fields']['unit']['evidence']='new actual source'
        accepted=[{'row_index':0,'field':'quantity'},{'row_index':0,'field':'unit'},{'row_index':1,'field':'unit'}]
        counts,events=runner.revisions(before,after,accepted)
        self.assertEqual({'accepted_field_revisions':3,'nonempty_replacements':1,'missing_fills':1,'source_provenance_only_changes':1},counts)
        self.assertEqual('1',events[0]['before']['raw_value']);self.assertEqual('2',events[0]['after']['raw_value'])
        self.assertTrue(runner.nonempty({'normalized_value':0}));self.assertFalse(runner.nonempty({'raw_value':' '}))
        with self.assertRaises(ValueError):runner.revisions(before,after,accepted+[accepted[0]])
        with self.assertRaises(ValueError):runner.revisions(before,after,[{'row_index':0,'field':'lot'}])

    def fixture_pilot(self):
        experiment=self.put({'fixed':'experiment'});panel=self.put({'fixed':'panel'});worker=self.put({'fixed':'new runner'})
        spec={'panel':panel,'sources':{'runner':worker}}
        records=[]
        for name in ('control','candidate'):
            run=self.put({'experiment':experiment,'panel':panel,'reference_access':False})
            records.append(self.put({'scope':'panel','variant':name,'run_manifest':run}))
        score={'status':'COMPLETE','scope':'CORRECTION_PILOT_PANEL','experiment':experiment,'panel':panel,
          'actual_scorer_invocations':2,'writer_readback_verified':True,'fixed':1,'prior323_lost':0,
          'safety':{'exact_loss_count':0,'new_wrong_count_all602':0,'new_absence_falsefill_count':0},
          'control_complete':records[0],'candidate_complete':records[1]}
        score_pin=self.put(score)
        cfg=self.put({'source':{'sha256':'87714bc07ea839a73115531e9358b2de0c17882a03d627a8353745fedf3c39d3'},
          'resource_policy':c.RESOURCES,'steps':[{'id':name,'worker':worker,'optimizer_updates_allowed':False} for name in ('control','candidate','paired_score')]})
        resources=[{'stage':name,'actual_exit_code':0,'failure':None,'stop_reason':None,'child_started':True,
          'worker_optimizer_updates_permission':False,'cleanup':{'confirmed_all_known_owned_exited':True},
          'logs_finalized_after_owned_cleanup':True,'peak_owned_process_tree_RSS_bytes':12345,'minimum_free_RAM_bytes':2*1024**3,
          'worker_summary':record} for name,record in zip(('control','candidate','paired_score'),records+[score_pin])]
        closed={'status':'COMPLETE','failure':None,'config':cfg,'cleanup':{'confirmed_all_known_owned_exited':True},
          'shared_lock_released_after_owned_closure':True,'resources':resources}
        return experiment,spec,score,score_pin,closed

    def test_full_gate_requires_real_pair_scorer_source_and_gaining_zero_loss_pilot(self):
        experiment,spec,score,score_pin,closed=self.fixture_pilot()
        runner.pilot_gate(experiment,spec,score_pin,self.put(closed))
        for scenario in ('nongain','lost','newwrong','falsefill','nocalls','noreadback','source','closure'):
            bad=deepcopy(score);root=deepcopy(closed)
            if scenario=='nongain':bad['fixed']=0
            elif scenario=='lost':bad['prior323_lost']=1
            elif scenario=='newwrong':bad['safety']['new_wrong_count_all602']=1
            elif scenario=='falsefill':bad['safety']['new_absence_falsefill_count']=1
            elif scenario=='nocalls':bad['actual_scorer_invocations']=0
            elif scenario=='noreadback':bad['writer_readback_verified']=False
            elif scenario=='source':bad['experiment']=self.put({'wrong':'experiment'})
            else:root['cleanup']['confirmed_all_known_owned_exited']=False
            record=self.put(bad);root['resources'][-1]['worker_summary']=record
            with self.subTest(scenario=scenario),self.assertRaises(ValueError):runner.pilot_gate(experiment,spec,record,self.put(root))
        wrong=deepcopy(closed);wrong['resources'][0]['actual_exit_code']=1
        with self.assertRaises(ValueError):runner.pilot_gate(experiment,spec,score_pin,self.put(wrong))

    def test_pilot_cannot_be_reused_after_source_or_panel_changes(self):
        experiment,spec,score,score_pin,closed=self.fixture_pilot()
        changed=deepcopy(spec);changed['sources']['runner']=self.put({'different':'runner'})
        with self.assertRaises(ValueError):runner.pilot_gate(experiment,changed,score_pin,self.put(closed))
        changed=deepcopy(spec);changed['panel']=self.put({'different':'panel'})
        with self.assertRaises(ValueError):runner.pilot_gate(experiment,changed,score_pin,self.put(closed))

    def parser_fixture(self):
        parent={'page_number':1,'source_sha256':'a'*64,'product_rows':[{'id':'r1','fields':{'quantity':{'raw_value':'1','normalized_value':1},
          'description':{'raw_value':'SYNTHETIC PRODUCT','bbox':[1,1,8,3]}}}],'document':{'document_type':'invoice_or_delivery'},'coordinate_space':'original_image'}
        cache=self.put({'source_sha256':'a'*64,'geometry':{'machine_only':True,'vision_LLM_calls':0,'original_size':[100,100],'orientation_ccw':0},
          'inference_inputs':{'reference':False,'human_answers':False,'Ada':False,'StockDay':False,'assistant_image_reads':0}})
        cm=self.put({'pages':[{'page_number':1,**cache}]});obs=self.put({'page':1,'source_image':{'sha256':'a'*64}})
        dummy=self.put({'source':'not private data'})
        profile={'pins':{'shared':dummy,'cache':cm}}
        spec={'results_root':str(self.root/'runs'),'sources':{'bridge':dummy,'guard':dummy},'profile':dummy,'native_summary':dummy,
          'baseline_complete':dummy,'baseline_prediction':dummy,'panel':dummy}
        control={'source_inventory':[{'page_number':1,'prediction_content_sha256':runner.digest(parent)}]}
        context=(spec,profile,{1:{'sha256':'a'*64}},{1:'a'*64},{'page_results':[obs]},control)
        io=types.SimpleNamespace(upright_from_original=lambda p,g,m:deepcopy(p),core=deepcopy)
        helpers={'io':io,'mapper':lambda p,*a:deepcopy(p),'finalize':lambda p,**k:{'raw_page_sha256':runner.digest(p)},
          'guard':lambda *a:(_ for _ in ()).throw(AssertionError('old missing-only guard must remain separate'))}
        shared=types.SimpleNamespace(PageBundle=lambda p:iter([deepcopy(parent)]))
        calls=[]
        def propose(p,*args):
            calls.append('bridge');value=deepcopy(p);value['product_rows'][0]['fields']['quantity']={'raw_value':'2','normalized_value':2}
            value['document_ai_correction_association']={'changes':[{'row_index':0,'field':'quantity'}],'rejected':[]};return value
        def conserve(before,proposed,*args):calls.append('new_policy');return deepcopy(proposed),{'status':'VERIFIED','accepted_changes':[{'row_index':0,'field':'quantity'}]}
        def project(before,mapped,audit):
            calls.append('projection');out=deepcopy(before);out['product_rows'][0]['fields']['quantity']=deepcopy(mapped['product_rows'][0]['fields']['quantity']);return out,{'accepted_changes':audit['accepted_changes']}
        bridge=types.SimpleNamespace(propose_and_apply=propose);guard=types.SimpleNamespace(conserve_corrections=conserve,project_corrections=project)
        def loader(name,p):return bridge if name=='correction_bridge' else guard if name=='correction_guard' else shared
        return parent,context,helpers,loader,calls

    def test_real_synthetic_writer_path_corrects_nonempty_without_roundtrip_others(self):
        parent,context,helpers,loader,calls=self.parser_fixture();before=deepcopy(parent)
        record=self.put({'experiment':'synthetic'})
        with patch.object(runner,'preflight',return_value=context),patch.object(runner,'runtime',return_value=helpers),patch.object(runner,'load',side_effect=loader):
            complete=runner.parse(record,'panel','candidate',self.root/'runs/candidate')
        value=c.read(complete['path']);page=c.read(self.root/'runs/candidate/extractions/page-0001.json')
        self.assertEqual(['bridge','new_policy','projection'],calls);self.assertEqual(1,value['revision_counts']['nonempty_replacements'])
        self.assertEqual('2',page['product_rows'][0]['fields']['quantity']['raw_value'])
        self.assertEqual(before['product_rows'][0]['fields']['description'],page['product_rows'][0]['fields']['description'])
        self.assertEqual(before,parent);self.assertTrue(value['writer_readback_verified']);self.assertFalse(value['reference_access'])
        self.assertEqual('original_image',page['document_ai_correction_association']['effective_changes_coordinate_space'])

    def test_control_writer_reuses_saved_canonical_without_adapter_or_policy(self):
        parent,context,helpers,loader,calls=self.parser_fixture()
        with patch.object(runner,'preflight',return_value=context),patch.object(runner,'runtime',side_effect=AssertionError('control must not load adapter runtime')),patch.object(runner,'load',side_effect=loader):
            complete=runner.parse(self.put({'experiment':'synthetic'}),'panel','control',self.root/'runs/control')
        self.assertEqual([],calls);self.assertEqual(parent,c.read(self.root/'runs/control/extractions/page-0001.json'))
        self.assertEqual(0,c.read(complete['path'])['revision_counts']['accepted_field_revisions'])

    def test_panel_safety_counts_all_losses_new_wrong_and_absence_independently(self):
        reference={'pages':[{'page_number':1,'source_sha256':'a'*64,'company_key':'COMPANY','rows':[{'id':'r','fields':{
          'quantity':{'state':'present'},'unit':{'state':'present'},'lot':{'state':'absent'}}}], 'header_fields':{}}]}
        def outcomes(ref,metric,documents=False):
            errors={(e['page'],str(e['row_id']),e['field']):e['status'] for e in metric['errors']}
            return {(1,'r',f):errors.get((1,'r',f),'exact') for f in ('quantity','unit')}
        shared=types.SimpleNamespace(present_outcomes=outcomes,UNMAPPED='UNMAPPED')
        scorer=types.SimpleNamespace(CRITICAL_FIELDS={'quantity','lot'},compare=lambda *args:{'same_frozen_definition':True})
        prior={'label_keys':[[1,'r','unit']]};mapping={'records':[],'issuer_groups':['DIAGNOSTIC']}
        a={'errors':[{'page':1,'row_id':'r','field':'quantity','status':'wrong'}]}
        b={'errors':[{'page':1,'row_id':'r','field':'unit','status':'wrong'},{'page':1,'row_id':'r','field':'lot','status':'unexpected_present'}]}
        result=runner.compare_panel(reference,[a,b],shared,scorer,prior,mapping)
        self.assertEqual(1,result['fixed']);self.assertEqual(1,result['prior323_lost']);self.assertEqual(1,result['safety']['new_wrong_count_all602'])
        self.assertEqual(1,result['safety']['exact_loss_count']);self.assertEqual(1,result['safety']['new_absence_falsefill_count'])
        self.assertEqual(1,result['safety']['absence_scope_separate']);self.assertFalse(result['absence_test_is_full18'])
        self.assertFalse(result['full585_claim_allowed']);self.assertEqual(2,result['product_present_denominator'])
        self.assertEqual(1,result['primary13'][0]['fixed'])


if __name__=='__main__':unittest.main()
