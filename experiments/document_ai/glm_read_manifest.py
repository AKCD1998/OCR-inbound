"""Read already-closed GLM evidence. No model/image/reference execution.

The static recipe belongs to one experiment. Actual read manifests may grow
from its original canary to the panel/full source union, preserving each old
request record verbatim. File hashing is delegated to the approved transport.
"""
from copy import deepcopy
from pathlib import PureWindowsPath
import base64
import hashlib
import json

from component_common import checked,read,RESOURCES
from eval_native import record_key,resource_closed

SERIAL='87714bc07ea839a73115531e9358b2de0c17882a03d627a8353745fedf3c39d3'
RECIPE='document-ai-glm-recipe.v1'
MANIFEST='document-ai-glm-read-manifest.v1'

def same(a,b):return isinstance(a,dict) and isinstance(b,dict) and record_key(a)==record_key(b)
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def _pin(p):return isinstance(p,dict) and set(p)=={'path','sha256'} and isinstance(p['path'],str) and len(p.get('sha256',''))==64
def _limits(limits):
    base={'maximum_long_side':896,'maximum_image_pixels':1048576,'maximum_new_tokens':1024,'context_tokens':2048,
          'maximum_raw_characters':131072,'maximum_rows':256,'maximum_cells':4096}
    if limits not in (base,{**base,'context_tokens':1024,'maximum_new_tokens':512}) or any(type(v) is not int for v in limits.values()):
        raise ValueError('Exact selected GLM context/output profile required')
def _path(a,b):return str(PureWindowsPath(a)).casefold()==str(PureWindowsPath(b)).casefold()

def recipe_metadata(recipe,component_pin,check=checked,panel_pin=None):
    required={'contract','model_binding','backend_binding','prompt_binding','source_plan38','master_source_inventory','native_worker','backend_source','limits'}
    if not isinstance(recipe,dict) or set(recipe)!=required or recipe['contract']!=RECIPE:raise ValueError('Static root GLM recipe required')
    _limits(recipe['limits'])
    check(component_pin)
    for k in required-{'contract','limits'}:
        if not _pin(recipe[k]):raise ValueError('Static GLM metadata/source pins required')
    # Bind metadata only. Never follow model/binary/image paths in those files.
    for key in ('model_binding','backend_binding','prompt_binding','native_worker','backend_source','master_source_inventory'):
        check(recipe[key])
    prompt=read(check(recipe['prompt_binding']))
    if prompt.get('prompt') not in ('Table Recognition:','Text Recognition:'):raise ValueError('Exact official OCR prompt required')
    inventory=read(check(recipe['master_source_inventory']))
    if not isinstance(inventory.get('files'),list) or len(inventory['files'])!=484:raise ValueError('Original immutable484 source inventory required')
    sources=dict(enumerate(inventory['files'],1));plan=read(check(recipe['source_plan38']))
    requests=validate_plan(plan,recipe,sources)
    if any(r['prompt']!=prompt['prompt'] for r in requests):raise ValueError('Static prompt binding and original source task differ')
    if (len(requests)!=38 or panel_pin is not None and
        (not isinstance(plan.get('panel'),dict) or plan['panel'].get('sha256')!=panel_pin.get('sha256'))):
        raise ValueError('Same frozen38 panel bytes required; source path copies remain explicit')
    if requests[0]['page_number']!=3 or plan.get('canary_request_ids')!=[requests[0]['request_id']]:raise ValueError('Deterministic first wholepage3 canary required')
    if panel_pin is not None:
        actual_panel=read(check(panel_pin))
        if (actual_panel.get('contract')!='document-ai-correction-pilot-panel.v1'
          or not same(actual_panel.get('source_inventory'),recipe['master_source_inventory'])
          or {r['page_number']:r['source_sha256'] for r in requests}!={p['page_number']:p['source_sha256'] for p in actual_panel['pages']}):
            raise ValueError('Equivalent panel copy must retain actual source inventory and page identities')
    return {'recipe':recipe,'plan':plan,'requests':{r['request_id']:r for r in requests},'sources':sources,'component':component_pin,
            'panel_binding':{'original_plan_panel':deepcopy(plan.get('panel')),'experiment_panel':deepcopy(panel_pin),
                             'original_plan_pin_rewritten':False,'same_panel_content_SHA_required':True}}

def validate_plan(plan,recipe,sources):
    if (plan.get('contract')!='document-ai-glm-pre-gate-plan.v1' or plan.get('expected_values_used') is not False
      or plan.get('production_activation') is not False):raise ValueError('Source-only GLM plan required')
    requests=plan.get('requests');seen=set();numbers=[]
    if not isinstance(requests,list) or not requests:raise ValueError('Finite source request plan required')
    for r in requests:
        n=r.get('page_number');g=r.get('geometry') or {}
        required={'request_id','page_number','source_image','source_sha256','geometry','source_inputs','context_kind','roi_upright',
                  'task','prompt','limits','selection_basis','legacy_context_eligibility_required','reference_answers_used'}
        if (set(r)!=required or set(g)!={'original_size','upright_size','orientation_ccw'}
          or set(r.get('source_inputs') or {})!={'canonical','cache','native'}
          or not all(_pin(p) for p in r['source_inputs'].values()) or not _pin(r.get('source_image'))
          or type(n) is not int or n not in sources or n in seen or r.get('source_sha256')!=sources[n]['sha256']
          or (r.get('source_image') or {}).get('sha256')!=sources[n]['sha256']
          or r.get('roi_upright')!=[0,0,*g.get('upright_size',[])] or r.get('limits')!=recipe['limits']
          or r.get('context_kind')!='WHOLE_PAGE_WITH_HEADERS_AND_ALL_NEIGHBORS'
          or r.get('legacy_context_eligibility_required') is not False or r.get('reference_answers_used') is not False
          or r.get('selection_basis')!='ALL_SOURCE_PANEL_PAGES_BEFORE_LEGACY_CONTEXT_GATES'
          or r.get('request_id')!='glm-page-%04d-%s'%(n,r.get('task'))
          or r.get('prompt')!={'table':'Table Recognition:','text':'Text Recognition:'}.get(r.get('task'))):
            raise ValueError('Bound complete source-page context required')
        seen.add(n);numbers.append(n)
    if numbers!=sorted(numbers):raise ValueError('Original ascending source request order required')
    return requests

def load_reads(recipe,component_pin,manifest_pin,numbers,check=checked,panel_pin=None):
    metadata=recipe_metadata(recipe,component_pin,check,panel_pin);manifest=read(check(manifest_pin))
    if (set(manifest)!={'contract','recipe','request_results'} or manifest.get('contract')!=MANIFEST
      or manifest.get('recipe')!=recipe or not isinstance(manifest.get('request_results'),list)):
        raise ValueError('Root-sealed source-only GLM read manifest required')
    wanted=set(numbers);records={};record_pins={};closed_cache={};summary_cache={};config_cache={}
    for entry in manifest['request_results']:
        if set(entry)!={'request_id','observation','summary','closed_source'}:raise ValueError('Actual GLM observation/summary/closure pins only')
        if any(not _pin(entry[k]) for k in ('observation','summary','closed_source')):raise ValueError('Actual native record pins required')
        skey=record_key(entry['summary'])
        if skey not in summary_cache:
            summary=read(check(entry['summary']));cfg_pin=summary.get('config');cfg=read(check(cfg_pin))
            if (summary.get('contract')!='document-ai-glm-native-batch.v1' or summary.get('status')!='EXECUTION_FINISHED'
              or summary.get('failure') is not None or summary.get('server_closed') is not True or summary.get('executed') is not True
              or not same(summary.get('worker'),recipe['native_worker']) or summary.get('component')!='glm-ocr'
              or summary.get('assistant_image_reads')!=0 or summary.get('optimizer_updates')!=0
              or summary.get('baseline_cache_modified') is not False or summary.get('production_activation') is not False):
                raise ValueError('Successful physically closed isolated GLM source worker required')
            if (cfg.get('contract')!='document-ai-glm-native-config.v1' or cfg.get('resource_policy')!=RESOURCES
              or cfg.get('optimizer_updates_allowed') is not False or cfg.get('production_activation') is not False
              or not same(cfg.get('model_binding'),recipe['model_binding']) or not same(cfg.get('backend_binding'),recipe['backend_binding'])
              or not same(cfg.get('prompt_binding'),recipe['prompt_binding']) or cfg.get('sources',{}).get('evidence',{}).get('sha256')!=component_pin['sha256']
              or not same(cfg.get('sources',{}).get('backend'),recipe['backend_source'])
              or cfg.get('context_tokens')!=recipe['limits']['context_tokens'] or cfg.get('max_output_tokens')!=recipe['limits']['maximum_new_tokens']):
                raise ValueError('Actual GLM model/backend/prompt/source recipe differs')
            check(cfg['sources']['evidence'])
            plan=read(check(cfg['plan']));requests=validate_plan(plan,recipe,metadata['sources']);requests={r['request_id']:r for r in requests}
            if (not same(summary.get('plan'),cfg['plan']) or summary.get('request_ids')!=cfg.get('request_ids')
              or any(x not in requests for x in cfg['request_ids']) or len(set(cfg['request_ids']))!=len(cfg['request_ids'])
              or not 1<=len(cfg['request_ids'])<=4):raise ValueError('Actual finite native request selection differs')
            expected_identity={'model':recipe['model_binding'],'backend':recipe['backend_binding'],'prompt':recipe['prompt_binding'],'config':cfg_pin}
            if summary.get('identity')!=expected_identity:raise ValueError('Actual native identity differs')
            count=len(cfg['request_ids'])
            if (any(summary.get(k)!=count for k in ('requests_prepared','requests_started','responses_returned','completed_record_count'))
              or [r.get('request_id') for r in summary.get('request_results',[])]!=cfg['request_ids']):raise ValueError('All actual started requests must have completed evidence records')
            summary_cache[skey]=(summary,cfg,requests,expected_identity)
        summary,cfg,requests,identity=summary_cache[skey]
        rid=entry['request_id'];request=requests.get(rid)
        if request is None:raise ValueError('Read is outside its actual native request plan')
        n=request['page_number']
        if n in records:raise ValueError('Duplicate GLM page/read is not independent evidence')
        if n in {r['page_number'] for r in metadata['requests'].values()}:
            original=metadata['requests'].get(rid)
            if request!=original:raise ValueError('Original38 request changed across batches')
        key=record_key(entry['closed_source'])
        if key not in closed_cache:
            closed=read(check(entry['closed_source']));serial=read(check(closed['config']))
            if (closed.get('status')!='COMPLETE' or closed.get('failure') is not None
              or closed.get('shared_lock_released_after_owned_closure') is not True
              or closed.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
              or serial.get('source',{}).get('sha256')!=SERIAL or serial.get('resource_policy')!=RESOURCES):raise ValueError('Actual original877 GLM physical closure required')
            closed_cache[key]=closed
        resources=[r for r in closed_cache[key].get('resources',[]) if same(r.get('worker_summary'),entry['summary'])]
        if len(resources)!=1:raise ValueError('Unique closed native child witness required')
        resource=resources[0];resource_closed(resource)
        argv=resource.get('actual_argv') or []
        def argument(flag):
            if argv.count(flag)!=1 or argv.index(flag)+1>=len(argv):raise ValueError('Actual GLM child argument missing')
            return argv[argv.index(flag)+1]
        if (resource.get('child_started') is not True or resource.get('worker_optimizer_updates_permission') is not False
          or not any(_path(a,recipe['native_worker']['path']) for a in argv)
          or not _path(argument('--config'),summary['config']['path']) or argument('--config-sha256')!=summary['config']['sha256']
          or not _path(argument('--output'),str(PureWindowsPath(entry['summary']['path']).parent))):raise ValueError('Actual native source/config/output differs')
        results=[r for r in summary['request_results'] if r.get('request_id')==rid and same(r.get('observation'),entry['observation'])]
        if len(results)!=1:raise ValueError('Observation is not the actually completed native result')
        result=results[0];obs=read(check(entry['observation']));raw=read(check(result['raw_response']))
        if (result.get('page_number')!=n or result.get('printed_content_coverage_verified') is not False
          or obs.get('contract')!='document-ai-glm-native-observation.v1'
          or obs.get('request')!=request or obs.get('request_sha256')!=digest(request) or obs.get('identity')!=identity
          or obs.get('raw_response')!=raw or not same(obs.get('raw_response_pin'),result['raw_response'])):raise ValueError('Actual raw GLM response/request differs')
        proof=obs.get('native_input_proof') or {};image=read(check(proof['image_proof']));http=read(check(proof['actual_HTTP_request']))
        if (not same(proof.get('plan'),cfg['plan']) or not same(image.get('prepared'),proof.get('prepared_image'))
          or image.get('source')!=request['source_image'] or image.get('actual_source_bytes_consumed_sha256')!=request['source_sha256']
          or image.get('source_geometry')!=request['geometry'] or image.get('roi_upright')!=request['roi_upright']
          or image.get('source_context_clipped') is not False or image.get('EXIF_reinterpreted') is not False
          or image.get('glyph_or_cell_boxes_invented') is not False):raise ValueError('Actual prepared full-source image proof differs')
        size=image.get('actual_prepared_size');g=request['geometry'];scale=min(1,896/max(g['upright_size']))
        expected_size=[max(1,int(round(x*scale))) for x in g['upright_size']]
        if size!=expected_size or size[0]*size[1]>recipe['limits']['maximum_image_pixels']:raise ValueError('Actual bounded prepared resolution differs')
        try:
            content=http['messages'][0]['content'];url=content[1]['image_url']['url']
            body=base64.b64decode(url.split(',',1)[1],validate=True)
        except (ValueError,KeyError,IndexError,TypeError):raise ValueError('Actual local image HTTP request required')
        expected_http={'model':'glm-ocr-isolated','messages':[{'role':'user','content':[{'type':'text','text':request['prompt']},
          {'type':'image_url','image_url':{'url':url}}]}],'temperature':0,'seed':0,'stream':False,
          'max_tokens':recipe['limits']['maximum_new_tokens'],'cache_prompt':False}
        if (not url.startswith('data:image/png;base64,') or hashlib.sha256(body).hexdigest()!=proof['prepared_image']['sha256']
          or http!=expected_http):raise ValueError('Actual HTTP prompt/prepared bytes/output limits differ; extra hints forbidden')
        generation=read(check(result['generation']));structure=read(check(result['structure']))
        records[n]={'observation':obs,'pin':entry['observation'],'identity':identity,'request':request,
                    'generation':generation,'structure':structure,'native_result':result,'source_record':entry}
        record_pins[str(n)]=deepcopy(entry)
    if set(records)!=wanted:raise ValueError('GLM read manifest must cover exactly the selected runtime source pages')
    return {'manifest':manifest_pin,'recipe':deepcopy(recipe),'records':records,'request_records':record_pins,
            'parser_model_calls':0,'source_image_decodes':0,'baseline_cache_modified':False,'panel_binding':metadata['panel_binding']}

def continuation(previous_records,current_records):
    if not isinstance(previous_records,dict) or not previous_records or not isinstance(current_records,dict):raise ValueError('Original GLM request records required')
    for page,record in previous_records.items():
        if current_records.get(page)!=record:raise ValueError('Prior GLM canary/panel record must be retained verbatim; no reread/replacement')
    return True
