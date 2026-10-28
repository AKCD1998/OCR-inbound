"""Publish an explicitly selected isolated job through the existing HQ task identity.

No credentials, privilege changes, old-task restart, or recursive copying.
The selected worker is responsible for model admission and shared resource locking.
"""
from __future__ import annotations
import argparse,hashlib,json,subprocess
from datetime import datetime,timezone
from pathlib import Path
import xml.etree.ElementTree as ET

HQ='100.90.166.72'
REMOTE=Path(r'\\100.90.166.72\D\OCR-Experiments\document-ai-20261028')
NATIVE=r'D:\OCR-Experiments\document-ai-20261028'
PYTHON=r'D:\OCR-Experiments\484-20261024\runtime\Scripts\python.exe'
IDENTITY_TASK='OCR_484_HQ_ONE_EPOCH_EXEC_ROOT_V2'
NS='http://schemas.microsoft.com/windows/2004/02/mit/task'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def psquote(s):return "'"+str(s).replace("'","''")+"'"
def publish(source,args,name,*,extra_files=(),max_minutes=30):
    if not name.startswith('OCR_DOCAI_') or not name.replace('_','').isalnum():raise ValueError('New isolated task name required')
    exists=subprocess.run(['schtasks','/Query','/S',HQ,'/TN',name],capture_output=True)
    if exists.returncode==0:raise FileExistsError('Task already exists; inspect it instead of restarting')
    output=subprocess.check_output(['schtasks','/Query','/S',HQ,'/TN',IDENTITY_TASK,'/XML'])
    text=output.decode('utf-16') if output.startswith((b'\xff\xfe',b'\xfe\xff')) else output.decode('utf-8-sig')
    task=ET.fromstring(text);tag=lambda s:'{'+NS+'}'+s
    principal=task.find(tag('Principals')).find(tag('Principal'))
    if principal.find(tag('LogonType')).text!='InteractiveToken':raise ValueError('Existing identity is not interactive')
    target=REMOTE/name
    if target.exists():raise FileExistsError('New isolated run directory required')
    target.mkdir(parents=True)
    pins=[]
    for f in [Path(source),*[Path(p) for p in extra_files]]:
        dest=target/f.name
        if dest.exists():raise ValueError('Source basename collision')
        dest.write_bytes(f.read_bytes())
        if sha(dest)!=sha(f):raise ValueError('Publication hash differs')
        pins.append({'file':f.name,'sha256':sha(f),'bytes':f.stat().st_size})
    native=NATIVE+'\\'+name
    native_source=native+'\\'+Path(source).name
    command='& '+psquote(PYTHON)+' -X utf8 -B '+psquote(native_source)+' '+ ' '.join(psquote(x) for x in args)
    log=native+'\\task.log'
    script="$ErrorActionPreference='Stop'\n"+'\n'.join("$env:"+key+"='1'" for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS','PYTHONDONTWRITEBYTECODE'))+'\n'+command+' >> '+psquote(log)+' 2>&1\nif($LASTEXITCODE -ne 0){exit $LASTEXITCODE}\n'
    script_path=target/'run.ps1';script_path.write_text(script,encoding='utf-8-sig')
    task.find(tag('RegistrationInfo')).find(tag('URI')).text='\\'+name
    task.find(tag('RegistrationInfo')).find(tag('Description')).text='User-authorized document AI isolated job; model resource gates remain required'
    task.find(tag('Settings')).find(tag('ExecutionTimeLimit')).text=f'PT{max_minutes}M'
    action=task.find(tag('Actions')).find(tag('Exec'))
    action.find(tag('Arguments')).text='-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "'+native+'\\run.ps1"'
    action.find(tag('WorkingDirectory')).text=native
    xml=target/'task.xml';ET.ElementTree(task).write(xml,encoding='utf-16',xml_declaration=True)
    receipt={'contract':'document-ai-isolated-HQ-publication.v1','created_at_utc':datetime.now(timezone.utc).isoformat(),'task':name,'source_files':pins,'task_script_sha256':sha(script_path),'args':args,'new_privileges_or_credentials':False,'identity_inherited_from_existing_task':IDENTITY_TASK,'model_resource_admission_delegated_to_selected_worker':True}
    (target/'PUBLICATION.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    subprocess.run(['schtasks','/Create','/S',HQ,'/TN',name,'/XML',str(xml)],check=True,capture_output=True)
    subprocess.run(['schtasks','/Run','/S',HQ,'/TN',name],check=True,capture_output=True)
    return {**receipt,'remote_directory':str(target),'native_directory':native}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--name',required=True);p.add_argument('--max-minutes',type=int,default=30);p.add_argument('args',nargs=argparse.REMAINDER);a=p.parse_args();args=a.args[1:] if a.args[:1]==['--'] else a.args
    print(json.dumps(publish(a.source,args,a.name,max_minutes=a.max_minutes),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
