"""Same-OCR content association: native geometry never supplies field answers."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from component_common import valid_box,rotate_box

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def normalize(observation,cache):
    if (observation.get('contract')!='document-ai-original-frame-geometry.v1' or observation.get('source_frame')!='original_image'
      or observation.get('source_image',{}).get('sha256')!=cache['source_sha256'] or observation.get('page')!=cache['page_number']
      or observation.get('source_size')!=cache['geometry']['original_size'] or observation.get('new_text_OCR_calls')!=0
      or observation.get('assistant_image_transcription') is not False):raise ValueError('Native/source/cache provenance differs')
    size=observation['source_size'];angle=cache['geometry']['orientation_ccw'];regions={};cells=[];seen=set();ids=set()
    for table in observation.get('regions',[]):
        if table['label'].casefold()=='table' and valid_box(table.get('bbox'),size):
            if table['id'] in regions:raise ValueError('Duplicate native table id')
            regions[table['id']]={**table,'bbox':rotate_box(table['bbox'],size,angle)}
    for cell in observation.get('cell_association',{}).get('cells',[]):
        if cell.get('coordinate_frame')!='original_image' or cell.get('table_id') not in regions or not valid_box(cell.get('bbox'),size):continue
        values=[cell.get(k) for k in ('start_row_offset_idx','end_row_offset_idx','start_col_offset_idx','end_col_offset_idx','row_span','col_span')]
        if any(type(v) is not int for v in values):continue
        row,endrow,col,endcol,rs,cs=values
        if min(row,col)<0 or rs!=1 or cs!=1 or endrow!=row+rs or endcol!=col+cs:continue
        key=(cell['table_id'],row,col)
        if key in seen or not isinstance(cell.get('id'),str) or not cell['id'] or cell['id'] in ids:raise ValueError('Ambiguous duplicate native cell identity/topology')
        seen.add(key);ids.add(cell['id']);cells.append({'id':cell['id'],'table_id':cell['table_id'],'row':row,'column':col,
          'bbox':rotate_box(cell['bbox'],size,angle),'original_bbox':cell['bbox'],'native_cell':deepcopy(cell)})
    return regions,cells

def assign(tokens,cells,rules):
    owners={}
    for token in tokens:
        scored=[]
        for cell in cells:
            hit=rules._intersection(token['bbox'],cell['bbox']);fraction=rules._area(hit)/rules._area(token['bbox']) if hit else 0
            scored.append((fraction,cell))
        scored.sort(key=lambda v:v[0],reverse=True)
        if scored and scored[0][0]>=.8 and (len(scored)==1 or scored[1][0]<=.2):owners[token['token_id']]=scored[0][1]
    return owners

def apply_regions(page,cache,observation,helpers,observation_pin,regions):
    """PP routing only; source header/row bands are not native table cells."""
    before=digest([page,cache,observation]);out=deepcopy(page);rules=helpers['rules'];core=helpers['core']
    audit={'status':'PP_REGION_SOURCE_HEADER_ROW_ABSTAINED','route':'PP_REGION_SOURCE_HEADER_ROW',
      'changes':[],'abstentions':[],'native_cells_used':0,'native_table_topology_supplied':False,
      'band_kind':'DERIVED_SOURCE_HEADER_ROW','physical_cell_borders_claimed':False,
      'native_observation':observation_pin,'source_confidence_gates':[.95,.70],'new_OCR_calls':0,'human_approved':False}
    out['document_ai_geometry_association']=audit
    if not regions or page.get('coordinate_space')!='upright_image' or (page.get('document') or {}).get('document_type')!='invoice_or_delivery':return out
    primary=rules._tokens(cache['working_tokens']);secondary=rules._tokens(cache['tesseract_working_tokens'],True)
    alternatives=[]
    for view in cache.get('targeted_views',[]):alternatives.extend(rules._tokens(view.get('tokens',[])))
    rows=out.get('product_rows',[]);lookup={t['token_id']:t for t in primary};proposals=[]
    for region_id,region in regions.items():
        rb=region['bbox'];tokens=[t for t in primary+secondary if rules._inside(t['bbox'],rb)]
        clean,_=core._read([{**t,'box':t['bbox']} for t in tokens],'primary',cache['geometry']['upright_size'])
        header=core._header(clean,cache['geometry']['upright_size'])
        if not header or any(t.score is None or t.score<.70 for g in header['anchors'].values() for t in g):
            audit['abstentions'].append({'region_id':region_id,'reason':'COHERENT_LITERAL_SOURCE_HEADER_NOT_ESTABLISHED'});continue
        if 'description' not in header['anchors'] or not {'quantity','unit'}.intersection(header['anchors']):continue
        anchors=[]
        for i,row in enumerate(rows):
            f=(row.get('fields') or {}).get('description') or {}
            found=[lookup[k] for k in f.get('token_ids',[]) if k in lookup and lookup[k]['text']==f.get('raw_value')
              and lookup[k]['bbox']==rules._box(f.get('bbox'))]
            if len(found)==1 and rules._inside(found[0]['bbox'],rb) and not rules._protected(row) and rules._name(found[0]['text']):
                anchors.append({'row_index':i,'token':found[0],'new':False})
        if len(anchors)<2 or len({a['row_index'] for a in anchors})!=len(anchors):
            audit['abstentions'].append({'region_id':region_id,'reason':'TWO_SAVED_GOODS_ANCHORS_INSIDE_PREDICTED_REGION_REQUIRED'});continue
        all_boxes=[(i,b) for i,row in enumerate(rows) if (b:=rules._field_box(row)) is not None and rules._inside(b,rb)]
        if not all_boxes or header['bottom']>=min(b[1] for _,b in all_boxes):continue
        if any(t['bbox'][3]<=header['bottom'] and rules.NONRECEIPT_TITLE.search(t['text']) for t in primary+secondary+alternatives):continue
        for anchor in anchors:
            i=anchor['row_index'];ab=anchor['token']['bbox'];height=rules._height(ab);cy=rules._cy(ab)
            if height>header['mh']*2:continue
            top=max(header['bottom'],ab[1]-.75*height);bottom=min(cache['geometry']['upright_size'][1],ab[3]+.75*height)
            for j,b in all_boxes:
                if i==j:continue
                other=rules._cy(b)
                if abs(cy-other)<=max(height,rules._height(b))*.75:top=bottom;break
                if other<cy:top=max(top,(cy+other)/2)
                else:bottom=min(bottom,(cy+other)/2)
            if top>=bottom or not (rb[1]<=top<bottom<=rb[3]):continue
            band=[rb[0],top,rb[2],bottom]
            if any((rules.SET.search(t['text']) or rules.FOOTER.search(t['text'])) and rules._intersection(t['bbox'],band) for t in primary+secondary+alternatives):continue
            for role in ('quantity','unit'):
                if role not in header['anchors'] or role in header['ambiguous']:continue
                left,right=header['bounds'][role]
                if not rb[0]<=left<right<=rb[2] or role=='quantity' and (left<=0 or right>=cache['geometry']['upright_size'][0]):continue
                source_band=[left,top,right,bottom]
                value,reason=rules._read_cell(source_band,primary,secondary,anchor,role,alternatives)
                if value is None:
                    audit['abstentions'].append({'region_id':region_id,'row_index':i,'field':role,'reason':reason});continue
                if helpers['owners']._foreign_owners(rows,i,role,value['tokens']) or not rules._missing((rows[i].get('fields') or {}).get(role)):continue
                proposals.append({'region_id':region_id,'region_bbox':rb,'row_index':i,'role':role,'value':value,'source_band':source_band})
    ownership={}
    for p in proposals:
        for t in p['value']['tokens']:
            for alias in t['aliases']:ownership.setdefault(alias,[]).append(p)
    for p in proposals:
        if any(len(ownership[a])!=1 for t in p['value']['tokens'] for a in t['aliases']):
            audit['abstentions'].append({'region_id':p['region_id'],'row_index':p['row_index'],'field':p['role'],'reason':'AMBIGUOUS_REGION_OR_ROW_SOURCE_OWNER'});continue
        t,other=p['value']['tokens'];role=p['role']
        rows[p['row_index']]['fields'][role]={'raw_value':t['text'],'normalized_value':p['value']['normalized_value'],
          'bbox':deepcopy(t['bbox']),'token_ids':[t['token_id']],'engine':t['engine'],'confidence':t['confidence'],
          'source_bbox_kind':'whole_actual_detection','source_spans':[{'token_id':t['token_id'],'raw_text':t['text'],
            'bbox':deepcopy(t['bbox']),'confidence':t['confidence'],'engine':t['engine']}],
          'corroborating_observation':deepcopy(other),'association_basis':'PP_REGION_SOURCE_HEADER_ROW',
          'model_geometry_evidence':{'native_observation':observation_pin,'region_id':p['region_id'],'bbox_upright':p['region_bbox'],
            'native_cells_used':0,'band_kind':'DERIVED_SOURCE_HEADER_ROW','physical_cell_border':False},
          'source_header_column_and_row_band':p['source_band'],'human_approved':False,'quantity_multiplication_applied':False,
          'review_flags':['experimental_PP_region_source_proposal_requires_review']}
        audit['changes'].append({'row_index':p['row_index'],'field':role,'source_token_ids':[v['token_id'] for v in p['value']['tokens']]})
    if audit['changes']:audit['status']='PP_REGION_SOURCE_HEADER_ROW_APPLIED'
    if digest([page,cache,observation])!=before:raise ValueError('PP region route mutated retained/native inputs')
    return out

def apply(page,cache,observation,helpers,observation_pin):
    before=digest([page,cache,observation]);out=deepcopy(page);rules=helpers['rules'];core=helpers['core'];foreign=helpers['owners']
    regions,cells=normalize(observation,cache)
    audit={'status':'NO_USABLE_NATIVE_CELL_TOPOLOGY','changes':[],'abstentions':[],
      'geometry_is_content_envelope_not_physical_borders':True,'new_OCR_calls':0,'native_observation':observation_pin,
      'source_confidence_gates':[.95,.70],'minimum_whole_word_overlap':.8,'maximum_competing_overlap':.2,'human_approved':False}
    out['document_ai_geometry_association']=audit
    if observation.get('component') in ('pp-layout','pp-layout-l'):
        if observation.get('cell_association',{}).get('cells'):raise ValueError('PP layout regions cannot be relabelled as native table cells')
        return apply_regions(page,cache,observation,helpers,observation_pin,regions)
    if not cells:
        return out
    if page.get('coordinate_space')!='upright_image' or (page.get('document') or {}).get('document_type')!='invoice_or_delivery':
        audit['status']='NO_ESTABLISHED_INVOICE_SOURCE_FRAME';return out
    primary=rules._tokens(cache['working_tokens']);secondary=rules._tokens(cache['tesseract_working_tokens'],True)
    alternatives=[]
    for view in cache.get('targeted_views',[]):alternatives.extend(rules._tokens(view.get('tokens',[])))
    rows=out.get('product_rows',[]);proposals=[];lookup={t['token_id']:t for t in primary}
    for table_id,table in regions.items():
        tc=[c for c in cells if c['table_id']==table_id];tokens=[t for t in primary+secondary if rules._inside(t['bbox'],table['bbox'])]
        clean,_=core._read([{**t,'box':t['bbox']} for t in tokens],'primary',cache['geometry']['upright_size'])
        header=core._header(clean,cache['geometry']['upright_size'])
        if not header or any(t.score is None or t.score<.70 for g in header['anchors'].values() for t in g):
            audit['abstentions'].append({'table_id':table_id,'reason':'COHERENT_LITERAL_SOURCE_HEADER_NOT_ESTABLISHED'});continue
        matched=assign(tokens,tc,rules);roles={}
        for role,words in header['anchors'].items():
            owned=[matched.get(t.id) for t in words]
            if owned and all(c is not None for c in owned) and len({c['id'] for c in owned})==1:
                cell=owned[0];valid=True
                for family in (primary,secondary):
                    text=sorted([t for t in family if matched.get(t['token_id'],{}).get('id')==cell['id']],key=lambda t:t['bbox'][0])
                    if text and (any(t['confidence']<.70 for t in text) or core._role(' '.join(t['text'] for t in text))!=role):valid=False
                if valid:roles[role]=cell
        if ('description' not in roles or not {'quantity','unit'}.intersection(roles)
          or len({c['row'] for c in roles.values()})!=1 or len({c['column'] for c in roles.values()})!=len(roles)):
            audit['abstentions'].append({'table_id':table_id,'reason':'UNIQUE_WHOLE_LITERAL_HEADER_CELL_OWNERS_NOT_ESTABLISHED'});continue
        anchors=[]
        for i,row in enumerate(rows):
            f=(row.get('fields') or {}).get('description') or {};ids=f.get('token_ids') or []
            found=[lookup[k] for k in ids if k in lookup and lookup[k]['text']==f.get('raw_value') and lookup[k]['bbox']==rules._box(f.get('bbox'))]
            if len(found)==1 and not rules._protected(row) and rules._name(found[0]['text']) and rules._inside(found[0]['bbox'],table['bbox']):
                cell=matched.get(found[0]['token_id'])
                if cell and cell['column']==roles['description']['column']:anchors.append({'row_index':i,'token':found[0],'new':False,'cell':cell})
        if len(anchors)<2 or len({a['cell']['row'] for a in anchors})!=len(anchors):
            audit['abstentions'].append({'table_id':table_id,'reason':'TWO_UNIQUE_SAVED_SOURCE_GOODS_ANCHORS_REQUIRED'});continue
        all_boxes=[(i,b) for i,row in enumerate(rows) if (b:=rules._field_box(row)) is not None and rules._inside(b,table['bbox'])]
        if not all_boxes or header['bottom']>=min(b[1] for _,b in all_boxes):continue
        if any(t['bbox'][3]<=header['bottom'] and rules.NONRECEIPT_TITLE.search(t['text']) for t in primary+secondary+alternatives):continue
        for anchor in anchors:
            i=anchor['row_index'];ab=anchor['token']['bbox'];height=rules._height(ab);cy=rules._cy(ab)
            if height>header['mh']*2 or anchor['cell']['row']<=roles['description']['row']:continue
            top=max(header['bottom'],ab[1]-.75*height);bottom=min(cache['geometry']['upright_size'][1],ab[3]+.75*height)
            for j,b in all_boxes:
                if i==j:continue
                other=rules._cy(b)
                if abs(cy-other)<=max(height,rules._height(b))*.75:top=bottom;break
                if other<cy:top=max(top,(cy+other)/2)
                else:bottom=min(bottom,(cy+other)/2)
            if top>=bottom:continue
            band=[table['bbox'][0],top,table['bbox'][2],bottom]
            if any((rules.SET.search(t['text']) or rules.FOOTER.search(t['text'])) and rules._intersection(t['bbox'],band) for t in primary+secondary+alternatives):continue
            for role in ('quantity','unit'):
                if role not in roles or role in header['ambiguous']:continue
                targets=[c for c in tc if c['row']==anchor['cell']['row'] and c['column']==roles[role]['column']]
                if len(targets)!=1:continue
                left,right=header['bounds'][role]
                if role=='quantity' and (left<=0 or right>=cache['geometry']['upright_size'][0]):continue
                value,reason=rules._read_cell([left,top,right,bottom],primary,secondary,anchor,role,alternatives)
                if value is None:audit['abstentions'].append({'row_index':i,'field':role,'reason':reason});continue
                cell=targets[0]
                if any(matched.get(t['token_id'],{}).get('id')!=cell['id'] for t in value['tokens']):continue
                if any(len([t for t in family if matched.get(t['token_id'],{}).get('id')==cell['id']])!=1 for family in (primary,secondary)):continue
                if foreign._foreign_owners(rows,i,role,value['tokens']) or not rules._missing((rows[i].get('fields') or {}).get(role)):continue
                proposals.append({'row_index':i,'role':role,'value':value,'cell':cell,'source_band':[left,top,right,bottom]})
    aliases={}
    for p in proposals:
        for token in p['value']['tokens']:
            for alias in token['aliases']:aliases.setdefault(alias,[]).append(p)
    for p in proposals:
        if any(len(aliases[a])!=1 for t in p['value']['tokens'] for a in t['aliases']):continue
        t,other=p['value']['tokens'];role=p['role']
        field={'raw_value':t['text'],'normalized_value':p['value']['normalized_value'],'bbox':deepcopy(t['bbox']),
          'token_ids':[t['token_id']],'engine':t['engine'],'confidence':t['confidence'],'source_bbox_kind':'whole_actual_detection',
          'source_spans':[{'token_id':t['token_id'],'raw_text':t['text'],'bbox':deepcopy(t['bbox']),'confidence':t['confidence'],'engine':t['engine']}],
          'corroborating_observation':deepcopy(other),'association_basis':'native_content_cell_whole_literal_header_existing_row_dual_reader',
          'model_geometry_evidence':{'native_observation':observation_pin,'cell_id':p['cell']['id'],'row':p['cell']['row'],'column':p['cell']['column'],
            'original_bbox':p['cell']['original_bbox'],'content_envelope_not_physical_border':True},
          'source_header_column_and_row_band':p['source_band'],'human_approved':False,'quantity_multiplication_applied':False,
          'review_flags':['experimental_geometry_source_proposal_requires_review']}
        rows[p['row_index']]['fields'][role]=field;audit['changes'].append({'row_index':p['row_index'],'field':role,'source_token_ids':[v['token_id'] for v in p['value']['tokens']]})
    audit['status']='APPLIED' if audit['changes'] else 'ABSTAINED'
    if digest([page,cache,observation])!=before:raise ValueError('Retained/native inputs mutated')
    return out
