"""Source-header/row-band proposals, without pretending bands are model cells.

Pure retained-token geometry. Actual table ROIs are preferred; when absent,
literal headings and two existing source-bound names can prove a derived
region. The verifier rebuilds every context from immutable inputs. It never
consumes candidate answers, catalogues, files, images, models or references.
"""
from copy import deepcopy
import re
from statistics import median
from component_common import rotate_box, valid_box
from correction_eligibility import BONUS, assess_row
from eval_geometry import digest

VERSION='document-ai-source-header-row-band.v2-row-barriers'
ROLES=('quantity','unit')
LIMIT=256

def _union(words):
    return [min(t['bbox'][0] for t in words),min(t['bbox'][1] for t in words),
            max(t['bbox'][2] for t in words),max(t['bbox'][3] for t in words)]

def _compact(text):return ''.join(str(text or '').split()).casefold()

def _same_baseline(anchor_box,value_box):
    overlap=max(0,min(anchor_box[3],value_box[3])-max(anchor_box[1],value_box[1]))
    return overlap>=.5*min(anchor_box[3]-anchor_box[1],value_box[3]-value_box[1])

def _inputs(page,cache,observation,helpers,pin):
    flags=cache.get('inference_inputs') or {};g=cache['geometry']
    if (any(flags.get(k) is not False for k in ('reference','human_answers','Ada','StockDay'))
            or flags.get('assistant_image_reads')!=0):raise ValueError('machine_only_inputs_required')
    if (observation.get('contract')!='document-ai-original-frame-geometry.v1'
            or observation.get('source_frame')!='original_image'
            or observation.get('source_image',{}).get('sha256')!=cache['source_sha256']
            or observation.get('page')!=cache['page_number'] or observation.get('source_size')!=g['original_size']
            or observation.get('new_text_OCR_calls')!=0 or observation.get('assistant_image_transcription') is not False
            or page.get('source_sha256')!=cache['source_sha256'] or page.get('page_number')!=cache['page_number']
            or page.get('coordinate_space')!='upright_image' or page.get('image_size')!=g['upright_size']):
        raise ValueError('immutable_source_identity_or_frame_differs')
    rules=helpers['rules'];core=helpers['core']
    if (page.get('document') or {}).get('document_type') in ('credit_note','credit_memo','return_note','purchase_vat_report','tax_register_report'):
        raise ValueError('explicit_non_receiving_parent_document')
    classifier=helpers.get('document_admission')
    if classifier is not None:
        if classifier.assess_document(page,cache,rules,core,observation=observation,observation_pin=pin).get('eligible') is not True:
            raise ValueError('document_source_admission_rejected')
    elif (page.get('document') or {}).get('document_type')!='invoice_or_delivery':
        raise ValueError('document_source_admission_required')
    regions=[];seen=set()
    for region in observation.get('regions',[]):
        if str(region.get('label','')).casefold()!='table':continue
        if not isinstance(region.get('id'),str) or not region['id'] or region['id'] in seen:
            raise ValueError('unique_actual_table_region_identity_required')
        if not valid_box(region.get('bbox'),g['original_size']):raise ValueError('invalid_actual_table_region')
        seen.add(region['id']);regions.append({'kind':'ACTUAL_NATIVE_TABLE_ROI','native_region_id':region['id'],
            'bbox':rotate_box(region['bbox'],g['original_size'],g['orientation_ccw'])})
    primary=rules._tokens(cache.get('working_tokens',[]));secondary=rules._tokens(cache.get('tesseract_working_tokens',[]),True)
    alternatives=[]
    for view in cache.get('targeted_views',[]):alternatives.extend(rules._tokens(view.get('tokens',[])))
    if any(not valid_box(t['bbox'],g['upright_size']) for t in primary+secondary+alternatives):
        raise ValueError('whole_source_detection_outside_declared_frame')
    if len(page.get('product_rows',[]))>LIMIT:raise ValueError('bounded_source_row_inventory_required')
    return regions,primary,secondary,alternatives

def _anchors(page,primary,domain,header,helpers):
    rules=helpers['rules'];bridge=helpers['correction_bridge'];lookup={t['token_id']:t for t in primary};anchors=[]
    footer_top=min((t['bbox'][1] for t in primary if rules._inside(t['bbox'],domain)
                    and t['bbox'][1]>header['bottom'] and rules.FOOTER.search(t['text'])),default=domain[3])
    for index,row in enumerate(page.get('product_rows',[])):
        f=(row.get('fields') or {}).get('description') or {}
        ids=f.get('token_ids') or [s.get('token_id') for s in f.get('source_spans',[]) if isinstance(s,dict)]
        if not ids or len(set(ids))!=len(ids) or any(key not in lookup for key in ids):continue
        words=sorted([lookup[key] for key in ids],key=lambda t:(rules._cy(t['bbox']),t['bbox'][0],t['token_id']))
        box=_union(words)
        if (rules._box(f.get('bbox'))!=box or _compact(f.get('raw_value'))!=_compact(' '.join(t['text'] for t in words))
                or not rules._name(' '.join(t['text'] for t in words)) or any(t['confidence']<.70 for t in words)
                or not rules._inside(box,domain) or box[1]<=header['bottom'] or box[3]>=footer_top
                or rules._height(box)>max(rules._height(t['bbox']) for t in words)*1.8):continue
        left,right=header['bounds']['description'];proof=None
        if not all(rules._inside(t['bbox'],[left,header['bottom'],right,domain[3]]) for t in words):
            proof=bridge._description_gap(box,header,lookup,rules)
            if proof is None:continue
        anchors.append({'row_index':index,'token':{**words[0],'bbox':box},'tokens':words,
            'eligibility':assess_row(row,rules),'description_column_proof':proof})
    return anchors

def _row_barriers(page,primary,secondary,domain,header,helpers):
    """Negative row boundaries; uncertain names never become goods anchors."""
    rules=helpers['rules'];bridge=helpers['correction_bridge'];lookup={t['token_id']:t for t in primary}
    barriers=[];used=set()
    for index,row in enumerate(page.get('product_rows',[])):
        field=(row.get('fields') or {}).get('description') or {};declared=rules._box(field.get('bbox'))
        ids=field.get('token_ids') or [s.get('token_id') for s in field.get('source_spans',[]) if isinstance(s,dict)]
        found=[lookup[key] for key in ids if key in lookup]
        used.update(a for t in found for a in t['aliases'])
        actual=_union(found) if found else None
        if declared is None:declared=actual
        if declared is None or not rules._inside(declared,domain) or declared[3]<=header['bottom']:continue
        bound=bool(ids and len(ids)==len(set(ids)) and len(found)==len(ids) and actual==declared)
        box=declared if actual is None else [min(declared[0],actual[0]),min(declared[1],actual[1]),max(declared[2],actual[2]),max(declared[3],actual[3])]
        barriers.append({'kind':'CANONICAL_SOURCE_ROW_BARRIER' if bound else 'UNRESOLVED_CANONICAL_ROW_LOCATION',
            'row_index':index,'bbox':box,'token_ids':[t['token_id'] for t in found],
            'declared_description_bbox':declared,'actual_detection_union':actual,
            'raw_name_matching_used':False,'receiving_eligibility_used':False,'positive_goods_anchor':False})
    # Unmodelled names are only negative barriers, and need two genuine reads.
    # No LOT/free/SET/footer string is inferred to be a goods row here.
    for token in primary:
        text=token['text'];box=token['bbox']
        if (set(token['aliases'])&used or token['confidence']<.95 or box[1]<=header['bottom']
                or not rules._inside(box,domain) or not rules._name(text)
                or BONUS.search(text) or rules.SET.search(text) or rules.FOOTER.search(text)
                or re.match(r'^\s*(?:LOT|BATCH|MFG|MFD|EXP|REF)(?=\b|[:#.\d])',text,re.I)):
            continue
        left,right=header['bounds']['description']
        if not rules._inside(box,[left,header['bottom'],right,domain[3]]) and bridge._description_gap(box,header,lookup,rules) is None:
            continue
        corroborating=[]
        for other in secondary:
            if (other['confidence']<.70 or _compact(other['text'])!=_compact(text)
                    or set(token['aliases'])&set(other['aliases']) or not _same_baseline(box,other['bbox'])):continue
            x=max(0,min(box[2],other['bbox'][2])-max(box[0],other['bbox'][0]))
            if x>=.8*min(box[2]-box[0],other['bbox'][2]-other['bbox'][0]):corroborating.append(other)
        if len(corroborating)!=1:continue
        other=corroborating[0];whole=_union([token,other])
        barriers.append({'kind':'UNMODELED_DUAL_SOURCE_NAME_BARRIER','row_index':None,'bbox':whole,
            'token_ids':[token['token_id'],other['token_id']],
            'primary_detection':deepcopy(token),'secondary_detection':deepcopy(other),'positive_goods_anchor':False})
    return barriers

def _contexts(page,cache,observation,helpers,pin):
    regions,primary,secondary,alternatives=_inputs(page,cache,observation,helpers,pin)
    rules,core,bridge=(helpers[k] for k in ('rules','core','correction_bridge'))
    size=cache['geometry']['upright_size'];lookup={t['token_id']:t for t in primary};contexts=[];rejected=[]
    token_digest=digest([primary,secondary,alternatives])
    domains=regions or [{'kind':'SOURCE_DERIVED_TABLE_REGION','native_region_id':None,'bbox':[0,0,*size]}]
    for domain in domains:
        local=[t for t in primary if rules._inside(t['bbox'],domain['bbox'])]
        clean,_=core._read([{**t,'box':t['bbox']} for t in local],'primary',size)
        header=bridge._literal_header(clean,core,size)
        if (not header or header['ambiguous'] or any(t.score is None or t.score<.70 for g in header['anchors'].values() for t in g)):
            rejected.append({'reason':'unambiguous_whole_literal_headers_required'});continue
        if any(t['bbox'][3]<=header['bottom'] and rules.NONRECEIPT_TITLE.search(t['text']) for t in primary+secondary+alternatives):
            rejected.append({'reason':'source_non_receipt_title'});continue
        anchors=_anchors(page,primary,domain['bbox'],header,helpers)
        eligible=[a for a in anchors if a['eligibility']['eligible']]
        if len(eligible)<2:
            rejected.append({'reason':'two_exact_existing_eligible_goods_names_required'});continue
        ordered=sorted(anchors,key=lambda a:(rules._cy(a['token']['bbox']),a['row_index']))
        if [a['row_index'] for a in ordered]!=sorted(a['row_index'] for a in ordered):
            rejected.append({'reason':'existing_row_source_order_conflict'});continue
        aliases={}
        for anchor in anchors:
            for token in anchor['tokens']:
                for alias in token['aliases']:aliases.setdefault(alias,set()).add(anchor['row_index'])
        if any(len(v)>1 for v in aliases.values()):
            rejected.append({'reason':'source_name_identity_reused_across_rows'});continue
        if any(abs(rules._cy(a['token']['bbox'])-rules._cy(b['token']['bbox']))<=max(rules._height(a['token']['bbox']),rules._height(b['token']['bbox']))*.75
               for a,b in zip(ordered,ordered[1:])):
            rejected.append({'reason':'disjoint_source_row_baselines_required'});continue
        header_words={role:[lookup[t.id] for t in words] for role,words in header['anchors'].items()}
        if any(core._role(' '.join(t['text'] for t in header_words[k]))!=k for k in ('description',*ROLES)):
            rejected.append({'reason':'whole_literal_header_role_differs'});continue
        body_top=max(header['bottom'],min(a['token']['bbox'][1]-.75*rules._height(a['token']['bbox']) for a in ordered))
        body_bottom=max(a['token']['bbox'][3]+.75*rules._height(a['token']['bbox']) for a in ordered)
        if not 0<=body_top<body_bottom<=size[1]:continue
        region=deepcopy(domain)
        if domain['kind']=='SOURCE_DERIVED_TABLE_REGION':
            content=[]
            for family,words in (('primary',primary),('secondary',secondary),('alternative',alternatives)):
                for token in words:
                    if rules._intersection(token['bbox'],[0,body_top,size[0],body_bottom]):
                        content.append({'family':family,'token_id':token['token_id'],'bbox':deepcopy(token['bbox']),
                            'engine':token['engine'],'confidence':token['confidence']})
            all_header_words=[t for words in header_words.values() for t in words]
            boxes=[t['bbox'] for t in all_header_words]+[t['bbox'] for t in content]
            if not boxes:continue
            extent=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(body_bottom,max(b[3] for b in boxes))]
            if not valid_box(extent,size):continue
            region={'kind':'SOURCE_DERIVED_TABLE_REGION','native_region_id':None,'bbox':extent,
                'extent_provenance':{'kind':'ALL_WHOLE_SOURCE_CONTENT_AND_SELECTED_HEADINGS',
                    'proven_source_row_span':[body_top,body_bottom],
                    'heading_token_ids':[t['token_id'] for t in all_header_words],'content_detections':content,
                    'value_unit_type_filtering_applied':False}}
        columns={};boundaries={}
        for role in ROLES:
            left,right=header['bounds'][role];left_kind=right_kind='ADJACENT_LITERAL_HEADER_MIDPOINT'
            edge_kind='ACTUAL_ROI_EDGE' if domain['kind']=='ACTUAL_NATIVE_TABLE_ROI' else 'SOURCE_CONTENT_EXTENT'
            if left==0:left=region['bbox'][0];left_kind=edge_kind
            if right==size[0]:right=region['bbox'][2];right_kind=edge_kind
            columns[role]=[left,right];boundaries[role]={'left':left_kind,'right':right_kind}
        bounds=[columns[k] for k in ROLES]
        if (any(not region['bbox'][0]<=left<right<=region['bbox'][2] for left,right in bounds)
                or max(bounds[0][0],bounds[1][0])<min(bounds[0][1],bounds[1][1])):
            rejected.append({'reason':'disjoint_bounded_quantity_and_unit_columns_required'});continue
        # Whole competing heading boxes, including neutral prices, cannot
        # intrude merely because their centres fall outside a proposed column.
        if any(other not in (role,'description') and min(t['bbox'][0] for t in words)<columns[role][1]
               and max(t['bbox'][2] for t in words)>columns[role][0]
               for role in ROLES for other,words in header_words.items()):
            rejected.append({'reason':'competing_whole_heading_intrudes_source_column'});continue
        peer_rows=[{'row_index':a['row_index'],'token_ids':[t['token_id'] for t in a['tokens']],
                    'bbox':deepcopy(a['token']['bbox']),'eligible':a['eligibility']['eligible']} for a in ordered]
        barriers=_row_barriers(page,primary,secondary,domain['bbox'],header,helpers)
        for ai,anchor in enumerate(ordered):
            if not anchor['eligibility']['eligible']:continue
            ab=anchor['token']['bbox'];height=rules._height(ab);cy=rules._cy(ab)
            top=max(header['bottom'],ab[1]-.75*height);bottom=ab[3]+.75*height
            if ai:top=max(top,(cy+rules._cy(ordered[ai-1]['token']['bbox']))/2)
            if ai+1<len(ordered):bottom=min(bottom,(cy+rules._cy(ordered[ai+1]['token']['bbox']))/2)
            ambiguous=False
            for barrier in barriers:
                if barrier['row_index']==anchor['row_index']:continue
                bb=barrier['bbox'];other=rules._cy(bb)
                if max(ab[1],bb[1])<min(ab[3],bb[3]) or other==cy:
                    ambiguous=True;break
                if other<cy:top=max(top,(cy+other)/2)
                else:bottom=min(bottom,(cy+other)/2)
            if ambiguous or not top<=ab[1]<ab[3]<=bottom:
                rejected.append({'row_index':anchor['row_index'],'reason':'ambiguous_or_overlapping_source_row_barrier'});continue
            if top>=bottom or not 0<=top<bottom<=size[1]:continue
            if domain['kind']=='ACTUAL_NATIVE_TABLE_ROI':
                if not domain['bbox'][1]<=top<bottom<=domain['bbox'][3]:continue
            row_band=[region['bbox'][0],top,region['bbox'][2],bottom]
            if any((rules.SET.search(t['text']) or rules.FOOTER.search(t['text']) or BONUS.search(t['text']))
                   and rules._intersection(t['bbox'],row_band) for t in primary+secondary+alternatives):
                rejected.append({'row_index':anchor['row_index'],'reason':'source_set_bonus_footer_in_row_band'});continue
            for role in ROLES:
                left,right=columns[role];band=[left,top,right,bottom]
                if not region['bbox'][0]<=left<right<=region['bbox'][2]:continue
                evidence={'route':'SOURCE_HEADER_ROW_BAND','coordinate_space':'upright_image',
                    'source_page':page['page_number'],'source_sha256':page['source_sha256'],
                    'retained_tokens_sha256':token_digest,'source_geometry_sha256':digest(cache['geometry']),
                    'native_observation':deepcopy(pin),'region':deepcopy(region),'native_cells_used':0,
                    'physical_cell_borders_claimed':False,'row_index':anchor['row_index'],'field':role,
                    'anchor_token_ids':[t['token_id'] for t in anchor['tokens']], 'anchor_bbox':deepcopy(ab),
                    'peer_source_rows':deepcopy(peer_rows),'source_column_bounds':[left,right],
                    'negative_row_barriers':deepcopy(barriers),'value_same_baseline_minimum_vertical_fraction':.5,
                    'source_column_boundary_basis':deepcopy(boundaries[role]),
                    'source_header_band':band,'source_row_band_bbox':row_band,
                    'role_header_tokens':deepcopy(header_words[role]),
                    'whole_source_headers':deepcopy(header_words),
                    'description_column_proof':deepcopy(anchor['description_column_proof'])}
                if len(contexts)>=LIMIT:raise ValueError('bounded_source_context_inventory_required')
                contexts.append({'row_index':anchor['row_index'],'role':role,'source_band':band,
                    'anchor':deepcopy(anchor),'region':region,'evidence':evidence,
                    'primary':primary,'secondary':secondary,'alternatives':alternatives})
    counts={}
    for context in contexts:
        key=(context['row_index'],context['role']);counts[key]=counts.get(key,0)+1
    return [x for x in contexts if counts[(x['row_index'],x['role'])]==1],rejected+[
        {'row_index':i,'field':role,'reason':'ambiguous_multiple_source_regions'} for (i,role),count in counts.items() if count!=1]

def verify(page,cache,observation,helpers,pin,row_index,role,evidence):
    """Rebuild from original source only; caller separately checks the value."""
    frozen=digest([page,cache,observation]);contexts,_=_contexts(page,cache,observation,helpers,pin)
    found=[x for x in contexts if x['row_index']==row_index and x['role']==role]
    if len(found)!=1 or found[0]['evidence']!=evidence:raise ValueError('recomputed_source_cell_evidence_differs')
    if digest([page,cache,observation])!=frozen:raise ValueError('source_context_verification_mutated_inputs')
    return deepcopy(found[0])

def _field(value,before,evidence):
    a,b=value['tokens']
    return {'raw_value':a['text'],'normalized_value':value['normalized_value'],'bbox':deepcopy(a['bbox']),
        'token_ids':[a['token_id']],'engine':a['engine'],'confidence':a['confidence'],
        'source_bbox_kind':'whole_actual_detection','source_spans':[{'token_id':a['token_id'],'raw_text':a['text'],
            'bbox':deepcopy(a['bbox']),'confidence':a['confidence'],'engine':a['engine']}],
        'corroborating_observation':deepcopy(b),'prior_source_evidence':deepcopy(before),
        'association_basis':'SOURCE_HEADER_ROW_BAND','source_header_column_and_row_band':deepcopy(evidence['source_header_band']),
        'model_geometry_evidence':{'native_observation':deepcopy(evidence['native_observation']),
            'region':deepcopy(evidence['region']),'native_cells_used':0,'physical_cell_borders_claimed':False},
        'human_approved':False,'human_verified':False,'business_correction_applied':False,
        'quantity_multiplication_applied':False,'review_flags':['experimental_source_row_band_requires_final_review']}

def propose(page,cache,observation,helpers,pin):
    frozen=digest([page,cache,observation]);audit={'contract':VERSION,'route':'SOURCE_HEADER_ROW_BAND',
        'status':'ABSTAINED','changes':[],'proposed':[],'rejected':[],'source_contexts':[],
        'native_cells_used':0,'physical_cell_borders_claimed':False,'new_OCR_calls':0,'new_model_calls':0,
        'reference_access':False,'human_approved':False}
    try:contexts,rejected=_contexts(page,cache,observation,helpers,pin)
    except (ValueError,TypeError,KeyError) as error:
        audit['rejected'].append({'reason':str(error)});return audit
    audit['rejected'].extend(rejected);pending={};pairs={};rows=page.get('product_rows',[]);rules=helpers['rules'];bridge=helpers['correction_bridge']
    for context in contexts:
        i,role=context['row_index'],context['role'];evidence=context['evidence'];audit['source_contexts'].append(deepcopy(evidence))
        value,reason=rules._read_cell(context['source_band'],context['primary'],context['secondary'],context['anchor'],role,context['alternatives'])
        if value is None:
            audit['rejected'].append({'row_index':i,'field':role,'reason':reason});continue
        if any(not _same_baseline(context['anchor']['token']['bbox'],t['bbox']) for t in value['tokens']):
            audit['rejected'].append({'row_index':i,'field':role,'reason':'actual_value_not_on_established_name_baseline'});continue
        before=(rows[i].get('fields') or {}).get(role);candidate=_field(value,before,evidence)
        event={'row_index':i,'field':role,'before':deepcopy(before),'candidate':candidate,'evidence':deepcopy(evidence),
               'reason':'INDEPENDENT_PRINTED_SOURCE_ROW_BAND_REASSOCIATION'}
        audit['proposed'].append(deepcopy(event))
        if bridge._old_same(before,candidate,role):
            audit['rejected'].append({'row_index':i,'field':role,'reason':'existing_field_already_matches_printed_source'});continue
        key=(i,role);pending[key]=event;pairs[key]=value['tokens']
    aliases={}
    for key,words in pairs.items():
        for word in words:
            for alias in word['aliases']:aliases.setdefault(alias,set()).add(key)
    while True:
        failed=[]
        for key,event in pending.items():
            reason=None
            if any(len(aliases[a])!=1 for t in pairs[key] for a in t['aliases']):reason='ambiguous_field_source_ownership'
            owners=helpers['owners']._foreign_owners(rows,key[0],key[1],pairs[key])
            for owner in owners:
                other=(owner['row_index'],owner['field'])
                if (other[0]!=key[0] or other[1] not in ROLES or other not in pending
                        or any(set(a['aliases'])&set(b['aliases']) for a in pairs[key] for b in pairs[other])):
                    reason='preserved_foreign_source_owner';break
            if reason:failed.append((key,reason))
        if not failed:break
        for key,reason in failed:
            pending.pop(key);audit['rejected'].append({'row_index':key[0],'field':key[1],'reason':reason})
    audit['changes']=[deepcopy(v) for v in pending.values()]
    audit['status']='PROPOSED' if audit['changes'] else 'ABSTAINED'
    if digest([page,cache,observation])!=frozen:raise ValueError('source_cell_proposal_mutated_inputs')
    return audit
