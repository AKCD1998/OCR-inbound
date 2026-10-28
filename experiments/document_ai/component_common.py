"""Pure metadata, geometry and artifact integrity helpers for isolated trials."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import socket
import sys

RESOURCES = {'CPU_threads': 1, 'minimum_start_free_RAM_bytes': 1983628573,
             'stop_free_RAM_bytes': 1288490188,
             'maximum_own_process_tree_RSS_bytes': 1073741824}
CONTROLLER_SHA256 = '07b918d7fe2cd8749f73c57aea6e8842aa2db93613788af90d2f2b40bb0bda4c'

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def pin(path):return {'path':str(Path(path).resolve()),'sha256':sha(path)}
def checked(record):
    path=Path(record['path']).resolve()
    if sha(path)!=record['sha256']:raise ValueError('Input bytes differ: '+str(path))
    return path

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.flush();os.fsync(stream.fileno())

def require_HQ():
    if socket.gethostname().casefold()!='server':raise ValueError('Heavy model work is 000HQ/SERVER only')

def valid_box(box,size):
    return isinstance(box,(list,tuple)) and len(box)==4 and all(type(x) in (int,float) and math.isfinite(x) for x in box) and 0<=box[0]<box[2]<=size[0] and 0<=box[1]<box[3]<=size[1]

def contains(outer,inner):return outer[0]<=inner[0] and outer[1]<=inner[1] and outer[2]>=inner[2] and outer[3]>=inner[3]

def rotate_box(box,size,angle,inverse=False):
    """Exact rectangular coordinate transform; no clipping or angle guessing."""
    if angle not in (0,90,180,270) or not valid_box(box,size):raise ValueError('Invalid explicit source frame')
    w,h=size;x0,y0,x1,y1=box
    if inverse:
        # size is the ORIGINAL source size; input belongs to its upright frame.
        raise ValueError('Use restore_box for inverse geometry')
    return {0:list(box),90:[y0,w-x1,y1,w-x0],180:[w-x1,h-y1,w-x0,h-y0],270:[h-y1,x0,h-y0,x1]}[angle]

def restore_box(box,original_size,angle):
    w,h=original_size;upright=[h,w] if angle in (90,270) else [w,h]
    if angle not in (0,90,180,270) or not valid_box(box,upright):raise ValueError('Out-of-frame native box; never clip')
    x0,y0,x1,y1=box
    result={0:list(box),90:[w-y1,x0,w-y0,x1],180:[w-x1,h-y1,w-x0,h-y0],270:[y0,h-x1,y1,h-x0]}[angle]
    if not valid_box(result,original_size):raise ValueError('Invalid restored source box')
    return result

def component_preflight(registry,component,available_ram=None,packages=None):
    spec=registry['components'][component]
    models=[registry['models'][x] for x in spec['models']]
    weights=sum(m['weight_bytes'] for m in models)
    installed={}
    for package in spec['required_distributions']:
        if packages is not None:installed[package]=packages.get(package)
        else:
            try:installed[package]=importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:installed[package]=None
    reasons=[]
    if weights>RESOURCES['maximum_own_process_tree_RSS_bytes']:reasons.append('selected_native_weights_alone_exceed_owned_RSS_cap')
    if available_ram is not None and available_ram<RESOURCES['minimum_start_free_RAM_bytes']:reasons.append('fresh_start_free_RAM_gate')
    missing=[k for k,v in installed.items() if v is None]
    if missing:reasons.append('missing_isolated_dependencies')
    return {'component':component,'admitted_for_bounded_canary':not reasons,
            'blocked_reasons':reasons,'required_artifact_bytes':sum(m['artifact_bytes'] for m in models),
            'native_weight_bytes':weights,'actual_RAM_requirement_not_inferred_from_weight_bytes':True,
            'packages':installed,'missing_distributions':missing,'resource_policy':RESOURCES,
            'model_imports':0,'model_calls':0,'optimizer_updates':0,
            'precision':spec.get('selected_precision','native_model_precision')}

def validate_task(task):
    if task.get('source_frame')!='original_image' or task.get('machine_only') is not True:raise ValueError('Original source/machine-only task required')
    if type(task['page']) is not int or not 1<=task['page']<=484:raise ValueError('Page outside fixed source inventory')
    size=task['source_size']
    if len(size)!=2 or any(type(v) is not int or v<=0 for v in size):raise ValueError('Invalid source size')
    seen=set()
    for token in task.get('tokens',[]):
        if set(token)-{'id','text','bbox','engine','confidence'}:raise ValueError('Token contains non-machine evidence fields')
        if not token.get('id') or token['id'] in seen or not isinstance(token.get('text'),str):raise ValueError('Invalid/duplicate original token')
        seen.add(token['id'])
        if not valid_box(token['bbox'],size):raise ValueError('Machine token outside source')
        if str(token.get('engine','')).upper().startswith(('HUMAN','ASSISTANT','USER','GOLD','SILVER')):raise ValueError('Manual/canonical text is not OCR input')
    return task

def attach_tokens(cells,tokens,size):
    """Keep whole-token ownership unique; never trim text or borrow a neighbour."""
    result=[];rejected=[]
    for i,cell in enumerate(cells):
        if not valid_box(cell.get('bbox'),size):
            rejected.append({'index':i,'reason':'cell_outside_source_or_degenerate'});continue
        result.append({**cell,'token_ids':[],'raw_text':None,'association_verified':False})
    ambiguous=[]
    for token in tokens:
        matches=[i for i,c in enumerate(result) if contains(c['bbox'],token['bbox'])]
        if len(matches)==1:result[matches[0]]['token_ids'].append(token['id'])
        elif len(matches)>1:ambiguous.append({'token_id':token['id'],'cell_indices':matches,'reason':'whole_token_has_multiple_owners'})
    byid={t['id']:t for t in tokens}
    for cell in result:
        ordered=sorted((byid[i] for i in cell['token_ids']),key=lambda t:(t['bbox'][1],t['bbox'][0],t['id']))
        cell['raw_text']=' '.join(t['text'] for t in ordered) or None
        cell['source_tokens']=ordered
        cell['source_text_preserved']=True
    return {'cells':result,'ambiguous_tokens':ambiguous,'rejected_cells':rejected,
            'actual_word_ownership_preserved':not ambiguous,'new_OCR_calls':0}

def verify_admission(path,expected_sha,worker,component):
    require_HQ()
    if sha(path)!=expected_sha:raise ValueError('Admission SHA differs')
    lease=read(path)
    if lease.get('contract')!='root-HQ-document-ai-admission.v1' or lease.get('approved_by')!='root' or lease.get('component')!=component:raise ValueError('Root component admission required')
    if lease.get('resource_policy')!=RESOURCES or lease.get('production_activation_allowed') is not False or lease.get('optimizer_updates_allowed') is not False:raise ValueError('Resource/no-production policy differs')
    if lease.get('worker')!=pin(worker) or lease.get('controller_sha256')!=CONTROLLER_SHA256 or lease.get('shared_lock_held') is not True:raise ValueError('Worker/shared07b admission differs')
    import psutil
    supervisor=psutil.Process(lease['supervisor_pid'])
    if supervisor.create_time()!=lease['supervisor_creation_time'] or supervisor.pid not in {p.pid for p in psutil.Process().parents()}:raise ValueError('Live exact ancestor supervisor required')
    if datetime.now(timezone.utc).timestamp()>lease['expires_at_epoch']:raise ValueError('Admission expired')
    if psutil.virtual_memory().available<RESOURCES['minimum_start_free_RAM_bytes']:raise ValueError('Fresh start RAM below policy')
    return lease
