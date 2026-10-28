"""Build a geometry trial from pinned existing OCR cache; never decode images."""
from __future__ import annotations
import argparse
from pathlib import Path
from component_common import RESOURCES,read,pin,checked,save,restore_box,validate_task,valid_box

def envelope(raw):
    if isinstance(raw,(list,tuple)) and len(raw)==4 and all(type(v) in (int,float) for v in raw):return list(raw)
    try:
        xs,ys=zip(*raw)
        return [min(xs),min(ys),max(xs),max(ys)]
    except (ValueError,TypeError):return None

def from_cache(entry):
    cache=read(checked(entry));geometry=cache['geometry'];inputs=cache['inference_inputs']
    if geometry.get('machine_only') is not True or geometry.get('vision_LLM_calls')!=0:raise ValueError('Only retained machine OCR geometry is eligible')
    if any(inputs.get(x) is not False for x in ('reference','human_answers','Ada','StockDay')) or inputs.get('assistant_image_reads')!=0:raise ValueError('Original OCR inputs have non-machine evidence')
    angle=geometry['orientation_ccw'];size=geometry['original_size'];tokens=[];excluded=[]
    for raw in cache['working_tokens']:
        b=envelope(raw.get('box'));tid=raw.get('token_id')
        try:
            restored=restore_box(b,size,angle)
            token={'id':tid,'text':raw['text'],'bbox':restored,'engine':raw['engine'],'confidence':raw['confidence']}
            if not raw['text'].strip():raise ValueError('empty_text')
            tokens.append(token)
        except (ValueError,KeyError,TypeError):excluded.append({'token_id':tid,'reason':'invalid_or_outside_original_frame_no_clipping'})
    source={'path':cache['source_path'],'sha256':cache['source_sha256']}
    supplier=cache.get('upright_page',{}).get('document',{}).get('supplier') or {}
    task={'page':cache['page_number'],'company':supplier.get('key') or 'UNMAPPED',
          'source_image':source,'source_size':size,'source_frame':'original_image','machine_only':True,
          'rotation_ccw':angle,'tokens':tokens,'retained_machine_cache':{'path':entry['path'],'sha256':entry['sha256']},
          'excluded_machine_tokens':excluded,'OCR_reader_binding_sha256':geometry['reader_binding_sha256']}
    validate_task(task);return task

def build(manifest_path,registry_path,component,mode,selected_pages=None,pilot_limit=12):
    manifest=read(manifest_path)
    if manifest.get('complete') is not True or len(manifest['pages'])!=484:raise ValueError('Complete retained484-cache manifest required')
    if component not in ('pp-layout','pp-layout-l','docling','qwen') or mode not in ('canary','pilot','full'):raise ValueError('Unknown component/stage')
    entries=manifest['pages']
    if selected_pages is not None:
        selected=set(selected_pages);entries=[x for x in entries if x['page_number'] in selected]
        if len(entries)!=len(selected):raise ValueError('Selected page absent or duplicated')
    limit={'canary':1,'pilot':pilot_limit,'full':484}[mode]
    tasks=[];companies=set();deferred=[]
    for entry in entries:
        task=from_cache(entry)
        if mode=='pilot' and task['company'] in companies:deferred.append(task);continue
        tasks.append(task);companies.add(task['company'])
        if len(tasks)>=limit:break
    if mode=='pilot' and len(tasks)<limit:tasks.extend(deferred[:limit-len(tasks)])
    if mode=='full' and len(tasks)!=484:raise ValueError('Full must contain all484 original sources')
    if not tasks or mode=='canary' and len(tasks)!=1 or mode=='pilot' and len(tasks)>16:raise ValueError('Invalid bounded source selection')
    return {'contract':'root-document-ai-source-only-trial-plan.v1','approved_by':'root','component':component,'mode':mode,
        'registry':pin(registry_path),'resource_policy':RESOURCES,'retained_cache_manifest':pin(manifest_path),
        'baseline_selection':'frozen component323 FINAL164+savedC4; raw OCR retained; no freshBASE',
        'baseline_score_not_measured_by_geometry_worker':323,'source_pages_in_inventory':484,
        'tasks':tasks,'actual_company_count':len({t['company'] for t in tasks}),'image_decodes_during_plan':0,
        'manual_image_transcriptions':0,'new_text_OCR_calls':0,'endpoint_evaluation_required':True}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--cache-manifest',type=Path,required=True);ap.add_argument('--registry',type=Path,required=True)
    ap.add_argument('--component',choices=['pp-layout','pp-layout-l','docling','qwen'],required=True);ap.add_argument('--mode',choices=['canary','pilot','full'],required=True)
    ap.add_argument('--pages',help='Optional comma separated existing page numbers');ap.add_argument('--pilot-limit',type=int,default=12);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    pages=[int(x) for x in a.pages.split(',')] if a.pages else None
    plan=build(a.cache_manifest,a.registry,a.component,a.mode,pages,a.pilot_limit);save(a.output,plan)
    print({'plan':pin(a.output),'tasks':len(plan['tasks']),'companies':plan['actual_company_count'],'image_decodes':0,'new_text_OCR_calls':0})

if __name__=='__main__':main()
