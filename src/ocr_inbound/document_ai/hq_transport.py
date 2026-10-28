"""Durable private HQ transport for the local final-review app.

Only file transport and polling run here. Readers, rendering and model work stay
under the original HQ shared lock. A browser restart reuses the job, not a worker.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
import time

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.pending-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
        os.link(temp,path)
    finally:os.unlink(temp)
def checked(record):
    if sha(record['local_path'])!=record['sha256']:raise ValueError('HQ deployment/source changed')
    return {'path':record['path'],'sha256':record['sha256']}

def translate_asset(native_path, native_root, shared_root):
    """Never accept an artifact outside this document's isolated output tree."""
    candidate=PureWindowsPath(native_path);base=PureWindowsPath(native_root)
    if '..' in candidate.parts or not candidate.is_relative_to(base):raise ValueError('HQ artifact escaped its job')
    return Path(shared_root).joinpath(*candidate.relative_to(base).parts)

def completed_proposals(execution, path, native_path):
    """Verify the actual worker bytes before changing only transport paths."""
    if execution.get('status')!='COMPLETE' or execution.get('shared_lock_released_after_owned_closure') is not True:
        raise RuntimeError('HQ processing stopped safely: '+str(execution.get('failure')))
    summaries=[r.get('worker_summary') for r in execution.get('resources',[]) if r.get('stage')=='ingress']
    if len(summaries)!=1 or not summaries[0] or PureWindowsPath(summaries[0]['path'])!=PureWindowsPath(native_path):
        raise ValueError('Actual ingress summary binding missing')
    data=Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest()!=summaries[0]['sha256']:raise ValueError('HQ proposal bytes changed after measurement')
    return json.loads(data.decode('utf-8-sig'))

class HQProcessor:
    def __init__(self,profile_path,poll_seconds=3):
        self.profile_path=Path(profile_path);self.profile=read(profile_path)
        if self.profile.get('contract')!='document-ai-private-HQ-profile.v1':raise ValueError('Private HQ profile required')
        if self.profile.get('production_activation_allowed') is not False:raise ValueError('Prototype profile only')
        self.poll_seconds=poll_seconds

    def __call__(self,document):
        p=self.profile;document_id=document['id']
        if not re.fullmatch('[a-f0-9]{32}',document_id):raise ValueError('Invalid document id')
        source=Path(document['source_path'])
        if sha(source)!=document['source_sha256']:raise ValueError('Uploaded source changed')
        deployment={k:checked(v) for k,v in p['deployment'].items()}
        job=Path(p['shared_root'])/'ingress'/document_id
        native=str(PureWindowsPath(p['native_root'])/'ingress'/document_id)
        state=job/'PUBLICATION_STATE.json'
        task='OCR_DOCAI_INGRESS_'+document_id.upper()
        if not state.exists():
            # Creating a namespace is exclusive. A partial publication is retained,
            # diagnosed and never silently retried as a second scheduled worker.
            job.mkdir(parents=True,exist_ok=False)
            dest=job/('source'+source.suffix);dest.write_bytes(source.read_bytes())
            if sha(dest)!=document['source_sha256']:raise ValueError('Source transfer hash differs')
            request={'contract':'document-ai-HQ-ingress-request.v1','document_id':document_id,
                     'source':{'path':str(PureWindowsPath(native)/dest.name),'sha256':sha(dest)},
                     'package_src':p['package_src'],'tesseract':p['tesseract'],
                     'code_pins':list(deployment.values()),'catalogue':p.get('catalogue'),
                     'reader_data_pins':p.get('reader_data_pins',[])}
            request_path=job/'request.json';write_new(request_path,request)
            output_native=str(PureWindowsPath(native)/'processing')
            configuration={**p['supervisor_template'],
                'source':deployment['serial_supervisor'], 'output_root':output_native,
                'maximum_wait_seconds':86400,'maximum_total_seconds':2400,
                'queue_driver':{'path':str(PureWindowsPath(p['native_root'])/task/'queued_supervisor.py'),
                                'sha256':deployment['queued_supervisor']['sha256']},
                'steps':[{'id':'ingress','component':'ingress','worker':deployment['ingress_worker'],
                          'optimizer_updates_allowed':False,'maximum_seconds':2400,
                          'input_pins':[request['source'],{'path':str(PureWindowsPath(native)/'request.json'),'sha256':sha(request_path)}],
                          'args':['--request',str(PureWindowsPath(native)/'request.json'),
                                  '--request-sha256',sha(request_path),'--output',str(PureWindowsPath(output_native)/'proposals.json'),
                                  '--admission','{admission}','--admission-sha256','{admission_sha256}'],
                          'summary_path':str(PureWindowsPath(output_native)/'proposals.json'),
                          'summary_equals':{'status':'COMPLETE','contract':'document-ai-proposals.v1'}}]}
            config=job/'job.json';write_new(config,configuration)
            publisher=Path(p['publisher']['local_path'])
            if sha(publisher)!=p['publisher']['sha256']:raise ValueError('Publisher source changed')
            spec=importlib.util.spec_from_file_location('_document_ai_private_publisher',publisher)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            # Persist intent BEFORE remote dispatch. A laptop loss after dispatch
            # reattaches to this exact job and cannot schedule a second worker.
            write_new(state,{'document_id':document_id,'source_sha256':document['source_sha256'],
                             'config_sha256':sha(config),'task':task,'phase':'PREPARED_FOR_DISPATCH'})
            publication=module.publish(p['deployment']['queued_supervisor']['local_path'],
                ['--config',str(PureWindowsPath(native)/'job.json'),'--config-sha256',sha(config)],task,max_minutes=1485)
            write_new(job/'DISPATCH_RECEIPT.json',publication)
        receipt=read(state)
        if receipt.get('source_sha256')!=document['source_sha256'] or receipt.get('document_id')!=document_id:
            raise ValueError('Existing HQ job does not belong to uploaded source')
        end=time.monotonic()+p.get('poll_deadline_seconds',88800)
        while time.monotonic()<end:
            if (job/'job.QUEUE_FAILED.json').exists():
                try:failure=read(job/'job.QUEUE_FAILED.json')
                except json.JSONDecodeError:time.sleep(self.poll_seconds);continue
                raise RuntimeError('HQ queue stopped: '+str(failure))
            final=job/'processing'/'RESULT.json'
            if final.exists():
                try:execution=read(final)
                except json.JSONDecodeError:time.sleep(self.poll_seconds);continue
                result=completed_proposals(execution,job/'processing'/'proposals.json',str(PureWindowsPath(native)/'processing'/'proposals.json'))
                if result.get('source_sha256')!=document['source_sha256']:raise ValueError('Result source mismatch')
                for page in result['pages']:
                    page['image_path']=str(translate_asset(page['image_path'],str(PureWindowsPath(native)/'processing'),job/'processing'))
                result['artifacts_root']=str(job/'processing')
                return result
            time.sleep(self.poll_seconds)
        raise TimeoutError('HQ job retained; inspect queue/task receipt before retrying')

def processor_from_profile(path):return HQProcessor(path)
