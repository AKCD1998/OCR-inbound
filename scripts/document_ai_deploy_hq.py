"""Publish exact new source files and a PRIVATE HQ ingress profile, no worker launch.

The operator supplies a reviewed serial configuration as the guard template.
Runtime paths/ordinary-process review/private catalogue never enter Git.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path,PureWindowsPath
import sys

REPO=Path(__file__).resolve().parents[1]

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--shared-root',type=Path,required=True)
    p.add_argument('--native-root',required=True);p.add_argument('--version',required=True)
    p.add_argument('--serial-template',type=Path,required=True);p.add_argument('--catalogue',type=Path)
    p.add_argument('--catalogue-native');p.add_argument('--profile',type=Path,required=True);a=p.parse_args()
    if not a.version.replace('-','').isalnum():raise ValueError('Simple immutable deployment version required')
    if a.profile.exists():raise FileExistsError('Profile exists; preserve old deployment')
    shared=a.shared_root/a.version;shared.mkdir(parents=True,exist_ok=False)
    native=PureWindowsPath(a.native_root)/a.version
    members={
        'serial_supervisor':'experiments/document_ai/serial_supervisor.py',
        'component_common':'experiments/document_ai/component_common.py',
        'metadata_probe':'experiments/document_ai/metadata_probe.py',
        'queued_supervisor':'experiments/document_ai/queued_supervisor.py',
        'ingress_worker':'experiments/document_ai/ingress_worker.py',
        'root_package':'src/ocr_inbound/__init__.py',
        'package':'src/ocr_inbound/document_ai/__init__.py',
        'core':'src/ocr_inbound/document_ai/core.py',
        'learning':'src/ocr_inbound/document_ai/learning.py',
        'ingress_adapter':'src/ocr_inbound/document_ai/hq_ingress.py',
        'supplier_parser':'src/ocr_inbound/batch_supplier_extraction.py'}
    deployment={}
    for key,rel in members.items():
        source=REPO/rel
        target=shared/(Path(rel) if rel.startswith('src/') else Path(rel).name)
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
        if sha(target)!=sha(source):raise ValueError('Source transfer differs')
        deployment[key]={'path':str(native/target.relative_to(shared)), 'local_path':str(target),'sha256':sha(target)}
    template=json.loads(a.serial_template.read_text(encoding='utf-8-sig'))
    template={k:template[k] for k in ('contract','approved_by','resource_policy','production_activation_allowed','pins','ordinary_external_processes')}
    template['pins']['metadata_probe']={k:v for k,v in deployment['metadata_probe'].items() if k!='local_path'}
    template['pins']['common']={k:v for k,v in deployment['component_common'].items() if k!='local_path'}
    tesseract=Path(r'\\100.90.166.72\C\Program Files\Tesseract-OCR\tesseract.exe')
    profile={'contract':'document-ai-private-HQ-profile.v1','production_activation_allowed':False,
        'shared_root':str(a.shared_root),'native_root':a.native_root,
        'package_src':str(native/'src'),'deployment':deployment,'supervisor_template':template,
        'publisher':{'local_path':str(REPO/'scripts/hq_document_ai_job.py'),'sha256':sha(REPO/'scripts/hq_document_ai_job.py')},
        'tesseract':{'path':r'C:\Program Files\Tesseract-OCR\tesseract.exe','sha256':sha(tesseract)}}
    profile['reader_data_pins']=[{'path':str(PureWindowsPath(r'C:\Program Files\Tesseract-OCR\tessdata')/(lang+'.traineddata')),
                                 'sha256':sha(tesseract.parent/'tessdata'/(lang+'.traineddata'))} for lang in ('tha','eng')]
    if bool(a.catalogue)!=bool(a.catalogue_native):raise ValueError('Catalogue source/native paths must be paired')
    if a.catalogue:profile['catalogue']={'path':a.catalogue_native,'sha256':sha(a.catalogue)}
    a.profile.parent.mkdir(parents=True,exist_ok=True)
    with a.profile.open('x',encoding='utf-8') as f:json.dump(profile,f,ensure_ascii=False,indent=2)
    print(json.dumps({'profile':str(a.profile),'source_files':len(members),'workers_started':0}))

if __name__=='__main__':main()
