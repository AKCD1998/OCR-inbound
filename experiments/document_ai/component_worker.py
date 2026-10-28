"""Serial CPU-only geometry trial; defaults to metadata-only validation."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import time
from component_common import (RESOURCES,read,sha,pin,save,checked,validate_task,
                              component_preflight,verify_admission,restore_box,rotate_box,valid_box,attach_tokens)

def materialization(registry,component,receipt_path,registry_path=None):
    receipt=read(receipt_path)
    if receipt.get('status')!='COMPLETE' or receipt.get('component')!=component:raise ValueError('Exact model materialization required')
    if registry_path and receipt.get('registry')!=pin(registry_path):raise ValueError('Materialization registry differs')
    for artifact in receipt['files']:checked(artifact)
    expected={(key,f['name']):(f['size'],f.get('sha256')) for key in registry['components'][component]['models'] for f in registry['models'][key]['files']}
    actual={(f['model'],f['member']):(f['size'],f['sha256']) for f in receipt['files']}
    if set(actual)!=set(expected):raise ValueError('Model materialization member list differs')
    for key,(size,digest) in expected.items():
        if actual[key][0]!=size or digest and actual[key][1]!=digest:raise ValueError('Model materialization bytes differ')
    return receipt

def payload(value):
    if isinstance(value,str):value=json.loads(value)
    if isinstance(value,dict) and isinstance(value.get('res'),dict):value=value['res']
    if not isinstance(value,dict):raise ValueError('Unsupported native result; preserve raw failure')
    return value

def plain(value):
    if value is None or isinstance(value,(str,int,float,bool)):return value
    if isinstance(value,dict):return {str(k):plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [plain(v) for v in value]
    if hasattr(value,'tolist'):return plain(value.tolist())
    raise TypeError('Native result is not supported JSON data: '+type(value).__name__)

class PaddleLayout:
    def __init__(self,root,key='pp-layout',progress=lambda _:None):
        progress('CV_IMPORT_STARTED')
        import cv2
        cv2.setNumThreads(1)
        progress('PADDLE_SDK_IMPORT_STARTED')
        from paddlex import create_model
        progress('PADDLE_SDK_IMPORT_COMPLETED')
        progress('MODEL_CONSTRUCTION_STARTED')
        # Same direct static SDK entry point already used by the audited
        # SLANet canary; avoid importing unrelated PaddleOCR wrapper pipelines.
        self.model=create_model(model_name='PP-DocLayout-L' if key=='pp-layout-l' else 'PP-DocLayout-M',model_dir=str(root/key),
            device='cpu',engine='paddle_static',cpu_threads=1,enable_mkldnn=False,enable_hpi=False)
        progress('MODEL_CONSTRUCTION_COMPLETED')
    def predict(self,image,tokens):
        import numpy as np
        result=list(self.model.predict(input=np.asarray(image)[:,:,::-1].copy(),batch_size=1))
        if len(result)!=1:raise ValueError('One page must yield one layout result')
        raw=plain(payload(result[0].json));regions=[]
        for i,item in enumerate(raw.get('boxes',[])):
            regions.append({'id':'layout-'+str(i),'label':str(item.get('label') or item.get('class_id')),
                            'score':float(item['score']),'bbox':[float(x) for x in item['coordinate']]})
        return {'raw':raw,'regions':regions,'cells':[],'layout_model_calls':1,'table_model_calls':0}
    def close(self):self.model.close()

def docling_native_cells(outputs,table_ids):
    """Retain structure geometry; generated/matched native strings are not answers."""
    if len(outputs)!=len(table_ids):raise ValueError('Native table response count differs from actual requested tables')
    cells=[]
    for table_id,out in zip(table_ids,outputs):
        for i,item in enumerate(out['tf_responses']):
            b=item.get('bbox')
            if not isinstance(b,dict) or not all(k in b for k in ('l','t','r','b')):continue
            cells.append({'id':table_id+'-cell-'+str(i),'table_id':table_id,
                'bbox':[float(b[k]) for k in ('l','t','r','b')],
                **{k:item[k] for k in ('start_row_offset_idx','end_row_offset_idx','start_col_offset_idx','end_col_offset_idx','row_span','col_span','column_header','row_header','row_section') if k in item},
                'native_bbox_is_content_envelope_not_verified_physical_border':True})
    return cells

class DoclingLayoutTables:
    def __init__(self,root,progress=lambda _:None):
        progress('CV_IMPORT_STARTED')
        import cv2
        cv2.setNumThreads(1)
        progress('TORCH_IMPORT_STARTED')
        import torch
        torch.set_num_threads(1);torch.set_num_interop_threads(1)
        progress('TRANSFORMERS_IMPORT_STARTED')
        from transformers import DFineForObjectDetection,RTDetrImageProcessor
        progress('EGRET_CONSTRUCTION_STARTED')
        self.processor=RTDetrImageProcessor.from_pretrained(root/'docling-layout',local_files_only=True)
        self.layout=DFineForObjectDetection.from_pretrained(root/'docling-layout',local_files_only=True).to('cpu').eval()
        progress('EGRET_CONSTRUCTION_COMPLETED')
        import docling_ibm_models.tableformer.common as c
        from docling_ibm_models.tableformer.data_management.tf_predictor import TFPredictor
        folder=root/'tableformer'/'model_artifacts'/'tableformer'/'fast'
        config=c.read_config(str(folder/'tm_config.json'));config['model']['save_dir']=str(folder)
        progress('TABLEFORMER_CONSTRUCTION_STARTED')
        self.table=TFPredictor(config,device='cpu',num_threads=1)
        progress('TABLEFORMER_CONSTRUCTION_COMPLETED')
    def predict(self,image,tokens):
        import numpy as np
        import torch
        inputs=self.processor(images=[image],return_tensors='pt')
        with torch.inference_mode():out=self.layout(**inputs)
        native=self.processor.post_process_object_detection(out,target_sizes=torch.tensor([[image.height,image.width]]),threshold=.6)[0]
        regions=[]
        for i,(label,score,box) in enumerate(zip(native['labels'].tolist(),native['scores'].tolist(),native['boxes'].tolist())):
            regions.append({'id':'layout-'+str(i),'label':self.layout.config.id2label[label],'score':score,'bbox':box})
        # Exact-frame check before SDK cropping: never clip to make a box usable.
        tables=[r for r in regions if r['label'].casefold()=='table' and valid_box(r['bbox'],image.size)]
        if len(tables)>4:raise ValueError('More than4 table calls on one page; retain layout and review bounded plan before extending')
        page={'width':image.width,'height':image.height,'image':np.asarray(image),
              'tokens':[{'id':i,'text':t['text'],'bbox':dict(zip(('l','t','r','b'),t['bbox']),coord_origin='TOPLEFT')} for i,t in enumerate(tokens)]}
        outputs=[]
        for table in tables:
            outputs.extend(self.table.multi_table_predict(page,[list(table['bbox'])],do_matching=True))
        raw={'layout':plain(native),'tables':plain(outputs)}
        return {'raw':raw,'regions':regions,'cells':docling_native_cells(outputs,[t['id'] for t in tables]),'layout_model_calls':1,'table_model_calls':len(tables)}
    def close(self):
        del self.layout;del self.table

def execute(args,plan,registry,proof):
    component=plan['component'];verify_admission(args.admission,args.admission_sha256,__file__,component)
    pre=component_preflight(registry,component)
    if not pre['admitted_for_bounded_canary']:raise ValueError('Preflight refuses native start: '+str(pre['blocked_reasons']))
    if component=='qwen':raise ValueError('Selected native Qwen cannot fit approved RSS budget')
    model_root=Path(proof['model_root']);output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    save(output/'STARTED.json',{'contract':'document-ai-component-trial.v1','utc':datetime.now(timezone.utc).isoformat(),'plan':pin(args.plan),'worker':pin(__file__),'registry':pin(args.registry),'component':component,'actual_model_predict_calls_started':0})
    import faulthandler
    faulthandler.dump_traceback_later(30,repeat=True)
    began=time.monotonic()
    def progress(phase):save(output/(phase+'.json'),{'phase':phase,'elapsed_seconds':time.monotonic()-began,'utc':datetime.now(timezone.utc).isoformat()})
    worker=PaddleLayout(model_root,component,progress) if component in ('pp-layout','pp-layout-l') else DoclingLayoutTables(model_root,progress)
    completed=[];calls=0;layout_calls=0;table_calls=0
    try:
        from PIL import Image
        for task in plan['tasks']:
            validate_task(task);source=checked(task['source_image']);angle=task.get('rotation_ccw',0)
            with Image.open(source) as im:
                if list(im.size)!=task['source_size']:raise ValueError('Raw source raster differs from pinned frame')
                image=im.convert('RGB')
            if angle:
                transpose={90:Image.Transpose.ROTATE_90,180:Image.Transpose.ROTATE_180,270:Image.Transpose.ROTATE_270}
                if angle not in transpose:raise ValueError('Only exact recorded right-angle rotation')
                image=image.transpose(transpose[angle])
            calls+=1
            save(output/('PREDICT_STARTED_'+str(task['page'])+'.json'),{'page':task['page'],'predict_call_index':calls,'source_image':task['source_image']})
            rotated_tokens=[{**t,'bbox':rotate_box(t['bbox'],task['source_size'],angle)} for t in task.get('tokens',[])]
            try:result=worker.predict(image,rotated_tokens)
            finally:image.close()
            layout_calls+=result['layout_model_calls'];table_calls+=result['table_model_calls']
            regions=[];rejected=[]
            for item in result['regions']:
                try:regions.append({**item,'bbox':restore_box(item['bbox'],task['source_size'],angle),'coordinate_frame':'original_image'})
                except ValueError:rejected.append({'id':item['id'],'reason':'native_region_outside_frame_no_clipping'})
            cells=[]
            for item in result.get('cells',[]):
                try:cells.append({**item,'bbox':restore_box(item['bbox'],task['source_size'],angle),'coordinate_frame':'original_image'})
                except ValueError:rejected.append({'id':item.get('id'),'reason':'native_cell_outside_frame_no_clipping'})
            association=attach_tokens(cells,task.get('tokens',[]),task['source_size'])
            page={'contract':'document-ai-original-frame-geometry.v1','component':component,'page':task['page'],'company':task.get('company'),
                  'source_image':task['source_image'],'source_size':task['source_size'],'source_frame':'original_image','rotation_ccw':angle,
                  'regions':regions,'cell_association':association,'rejected_native_geometry':rejected,
                  'raw_native_result':result['raw'],'layout_model_calls':result['layout_model_calls'],'table_model_calls':result['table_model_calls'],
                  'new_text_OCR_calls':0,'assistant_image_transcription':False,'endpoint_accuracy_gain':None,
                  'geometry_detection_is_not_verified_product_table':True}
            dest=output/('page-'+str(task['page']).zfill(4)+'.json');save(dest,page);completed.append(pin(dest))
    finally:
        worker.close();faulthandler.cancel_dump_traceback_later()
    summary={'contract':'document-ai-component-trial.v1','status':'COMPLETE','component':component,'plan':pin(args.plan),'registry':pin(args.registry),'materialization':pin(args.materialization),
             'pages_completed':len(completed),'actual_model_predict_calls_started':calls,'page_results':completed,'elapsed_seconds':time.monotonic()-began,
             'actual_completed_layout_model_calls':layout_calls,'actual_completed_table_model_calls':table_calls,
             'new_text_OCR_calls':0,'optimizer_updates':0,'endpoint_score_status':'NOT_EVALUATED','endpoint_gain':None,'known_development_set':True,'production_activation':False}
    save(output/'SUMMARY.json',summary);return summary

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--registry',type=Path,required=True);ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--plan-sha256',required=True);ap.add_argument('--materialization',type=Path)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--execute',action='store_true');ap.add_argument('--admission',type=Path);ap.add_argument('--admission-sha256');a=ap.parse_args()
    if sha(a.plan)!=a.plan_sha256:raise ValueError('Plan SHA differs')
    plan=read(a.plan);registry=read(a.registry)
    if plan.get('contract')!='root-document-ai-source-only-trial-plan.v1' or plan.get('approved_by')!='root' or plan.get('resource_policy')!=RESOURCES:raise ValueError('Root bounded source-only plan required')
    if plan.get('registry')!=pin(a.registry):raise ValueError('Registry changed')
    if plan.get('mode') not in ('canary','pilot','full'):raise ValueError('Unknown stage')
    tasks=plan['tasks'];limit={'canary':1,'pilot':16,'full':484}[plan['mode']]
    if not 0<len(tasks)<=limit or len({t['page'] for t in tasks})!=len(tasks):raise ValueError('Stage/page bound differs')
    if plan['mode']=='full' and len(tasks)!=484:raise ValueError('Full stage must account all484 sources')
    for task in tasks:validate_task(task)
    pre=component_preflight(registry,plan['component'])
    if not a.execute:
        print(json.dumps({'valid':True,'executed':False,'tasks':len(tasks),'preflight':pre,'model_calls':0}));return
    if not a.materialization or not a.admission or not a.admission_sha256:raise ValueError('Exact materialization and live supervised admission required')
    proof=materialization(registry,plan['component'],a.materialization,a.registry)
    print(json.dumps(execute(a,plan,registry,proof),ensure_ascii=False))

if __name__=='__main__':main()
