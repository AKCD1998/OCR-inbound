"""HQ-only bounded import/IO diagnosis; never loads images or model weights."""
from __future__ import annotations
import argparse
import faulthandler
import importlib
import importlib.machinery
import importlib.metadata
import json
import os
from pathlib import Path
import time
from component_common import verify_admission,save,pin

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--modules',default='numpy,cv2');p.add_argument('--vendor',type=Path)
    p.add_argument('--admission',type=Path,required=True);p.add_argument('--admission-sha256',required=True)
    a=p.parse_args();verify_admission(a.admission,a.admission_sha256,__file__,'runtime-diagnostic')
    names=a.modules.split(',')
    if not names or any(n not in ('numpy','cv2','paddle','paddlex','torch','transformers') for n in names):raise ValueError('Only selected SDK imports')
    if a.vendor:
        import sys
        sys.path.insert(0,str(a.vendor.resolve()))
    folder=a.output.parent;folder.mkdir(parents=True,exist_ok=True)
    trace=folder/'file-reads.jsonl';phases=folder/'import-phases.jsonl'
    begin=time.monotonic();records=[];reader=importlib.machinery.SourceFileLoader.get_data
    with trace.open('x',encoding='utf-8') as stream,phases.open('x',encoding='utf-8') as phase:
        def log(f,value):f.write(json.dumps(value,ensure_ascii=False)+'\n');f.flush()
        def traced(self,path):
            at=time.monotonic();log(stream,{'event':'read_started','file':str(path),'at':at-begin})
            try:
                data=reader(self,path)
                log(stream,{'event':'read_complete','file':str(path),'seconds':time.monotonic()-at,'bytes':len(data)})
                return data
            except BaseException as exc:
                log(stream,{'event':'read_error','file':str(path),'seconds':time.monotonic()-at,'type':type(exc).__name__});raise
        importlib.machinery.SourceFileLoader.get_data=traced
        faulthandler.dump_traceback_later(20,repeat=True)
        try:
            for name in names:
                at=time.monotonic();log(phase,{'module':name,'event':'import_started','at':at-begin})
                m=importlib.import_module(name)
                if name=='cv2':m.setNumThreads(1)
                if name=='numpy':
                    values=m.arange(4,dtype=m.int64).reshape(2,2)
                    if int(values.sum())!=6:raise ValueError('Native ndarray arithmetic failed')
                item={'module':name,'event':'import_complete','seconds':time.monotonic()-at,
                      'file':str(m.__file__),'version':getattr(m,'__version__',None)}
                records.append(item);log(phase,item)
        finally:
            importlib.machinery.SourceFileLoader.get_data=reader;faulthandler.cancel_dump_traceback_later()
    save(a.output,{'contract':'document-ai-runtime-diagnostic.v1','status':'COMPLETE','imports':records,
                   'elapsed_seconds':time.monotonic()-begin,'trace':pin(trace),'phases':pin(phases),
                   'model_calls':0,'image_decodes':0,'optimizer_updates':0,'frozen_runtime_modified':False})

if __name__=='__main__':main()
