from copy import deepcopy
import importlib.util
from pathlib import Path
import json
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from experiments.document_ai import glm_load_diagnostic_worker as d

class Time:
    value=0
    def clock(self):return self.value
    def sleep(self,n):self.value+=n

def config():return {'contract':d.CONTRACT,'resource_policy':dict(d.CAPS),
    'optimizer_updates_allowed':False,'production_activation':False,'source_image_decodes_allowed':False,
    'generation_requests_allowed':False,'load_timeout_seconds':240,'sample_interval_seconds':5,
    'maximum_seconds':360,'log_verbosity':5,'cutoff_utc':'2026-10-30T09:30:00+00:00',
    'sources':{k:{'path':'D:/exact/'+k,'sha256':v} for k,v in d.SOURCE_HASHES.items()}}

def owned():
    return SimpleNamespace(pid=45,create_time=lambda:100,cpu_times=lambda:SimpleNamespace(user=2.5,system=.25),
       io_counters=lambda:SimpleNamespace(read_bytes=42,write_bytes=8,read_count=2,write_count=1),
       memory_info=lambda:SimpleNamespace(rss=10000),num_threads=lambda:3,
       net_connections=lambda kind:[SimpleNamespace(status='LISTEN',laddr=SimpleNamespace(ip='127.0.0.1',port=12222))])

def source_graph():
    directory=Path(d.__file__).parent
    names={'common':'component_common.py','backend':'glm_backend.py','evidence':'glm_evidence.py',
           'quant_verifier':'glm_quantize_worker.py','native':'glm_native_worker.py'}
    return {key:d.pin(directory/name) for key,name in names.items()}

class DiagnosticTests(unittest.TestCase):
    def test_exact_policy_limits_and_no_generation(self):
        self.assertIsNotNone(d.validate_config(config()))
        for key,value in [('load_timeout_seconds',241),('sample_interval_seconds',1),('log_verbosity',4),
                          ('generation_requests_allowed',True),('source_image_decodes_allowed',True),('maximum_seconds',600)]:
            c=config();c[key]=value
            with self.assertRaises(ValueError):d.validate_config(c)
        c=config();c['resource_policy']['maximum_own_process_tree_RSS_bytes']+=1
        with self.assertRaises(ValueError):d.validate_config(c)
    def test_only_verbosity_changes_backend_command(self):
        b=SimpleNamespace(server_command=Mock(return_value=['EXE','--threads','1','--no-warmup']))
        cfg={'context_tokens':1024,'max_output_tokens':512,'image_max_tokens':256}
        result=d.diagnostic_argv(b,{'server':{'path':'EXE'}},{'decoder':{'path':'D'},'projector':{'path':'P'}},cfg,12222)
        self.assertEqual(result,['EXE','--threads','1','--no-warmup','--log-verbosity','5'])
        self.assertEqual(b.server_command.call_args.kwargs,{'port':12222,'context_tokens':1024,'max_output_tokens':512,'image_max_tokens':256})
    def test_process_sample_bound_to_creation_and_server_scope(self):
        value=d.process_sample(owned(),100,5)
        self.assertEqual(value['cpu_user_seconds'],2.5);self.assertEqual(value['read_bytes'],42)
        self.assertEqual(value['scope'],'EXACT_SERVER_PROCESS_NOT_TOTAL_OWNED_TREE')
        with self.assertRaises(ValueError):d.process_sample(owned(),101,5)
    def test_timeout_no_generation_and_samples_every_five_seconds(self):
        clock=Time();samples=[];urls=[]
        def health(url,timeout):urls.append(url);raise TimeoutError('loading')
        proc=SimpleNamespace(poll=lambda:None)
        outcome,elapsed,n=d.monitor(proc,owned(),100,'http://127.0.0.1:12222',10,5,samples.append,health,clock.clock,clock.sleep)
        self.assertEqual((outcome,elapsed,n),('LOAD_TIMEOUT',10,3))
        self.assertEqual([x['elapsed_seconds'] for x in samples],[0,5,10])
        self.assertTrue(all(x.endswith('/health') for x in urls))
    def test_ready_requires_owned_listener_and_exits_without_generation(self):
        clock=Time();proc=SimpleNamespace(poll=lambda:None)
        outcome,_,_=d.monitor(proc,owned(),100,'http://127.0.0.1:12222',240,5,lambda _:None,
            lambda *a,**kw:{'status':'ok'},clock.clock,clock.sleep)
        self.assertEqual(outcome,'MODEL_AND_VISION_READY')
        wrong=owned();wrong.net_connections=lambda kind:[]
        with self.assertRaises(ValueError):d.monitor(proc,wrong,100,'http://127.0.0.1:12222',240,5,lambda _:None,
            lambda *a,**kw:{'status':'ok'},clock.clock,clock.sleep)
    def test_terminate_error_does_not_skip_kill_wait(self):
        with d.original_modules(source_graph()) as modules:
            close=modules['quant_verifier'].close_owned_child
            p=Mock();p.returncode=None;p.poll.side_effect=[None,None,-9]
            p.terminate.side_effect=PermissionError('denied');p.wait.side_effect=[TimeoutError('wait'),None]
            result=close(p)
            self.assertTrue(result['confirmed_closed']);p.kill.assert_called_once();self.assertEqual(p.wait.call_count,2)
            p=Mock();p.poll.return_value=None;p.returncode=None
            p.terminate.side_effect=PermissionError();p.kill.side_effect=PermissionError();p.wait.side_effect=TimeoutError()
            self.assertFalse(close(p)['confirmed_closed'])
            p=Mock();p.poll.side_effect=OSError('uncertain');p.wait.side_effect=TimeoutError()
            self.assertFalse(close(p)['confirmed_closed']);p.terminate.assert_called_once();p.kill.assert_called_once()
    def test_original_module_activation_restores_prior_aliases_on_error(self):
        names=['component_common','glm_backend','glm_evidence','glm_quantize_worker','_glm_load_diagnostic_original_native']
        before={name:sys.modules.get(name) for name in names}
        with tempfile.TemporaryDirectory() as t:
            pins={}
            for key in ('common','backend','evidence','quant_verifier','native'):
                p=Path(t)/(key+'.py');p.write_text("raise RuntimeError('synthetic')" if key=='evidence' else 'VALUE=1',encoding='utf-8');pins[key]=d.pin(p)
            with self.assertRaises(RuntimeError):
                with d.original_modules(pins):pass
        for name in names:self.assertIs(sys.modules.get(name),before[name])
    def test_pristine_isolated_import_actual_dependency_graph(self):
        sources=source_graph()
        script="""import importlib.util,json,sys
s=importlib.util.spec_from_file_location('load_probe',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
before=set(sys.modules)
with m.original_modules(json.loads(sys.argv[2])) as modules:
 assert modules['native'].close_owned_child is modules['quant_verifier'].close_owned_child
 assert modules['native'].backend is modules['backend']
 assert modules['native'].evidence is modules['evidence']
assert 'glm_quantize_worker' not in sys.modules
assert not any(x in sys.modules for x in ('psutil','PIL','paddle','torch','transformers'))
print('PURE_IMPORT_GRAPH_PASS')
"""
        r=subprocess.run([sys.executable,'-I','-S','-B','-c',script,str(Path(d.__file__)),json.dumps(sources)],
            text=True,capture_output=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),'PURE_IMPORT_GRAPH_PASS')

if __name__=='__main__':unittest.main()
