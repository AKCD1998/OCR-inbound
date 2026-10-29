"""Bounded model-free import I/O observation; exact cache guard stays active."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import importlib.machinery
import json
import os
from pathlib import Path
import sys
import threading
import time
from component_common import checked,pin,save,verify_admission
from python_cache import apply_cache


class IOTrace:
    def __init__(self):
        self.started=time.monotonic();self.cpu_started=time.process_time()
        self.state={'raw_calls':0,'raw_wall_seconds':0.,'raw_CPU_seconds':0.,'guard_calls':0,
                    'guard_wall_seconds':0.,'guard_CPU_seconds':0.,'source_bytes':0,'PYC_bytes':0,
                    'resource_bytes':0,'read_errors':0,'guard_errors':0,'current_raw':None,'current_guard':None,
                    'raw_exception_types':{},'guard_exception_types':{},'last_raw':None,'last_guard':None}

    def wrap(self,original,guarded=False):
        state=self.state;prefix='guard' if guarded else 'raw'
        def observed(loader,path):
            began=time.monotonic();cpu=time.process_time()
            state['current_'+prefix]={'path':os.fsdecode(path),'module_source':str(getattr(loader,'path','')),
                                      'started_seconds':began-self.started}
            try:
                value=original(loader,path)
                if not guarded:
                    suffix=str(path).lower();kind='PYC' if suffix.endswith('.pyc') else 'source' if suffix.endswith('.py') else 'resource'
                    state[kind+'_bytes']+=len(value)
                return value
            except BaseException as error:
                state['guard_errors' if guarded else 'read_errors']+=1
                types=state[prefix+'_exception_types'];name=type(error).__name__;types[name]=types.get(name,0)+1
                raise
            finally:
                elapsed=time.monotonic()-began
                state['last_'+prefix]={'path':os.fsdecode(path),'module_source':str(getattr(loader,'path','')),'wall_seconds':elapsed}
                state[prefix+'_calls']+=1;state[prefix+'_wall_seconds']+=elapsed
                state[prefix+'_CPU_seconds']+=time.process_time()-cpu;state['current_'+prefix]=None
        return observed

    def snapshot(self,phase):
        value={k:dict(v) if isinstance(v,dict) else v for k,v in self.state.items()}
        value.update(phase=phase,elapsed_seconds=time.monotonic()-self.started,
                     process_CPU_seconds=time.process_time()-self.cpu_started,
                     guarded_minus_raw_wall_seconds=value['guard_wall_seconds']-value['raw_wall_seconds'],
                     model_calls=0,model_constructs=0,model_weight_loads=0,source_image_decodes=0,optimizer_updates=0,
                     utc=datetime.now(timezone.utc).isoformat())
        return value


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache-manifest',type=Path,required=True);p.add_argument('--cache-manifest-sha256',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--admission',type=Path,required=True);p.add_argument('--admission-sha256',required=True)
    a=p.parse_args();verify_admission(a.admission,a.admission_sha256,__file__,'docling-import-diagnostic')
    manifest=checked({'path':str(a.cache_manifest),'sha256':a.cache_manifest_sha256})
    output=a.output.resolve()
    if output.drive.upper()!='D:' or 'OCR-Experiments' not in output.parts or output.exists():raise ValueError('New isolated HQ diagnostic output required')
    output.mkdir(parents=True,exist_ok=False);trace=IOTrace();phase='CACHE_SELECTION_STARTED';stop=threading.Event()
    def emit(label):
        sys.stderr.write('DOCAI_IMPORT_IO '+json.dumps(trace.snapshot(label),ensure_ascii=False,allow_nan=False)+'\n');sys.stderr.flush()
    def heartbeat():
        while not stop.wait(15):emit(phase)
    def timeout():
        emit('SDK_IMPORT_DEADLINE_480_SECONDS');os._exit(125)
    timer=threading.Timer(480,timeout);timer.daemon=True;timer.start()
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    loader=importlib.machinery.SourceFileLoader
    loader.get_data=trace.wrap(loader.get_data)
    selected=apply_cache(manifest,a.cache_manifest_sha256)
    loader.get_data=trace.wrap(loader.get_data,guarded=True)
    emit('EXACT_CACHE_GUARD_INSTALLED')
    try:
        phase='CV_IMPORT_STARTED';emit(phase);import cv2
        cv2.setNumThreads(1)
        phase='TORCH_IMPORT_STARTED';emit(phase);import torch
        torch.set_num_threads(1);torch.set_num_interop_threads(1)
        phase='TRANSFORMERS_IMPORT_STARTED';emit(phase)
        from transformers import DFineForObjectDetection,RTDetrImageProcessor
        phase='TABLE_SDK_IMPORT_STARTED';emit(phase)
        from docling_ibm_models.tableformer.data_management.tf_predictor import TFPredictor
        phase='NATIVE_ABI_STARTED';emit(phase);import numpy as np
        data=np.arange(4,dtype=np.int64).reshape(2,2);tensor=torch.from_numpy(data)
        if int(tensor.sum().item())!=6 or not np.array_equal(tensor.numpy(),data) or cv2.resize(np.arange(9,dtype=np.uint8).reshape(3,3),(6,6)).shape!=(6,6):raise ValueError('Native ABI roundtrip differs')
        if [torch.get_num_threads(),torch.get_num_interop_threads(),cv2.getNumThreads()]!=[1,1,1] or tensor.device.type!='cpu':raise ValueError('Native CPU1 differs')
        phase='REQUIRED_IMPORTS_AND_ABI_PASSED';emit(phase)
        save(output/'SUMMARY.json',dict(trace.snapshot(phase),contract='document-ai-import-io-diagnostic.v1',status='COMPLETE',
             worker=pin(__file__),runtime_cache=selected,native_ABI_passed=True,CPU_threads=1,
             versions={'numpy':np.__version__,'torch':torch.__version__,'cv2':cv2.__version__},
             observer_changes_returned_bytes_or_exceptions=False,maximum_SDK_import_seconds=480))
    finally:
        timer.cancel();stop.set();thread.join(timeout=1)


if __name__=='__main__':main()
