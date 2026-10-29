"""Counterbalanced data-read probe of 32 approved source files; never executes code."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import sys
import threading
import time
from component_common import checked,read,pin,save,verify_admission

GROUPS=('CPython_stdlib','torch','sympy','torchvision','transformers','numpy','cv2','docling_ibm_models')


def source_group(path):
    value=str(path).replace('\\','/')
    return value.split('/site-packages/',1)[1].split('/',1)[0] if '/site-packages/' in value else 'CPython_stdlib'


def select_sources(manifest):
    grouped={name:[] for name in GROUPS}
    for record in manifest['cached_modules']:
        group=source_group(record['source']['path'])
        if group in grouped:
            if record.get('compile_source_bytes_sha256')!=record['source']['sha256']:raise ValueError('Approved compile/source pin differs')
            grouped[group].append(record['source'])
    selected=[]
    for group in GROUPS:
        values=sorted(grouped[group],key=lambda x:x['path'])
        if len(values)<4:raise ValueError('Four registered sources required in dependency group '+group)
        selected.extend({'group':group,'source':values[n*len(values)//4]} for n in range(4))
    if len(selected)!=32 or len({x['source']['path'] for x in selected})!=32:raise ValueError('Exactly32 distinct registered sources required')
    return selected


def measure(source,method,reader=None):
    if reader is None:
        if method=='SourceFileLoader_open_code':
            reader=lambda path:importlib.machinery.SourceFileLoader('unexecuted_source_read_probe',path).get_data(path)
        elif method=='ordinary_binary_read':
            def reader(path):
                with open(path,'rb') as stream:return stream.read()
        else:raise ValueError('Unknown read method')
    began=time.monotonic();cpu=time.process_time();data=reader(source['path'])
    observation={'method':method,'read_wall_seconds':time.monotonic()-began,'read_CPU_seconds':time.process_time()-cpu,'bytes':len(data)}
    began=time.monotonic();cpu=time.process_time();digest=hashlib.sha256(data).hexdigest()
    observation.update(SHA_wall_seconds=time.monotonic()-began,SHA_CPU_seconds=time.process_time()-cpu,
                       actual_sha256=digest,expected_sha256=source['sha256'],SHA_matches=digest==source['sha256'])
    if digest!=source['sha256']:raise ValueError('Actual live source bytes differ from registered SHA')
    return data,observation


def run_pairs(selected,emit=lambda row:None,readers=None):
    methods=('SourceFileLoader_open_code','ordinary_binary_read');rows=[]
    for number,item in enumerate(selected):
        # Each file sees both AB and BA; alternate which order goes first.
        for repeat in range(2):
            order=methods if (number+repeat)%2==0 else methods[::-1];buffers=[]
            for position,method in enumerate(order):
                data,observed=measure(item['source'],method,None if readers is None else readers[method]);buffers.append(data)
                row=dict(observed,source=item['source'],group=item['group'],file_index=number,round=repeat,
                         position=position,order='AB' if order==methods else 'BA')
                rows.append(row);emit(row)
            if buffers[0]!=buffers[1]:raise ValueError('Read mechanisms returned different actual bytes')
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache-manifest',type=Path,required=True)
    p.add_argument('--cache-manifest-sha256',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--admission',type=Path,required=True);p.add_argument('--admission-sha256',required=True)
    a=p.parse_args();verify_admission(a.admission,a.admission_sha256,__file__,'docling-source-read-AB')
    output=a.output.resolve()
    if output.drive.upper()!='D:' or 'OCR-Experiments' not in output.parts or output.exists():raise ValueError('New isolated HQ output required')
    output.mkdir(parents=True,exist_ok=False);began=time.monotonic()
    def emit(row):
        sys.stdout.write('SOURCE_READ_AB '+json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');sys.stdout.flush()
    def timeout():
        emit({'phase':'WORKER_DEADLINE_480','elapsed_seconds':time.monotonic()-began,'model_calls':0});os._exit(125)
    timer=threading.Timer(480,timeout);timer.daemon=True;timer.start()
    try:
        manifest_pin={'path':str(a.cache_manifest),'sha256':a.cache_manifest_sha256};manifest=read(checked(manifest_pin))
        selected=select_sources(manifest)
        save(output/'SELECTED_SOURCES.json',{'sources':selected,'files':32,'groups':dict(Counter(x['group'] for x in selected)),
                                            'pre_read_source_hashing':False,'counterbalanced_rounds_per_file':2})
        rows=run_pairs(selected,emit)
        save(output/'SUMMARY.json',{'contract':'document-ai-source-read-AB.v1','status':'COMPLETE','worker':pin(__file__),
             'cache_manifest':manifest_pin,'files':32,'read_calls':len(rows),'counterbalanced_rounds_per_file':2,
             'rows':rows,'all_returned_buffers_SHA_verified':True,'all_pairs_returned_identical_bytes':True,
             'elapsed_seconds':time.monotonic()-began,'maximum_worker_seconds':480,'model_calls':0,'model_constructs':0,
             'model_weight_loads':0,'source_image_decodes':0,'optimizer_updates':0,'SDK_imports':0,'code_execution_from_sources':0,
             'no_hardware_or_security_product_cause_attribution':True,'guard_changes':False})
    finally:timer.cancel()


if __name__=='__main__':main()
