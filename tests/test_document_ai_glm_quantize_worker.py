"""Invented tiny GGUF/receipt/process cases; no weights or HQ jobs."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import struct,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import glm_quantize_worker as worker
import glm_backend

def tiny_gguf(*,architecture='clip',file_type=2,kind=2,duplicate=False,extra_tensor=False):
    def s(v):
        raw=v.encode();return struct.pack('<Q',len(raw))+raw
    meta=[('general.architecture',8,s(architecture)),('general.file_type',4,struct.pack('<I',file_type))]
    out=b'GGUF'+struct.pack('<IQQ',3,2 if duplicate or extra_tensor else 1,len(meta))
    for key,t,val in meta:out+=s(key)+struct.pack('<I',t)+val
    for index,name in enumerate(['v.blk.0.attn_q.weight','v.blk.0.attn_k.weight'] if duplicate or extra_tensor else ['v.blk.0.attn_q.weight']):
        out+=s(name)+struct.pack('<IQQIQ',2,32,2,kind,96*index if extra_tensor else 0)
    out+=b'\0'*((-len(out))%32)
    return out+b'\0'*((96 if extra_tensor else 0)+(68 if kind==8 else 36))

def fake_pin(path,sha='a'*64):return {'path':str(path),'sha256':sha}

class GGUFTests(unittest.TestCase):
    def test_metadata_and_every_tensor_range_must_be_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'new.gguf';raw=tiny_gguf();p.write_bytes(raw)
            result=worker.projector_header(p)
            self.assertEqual('clip',result['architecture']);self.assertEqual({'2':1},result['tensor_type_counts'])
            self.assertTrue(result['all_tensor_payload_ranges_present']);self.assertFalse(result['tensor_values_decoded'])
            for wrong in (raw[:-1],tiny_gguf(architecture='glm4'),tiny_gguf(file_type=7),
                          tiny_gguf(kind=99),tiny_gguf(duplicate=True)):
                p.write_bytes(wrong)
                with self.subTest(length=len(wrong)),self.assertRaises(ValueError):worker.projector_header(p)

    def test_unconverted_q8_payload_cannot_masquerade_as_quantized_output(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'not-quantized.gguf';p.write_bytes(tiny_gguf(kind=8))
            with self.assertRaises(ValueError):worker.projector_header(p)

class QuantizePolicyTests(unittest.TestCase):
    def config(self,folder):
        return {'contract':worker.CONTRACT,'resource_policy':deepcopy(worker.common.RESOURCES),
            'maximum_seconds':540,'cutoff_utc':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
            'source_materialization_summary':fake_pin('summary.json'),'closed_materialization_root':fake_pin('root.json'),
            'backend_module':fake_pin(glm_backend.__file__), 'common':fake_pin(worker.common.__file__,worker.COMMON_SHA),
            'isolated_python':fake_pin(sys.executable),'projector_source':fake_pin('projector.gguf',worker.PROJECTOR_SHA),
            'output_filename':'projector-Q4_0.gguf','output_root':str(Path(folder)/'new-output'),
            'production_activation':False,'optimizer_updates_allowed':False,'source_image_decodes_allowed':False}

    def test_policy_cannot_raise_caps_extend_deadline_or_write_outside_isolation(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(worker,'ALLOWED_ROOT',Path(folder)):
            cfg=self.config(folder);worker.validate_config(cfg,cfg['output_root'],check_files=False)
            for mode in ('RSS','duration','optimizer','traversal','directory'):
                c=deepcopy(cfg)
                if mode=='RSS':c['resource_policy']['maximum_own_process_tree_RSS_bytes']*=2
                elif mode=='duration':c['maximum_seconds']=601
                elif mode=='optimizer':c['optimizer_updates_allowed']=True
                elif mode=='traversal':c['output_filename']='../old.gguf'
                else:c['output_root']=str(Path(folder).parent/'outside')
                with self.subTest(mode=mode),self.assertRaises(ValueError):
                    worker.validate_config(c,c['output_root'],check_files=False)

    def proof_fixture(self):
        cfg={'source_materialization_summary':fake_pin('summary.json'),'closed_materialization_root':fake_pin('root.json'),
             'projector_source':fake_pin('projector.gguf',worker.PROJECTOR_SHA),'isolated_python':fake_pin('python.exe')}
        summary={'contract':'document-ai-glm-materialize.v1','status':'COMPLETE','component':'glm-materialize',
            'executed':True,'worker':fake_pin('prepare.py',worker.PREPARE_WORKER_SHA),'config':fake_pin('prepare.json'),
            'model_calls':0,'quantization_calls':0,'source_image_decodes':0,'optimizer_updates':0,
            'production_activation':False,'baseline_cache_modified':False,'isolated_python':cfg['isolated_python'],
            'artifacts':[{'role':'projector','file':cfg['projector_source'],'bytes':worker.PROJECTOR_BYTES}],
            'backend':{'quantizer':fake_pin('quantize.exe'),'files':[{'relative_path':'quantize.exe','pin':fake_pin('quantize.exe')}]}}
        resource={'worker_summary':cfg['source_materialization_summary'],'actual_exit_code':0,'child_started':True,
            'failure':None,'cleanup':{'confirmed_all_known_owned_exited':True},'worker_optimizer_updates_permission':False,
            'logs_finalized_after_owned_cleanup':True,'peak_owned_process_tree_RSS_bytes':1000,
            'minimum_free_RAM_bytes':2_000_000_000,
            'actual_argv':['python.exe','prepare.py','--config','prepare.json','--config-sha256','a'*64]}
        closed={'contract':'document-ai-HQ-serial-result.v1','status':'COMPLETE','failure':None,
            'cleanup':{'confirmed_all_known_owned_exited':True},'shared_lock_acquired':True,
            'shared_lock_released_after_owned_closure':True,'resources':[resource]}
        return cfg,summary,closed

    def test_source_summary_cannot_be_detached_from_closed_causal_resource(self):
        cfg,summary,closed=self.proof_fixture()
        def read(path):return summary if path=='summary.json' else closed
        with patch.object(worker.common,'read',read):
            worker.materialization_proof(cfg,check=lambda p:p['path'])
            for mode in ('summary_pin','not_closed','failed','foreign_argv','wrong_source'):
                c=deepcopy(closed);s=deepcopy(summary)
                if mode=='summary_pin':c['resources'][0]['worker_summary']=fake_pin('foreign.json')
                elif mode=='not_closed':c['shared_lock_released_after_owned_closure']=False
                elif mode=='failed':c['resources'][0]['actual_exit_code']=1
                elif mode=='foreign_argv':c['resources'][0]['actual_argv'][1]='unrelated.py'
                else:s['artifacts'][0]['file']=fake_pin('foreign.gguf')
                with self.subTest(mode=mode),patch.object(worker.common,'read',lambda p:s if p=='summary.json' else c),self.assertRaises(ValueError):
                    worker.materialization_proof(cfg,check=lambda p:p['path'])

    def test_failed_child_keeps_partial_and_never_promotes_or_claims_complete(self):
        self.run_simulated_child(1)

    def test_success_requires_real_exit_complete_header_and_preserves_source(self):
        self.run_simulated_child(0)

    def test_missing_source_tensor_is_not_promoted_even_with_valid_exit_and_q4_header(self):
        self.run_simulated_child(0,missing_tensor=True)

    def test_access_denied_on_terminate_still_attempts_kill_and_wait(self):
        class Process:
            def __init__(self):self.returncode=None;self.killed=False
            def poll(self):return self.returncode
            def terminate(self):raise PermissionError('synthetic terminate failure')
            def wait(self,**kwargs):
                if not self.killed:raise worker.subprocess.TimeoutExpired('synthetic',1)
                self.returncode=-9;return -9
            def kill(self):self.killed=True
        p=Process();cleanup=worker.close_owned_child(p)
        self.assertTrue(p.killed);self.assertTrue(cleanup['confirmed_closed'])
        self.assertIn({'operation':'terminate','type':'PermissionError'},cleanup['errors'])
        self.assertEqual(['kill'],cleanup['actions'])

    def run_simulated_child(self,exit_code,missing_tensor=False):
        with tempfile.TemporaryDirectory() as folder:
            cfg=self.config(folder);output=Path(cfg['output_root'])
            cfg['projector_source']['path']=str(Path(folder)/'source-projector.gguf')
            Path(cfg['projector_source']['path']).write_bytes(tiny_gguf(file_type=7,kind=8,extra_tensor=missing_tensor))
            source={'backend':{'quantizer':{'path':str(Path(folder)/'quantize.exe')}}}
            class Process:
                def __init__(self,argv,**kwargs):
                    Path(argv[-3]).write_bytes(tiny_gguf());self.returncode=exit_code
                def wait(self,**kwargs):return self.returncode
                def poll(self):return self.returncode
            def check(pin):return Path(pin['path'])
            with patch.object(worker.common,'require_HQ'),patch.object(worker,'validate_config',return_value=(output,datetime.now(timezone.utc).timestamp()+3600)),\
                 patch.object(worker,'materialization_proof',return_value=(source,{})),patch.object(worker.common,'checked',check),\
                 patch.object(worker.subprocess,'Popen',Process):
                if exit_code or missing_tensor:
                    with self.assertRaises(RuntimeError):worker.run_quantization(cfg,output,fake_pin('config.json'))
                else:worker.run_quantization(cfg,output,fake_pin('config.json'))
            summary=json.loads((output/'SUMMARY.json').read_text(encoding='utf8'))
            self.assertEqual(1,summary['quantization_started']);self.assertEqual(0,summary['model_calls'])
            self.assertEqual(0,summary['source_image_decodes']);self.assertEqual(0,summary['optimizer_updates'])
            if exit_code or missing_tensor:
                self.assertEqual('FAILED',summary['status']);self.assertEqual(0,summary['quantization_completed'])
                self.assertIsNone(summary['quantized_projector']);self.assertFalse((output/cfg['output_filename']).exists())
                self.assertTrue((output/(cfg['output_filename']+'.partial')).exists())
            else:
                self.assertEqual('COMPLETE',summary['status']);self.assertEqual(1,summary['quantization_completed'])
                self.assertTrue((output/cfg['output_filename']).exists());self.assertTrue(summary['child_closed'])

if __name__=='__main__':unittest.main()
