"""HQ data-only download of exact public model artifacts into a new experiment."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import urllib.request
from component_common import read,sha,pin,save,require_HQ,RESOURCES

def matches(path,entry):
    if path.stat().st_size!=entry['size']:return False
    if entry.get('sha256'):return sha(path)==entry['sha256']
    h=hashlib.sha1();h.update(('blob '+str(entry['size'])+'\0').encode())
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()==entry['git_blob_sha1']

def materialize(registry_path,component,root,receipt):
    require_HQ();registry=read(registry_path);spec=registry['components'][component]
    weights=sum(registry['models'][x]['weight_bytes'] for x in spec['models'])
    if weights>RESOURCES['maximum_own_process_tree_RSS_bytes']:
        result={'contract':'document-ai-model-data-materialization.v1','component':component,'status':'SKIPPED_RESOURCE_BUDGET','native_weight_bytes':weights,'model_calls':0,'downloaded_bytes':0,'reason':'Native weights alone exceed RSS cap; no unreviewed quantization substitute'}
        save(receipt,result);return result
    root=Path(root).resolve()
    if root.drive.casefold()!='d:' or 'OCR-Experiments' not in root.parts or 'runtime' in root.parts:raise ValueError('New D:/OCR-Experiments data-only model folder required')
    files=[];downloaded=0
    for key in spec['models']:
        for entry in registry['models'][key]['files']:
            rel=Path(entry['name'])
            if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe artifact member')
            dest=root/key/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            reused=dest.exists()
            if reused:
                if not matches(dest,entry):raise ValueError('Existing artifact differs; preserve and stop')
            else:
                partial=dest.with_name(dest.name+'.partial')
                with urllib.request.urlopen(entry['url'],timeout=60) as response,partial.open('xb') as stream:
                    while True:
                        block=response.read(131072)
                        if not block:break
                        stream.write(block);downloaded+=len(block)
                        if stream.tell()>entry['size']:raise ValueError('Artifact exceeded pinned byte length')
                if not matches(partial,entry):raise ValueError('Artifact hash differs; partial retained')
                partial.rename(dest)
            files.append({**pin(dest),'size':entry['size'],'model':key,'member':entry['name'],'reused_exact_bytes':reused})
    result={'contract':'document-ai-model-data-materialization.v1','component':component,'status':'COMPLETE','registry':pin(registry_path),'model_root':str(root),'files':files,'downloaded_bytes':downloaded,'model_imports':0,'model_calls':0,'optimizer_updates':0}
    save(receipt,result);return result

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--registry',type=Path,required=True);ap.add_argument('--component',choices=['pp-layout','pp-layout-l','docling','qwen'],required=True);ap.add_argument('--model-root',type=Path,required=True);ap.add_argument('--receipt',type=Path,required=True);a=ap.parse_args()
    import json
    print(json.dumps(materialize(a.registry,a.component,a.model_root,a.receipt),ensure_ascii=False))
if __name__=='__main__':main()
