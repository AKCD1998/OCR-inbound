"""Invented guard/runner-boundary cases; no OCR SDK or private artifacts."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments/document_ai'))
import correction_bridge as bridge
import correction_guard as guard
import correction_runner as runner
import source_cell_association as cells
import component_common as common
from tests.test_document_ai_correction_bridge import fixture,HELPERS,PIN


class FreshGuardTests(unittest.TestCase):
    def setUp(self):
        self.page,self.cache,self.obs=fixture()
        self.cache['geometry'].update(machine_only=True,vision_LLM_calls=0)
        self.helpers={**HELPERS,'correction_bridge':bridge,'cell_association':cells}
        # Old quantity is an incomplete/low-quality source pair. It remains
        # untouched in the cache, not counted as a third independent engine.
        next(t for t in self.cache['working_tokens'] if t['token_id']=='p:q1')['confidence']=.3
        context=next(c for c in cells._contexts(self.page,self.cache,self.obs,self.helpers,PIN)[0]
                     if (c['row_index'],c['role'])==(0,'quantity'))
        evidence=deepcopy(context['evidence']);evidence['route']='FRESH_WHOLE_SOURCE_ROW_BAND'
        p=next(t for t in context['primary'] if t['token_id']=='p:q1')
        t=next(t for t in context['secondary'] if t['token_id']=='tesseract:q1')
        p=deepcopy(p);t=deepcopy(t)
        for word,tid in ((p,'paddle:fresh:p1'),(t,'tesseract:fresh:t1')):
            word.update(text='11',confidence=.99,token_id=tid,aliases=[tid])
        value={'tokens':[p,t],'raw_value':'11','normalized_value':'11'}
        proof={'request_id':'synthetic-source-only','observations':{'path':'observations.json','sha256':'a'*64}}
        field=cells._field(value,self.page['product_rows'][0]['fields']['quantity'],evidence)
        field.update(association_basis='FRESH_WHOLE_SOURCE_ROW_BAND',fresh_source_evidence=deepcopy(proof),
                     extra_independent_engine_families=0)
        context.update(fresh_primary=[p],fresh_secondary=[t],fresh_alternatives=[],fresh_source_evidence=proof)
        self.context=context;self.evidence=evidence;self.field=field
        def verify(*args):
            if args[-1]!=self.evidence:raise ValueError('fake source receipt')
            return deepcopy(self.context)
        self.helpers['fresh_source_cells']=SimpleNamespace(verify=verify)

    def candidate(self):
        result=deepcopy(self.page);result['product_rows'][0]['fields']['quantity']=deepcopy(self.field)
        result['document_ai_correction_association']={'changes':[{'row_index':0,'field':'quantity',
            'before':deepcopy(self.page['product_rows'][0]['fields']['quantity']),
            'candidate':deepcopy(self.field),'evidence':deepcopy(self.evidence)}]}
        return result

    def apply(self):
        return guard.conserve_corrections(self.page,self.candidate(),self.cache,self.obs,self.helpers,PIN)

    def test_proven_fresh_read_can_replace_incomplete_old_pair_without_cache_mutation(self):
        frozen=deepcopy((self.page,self.cache,self.obs));result,audit=self.apply()
        self.assertEqual(1,len(audit['accepted_changes']),audit['rejected_changes'])
        self.assertEqual('11',result['product_rows'][0]['fields']['quantity']['raw_value'])
        self.assertEqual(self.page['product_rows'][0]['fields']['quantity'],
                         result['product_rows'][0]['fields']['quantity']['source_revision']['previous_source_field'])
        self.assertEqual(frozen,(self.page,self.cache,self.obs))
        projected,_=guard.project_corrections(self.page,result,audit)
        for name in ('description','unit','lot','supplier_code'):
            self.assertEqual(self.page['product_rows'][0]['fields'][name],projected['product_rows'][0]['fields'][name])

    def test_original_qualified_pair_disagreement_is_not_outvoted(self):
        next(t for t in self.cache['working_tokens'] if t['token_id']=='p:q1')['confidence']=.99
        _,audit=self.apply();self.assertFalse(audit['accepted_changes'])
        self.assertIn('qualified_original_dual_reader_pair_disagrees_with_fresh_pair',str(audit))

    def test_foreign_price_lot_and_neighbour_owner_survive_new_token_ids_and_jitter(self):
        original=deepcopy(self.page)
        for index,role in ((0,'lot'),(0,'unit'),(1,'quantity')):
            self.page=deepcopy(original)
            box=deepcopy(self.context['fresh_primary'][0]['bbox']);box[0]+=0.2;box[2]+=0.2
            self.page['product_rows'][index]['fields'][role]={'raw_value':'OLD SOURCE','bbox':box,'token_ids':['different-old-id']}
            with self.subTest(owner=(index,role)):
                _,audit=self.apply();self.assertFalse(audit['accepted_changes'])
                self.assertIn('preserved_foreign_source_owner',str(audit))

    def test_no_fabricated_value_family_or_receipt_can_pass_guard(self):
        original=deepcopy(self.field)
        for mode in ('raw','confidence','receipt','family','fake-cell'):
            self.field=deepcopy(original)
            if mode=='raw':self.field['raw_value']='999'
            elif mode=='confidence':self.context['fresh_primary'][0]['confidence']=.94
            elif mode=='receipt':self.field['fresh_source_evidence']['request_id']='unbound'
            elif mode=='family':self.field['extra_independent_engine_families']=1
            else:self.field['model_geometry_evidence']['cell_id']='invented-native-cell'
            with self.subTest(mode=mode):
                _,audit=self.apply();self.assertFalse(audit['accepted_changes'])
            self.context['fresh_primary'][0]['confidence']=.99


class FreshBoundaryTests(unittest.TestCase):
    def test_actual_fresh_component_bridge_guard_and_projection_admit_legitimate_source(self):
        from tests.test_document_ai_fresh_source_cells import fresh_fixture
        import fresh_source_cells
        page,cache,obs,helpers=fresh_fixture()
        helpers['fresh_source_cells']=fresh_source_cells
        frozen=deepcopy((page,cache,obs))
        proposed=bridge.propose_and_apply(page,cache,obs,helpers,PIN)
        revised,audit=guard.conserve_corrections(page,proposed,cache,obs,helpers,PIN)
        admitted=[x for x in audit['accepted_changes'] if x['evidence'].get('route')=='FRESH_WHOLE_SOURCE_ROW_BAND']
        self.assertEqual(1,len(admitted),audit['rejected_changes'])
        self.assertEqual('10',revised['product_rows'][0]['fields']['quantity']['raw_value'])
        projected,_=guard.project_corrections(page,revised,audit)
        field=projected['product_rows'][0]['fields']['quantity']
        self.assertEqual(page['product_rows'][0]['fields']['quantity'],field['source_revision']['previous_source_field'])
        self.assertEqual(0,field['extra_independent_engine_families'])
        self.assertEqual(frozen,(page,cache,obs))
        for old,new in zip(page['product_rows'],projected['product_rows']):
            self.assertEqual(old['row_number'],new['row_number'])
            for name in ('description','lot','supplier_code'):
                self.assertEqual(old['fields'][name],new['fields'][name])

    def test_actual_fresh_component_cannot_borrow_near_overlapping_foreign_ink(self):
        from tests.test_document_ai_fresh_source_cells import fresh_fixture
        import fresh_source_cells
        page,cache,obs,helpers=fresh_fixture();helpers['fresh_source_cells']=fresh_source_cells
        page['product_rows'][0]['fields']['lot']={'raw_value':'KEEP','bbox':[530.2,220,570.2,240],
                                                'token_ids':['old-lot-different-id']}
        proposed=bridge.propose_and_apply(page,cache,obs,helpers,PIN)
        _,audit=guard.conserve_corrections(page,proposed,cache,obs,helpers,PIN)
        self.assertFalse([x for x in audit['accepted_changes'] if (x['row_index'],x['field'])==(0,'quantity')])
        self.assertIn('preserved_foreign_source_owner',str(audit)+str(proposed['document_ai_correction_association']['rejected']))

    def test_qualified_numeric_format_equivalence_is_not_a_source_contradiction(self):
        from tests.test_document_ai_fresh_source_cells import fresh_fixture
        import fresh_source_cells
        page,cache,obs,helpers=fresh_fixture(text='10.0',weak_old=False)
        helpers['fresh_source_cells']=fresh_source_cells
        proposed=bridge.propose_and_apply(page,cache,obs,helpers,PIN)
        revised,audit=guard.conserve_corrections(page,proposed,cache,obs,helpers,PIN)
        fresh=[x for x in audit['accepted_changes'] if x['evidence'].get('route')=='FRESH_WHOLE_SOURCE_ROW_BAND']
        # If another old route proposes an equivalent value using different
        # source IDs, the combiner remains conservative. Exercise the fresh
        # transaction itself to test the independent guard equivalence.
        event=fresh_source_cells.propose(page,cache,obs,helpers,PIN)['changes'][0]
        candidate=deepcopy(page);candidate['product_rows'][0]['fields']['quantity']=deepcopy(event['candidate'])
        candidate['document_ai_correction_association']={'changes':[event]}
        _,audit=guard.conserve_corrections(page,candidate,cache,obs,helpers,PIN)
        self.assertEqual(1,len(audit['accepted_changes']),audit['rejected_changes'])

    def test_geometry_owner_checks_do_not_depend_on_matching_alias_ids(self):
        rows=[{'fields':{'description':{'bbox':[0,0,20,10]},'quantity':{'bbox':[30,0,40,10]}}},
              {'fields':{'unit':{'bbox':[40,0,50,10],'source_spans':[{'bbox':[39.9,0,50,10]}]}}}]
        tokens=[{'bbox':[30,0,40,10],'aliases':['NEW-ID']}]
        owners=guard._geometry_foreign_owners(rows,0,'quantity',tokens,HELPERS['rules'])
        self.assertEqual([(1,'unit')],[(x['row_index'],x['field']) for x in owners])

    def test_fresh_module_without_required_dependency_closure_is_not_implicitly_loaded(self):
        # load_components cannot resolve either new dependency without its pin.
        with self.assertRaises(KeyError):
            runner.load_components({'active_components':['fresh_source_cells'],'sources':{}},lambda x:None)

    def test_combiner_does_not_choose_between_disagreeing_old_and_fresh_routes(self):
        page,cache,obs=fixture();field={'raw_value':'11','normalized_value':'11','token_ids':['new'],'bbox':[530,220,570,240]}
        change={'row_index':0,'field':'quantity','before':page['product_rows'][0]['fields']['quantity'],
                'candidate':field,'evidence':{'route':'FRESH_WHOLE_SOURCE_ROW_BAND'}}
        fresh=SimpleNamespace(propose=lambda *args:{'proposed':[change],'changes':[change],'rejected':[]})
        helpers={**HELPERS,'fresh_source_cells':fresh}
        result=bridge.propose_and_apply(page,cache,obs,helpers,PIN)
        self.assertFalse([x for x in result['document_ai_correction_association']['changes'] if (x['row_index'],x['field'])==(0,'quantity')])
        self.assertIn('INDEPENDENT_ASSOCIATION_ROUTES_DISAGREE',str(result['document_ai_correction_association']['rejected']))


class FreshManifestTests(unittest.TestCase):
    def test_tiny_scope_is_source_bound_and_missing_tiny_cannot_start38(self):
        self.assertEqual({40},runner.selected_numbers('tiny',{40:'source',119:'source'},40))
        for page in (None,True,999):
            with self.subTest(page=page),self.assertRaises(ValueError):runner.selected_numbers('tiny',{40:'source'},page)
        with self.assertRaisesRegex(ValueError,'before38'):
            runner.fresh_tiny_gate({}, {},None,None)

    def test_tiny_gate_requires_real_same_source_two_scorers_writer_and_closed_children(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name);serial_sha='87714bc07ea839a73115531e9358b2de0c17882a03d627a8353745fedf3c39d3'
            def put(file,value):
                common.save(folder/file,value);return common.pin(folder/file)
            source={'path':'source-manifest','sha256':'a'*64};experiment={'path':'experiment','sha256':'b'*64}
            panel={'path':'panel','sha256':'c'*64};worker={'path':'runner','sha256':'d'*64}
            spec={'panel':panel,'fresh_source_manifest':source,'sources':{'runner':worker}}
            children=[]
            for variant in ('control','candidate'):
                run=put(variant+'-run.json',{'experiment':experiment,'fresh_source_manifest':source,'reference_access':False})
                children.append(put(variant+'.json',{'scope':'tiny','variant':variant,'pages':1,'run_manifest':run}))
            score={'status':'COMPLETE','scope':'CORRECTION_SOURCE_TINY','experiment':experiment,'panel':panel,
                'fresh_source_manifest':source,'processed_images':1,'actual_scorer_invocations':2,'writer_readback_verified':True,
                'prior323_lost':0,'safety':{'exact_loss_count':0,'new_wrong_count_all602':0,'new_absence_falsefill_count':0},
                'control_complete':children[0],'candidate_complete':children[1]}
            score_pin=put('score.json',score)
            resource={'actual_exit_code':0,'failure':None,'stop_reason':None,'cleanup':{'confirmed_all_known_owned_exited':True},
                'logs_finalized_after_owned_cleanup':True,'peak_owned_process_tree_RSS_bytes':1000,'minimum_free_RAM_bytes':2*1024**3,
                'child_started':True,'worker_optimizer_updates_permission':False}
            stages=['control','candidate','paired_score']
            config=put('serial.json',{'source':{'sha256':serial_sha},'resource_policy':common.RESOURCES,
                'steps':[{'id':x,'worker':worker,'optimizer_updates_allowed':False} for x in stages]})
            closed={'status':'COMPLETE','failure':None,'cleanup':{'confirmed_all_known_owned_exited':True},
                'shared_lock_released_after_owned_closure':True,'config':config,
                'resources':[{**deepcopy(resource),'stage':stage,'worker_summary':pin} for stage,pin in zip(stages,children+[score_pin])]}
            closed_pin=put('closed.json',closed)
            self.assertEqual(score,runner.fresh_tiny_gate(experiment,spec,score_pin,closed_pin))
            for mode in ('one-scorer','wrong-source','harm','writer','not-tiny'):
                changed=deepcopy(score)
                if mode=='one-scorer':changed['actual_scorer_invocations']=1
                elif mode=='wrong-source':changed['fresh_source_manifest']={**source,'sha256':'f'*64}
                elif mode=='harm':changed['safety']['exact_loss_count']=1
                elif mode=='writer':changed['writer_readback_verified']=False
                else:changed['scope']='CORRECTION_PILOT_PANEL'
                with self.subTest(mode=mode),self.assertRaises(ValueError):
                    runner.fresh_tiny_gate(experiment,spec,put(mode+'.json',changed),closed_pin)

    def test_complete46_source_order_and_held14_are_enforced(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name)
            def put(file,value):
                common.save(folder/file,value);return common.pin(folder/file)
            module=put('module.json',{})
            recipe=put('recipe.json',{})
            derivation={'module':module,'recipe':recipe}
            requests=[]
            for i in range(60):
                req={'request_id':'source-%02d'%i}
                context=put('context-%02d.json'%i,{'request_binding':deepcopy(req),
                    'derivation':{'recipe':recipe,'crop_admission':{'eligible':i<46}}})
                requests.append({**req,'context_proof':context})
            plan=put('plan.json',{'contract':'document-ai-whole-cell-source-plan.v1','machine_only':True,'requests':requests})
            worker=put('worker.json',{})
            configuration=put('config.json',{'plan':plan,'derivation_runtime':derivation})
            records=[{'request_id':r['request_id'],'observations':{},'summary':{},'closed_source':{},'crop_proof':{},
                      'raw':{'detector':{},'recognizers':[],'tesseract_tsv':{}}} for r in requests[:46]]
            manifest={'contract':'document-ai-fresh-whole-source-reads.v1','plan':plan,'native_worker':worker,
                      'configuration':configuration,'derivation_runtime':derivation,'request_results':records}
            def check(value):return Path(value['path'])
            def spec(file,payload):
                return {'fresh_source_manifest':put(file,payload),'sources':{'fresh_source_derivation':module,
                    'fresh_source_protocol':{'path':'unused-protocol','sha256':'7892c593409e2e42908f6bf858ea2da84b18f0a87c8f8810b172b62116800107'}}}
            fixed={k:manifest[k]['sha256'] for k in ('plan','native_worker','configuration')}
            with patch.object(runner,'FRESH_FIXED',fixed):
                self.assertEqual(46,len(runner.fresh_source_metadata(spec('manifest.json',manifest),check)[1]))
                for mode in ('partial','order','duplicate','held','extra-answer'):
                    changed=deepcopy(manifest)
                    if mode=='partial':changed['request_results'].pop()
                    elif mode=='order':changed['request_results'].reverse()
                    elif mode=='duplicate':changed['request_results'][1]=deepcopy(changed['request_results'][0])
                    elif mode=='held':changed['request_results'][-1]['request_id']='source-59'
                    else:changed['request_results'][0]['expected_business_answer']='forbidden'
                    with self.subTest(mode=mode),self.assertRaises(ValueError):
                        runner.fresh_source_metadata(spec(mode+'.json',changed),check)

    def fixture(self,folder):
        folder=folder.resolve()
        def put(file,value):
            common.save(folder/file,value);return common.pin(folder/file)
        plan=put('plan.json',{});worker=put('worker.json',{})
        config={'models':{},'sdk_sources':{},'tesseract':{},'resource_policy':common.RESOURCES,'limits':{}}
        configuration=put('config.json',config);derivation={'module':worker,'recipe':plan}
        request={'request_id':'source-0','page_number':1,'row_index':0,'field':'unit',
                 'source_image':{'path':'not-opened.png','sha256':'a'*64},'geometry':{'original_size':[100,100]},
                 'context_proof':put('context.json',{})}
        summary={'status':'COMPLETE','executed':True,'failure':None,'component':'whole-cell-source',
            'request_id':'source-0','requests_completed':1,'requests_selected':1,'worker':worker,'config':configuration,
            'plan':plan,'derivation_runtime':derivation,'assistant_image_reads':0,'optimizer_updates':0,
            'baseline_cache_modified':False,'canonical_values_modified':False,'production_activation':False,
            'actual_detector_regions':1,**deepcopy(config)}
        summary_pin=put('SUMMARY.json',summary)
        observations={k:deepcopy(request[k]) for k in ('request_id','page_number','row_index','field','source_image','geometry')}
        observations.update(crop={},literal_source_only=True,logical_field_values_assigned=False,
                            baseline_cache_modified=False,extra_independent_engine_families=0)
        observed_pin=put('OBSERVATIONS.json',observations)
        serial=put('SERIAL.json',{'source':{'sha256':'87714bc07ea839a73115531e9358b2de0c17882a03d627a8353745fedf3c39d3'},
                                'resource_policy':common.RESOURCES})
        resource={'actual_exit_code':0,'failure':None,'stop_reason':None,'cleanup':{'confirmed_all_known_owned_exited':True},
            'logs_finalized_after_owned_cleanup':True,'peak_owned_process_tree_RSS_bytes':1000,'minimum_free_RAM_bytes':2*1024**3,
            'child_started':True,'worker_optimizer_updates_permission':False,'worker_summary':summary_pin,
            'actual_argv':[worker['path'],'--request-id','source-0','--output',str(folder),'--config',configuration['path'],
                           '--config-sha256',configuration['sha256'],'--execute']}
        closed={'status':'COMPLETE','failure':None,'shared_lock_released_after_owned_closure':True,
                'cleanup':{'confirmed_all_known_owned_exited':True},'config':serial,'resources':[resource]}
        closed_pin=put('CLOSED.json',closed)
        detector=put('PADDLE_DETECTOR_RAW.json',{});recognizer=put('PADDLE_REC_RAW_000.json',{})
        tsv=folder/'TESSERACT_RAW.tsv';tsv.write_text('raw TSV synthetic',encoding='utf8')
        crop_proof=put('CROP_PROOF.json',{'request':request,'crop':observations['crop'],
            'physical_crop':{'path':str(folder/'whole_ROI.png'),'sha256':'a'*64}})
        record={'request_id':'source-0','observations':observed_pin,'summary':summary_pin,'closed_source':closed_pin,'crop_proof':crop_proof,
                'raw':{'detector':detector,'recognizers':[{'detection_index':0,'raw':recognizer}],'tesseract_tsv':common.pin(tsv)}}
        manifest={'plan':plan,'native_worker':worker,'configuration':configuration,'derivation_runtime':derivation,'request_results':[record]}
        spec={'fresh_source_manifest':{'path':'sealed-source-manifest','sha256':'f'*64}}
        return put,request,summary,observations,closed,record,manifest,spec,config

    def test_fixture_native_argv_and_pins_use_one_canonical_temporary_directory(self):
        # Windows CI may supply an aliased TEMP path. Pins resolve it, so the
        # invented native argv must describe the same canonical directory.
        # A dotted spelling reproduces that mismatch without an OS dependency.
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name)
            values=self.fixture(folder/'temporary-alias'/'..')
            _,request,_,_,closed,_,manifest,spec,config=values
            self.assertEqual(str(folder.resolve()),closed['resources'][0]['actual_argv'][4])
            with patch.object(runner,'fresh_source_metadata',lambda *args:(manifest,{'source-0':request},config)):
                self.assertEqual(1,len(runner.load_fresh_source_reads(spec,common.checked)['records']))

    def test_actual_closed_native_artifacts_load_and_unclosed_or_unbound_outputs_refuse(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name)
            put,request,summary,observed,closed,record,manifest,spec,config=self.fixture(folder)
            def metadata(*args):return manifest,{'source-0':request},config
            with patch.object(runner,'fresh_source_metadata',metadata):
                result=runner.load_fresh_source_reads(spec,common.checked)
                self.assertEqual(1,len(result['records']))
                self.assertEqual('raw TSV synthetic',result['records'][0]['raw_proof']['tesseract_tsv'])
                self.assertFalse(result['worker_summary_seals_raw_hashes'])
                for mode in ('failed-root','unclosed','wrong-argv','wrong-output','failed-model','extra-family','raw-escape'):
                    changed_closed=deepcopy(closed);changed_summary=deepcopy(summary);changed_observed=deepcopy(observed)
                    changed_record=deepcopy(record)
                    if mode=='failed-root':changed_closed['status']='FAILED'
                    elif mode=='unclosed':changed_closed['resources'][0]['cleanup']['confirmed_all_known_owned_exited']=False
                    elif mode=='wrong-argv':changed_closed['resources'][0]['actual_argv'][2]='foreign-request'
                    elif mode=='wrong-output':changed_closed['resources'][0]['actual_argv'][4]=str(folder/'foreign')
                    elif mode=='failed-model':changed_summary['status']='FAILED'
                    elif mode=='extra-family':changed_observed['extra_independent_engine_families']=1
                    else:changed_record['raw']['detector']=put('foreign-detector.json',{})
                    # Source pin files are deliberately updated in this fixture:
                    # semantic lineage checks must fail even after re-pinning.
                    Path(record['summary']['path']).write_text(__import__('json').dumps(changed_summary),encoding='utf8')
                    Path(record['observations']['path']).write_text(__import__('json').dumps(changed_observed),encoding='utf8')
                    Path(record['closed_source']['path']).write_text(__import__('json').dumps(changed_closed),encoding='utf8')
                    changed_record['summary']=common.pin(record['summary']['path'])
                    changed_record['observations']=common.pin(record['observations']['path'])
                    changed_closed['resources'][0]['worker_summary']=changed_record['summary']
                    Path(record['closed_source']['path']).write_text(__import__('json').dumps(changed_closed),encoding='utf8')
                    changed_record['closed_source']=common.pin(record['closed_source']['path'])
                    manifest['request_results']=[changed_record]
                    with self.subTest(mode=mode),self.assertRaises(ValueError):runner.load_fresh_source_reads(spec,common.checked)


if __name__=='__main__':unittest.main()
