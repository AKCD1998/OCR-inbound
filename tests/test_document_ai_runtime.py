"""No SDKs/model data: real engine argument and inventory slice contracts."""
import importlib.util
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULES=Path(__file__).resolve().parents[1]/'experiments/document_ai'
sys.path.insert(0,str(MODULES))
import component_worker as worker

class RuntimeRepairContracts(unittest.TestCase):
    def test_native_runner_receives_one_thread_and_plain_paddle(self):
        calls=[]
        def create_model(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(runner=SimpleNamespace(_config={'cpu_threads':1,'run_mode':'paddle','device_type':'cpu'}))
        fake_modules={'cv2':SimpleNamespace(setNumThreads=lambda n:None),'paddlex':SimpleNamespace(),
            'paddlex.inference':SimpleNamespace(),'paddlex.inference.models':SimpleNamespace(create_predictor=create_model),
            'paddlex.utils':SimpleNamespace(),'paddlex.utils.flags':SimpleNamespace(EAGER_INITIALIZATION=False)}
        with patch.dict(sys.modules,fake_modules):
            result=worker.PaddleLayout(Path('isolated-model-data'))
        self.assertEqual(calls[0]['engine_config'],{'cpu_threads':1,'run_mode':'paddle'})
        self.assertNotIn('cpu_threads',set(calls[0])-{'engine_config'})
        self.assertEqual(result.runner_settings['cpu_threads'],1)

    def test_runner_with_unbound_thread_default_is_rejected(self):
        fake=SimpleNamespace(runner=SimpleNamespace(_config={'cpu_threads':10,'run_mode':'paddle','device_type':'cpu'}))
        fake_modules={'cv2':SimpleNamespace(setNumThreads=lambda n:None),'paddlex':SimpleNamespace(),
            'paddlex.inference':SimpleNamespace(),'paddlex.inference.models':SimpleNamespace(create_predictor=lambda **k:fake),
            'paddlex.utils':SimpleNamespace(),'paddlex.utils.flags':SimpleNamespace(EAGER_INITIALIZATION=False)}
        with patch.dict(sys.modules,fake_modules):
            with self.assertRaises(ValueError):worker.PaddleLayout(Path('isolated-model-data'))

    def test_full_shards_cover_the_same_484_pages_exactly_once(self):
        plan={'mode':'full','tasks':[{'page':n} for n in range(1,485)]}
        all_pages=[]
        for start in range(0,484,64):all_pages.extend(t['page'] for t in worker.select_tasks(plan,start,min(64,484-start)))
        self.assertEqual(all_pages,list(range(1,485)))
        with self.assertRaises(ValueError):worker.select_tasks(plan,480,10)

    def test_canary_cannot_be_silently_resliced(self):
        plan={'mode':'canary','tasks':[{'page':2}]}
        self.assertEqual(worker.select_tasks(plan),plan['tasks'])
        with self.assertRaises(ValueError):worker.select_tasks(plan,0,1)

class SupervisorLockReceiptTests(unittest.TestCase):
    def test_busy_lock_does_not_claim_it_was_released(self):
        import serial_supervisor as supervisor
        @contextmanager
        def busy(*args):
            raise PermissionError('another job owns this lock')
            yield
        class Registry:
            last_cleanup=None
            def __init__(self,*args):pass
            def cleanup(self):return {'confirmed_all_known_owned_exited':True}
        ownership=SimpleNamespace(OwnedRegistry=Registry,safe_owned_lock=busy,LOCK='not-a-real-lock')
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'config.json';config.write_text('{}',encoding='utf-8')
            output=Path(directory)/'run'
            data={'pins':{'ownership':{'path':'ownership'},'metadata_probe':{'path':'probe'}}}
            argv=['supervisor','--config',str(config),'--config-sha256',supervisor.sha(config),'--execute']
            with patch.object(sys,'argv',argv),patch.object(supervisor,'read',return_value=data),patch.object(supervisor,'validate',return_value=output),patch.object(supervisor,'require_HQ'),patch.object(supervisor,'load',side_effect=[ownership,SimpleNamespace()]):
                with self.assertRaises(SystemExit):supervisor.main()
            result=json.loads((output/'RESULT.json').read_text(encoding='utf-8'))
            self.assertEqual(result['status'],'FAILED')
            self.assertFalse(result['shared_lock_acquired'])
            self.assertFalse(result['shared_lock_released_after_owned_closure'])
            self.assertEqual(result['resources'],[])

if __name__=='__main__':unittest.main()
