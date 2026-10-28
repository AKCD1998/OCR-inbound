"""Source-only readiness check, deliberately NOT benchmark field evaluation."""
from __future__ import annotations
import argparse
from pathlib import Path
from component_common import read,checked,pin,save,contains,restore_box,valid_box
from build_trial_plan import envelope

HEADER_ROLES={'quantity':{'จำนวน','qty','quantity'},'unit':{'หน่วย','unit','uom','u/m'},
              'description':{'รายการสินค้า','ชื่อสินค้า','description','product description'}}

def readiness(observation,cache):
    if observation['source_image']['sha256']!=cache['source_sha256'] or observation['page']!=cache['page_number']:raise ValueError('Native/cache source differs')
    g=cache['geometry'];size=g['original_size'];tokens=[]
    for raw in cache['working_tokens']:
        try:b=restore_box(envelope(raw['box']),size,g['orientation_ccw'])
        except ValueError:continue
        tokens.append({**raw,'bbox':b})
    byid={t['token_id']:t for t in tokens};headers={}
    for t in tokens:
        text=' '.join(t['text'].split()).casefold()
        for role,forms in HEADER_ROLES.items():
            if text in forms and t['confidence']>=.95:headers.setdefault(role,[]).append(t)
    anchors=[]
    for i,row in enumerate(cache.get('upright_page',{}).get('product_rows',[])):
        f=(row.get('fields') or {}).get('description') or {}
        for span in f.get('source_spans',[]):
            token=byid.get(span.get('token_id'))
            if token and token['text']==span.get('raw_text') and token['engine']==span.get('engine'):
                try:original=restore_box(span['bbox'],size,g['orientation_ccw'])
                except ValueError:continue
                if token['bbox']==original:anchors.append({'row_index':i,'token_id':token['token_id'],'bbox':original});break
    observations=[]
    for table in observation['regions']:
        if table['label'].casefold()!='table' or not valid_box(table['bbox'],size):continue
        owned_headers={role:[t['token_id'] for t in group if contains(table['bbox'],t['bbox'])] for role,group in headers.items()}
        owned_anchors=[a for a in anchors if contains(table['bbox'],a['bbox'])]
        source_ready=bool(owned_headers.get('quantity') and owned_headers.get('unit') and len(owned_anchors)>=2)
        cells=[c for c in observation['cell_association']['cells'] if c.get('table_id')==table['id']]
        observations.append({'region_id':table['id'],'model_score':table['score'],'bbox':table['bbox'],
            'contained_literal_header_token_ids':owned_headers,'contained_saved_source_row_anchors':owned_anchors,
            'source_anchored_table_region_candidate':source_ready,'native_cells':len(cells),
            'native_cells_with_saved_tokens':sum(bool(c['token_ids']) for c in cells),
            'physical_cell_borders_verified':False})
    return {'page':cache['page_number'],'source_sha256':cache['source_sha256'],'tables':observations,
        'source_anchored_table_region_candidates':sum(t['source_anchored_table_region_candidate'] for t in observations),
        'native_cells':len(observation['cell_association']['cells']),
        'ambiguous_token_owners':len(observation['cell_association']['ambiguous_tokens']),
        'endpoint_field_accuracy':'NOT_EVALUATED','field_gain':None,'reference_access':False,'new_OCR_calls':0,'image_decodes':0,
        'reason_if_no_cells':'Layout regions alone cannot fill quantity/unit cells' if not observation['cell_association']['cells'] else None}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--native-summary',type=Path,required=True);ap.add_argument('--cache-manifest',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    summary=read(a.native_summary)
    if summary.get('status')!='COMPLETE':raise ValueError('Completed actual native output required')
    records={x['page_number']:x for x in read(a.cache_manifest)['pages']};outcomes=[]
    for result in summary['page_results']:
        page=read(checked(result));cache=read(checked(records[page['page']]))
        outcomes.append(readiness(page,cache))
    save(a.output,{'contract':'document-ai-source-only-geometry-readiness.v1','status':'COMPLETE','native_summary':pin(a.native_summary),
        'pages':outcomes,'reference_access':False,'image_decodes':0,'new_OCR_calls':0,'endpoint_gain':None})

if __name__=='__main__':main()
