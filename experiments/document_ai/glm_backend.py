"""Pure, pinned llama.cpp GLM-OCR command and completion contracts.

This module never downloads, launches a process, imports an ML SDK, decodes an
image or reads an invoice/reference. The caller owns original resource/child
supervision and must seal actual binaries, all DLLs, weights and raw responses.
File-size budgeting is not an inference-RSS measurement or an accuracy claim.
"""
from copy import deepcopy
from pathlib import PurePosixPath, PureWindowsPath
import re

VERSION='document-ai-glm-backend.v1'
RELEASE='b11998'
REVISION='78feec062d50ec9e8940244cac918ac4480b60cb'
CAPS={'CPU_threads':1,'minimum_start_free_RAM_bytes':1983628573,
      'stop_free_RAM_bytes':1288490188,'maximum_own_process_tree_RSS_bytes':1073741824}
PROMPTS=('Text Recognition:','Table Recognition:','Formula Recognition:')
QUANTS=('Q4_0','Q4_1','Q4_K_M','Q3_K_M')
OFFICIAL_Q8_BYTES={'decoder':950433408,'projector':484403648}

def _integer(value,name,low=1,high=None):
    if type(value) is not int or value<low or high is not None and value>high:
        raise ValueError('Bounded integer required: '+name)
    return value

def _path(value):
    value=str(value)
    if (not value or any(ch in value for ch in ('\x00','\r','\n')) or '://' in value
            or not (PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute())
            or '..' in PureWindowsPath(value).parts):
        raise ValueError('Explicit absolute local artifact path required')
    return value

def validate_resources(resources):
    if type(resources) is not dict or any(type(resources.get(k)) is not int or resources[k]!=v for k,v in CAPS.items()):
        raise ValueError('Original CPU/RAM/RSS caps must remain unchanged')
    return deepcopy(CAPS)

def quantize_command(executable,source,destination,*,quantization='Q4_0',dry_run=False):
    """One CPU thread, explicit lossy re-quantization, bounded slab buffers.

    On Windows the selected backend's unmap_fragment is a no-op. The 16 MiB
    limit bounds conversion slabs, NOT all resident input-mapping pages.
    The original supervisor must still stop the actual owned tree at its cap.
    """
    exe,src,dst=map(_path,(executable,source,destination))
    if src.replace('\\','/').casefold()==dst.replace('\\','/').casefold():
        raise ValueError('Quantization cannot overwrite its source')
    if quantization not in QUANTS or type(dry_run) is not bool:
        raise ValueError('Explicit supported isolated quantization arm required')
    return [exe,'--allow-requantize','--max-buffer-size','16']+(['--dry-run'] if dry_run else [])+[src,dst,quantization,'1']

def server_command(executable,decoder,projector,*,port,context_tokens=2048,
                   max_output_tokens=1024,image_max_tokens=256):
    """Local-only, finite, single-slot CPU server with no hidden model fetches."""
    exe,model,vision=map(_path,(executable,decoder,projector))
    _integer(port,'port',1024,65535)
    if context_tokens not in (1024,2048):raise ValueError('Explicit bounded1024/2048 context required')
    _integer(max_output_tokens,'max_output_tokens',1,context_tokens-256)
    if image_max_tokens not in (64,128,256):raise ValueError('Explicit bounded visual token budget required')
    return [exe,'--model',model,'--mmproj',vision,'--alias','glm-ocr-isolated','--host','127.0.0.1','--port',str(port),
        '--threads','1','--threads-batch','1','--threads-http','1','--parallel','1',
        '--gpu-layers','0','--no-mmproj-offload','--fit','off','--load-mode','none','--lazy-mode','off',
        '--ctx-size',str(context_tokens),'--predict',str(max_output_tokens),'--batch-size','64','--ubatch-size','32',
        '--cache-type-k','f16','--cache-type-v','f16','--cache-ram','0','--ctx-checkpoints','0',
        '--no-cache-idle-slots','--no-context-shift','--no-cont-batching','--flash-attn','off',
        '--image-min-tokens','8','--image-max-tokens',str(image_max_tokens),'--no-warmup',
        '--poll','0','--poll-batch','0','--offline','--no-webui','--log-colors','off','--log-timestamps']

def memory_preflight(decoder_bytes,projector_bytes,*,context_tokens,reservations):
    """Account for BOTH weight sets, KV, image/prefill scratch and owned runtime.

    Reservations are explicit prospective budgets, not fabricated measurements.
    Seventeen decoder layers conservatively include the NextN/MTP layer. Passing
    only permits a bounded monitored canary; it never proves runtime fit.
    """
    _integer(decoder_bytes,'decoder_bytes');_integer(projector_bytes,'projector_bytes')
    if context_tokens not in (1024,2048):raise ValueError('Bounded context required')
    keys={'vision_scratch_bytes','decoder_prefill_scratch_bytes','runtime_and_owned_parent_bytes'}
    if type(reservations) is not dict or set(reservations)!=keys:
        raise ValueError('All explicit scratch/runtime reservations required')
    for key,value in reservations.items():_integer(value,key)
    kv=2*17*8*128*2*context_tokens
    weights=decoder_bytes+projector_bytes;required=weights+kv+sum(reservations.values());cap=CAPS['maximum_own_process_tree_RSS_bytes']
    return {'contract':'document-ai-glm-memory-preflight.v1',
        'status':'BOUNDED_CANARY_REQUIRED' if required<=cap else 'REJECTED_RESOURCE_BUDGET',
        'decoder_weight_bytes':decoder_bytes,'projector_weight_bytes':projector_bytes,
        'all_weight_bytes':weights,'KV_budget_bytes':kv,'decoder_layers_budgeted_including_NextN':17,
        'explicit_unmeasured_reservations':deepcopy(reservations),'total_budget_bytes':required,
        'owned_RSS_cap_bytes':cap,'budget_headroom_bytes':cap-required,'actual_RSS_measurement_required':True,
        'mmap_or_swap_excluded_from_budget_savings':True,'runtime_fit_proven':False}

def completion_request(image_data_url,*,prompt='Text Recognition:',max_output_tokens=1024):
    """The caller supplies and seals image bytes; no decoding is performed here."""
    if prompt not in PROMPTS:raise ValueError('Exact officially supported OCR task prompt required')
    _integer(max_output_tokens,'max_output_tokens',1,1792)
    if (type(image_data_url) is not str or not re.fullmatch(r'data:image/(?:png|jpeg);base64,[A-Za-z0-9+/]+={0,2}',image_data_url)
            or len(image_data_url)>16*1024*1024):
        raise ValueError('One bounded local encoded image required; remote URLs refused')
    return {'model':'glm-ocr-isolated','messages':[{'role':'user','content':[
        {'type':'text','text':prompt},{'type':'image_url','image_url':{'url':image_data_url}}]}],
        'temperature':0,'seed':0,'stream':False,'max_tokens':max_output_tokens,'cache_prompt':False}

def completion_receipt(raw,request,*,context_tokens):
    """Preserve literal output. A normal stop is not proof of document coverage."""
    if context_tokens not in (1024,2048):raise ValueError('Bounded context required')
    limit=_integer(request.get('max_tokens'),'max_tokens',1,context_tokens-256)
    reasons=[];text=None;finish=None
    if isinstance(raw,dict) and raw.get('error'):
        reasons.append('BACKEND_REPORTED_ERROR')
    choices=raw.get('choices') if isinstance(raw,dict) else None
    if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):
        reasons.append('ONE_ACTUAL_COMPLETION_REQUIRED')
    else:
        finish=choices[0].get('finish_reason');message=choices[0].get('message')
        text=message.get('content') if isinstance(message,dict) else None
        if finish!='stop':reasons.append('GENERATION_DID_NOT_STOP_NORMALLY')
        if choices[0].get('error'):reasons.append('BACKEND_REPORTED_ERROR')
        if not isinstance(text,str) or not text.strip():reasons.append('NONEMPTY_LITERAL_OUTPUT_REQUIRED')
        if choices[0].get('truncated') is True:reasons.append('EXPLICIT_TRUNCATION')
    actual_usage=raw.get('usage') if isinstance(raw,dict) else None
    usage=actual_usage if isinstance(actual_usage,dict) else {}
    counts={k:usage.get(k) for k in ('prompt_tokens','completion_tokens','total_tokens')}
    if any(type(v) is not int or v<0 for v in counts.values()):reasons.append('ACTUAL_TOKEN_COUNTS_REQUIRED')
    else:
        if counts['prompt_tokens']==0 or counts['completion_tokens']==0:reasons.append('POSITIVE_ACTUAL_INPUT_OUTPUT_TOKEN_COUNTS_REQUIRED')
        if counts['completion_tokens']>=limit:reasons.append('OUTPUT_TOKEN_LIMIT_REACHED')
        if counts['prompt_tokens']+counts['completion_tokens']>=context_tokens:reasons.append('CONTEXT_LIMIT_REACHED')
        if counts['total_tokens']!=counts['prompt_tokens']+counts['completion_tokens']:reasons.append('INCONSISTENT_ACTUAL_TOKEN_COUNTS')
    if isinstance(raw,dict) and raw.get('truncated') is True:reasons.append('EXPLICIT_TRUNCATION')
    return {'contract':'document-ai-glm-generation-result.v1','backend_release':RELEASE,
        'status':'GENERATION_FINISHED' if not reasons else 'GENERATION_INCOMPLETE',
        'generation_complete':not reasons,'raw_text':text,'finish_reason':finish,'usage':deepcopy(actual_usage),
        'timings':deepcopy(raw.get('timings')) if isinstance(raw,dict) else None,
        'max_output_tokens':limit,'context_tokens':context_tokens,'hold_reasons':list(dict.fromkeys(reasons)),
        'document_coverage_verified':False,'numeric_OCR_confidence':None,'glyph_boxes_supplied':False,
        'business_correction_applied':False,'human_verified':False}
