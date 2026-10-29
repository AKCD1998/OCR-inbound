"""Bounded HQ metadata checks only; does not load a parser, scorer or SDK."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time

def file_sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1048576),b''):digest.update(chunk)
    return digest.hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--config-sha256',required=True);a=p.parse_args()
    if file_sha(a.config)!=a.config_sha256:raise ValueError('Metadata configuration differs')
    config=json.loads(a.config.read_text(encoding='utf-8-sig'))
    if (config.get('approved_by')!='root' or config.get('scope')!='metadata_only_endpoint_assets'
      or config.get('heavy_work_allowed') is not False or config.get('worker_sha256')!=file_sha(__file__)
      or socket.gethostname().casefold()!='server'):raise ValueError('Root HQ metadata-only configuration required')
    sys.path.insert(0,config['bridge_root'])
    from component_common import RESOURCES,checked,pin,read,save
    from eval_assets import preflight
    import psutil
    process=psutil.Process();allowed=process.cpu_affinity();process.cpu_affinity([allowed[0]])
    out=Path(config['output']);out.mkdir(parents=True,exist_ok=False)
    began=time.monotonic();peak=0;minimum=psutil.virtual_memory().available;cache_verified=0;profiles=[];failure=None
    def resources():
        nonlocal peak,minimum
        info=process.memory_info();peak=max(peak,getattr(info,'peak_wset',info.rss));minimum=min(minimum,psutil.virtual_memory().available)
        if time.monotonic()-began>180 or info.rss>RESOURCES['maximum_own_process_tree_RSS_bytes'] or minimum<RESOURCES['stop_free_RAM_bytes']:
            raise RuntimeError('Metadata deadline/RAM/RSS bound reached')
    try:
        if minimum<RESOURCES['minimum_start_free_RAM_bytes']:raise RuntimeError('Metadata start free-RAM gate')
        seen_cache=set()
        for record in config['profiles']:
            resources();profile=read(checked(record));proof=preflight(profile)
            profiles.append({'profile':record,'component':profile['component'],'preflight':proof})
            parent_complete=read(checked(profile['pins']['parent_complete']))
            if parent_complete.get('complete') is not True or parent_complete.get('pages')!=484 or parent_complete.get('prediction_sha256')!=profile['pins']['parent_predictions']['sha256']:
                raise ValueError('Physical saved C4 completion/control binding differs')
            cache_pin=profile['pins']['cache']
            if cache_pin['sha256'] in seen_cache:continue
            seen_cache.add(cache_pin['sha256']);cache=read(checked(cache_pin))
            for page_record in cache['pages']:
                resources();page=read(checked(page_record));g=page['geometry'];flags=page['inference_inputs']
                if (page['page_number']!=page_record['page_number'] or page['source_sha256']!=page_record['source_sha256']
                  or g.get('machine_only') is not True or g.get('vision_LLM_calls')!=0
                  or any(flags.get(k) is not False for k in ('reference','human_answers','Ada','StockDay'))
                  or flags.get('assistant_image_reads')!=0
                  or not all(k in page for k in ('working_tokens','tesseract_working_tokens','targeted_views'))):
                    raise ValueError('Physical retained-cache metadata/source contract differs')
                cache_verified+=1
        forbidden=[name for name in sys.modules if name.split('.')[0] in {'numpy','paddle','paddleocr','paddlex','torch','cv2','PIL','docling','docling_ibm_models','transformers'}]
        if forbidden:raise RuntimeError('SDK was imported during metadata-only checks')
        resources()
    except BaseException as exc:failure={'type':type(exc).__name__,'message':str(exc)}
    sdk_roots=sorted({name.split('.')[0] for name in sys.modules if name.split('.')[0] in {'numpy','paddle','paddleocr','paddlex','torch','cv2','PIL','docling','docling_ibm_models','transformers'}})
    result={'contract':'document-ai-actual-HQ-metadata-preflight.v1','status':'COMPLETE' if failure is None else 'FAILED',
      'failure':failure,'profiles':profiles,'physical_cache_pages_verified_once':cache_verified,
      'elapsed_seconds':time.monotonic()-began,'peak_own_RSS_bytes':peak,'minimum_free_RAM_bytes':minimum,
      'worker':pin(__file__),'config':pin(a.config),'pid':os.getpid(),'creation_time':process.create_time(),
      'cpu_affinity':process.cpu_affinity(),'child_processes_spawned':0,'model_imports':len(sdk_roots),'observed_SDK_modules':sdk_roots,'model_calls':0,
      'image_decodes':0,'reference_answers_loaded':False,'parser_calls':0,'scorer_calls':0,'optimizer_updates':0,
      'metadata_only':True,'new_baseline_read':False}
    save(out/'RESULT.json',result);print(json.dumps(result,ensure_ascii=False))
    if failure:raise SystemExit(1)

if __name__=='__main__':main()
