"""One admitted HQ metadata/data-only stage: existing OCR plans + public files."""
from __future__ import annotations
import argparse
from pathlib import Path
from component_common import read,sha,pin,save,checked,verify_admission,component_preflight
from build_trial_plan import build
from materialize_models import materialize

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--registry',type=Path,required=True);ap.add_argument('--registry-sha256',required=True)
    ap.add_argument('--cache-manifest',type=Path,required=True);ap.add_argument('--cache-manifest-sha256',required=True)
    ap.add_argument('--component',choices=['pp-layout','pp-layout-l','docling','qwen'],required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--model-root',type=Path,required=True);ap.add_argument('--admission',type=Path,required=True);ap.add_argument('--admission-sha256',required=True);a=ap.parse_args()
    verify_admission(a.admission,a.admission_sha256,__file__,'component-data')
    checked({'path':str(a.registry),'sha256':a.registry_sha256});checked({'path':str(a.cache_manifest),'sha256':a.cache_manifest_sha256})
    a.output.mkdir(parents=True,exist_ok=False)
    plans=[]
    for mode,pages in [('canary',[2]),('pilot',None)]:
        plan=build(a.cache_manifest,a.registry,a.component,mode,pages);target=a.output/(mode+'-plan.json');save(target,plan);plans.append(pin(target))
    receipt=a.output/'materialization.json';result=materialize(a.registry,a.component,a.model_root,receipt)
    qwen_preflight=None
    if a.component=='docling':
        qwen_path=a.output/'qwen-resource-preflight.json';save(qwen_path,component_preflight(read(a.registry),'qwen'))
        materialize(a.registry,'qwen',a.model_root,a.output/'qwen-materialization.json')
        qwen_preflight=pin(qwen_path)
    save(a.output/'SUMMARY.json',{'contract':'document-ai-component-data-preparation.v1','status':'COMPLETE','component':a.component,
        'plans':plans,'materialization':pin(receipt),'materialization_status':result['status'],'Qwen_metadata_preflight':qwen_preflight,'model_imports':0,'model_calls':0,'new_text_OCR_calls':0,'image_decodes':0,'optimizer_updates':0})

if __name__=='__main__':main()
