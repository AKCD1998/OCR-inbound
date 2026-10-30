"""Pre-gate GLM transcription evidence and versioned independent admission.

Standard library only. No images, files, network, SDK or model calls. GLM
supplies text/table structure, never glyph boxes or numeric OCR confidence.
Unmatched rows remain visible even when conservative field admission abstains.
"""
from copy import deepcopy
from decimal import Decimal,InvalidOperation
from html.parser import HTMLParser
import hashlib
import json
import math
import re
import unicodedata

PLAN='document-ai-glm-pre-gate-plan.v1'
OBSERVATION='document-ai-glm-native-observation.v1'
POLICY='GLM_PRINTED_TABLE_PLUS_INDEPENDENT_TESS_V1'
PROMPTS={'table':'Table Recognition:','text':'Text Recognition:'}
LIMITS={'maximum_long_side':896,'maximum_image_pixels':1048576,'maximum_new_tokens':1024,
        'context_tokens':2048,'maximum_raw_characters':131072,'maximum_rows':256,'maximum_cells':4096}
LIMIT_PROFILES={'standard2048':LIMITS,'tight1024':{**LIMITS,'context_tokens':1024,'maximum_new_tokens':512}}
OFFICIAL_SOURCES=['https://huggingface.co/zai-org/GLM-OCR','https://github.com/zai-org/GLM-OCR/blob/main/glmocr/config.yaml']
BONUS=re.compile(r'\b(?:bonus|free\s*goods?|foc|free\s*item)\b|ของแถม|สินค้าแถม',re.I)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def pin(value):
    return (isinstance(value,dict) and set(value)=={'path','sha256'} and isinstance(value['path'],str)
            and bool(value['path']) and re.fullmatch('[0-9a-f]{64}',str(value['sha256'])) is not None)

def validate_limits(value):
    if not isinstance(value,dict) or not any(value==v for v in LIMIT_PROFILES.values()):
        raise ValueError('Exact prospective2048/1024 or1024/512 GLM resource profile required')
    if any(type(v) is not int for v in value.values()):raise ValueError('Integer resource bounds required')
    return deepcopy(value)


def _text(value):return unicodedata.normalize('NFC',str(value or '')).strip()
def _compact(value):return re.sub(r'\s+','',_text(value)).casefold()
def _same(a,b,role):
    if role!='quantity':return _text(a)==_text(b)
    try:
        x,y=[Decimal(str(v).replace(',','')) for v in (a,b)]
        return x.is_finite() and y.is_finite() and x==y
    except (InvalidOperation,ValueError,TypeError):return False


def build_plan(source_pages,panel_pin,input_manifest_pin,task='table',resource_profile='standard2048'):
    """Every source page reaches GLM before any old header/row/cell gate."""
    if task not in PROMPTS or not pin(panel_pin) or not pin(input_manifest_pin):raise ValueError('Pinned source-only task required')
    if resource_profile not in LIMIT_PROFILES:raise ValueError('Explicit GLM resource profile required')
    limits=validate_limits(LIMIT_PROFILES[resource_profile]);requests=[];seen=set()
    for page in sorted(source_pages,key=lambda p:p['page_number']):
        n=page['page_number'];g=page['geometry'];image=page['source_image']
        if (type(n) is not int or not 1<=n<=484 or n in seen or not pin(image)
                or image['sha256']!=page['source_sha256']):raise ValueError('Unique actual source identity required')
        seen.add(n);ow,oh=g['original_size'];uw,uh=g['upright_size'];angle=g['orientation_ccw']
        if (any(type(x) is not int or x<=0 for x in (ow,oh,uw,uh)) or type(angle) is not int or angle not in (0,90,180,270)
                or [uw,uh] != ([oh,ow] if angle in (90,270) else [ow,oh])):raise ValueError('Exact source geometry required')
        inputs=page['source_inputs']
        if set(inputs)!={'canonical','cache','native'} or not all(pin(p) for p in inputs.values()):raise ValueError('Original source pins only')
        requests.append({'request_id':'glm-page-%04d-%s'%(n,task),'page_number':n,'source_image':deepcopy(image),
            'source_sha256':page['source_sha256'],'geometry':deepcopy(g),'source_inputs':deepcopy(inputs),
            'context_kind':'WHOLE_PAGE_WITH_HEADERS_AND_ALL_NEIGHBORS','roi_upright':[0,0,uw,uh],
            'task':task,'prompt':PROMPTS[task],'limits':deepcopy(limits),
            'selection_basis':'ALL_SOURCE_PANEL_PAGES_BEFORE_LEGACY_CONTEXT_GATES',
            'legacy_context_eligibility_required':False,'reference_answers_used':False})
    if not 1<=len(requests)<=484:raise ValueError('Finite source page inventory required')
    return {'contract':PLAN,'panel':deepcopy(panel_pin),'source_input_manifest':deepcopy(input_manifest_pin),
            'requests':requests,'canary_request_ids':[requests[0]['request_id']],
            'expected_values_used':False,'production_activation':False}


def wrap_response(request,identity,response,raw_response_pin):
    """Native producer calls this only after saving its exact HTTP response."""
    if set(identity)!={'model','backend','prompt','config'} or not all(pin(p) for p in identity.values()) or not pin(raw_response_pin):
        raise ValueError('Model/backend/prompt/config/raw response pins required')
    return {'contract':OBSERVATION,'request':deepcopy(request),'request_sha256':digest(request),
            'identity':deepcopy(identity),'raw_response':deepcopy(response),'raw_response_pin':deepcopy(raw_response_pin),
            'model_confidence':None,'business_corrections':[],'assistant_image_reads':0,'optimizer_updates':0}


class _Tables(HTMLParser):
    def __init__(self,raw):
        super().__init__(convert_charrefs=True);self.raw=raw;self.lines=[0]
        self.lines += [i+1 for i,c in enumerate(raw) if c=='\n']
        self.tables=[];self.table=None;self.row=None;self.cell=None;self.bad=False;self.total=0
    def absolute_offset(self):
        line,col=self.getpos();return self.lines[line-1]+col
    def handle_starttag(self,tag,attrs):
        if tag=='table':
            if self.table is not None:self.bad=True;return
            self.table={'rows':[]};return
        if self.table is None:return
        if tag=='tr':
            if self.row is not None:self.bad=True
            self.row={'cells':[]};return
        if tag in ('td','th'):
            if self.row is None or self.cell is not None:self.bad=True;return
            attrs=dict(attrs)
            try:rs,cs=int(attrs.get('rowspan','1')),int(attrs.get('colspan','1'))
            except (TypeError,ValueError):self.bad=True;return
            if not 1<=rs<=64 or not 1<=cs<=64:self.bad=True;return
            self.cell={'text_parts':[],'tag':tag,'raw_markup_span':[self.absolute_offset(),None],
                       'rowspan':rs,'colspan':cs,'is_header':tag=='th'};return
        if tag=='br' and self.cell is not None:self.cell['text_parts'].append('\n')
        elif tag not in ('thead','tbody','tfoot'):self.bad=True
    def handle_endtag(self,tag):
        if self.table is None:return
        if tag in ('td','th'):
            if self.cell is None or self.row is None:self.bad=True;return
            closing=re.match(r'</\s*'+tag+r'\s*>',self.raw[self.absolute_offset():],re.I)
            if self.cell['tag']!=tag or closing is None:self.bad=True;return
            self.cell.pop('tag')
            self.cell['raw_markup_span'][1]=self.absolute_offset()+closing.end()
            self.cell['raw_text']=''.join(self.cell.pop('text_parts')).strip()
            self.cell['source_bbox']=None;self.cell['character_boxes_available']=False
            self.row['cells'].append(self.cell);self.cell=None;self.total+=1
            if self.total>LIMITS['maximum_cells']:self.bad=True
        elif tag=='tr':
            if self.row is None or self.cell is not None:self.bad=True;return
            self.table['rows'].append(self.row);self.row=None
            if len(self.table['rows'])>LIMITS['maximum_rows']:self.bad=True
        elif tag=='table':
            if self.row is not None or self.cell is not None:self.bad=True;return
            self.tables.append(self.table);self.table=None
    def handle_data(self,data):
        if self.cell is not None:self.cell['text_parts'].append(data)


def intake(request,observation,expected_identity):
    """Clean generation termination is distinct from syntax and correctness."""
    out={'status':'INCOMPLETE','printed_transcription':None,'tables':[],'business_corrections':[],
         'unconfirmed':[],'model_confidence':None,'policy':POLICY,'receiving_approval':False}
    validate_limits(request.get('limits'))
    if (request.get('prompt')!=PROMPTS.get(request.get('task'))
      or request.get('legacy_context_eligibility_required') is not False or request.get('reference_answers_used') is not False
      or set(expected_identity)!={'model','backend','prompt','config'} or not all(pin(p) for p in expected_identity.values())
      or observation.get('contract')!=OBSERVATION or observation.get('request')!=request
      or observation.get('request_sha256')!=digest(request) or observation.get('identity')!=expected_identity
      or observation.get('model_confidence') is not None or observation.get('business_corrections')!=[]
      or observation.get('assistant_image_reads')!=0 or observation.get('optimizer_updates')!=0
      or not pin(observation.get('raw_response_pin'))):raise ValueError('Bound native source-only GLM observation required')
    response=observation['raw_response'];choices=response.get('choices') if isinstance(response,dict) else None
    if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):
        out['unconfirmed'].append('EXACTLY_ONE_NATIVE_COMPLETION_REQUIRED');return out
    message=choices[0].get('message');raw=message.get('content') if isinstance(message,dict) else None
    finish=choices[0].get('finish_reason')
    usage=response.get('usage');usage=usage if isinstance(usage,dict) else {}
    used,total,prompt=(usage.get(k) for k in ('completion_tokens','total_tokens','prompt_tokens'))
    if (not isinstance(raw,str) or not raw.strip() or len(raw)>LIMITS['maximum_raw_characters']
      or finish!='stop' or type(used) is not int or not 0<used<request['limits']['maximum_new_tokens']
      or type(prompt) is not int or prompt<=0 or type(total) is not int or total!=prompt+used
      or total>=request['limits']['context_tokens'] or response.get('truncated') is True
      or choices[0].get('truncated') is True or response.get('error') or choices[0].get('error')):
        out['unconfirmed'].append('TRUNCATED_EMPTY_OR_UNVERIFIED_TERMINATION');return out
    out.update(printed_transcription={'raw_text':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),
        'raw_response':deepcopy(observation['raw_response_pin']),'finish_reason':finish,'generated_tokens':used,
        'coverage_of_every_printed_character_confirmed':False},generation_terminated_cleanly=True)
    parser=_Tables(raw)
    try:parser.feed(raw);parser.close()
    except (ValueError,TypeError,IndexError):parser.bad=True
    if parser.bad or parser.table is not None or parser.row is not None or parser.cell is not None:
        out['unconfirmed'].append('MALFORMED_OR_TRUNCATED_TABLE');return out
    if request['task']=='table' and not parser.tables:
        out['unconfirmed'].append('NO_STRUCTURED_TABLE_RETURNED');return out
    out.update(status='COMPLETE',tables=parser.tables)
    out['syntax_validity_is_not_transcription_accuracy']=True
    return out


def _union(words):return [min(w['bbox'][0] for w in words),min(w['bbox'][1] for w in words),max(w['bbox'][2] for w in words),max(w['bbox'][3] for w in words)]
def _baseline(a,b):return max(0,min(a[3],b[3])-max(a[1],b[1]))>=.5*min(a[3]-a[1],b[3]-b[1])


def _model_rows(parsed,core):
    rows=[];unknown=[]
    for ti,table in enumerate(parsed['tables']):
        header=None
        for ri,row in enumerate(table['rows']):
            if any(c['rowspan']!=1 or c['colspan']!=1 for c in row['cells']):
                unknown.append({'table':ti,'row':ri,'reason':'MERGED_MODEL_CELLS_UNCONFIRMED','cells':deepcopy(row['cells'])});continue
            roles=[core._role(c['raw_text']) for c in row['cells']]
            if 'description' in roles and any(r in roles for r in ('quantity','unit')):
                if len([r for r in roles if r])!=len(set(r for r in roles if r)):
                    unknown.append({'table':ti,'row':ri,'reason':'AMBIGUOUS_MODEL_HEADER','cells':deepcopy(row['cells'])});header=None
                else:header=roles
                continue
            if header is None or len(header)!=len(row['cells']):
                unknown.append({'table':ti,'row':ri,'reason':'UNRESOLVED_MODEL_ROW_STRUCTURE','cells':deepcopy(row['cells'])});continue
            rows.append({'table':ti,'model_row':ri,'cells':deepcopy(row['cells']),'roles':header,
                         'fields':{role:{'value':cell['raw_text'],'column':ci,'raw_markup_span':cell['raw_markup_span']}
                                   for ci,(role,cell) in enumerate(zip(header,row['cells'])) if role}})
    return rows,unknown


def _derive(page,cache,observation,helpers,glm_pin):
    request=observation['request'];parsed=intake(request,observation,helpers['glm_identity'])
    if not pin(glm_pin):raise ValueError('Actual GLM source observation pin required')
    flags=cache.get('inference_inputs') or {};g=cache['geometry'];rules=helpers['rules'];core=helpers['core']
    if (page.get('page_number')!=request['page_number'] or page.get('source_sha256')!=request['source_sha256']
      or cache.get('source_sha256')!=request['source_sha256'] or cache.get('page_number')!=request['page_number']
      or request.get('geometry')!={k:g[k] for k in ('original_size','upright_size','orientation_ccw')}
      or request.get('roi_upright')!=[0,0,*g['upright_size']] or page.get('coordinate_space')!='upright_image'
      or page.get('image_size')!=g['upright_size'] or any(flags.get(k) is not False for k in ('reference','human_answers','Ada','StockDay'))
      or flags.get('assistant_image_reads')!=0):raise ValueError('Immutable actual machine source frame required')
    if parsed['status']!='COMPLETE':return {},parsed,[{'reason':'GLM_OUTPUT_INCOMPLETE','details':parsed['unconfirmed']}]
    model_rows,unconfirmed=_model_rows(parsed,core)
    primary=rules._tokens(cache.get('working_tokens',[]));secondary=rules._tokens(cache.get('tesseract_working_tokens',[]),True)
    alternatives=[t for view in cache.get('targeted_views',[]) for t in rules._tokens(view.get('tokens',[]))]
    old_rows=page.get('product_rows',[]);contexts={};blocked=set()
    canonical_aliases=set()
    name_boxes=[rules._box((row.get('fields',{}).get('description') or {}).get('bbox')) for row in old_rows]
    name_boxes=[b for b in name_boxes if b]
    for row in old_rows:
        field=(row.get('fields',{}).get('description') or {})
        for token in primary:
            if token['token_id'] in (field.get('token_ids') or []):canonical_aliases.update(token['aliases'])
    unmodeled_barriers=[]
    for token in primary:
        text,box=token['text'],token['bbox']
        if (set(token['aliases'])&canonical_aliases or token['confidence']<.95 or not rules._name(text)
          or not name_boxes or not min(b[0] for b in name_boxes)<(box[0]+box[2])/2<max(b[2] for b in name_boxes)
          or core._role(text) or BONUS.search(text) or rules.SET.search(text) or rules.FOOTER.search(text)
          or re.match(r'^\s*(?:LOT|BATCH|MFG|MFD|EXP|REF)(?=\b|[:#.\d])',text,re.I)):
            continue
        peers=[t for t in secondary if t['confidence']>=.70 and _compact(t['text'])==_compact(text)
               and not set(t['aliases'])&set(token['aliases']) and _baseline(box,t['bbox'])
               and max(0,min(box[2],t['bbox'][2])-max(box[0],t['bbox'][0]))>=.8*min(box[2]-box[0],t['bbox'][2]-t['bbox'][0])]
        if len(peers)==1:
            unmodeled_barriers.append({'kind':'UNMODELED_DUAL_SOURCE_NAME_NEGATIVE_BARRIER','bbox':_union([token,peers[0]]),
              'primary_detection':deepcopy(token),'secondary_detection':deepcopy(peers[0]),'positive_goods_anchor':False})
    if (rules.NONRECEIPT_TITLE.search(parsed['printed_transcription']['raw_text'])
      or any(rules.NONRECEIPT_TITLE.search(t['text']) for t in primary+secondary+alternatives)):
        return {},parsed,[*unconfirmed,{'reason':'EXPLICIT_NON_RECEIVING_PRINTED_TITLE'}]
    for model in model_rows:
        desc=model['fields'].get('description',{}).get('value');code=model['fields'].get('supplier_code',{}).get('value')
        matches=[]
        for i,row in enumerate(old_rows):
            f=row.get('fields') or {};d=(f.get('description') or {}).get('raw_value');s=(f.get('supplier_code') or {}).get('raw_value')
            if desc and _compact(desc)==_compact(d) and (not code or _compact(code)==_compact(s)):matches.append(i)
        if len(matches)!=1:
            unconfirmed.append({**model,'reason':'UNMATCHED_OR_AMBIGUOUS_CANONICAL_ROW'});continue
        index=matches[0];old=old_rows[index];desc_field=old['fields']['description'];ids=desc_field.get('token_ids') or []
        lookup={t['token_id']:t for t in primary};words=[lookup[k] for k in ids if k in lookup]
        if (not ids or len(words)!=len(set(ids)) or _union(words)!=rules._box(desc_field.get('bbox'))
          or any(w['confidence']<.70 for w in words) or _compact(' '.join(w['text'] for w in words))!=_compact(desc)):
            unconfirmed.append({**model,'reason':'SOURCE_NAME_ANCHOR_UNCONFIRMED'});continue
        anchor=_union(words)
        if not helpers['row_eligible'](old) or (page.get('document') or {}).get('document_type') in ('credit_note','return_note','credit_memo','purchase_vat_report','tax_register_report'):
            unconfirmed.append({**model,'reason':'PROTECTED_OR_EXPLICIT_NON_RECEIVING_SOURCE'});continue
        height=anchor[3]-anchor[1];row_band=[0,max(0,anchor[1]-height*.75),g['upright_size'][0],min(g['upright_size'][1],anchor[3]+height*.75)]
        negative=[t for t in primary+secondary+alternatives if rules._intersection(t['bbox'],row_band)
                  and (rules.SET.search(t['text']) or rules.FOOTER.search(t['text']) or BONUS.search(t['text']))]
        if negative:
            unconfirmed.append({**model,'reason':'ACTUAL_SOURCE_SET_BONUS_FOOTER_ROW_VETO','source_tokens':deepcopy(negative)});continue
        other_names=[(i,rules._box((r.get('fields',{}).get('description') or {}).get('bbox'))) for i,r in enumerate(old_rows) if i!=index]
        other_names.extend((None,b['bbox']) for b in unmodeled_barriers)
        if any(b and max(b[1],anchor[1])<min(b[3],anchor[3]) for _,b in other_names):
            unconfirmed.append({**model,'reason':'OVERLAPPING_CANONICAL_NAME_ROW_BARRIER'});continue
        top,bottom=0,g['upright_size'][1]
        for _,box in other_names:
            if not box:continue
            if box[3]<=anchor[1]:top=max(top,box[3])
            elif box[1]>=anchor[3]:bottom=min(bottom,box[1])
        barriers=[{'row_index':i,'bbox':deepcopy(b)} for i,b in other_names if b]
        candidates={}
        for role,cell in model['fields'].items():
            if role=='description':continue
            value=cell['value']
            found=[t for t in secondary if t['confidence']>=.70 and _baseline(anchor,t['bbox'])
                   and t['bbox'][3]-t['bbox'][1]<=height*1.65 and top<=t['bbox'][1]<t['bbox'][3]<=bottom
                   and not any(_baseline(b,t['bbox']) for _,b in other_names if b) and _same(t['text'],value,role)]
            candidates[role]=found
        # Unique monotonic whole-source assignment of at least two model
        # columns. The companion is evidence, never a value to be inferred.
        candidates['description']=[{'bbox':anchor,'aliases':ids,'token_id':ids[0]}]
        roles=[r for r in model['roles'] if r in candidates and candidates[r]]
        assignments=[]
        def visit(pos,chosen):
            if len(assignments)>1:return
            if pos==len(roles):assignments.append(dict(chosen));return
            role=roles[pos]
            for word in candidates[role][:9]:
                if len(candidates[role])>8:continue
                if chosen and list(chosen.values())[-1]['bbox'][2]>word['bbox'][0]:continue
                if any(set(word['aliases'])&set(t['aliases']) for t in chosen.values()):continue
                visit(pos+1,{**chosen,role:word})
        if len(roles)>=3:visit(0,{})
        if len(assignments)!=1:
            unconfirmed.append({**model,'reason':'INDEPENDENT_WHOLE_SOURCE_COLUMN_ASSIGNMENT_NOT_UNIQUE'});continue
        actual=assignments[0]
        for role in ('quantity','unit'):
            if role not in actual:continue
            cell=model['fields'][role];word=actual[role];value=cell['value']
            grammar=helpers['grammar'];unit=grammar.parse_literal_unit(value) if role=='unit' else None
            if (role=='quantity' and not rules.COUNT.fullmatch(value.strip()) or role=='unit' and
              (not unit or unit['packing_raw'] or unit['set_unit_requires_nonadditive_guard'])):
                unconfirmed.append({**model,'field':role,'reason':'PRINTED_LITERAL_NOT_RECEIVING_Q_OR_U'});continue
            if role=='quantity':
                number=Decimal(value.replace(',',''))
                if not number.is_finite() or not 0<=number<=10**12:
                    unconfirmed.append({**model,'field':role,'reason':'PRINTED_QUANTITY_OUTSIDE_FROZEN_LITERAL_RANGE'});continue
            if any(rules._intersection(t['bbox'],word['bbox']) and not(set(t['aliases'])&set(word['aliases'])) for t in secondary):
                unconfirmed.append({**model,'field':role,'reason':'OVERLAPPING_INDEPENDENT_SOURCE_AMBIGUITY'});continue
            wrong_headers=[t for t in primary+secondary+alternatives if t['bbox'][3]<=anchor[1]
                           and max(t['bbox'][0],word['bbox'][0])<min(t['bbox'][2],word['bbox'][2])
                           and core._role(t['text']) not in (None,'',role)]
            if wrong_headers:
                unconfirmed.append({**model,'field':role,'reason':'ACTUAL_COMPETING_SOURCE_COLUMN_HEADER','source_tokens':deepcopy(wrong_headers)});continue
            owner=helpers['owners']._foreign_owners(old_rows,index,role,[word])
            for oi,other in enumerate(old_rows):
                for name,field in (other.get('fields') or {}).items():
                    if (oi==index and name==role) or not isinstance(field,dict):continue
                    boxes=[rules._box(field.get('bbox'))]+[rules._box(s.get('bbox')) for s in field.get('source_spans',[]) if isinstance(s,dict)]
                    if any(b and rules._intersection(b,word['bbox']) for b in boxes):
                        owner.append({'row_index':oi,'field':name,'basis':'PRESERVED_FOREIGN_WHOLE_SOURCE_GEOMETRY'})
            band=word['bbox'];old_value,_=rules._read_cell(band,primary,secondary,{'token':{'bbox':anchor}},role,alternatives)
            if old_value is not None and not _same(old_value['tokens'][0]['text'],value,role):
                unconfirmed.append({**model,'field':role,'reason':'QUALIFIED_OLD_PAIR_CONTRADICTS_GLM'});continue
            proof={'policy':POLICY,'coordinate_space':'upright_image','glm_observation':deepcopy(glm_pin),'request_sha256':digest(request),
              'identity':deepcopy(observation['identity']),'table':model['table'],'model_row':model['model_row'],
              'model_cell_markup_span':deepcopy(cell['raw_markup_span']),'model_value':value,
              'source_name_token_ids':ids,'source_name_bbox':anchor,'independent_source_token':deepcopy(word),
              'ordered_source_columns':{r:deepcopy(t) for r,t in actual.items()},'foreign_owners':owner,
              'negative_source_row_band':row_band,'negative_source_row_tokens':[],
              'canonical_row_barriers':barriers,'source_row_interval':[top,bottom],
              'unmodeled_dual_source_negative_barriers':deepcopy(unmodeled_barriers),
              'whole_source_read_height_ratio_limit':1.65,'unique_canonical_source_row_owner':True,
              'no_GLM_glyph_box_or_numeric_confidence':True,'old_context_prerequisite':False}
            key=(index,role)
            if key in contexts or key in blocked:
                contexts.pop(key,None);blocked.add(key)
                unconfirmed.append({**model,'field':role,'reason':'DUPLICATE_MODEL_ROW_SOURCE_IDENTITY'});continue
            contexts[key]={'row_index':index,'field':role,'before':deepcopy(old['fields'].get(role)),
                'value':value,'normalized_value':format(Decimal(value.replace(',','')),'f') if role=='quantity' else value,
                'token':word,'anchor':words,'evidence':proof,'model_row':model,'foreign_owners':owner}
    return contexts,parsed,unconfirmed


def propose(page,cache,observation,helpers,glm_pin):
    sealed=digest([page,cache,observation]);contexts,parsed,unknown=_derive(page,cache,observation,helpers,glm_pin)
    audit={'contract':POLICY,'status':'UNCONFIRMED','proposed':[],'changes':[],'unconfirmed':unknown,
           'printed_transcription':parsed['printed_transcription'],'business_corrections':[],
           'new_model_calls':0,'model_confidence':None,'receiving_approval':False}
    for key,context in contexts.items():
        i,role=key;word=context['token'];old=context['before']
        if context['foreign_owners']:
            audit['unconfirmed'].append({'row_index':i,'field':role,'reason':'PRESERVED_FOREIGN_SOURCE_OWNER'});continue
        if (isinstance(old,dict) and _same(old.get('raw_value'),context['value'],role)
          and _same(old.get('normalized_value'),context['normalized_value'],role)):continue
        field={'raw_value':context['value'],'normalized_value':context['normalized_value'],'bbox':deepcopy(word['bbox']),
          'token_ids':[word['token_id']],'engine':'GLM_OCR_CORROBORATED_BY_ACTUAL_TESSERACT','confidence':None,
          'corroborating_observation':deepcopy(word),'model_confidence':None,'source_bbox_kind':'actual_independent_Tess_whole_detection_not_GLM_glyph',
          'corroborating_observation_coordinate_space':'upright_image',
          'source_spans':[{'token_id':word['token_id'],'raw_text':word['text'],'bbox':deepcopy(word['bbox']),
                           'engine':word['engine'],'confidence':word['confidence'],'coordinate_space':'upright_image'}],
          'glm_printed_evidence':deepcopy(context['evidence']),'prior_source_evidence':deepcopy(old),
          'business_correction_applied':False,'human_approved':False,'receiving_approval':False,
          'review_flags':['experimental_GLM_printed_fact_requires_final_review']}
        change={'row_index':i,'field':role,'before':deepcopy(old),'candidate':field,'evidence':deepcopy(context['evidence'])}
        audit['proposed'].append(change);audit['changes'].append(deepcopy(change))
    if audit['changes']:audit['status']='PROPOSED'
    if digest([page,cache,observation])!=sealed:raise ValueError('GLM evidence mutated retained inputs')
    return audit


def verify(page,cache,observation,helpers,glm_pin,row_index,role,evidence):
    contexts,_,_=_derive(page,cache,observation,helpers,glm_pin);context=contexts.get((row_index,role))
    if context is None or context['evidence']!=evidence or context['foreign_owners']:
        raise ValueError('Independently recomputed GLM/source proof differs')
    return deepcopy(context)
