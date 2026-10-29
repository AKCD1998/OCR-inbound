"""Optional verified CPython bytecode cache, outside the accepted environment.

Warmup imports only the needed SDK classes and tests native ABI. It constructs
no model, opens no image and reads no weight. Native consumers use -B and read
the verified cache without writing it. Source/bytecode SHA checks remain active.
"""
from __future__ import annotations
import argparse
import atexit
import base64
import csv
import faulthandler
import hashlib
import importlib.metadata
import importlib.util
import importlib.machinery
import os
from pathlib import Path
import sys
import time
from component_common import checked,pin,read,save,sha,require_HQ,verify_admission

CONTRACT='document-ai-verified-python-cache.v1'
SOURCE_INDEX='document-ai-approved-python-source-index.v1'

def path_key(path):
    # Paths were frozen by the producer. Do not perform thousands of extra
    # filesystem-resolve calls before every actual import.
    return os.path.normcase(os.path.abspath(os.fsdecode(path)))

def under(path,root):
    try:return os.path.commonpath([path_key(path),path_key(root)])==path_key(root)
    except ValueError:return False

def distribution_record_path(dist):
    # Some accepted Windows wheels list the same RECORD with both separator
    # styles. Preserve one physical origin; distinct metadata records conflict.
    candidates={}
    for relative in dist.files or []:
        if not str(relative).replace('\\','/').endswith('.dist-info/RECORD'):continue
        path=Path(dist.locate_file(relative))
        candidates[path_key(path)]=path
    if len(candidates)!=1:raise ValueError('One accepted physical distribution RECORD required')
    return next(iter(candidates.values()))

def distribution_source_hashes(record_path,dist,environment):
    grouped={}
    for relative,hashed,size in csv.reader(Path(record_path).read_text(encoding='utf-8-sig').splitlines()):
        if not relative.endswith('.py'):continue
        path=Path(os.path.abspath(str(dist.locate_file(relative))))
        if not under(path,environment):raise ValueError('Distribution source escapes accepted environment')
        item=grouped.setdefault(path_key(path),{'path':path,'hashes':set()})
        if not hashed:continue
        if not hashed.startswith('sha256='):raise ValueError('Expected exact SHA256 for Python source: '+relative)
        value=hashed.split('=',1)[1];raw=base64.urlsafe_b64decode(value+'='*((4-len(value)%4)%4))
        if len(raw)!=32:raise ValueError('Invalid distribution source digest')
        item['hashes'].add(raw.hex())
    result=[]
    for key,item in sorted(grouped.items()):
        if len(item['hashes'])!=1:raise ValueError('One exact SHA256 required across physical Python source aliases: '+str(item['path']))
        result.append((item['path'],next(iter(item['hashes']))))
    return result

def cache_identity(manifest,python_pin=None):
    if manifest.get('contract')!=CONTRACT or manifest.get('status')!='COMPLETE':raise ValueError('Completed verified Python cache required')
    if manifest.get('python')!=(python_pin or pin(sys.executable)) or manifest.get('cache_tag')!=sys.implementation.cache_tag or manifest.get('bytecode_magic')!=importlib.util.MAGIC_NUMBER.hex():
        raise ValueError('Cache interpreter/bytecode identity differs')

def install_lazy_checks(manifest,index,loader_type=importlib.machinery.SourceFileLoader):
    """Hash the exact bytes returned to CPython, without replacing those bytes."""
    cache_identity(manifest)
    if index.get('contract')!=SOURCE_INDEX or index.get('python')!=manifest['python']:
        raise ValueError('Approved source index differs from accepted interpreter')
    expected={}
    for record in index['sources']:
        key=path_key(record['source']['path']);value=record['source']['sha256']
        if key in expected and expected[key]!=value:raise ValueError('Conflicting approved source hashes')
        expected[key]=value
    caches={}
    for record in manifest['cached_modules']:
        key=path_key(record['cache']['path']);source=record['source']
        if key in caches or not under(key,manifest['cache_root']) or expected.get(path_key(source['path']))!=source['sha256']:
            raise ValueError('Conflicting or unregistered cache/source binding')
        caches[key]=record
    if len(caches)!=manifest['cached_module_count'] or not caches:raise ValueError('Cache inventory count differs')
    original=loader_type.get_data
    observed={'verification_mode':'exact_hash_on_actual_import','source_checks':0,'bytecode_checks':0,
              'noncode_resource_reads':0,'unknown_cache_rejections':0,'unknown_source_rejections':0,
              'source_paths':set(),'bytecode_paths':set()}
    def verify_source(path,data):
        key=path_key(path);wanted=expected.get(key)
        if wanted is None:
            observed['unknown_source_rejections']+=1
            raise ImportError('Unregistered Python source: '+os.fsdecode(path))
        if hashlib.sha256(data).hexdigest()!=wanted:raise ImportError('Python source bytes differ: '+os.fsdecode(path))
        observed['source_checks']+=1;observed['source_paths'].add(key)
    def actual_bytes(loader,path):
        # A missing unknown PYC keeps CPython's normal OSError/source fallback.
        # An existing unknown PYC is always refused before it can be executed.
        data=original(loader,path);key=path_key(path)
        if key.endswith('.pyc'):
            record=caches.get(key)
            if not under(key,manifest['cache_root']) or record is None:
                observed['unknown_cache_rejections']+=1
                raise ImportError('Unregistered Python bytecode: '+os.fsdecode(path))
            if getattr(loader,'path',None) is not None and path_key(loader.path)!=path_key(record['source']['path']):
                raise ImportError('Bytecode belongs to another actual source module')
            if hashlib.sha256(data).hexdigest()!=record['cache']['sha256']:raise ImportError('Python bytecode bytes differ: '+os.fsdecode(path))
            # Valid timestamps would otherwise let CPython skip reading source.
            # Verify the paired source on EVERY actual PYC read, before return.
            source_bytes=original(loader,record['source']['path'])
            verify_source(record['source']['path'],source_bytes)
            observed['bytecode_checks']+=1;observed['bytecode_paths'].add(key)
        elif key.endswith('.py'):
            verify_source(path,data)
        else:
            observed['noncode_resource_reads']+=1
        return data
    loader_type.get_data=actual_bytes
    return observed

def owned_cache(path,new=False):
    path=Path(path).resolve()
    if path.drive.upper()!='D:' or 'OCR-Experiments' not in path.parts or new and path.exists():
        raise ValueError('A new isolated HQ D cache is required')
    return path

def verify_cache(manifest,check=checked,python_pin=None):
    cache_identity(manifest,python_pin)
    root=Path(manifest['cache_root']).resolve();expected=set()
    for item in manifest['cached_modules']:
        source=check(item['source']);cache=check(item['cache'])
        with cache.open('rb') as stream:magic=stream.read(4)
        if not Path(cache).resolve().is_relative_to(root) or magic!=importlib.util.MAGIC_NUMBER:
            raise ValueError('Cache path or bytecode magic differs')
        if item.get('compile_source_bytes_sha256') not in (None,item['source']['sha256']):
            raise ValueError('Compiled source bytes no longer equal the installed source')
        expected.add(Path(cache).resolve())
    if not expected or {p.resolve() for p in root.rglob('*.pyc')}!=expected:
        raise ValueError('Missing or unregistered bytecode cache file')
    if len(expected)!=manifest.get('cached_module_count'):raise ValueError('Cache count differs')
    return root

def apply_cache(path,digest):
    require_HQ()
    record={'path':str(Path(path).resolve()),'sha256':digest};manifest=read(checked(record))
    root=owned_cache(manifest['cache_root'])
    if sys.dont_write_bytecode is not True:raise ValueError('Native model cache consumption must remain read-only under -B')
    mode=manifest.get('verification_mode')
    if mode in ('exact_hash_on_actual_import','PYC_blob_with_live_source_SHA_on_every_load'):
        if manifest.get('cache_helper',{}).get('sha256')!=sha(__file__):raise ValueError('Actual lazy cache helper bytes differ from selected manifest')
        index=read(checked(manifest['approved_source_index']))
        if mode=='PYC_blob_with_live_source_SHA_on_every_load':
            checked(manifest['bundle_helper'])
            import bytecode_bundle
            if sha(bytecode_bundle.__file__)!=manifest['bundle_helper']['sha256']:raise ValueError('Actual PYC bundle helper bytes differ')
            activation=bytecode_bundle.activate_bundle(manifest,index,read(checked(manifest['bytecode_blob_index'])))
            observed=activation.observed
            atexit.register(activation.close)
        else:observed=install_lazy_checks(manifest,index)
        if sys.argv.count('--output')==1:
            output=Path(sys.argv[sys.argv.index('--output')+1]).resolve()
            if output.drive.upper()=='D:' and 'OCR-Experiments' in output.parts:
                def audit_receipt():
                    value={k:sorted(v) if isinstance(v,set) else v for k,v in observed.items()}
                    value.update(manifest=record,helper=pin(__file__),read_only=True,
                                 model_calls_by_cache_helper=0,source_image_decodes=0)
                    target=output/'RUNTIME_CACHE_LAZY_AUDIT.json'
                    if not target.exists():save(target,value)
                atexit.register(audit_receipt)
    else:
        root=verify_cache(manifest)
    sys.pycache_prefix=str(root)
    return record

def prepare_lazy_index(args):
    require_HQ();verify_admission(args.admission,args.admission_sha256,__file__,'docling-cache-index')
    previous_pin={'path':str(args.previous_cache_manifest.resolve()),'sha256':args.previous_cache_manifest_sha256}
    previous=read(checked(previous_pin));cache_identity(previous)
    install=read(checked(previous['install_result']))
    if {n:importlib.metadata.version(n) for n in install['installed_metadata']}!=install['installed_metadata']:
        raise ValueError('Accepted installed package metadata differs')
    root=owned_cache(args.index_root,new=True);root.mkdir(parents=True,exist_ok=False)
    expected={};origins=[]
    def add(path,digest,origin):
        key=path_key(path)
        if key in expected and expected[key]['source']['sha256']!=digest:raise ValueError('Source origins disagree: '+str(path))
        expected.setdefault(key,{'source':{'path':os.path.abspath(str(path)),'sha256':digest},'origin':origin})
    for record in previous['cached_modules']:
        add(record['source']['path'],record['source']['sha256'],{'verified_cache_manifest':previous_pin})
    environment=Path(sys.prefix)
    for name in install['installed_metadata']:
        dist=importlib.metadata.distribution(name)
        record_path=distribution_record_path(dist);record_pin=pin(record_path);origins.append({'distribution':name,'RECORD':record_pin})
        for path,digest in distribution_source_hashes(record_path,dist,environment):
            add(path,digest,{'distribution':name,'RECORD':record_pin})
    stdlib=Path(sys.base_prefix)/'Lib';stdlib_snapshot=0
    for folder,dirs,files in os.walk(stdlib):
        dirs[:]=[d for d in dirs if d not in ('site-packages','__pycache__')]
        for name in files:
            if not name.endswith('.py'):continue
            path=Path(folder)/name
            if path_key(path) in expected:continue
            add(path,sha(path),{'accepted_stdlib_snapshot':str(stdlib),'python':previous['python']});stdlib_snapshot+=1
    index={'contract':SOURCE_INDEX,'python':previous['python'],'install_result':previous['install_result'],
           'previous_verified_cache':previous_pin,'distribution_RECORD_origins':origins,
           'stdlib_source_root':str(stdlib),'extra_stdlib_source_snapshots':stdlib_snapshot,
           'sources':[expected[k] for k in sorted(expected)],'source_count':len(expected),
           'model_calls':0,'model_weight_loads':0,'source_image_decodes':0,'optimizer_updates':0}
    index_path=root/'APPROVED_SOURCE_INDEX.json';save(index_path,index)
    selected=dict(previous,verification_mode='exact_hash_on_actual_import',approved_source_index=pin(index_path),
                  previous_verified_cache_manifest=previous_pin,cache_helper=pin(__file__))
    manifest=root/'CACHE_MANIFEST.json';save(manifest,selected)
    result={'contract':'document-ai-cache-index-result.v1','status':'COMPLETE','cache_manifest':pin(manifest),
            'approved_source_index':pin(index_path),'source_count':len(expected),'cached_module_count':previous['cached_module_count'],
            'model_calls':0,'model_weight_loads':0,'model_constructs':0,'source_image_decodes':0,'optimizer_updates':0,
            'frozen_runtime_modified':False,'source_bytes_loaded_by_models':0,'no_bytecode_recompiled':True}
    save(args.output,result);return result

def collect_cache(root,modules,compiled_bytes,allowed_roots):
    """Freeze exactly the bytecode actually generated by required imports."""
    sources={}
    for module in modules:
        filename=getattr(module,'__file__',None)
        if not filename or not filename.endswith('.py'):continue
        source=Path(filename).resolve()
        if not source.is_file() or not any(source.is_relative_to(r) for r in allowed_roots):continue
        cache=Path(importlib.util.cache_from_source(str(source))).resolve()
        if cache.is_file() and cache.is_relative_to(root):sources[cache]=source
    quarantined=[]
    for cache in list(root.rglob('*.pyc')):
        cache=cache.resolve()
        if cache in sources:continue
        if not cache.is_relative_to(root):raise ValueError('Unregistered cache escaped the new root')
        target=(root/'unconfirmed'/cache.relative_to(root)).with_suffix('.pyc.unconfirmed').resolve()
        if not target.is_relative_to(root) or target.exists():raise ValueError('Unsafe cache quarantine target')
        before=pin(cache);target.parent.mkdir(parents=True,exist_ok=True);cache.rename(target)
        quarantined.append({'original':before,'preserved':pin(target),'reason':'not_a_current_required_module'})
    records=[]
    for cache,source in sorted(sources.items(),key=lambda item:str(item[0])):
        source_pin=pin(source);compiled=compiled_bytes.get(str(source))
        if compiled is not None and compiled!=source_pin['sha256']:raise ValueError('Installed source changed while compiling')
        records.append({'source':source_pin,'cache':pin(cache),'compile_source_bytes_sha256':compiled})
    return records,quarantined

def warmup(args):
    require_HQ();verify_admission(args.admission,args.admission_sha256,__file__,'docling-cache')
    install_pin={'path':str(args.install_result.resolve()),'sha256':args.install_result_sha256}
    install=read(checked(install_pin));checked(install['python'])
    if install.get('status')!='COMPLETE' or Path(sys.executable).resolve()!=Path(install['python']['path']).resolve():raise ValueError('Use the accepted isolated environment interpreter')
    actual={name:importlib.metadata.version(name) for name in install['installed_metadata']}
    if actual!=install['installed_metadata']:raise ValueError('Accepted package versions changed')
    root=owned_cache(args.cache_root,new=True);root.mkdir(parents=True,exist_ok=False)
    output=args.output.resolve()
    if output.exists():raise ValueError('Preserve previous warmup results')
    output.mkdir(parents=True,exist_ok=False)
    began=time.monotonic();faulthandler.enable();phases=[];compiled={}
    allowed_roots=[Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve()]
    def audit(event,values):
        if event!='compile' or len(values)<2 or not isinstance(values[0],bytes) or not isinstance(values[1],str):return
        path=Path(values[1])
        if not path.is_absolute():return
        path=path.resolve()
        if any(path.is_relative_to(r) for r in allowed_roots):compiled[str(path)]=hashlib.sha256(values[0]).hexdigest()
    sys.addaudithook(audit)
    sys.pycache_prefix=str(root);sys.dont_write_bytecode=False
    def phase(name):
        record={'phase':name,'elapsed_seconds':time.monotonic()-began};phases.append(record)
        save(output/(str(len(phases)).zfill(2)+'-'+name+'.json'),record)
    phase('CV_IMPORT_STARTED');import cv2
    cv2.setNumThreads(1)
    phase('TORCH_IMPORT_STARTED');import torch
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    phase('LAYOUT_SDK_IMPORT_STARTED')
    from transformers import DFineForObjectDetection,RTDetrImageProcessor
    phase('TABLE_SDK_IMPORT_STARTED')
    from docling_ibm_models.tableformer.data_management.tf_predictor import TFPredictor
    phase('NATIVE_ABI_STARTED');import numpy as np
    data=np.arange(4,dtype=np.int64).reshape(2,2);tensor=torch.from_numpy(data)
    if int(tensor.sum().item())!=6 or not np.array_equal(tensor.numpy(),data) or cv2.resize(np.arange(9,dtype=np.uint8).reshape(3,3),(6,6)).shape!=(6,6):
        raise ValueError('Native NumPy/Torch/OpenCV ABI differs')
    if [torch.get_num_threads(),torch.get_num_interop_threads(),cv2.getNumThreads()]!=[1,1,1] or tensor.device.type!='cpu':raise ValueError('Actual CPU1 binding differs')
    phase('REQUIRED_IMPORTS_AND_ABI_PASSED')
    sys.dont_write_bytecode=True
    records,quarantined=collect_cache(root,list(sys.modules.values()),compiled,allowed_roots)
    manifest={'contract':CONTRACT,'status':'COMPLETE','python':pin(sys.executable),'python_version':sys.version,
              'cache_tag':sys.implementation.cache_tag,'bytecode_magic':importlib.util.MAGIC_NUMBER.hex(),
              'cache_root':str(root),'install_result':install_pin,'installed_metadata':actual,'cached_modules':records,
              'cached_module_count':len(records),'source_bytes':sum(Path(x['source']['path']).stat().st_size for x in records),
              'cache_bytes':sum(Path(x['cache']['path']).stat().st_size for x in records),'quarantined':quarantined,
              'actual_required_imports':['cv2','torch','DFineForObjectDetection','RTDetrImageProcessor','TFPredictor'],
              'native_ABI_passed':True,'CPU_threads':1,'frozen_runtime_modified':False,
              'model_weight_loads':0,'model_constructs':0,'model_calls':0,'source_image_decodes':0,'optimizer_updates':0}
    verify_cache(manifest)
    manifest_path=root/'CACHE_MANIFEST.json';save(manifest_path,manifest)
    if {name:importlib.metadata.version(name) for name in actual}!=actual:raise ValueError('Package metadata changed during cache preparation')
    result={'contract':'document-ai-cache-warmup-result.v1','status':'COMPLETE','cache_manifest':pin(manifest_path),
            'install_result':install_pin,'python':pin(sys.executable),'phases':phases,'elapsed_seconds':time.monotonic()-began,
            'cached_module_count':len(records),'native_ABI_passed':True,'model_weight_loads':0,'model_constructs':0,
            'model_calls':0,'source_image_decodes':0,'optimizer_updates':0,'frozen_runtime_modified':False}
    save(output/'SUMMARY.json',result);return result

def main():
    if '--prepare-lazy-index' in sys.argv:
        p=argparse.ArgumentParser(description='Metadata-only source/bytecode import hash index; no SDK imports')
        p.add_argument('--prepare-lazy-index',action='store_true');p.add_argument('--previous-cache-manifest',type=Path,required=True)
        p.add_argument('--previous-cache-manifest-sha256',required=True);p.add_argument('--index-root',type=Path,required=True)
        p.add_argument('--output',type=Path,required=True);p.add_argument('--admission',type=Path,required=True);p.add_argument('--admission-sha256',required=True)
        print(prepare_lazy_index(p.parse_args()));return
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--install-result',type=Path,required=True);p.add_argument('--install-result-sha256',required=True)
    p.add_argument('--cache-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--admission',type=Path,required=True);p.add_argument('--admission-sha256',required=True);a=p.parse_args()
    print(warmup(a))

if __name__=='__main__':main()
