"""Three serial pure steps from an ACTUAL completed native summary.

Build tiny after model canary; build full only after actual tiny scorer proof
and a completed full484 native summary. This file does not launch a worker.
"""
from __future__ import annotations
import argparse
from pathlib import Path,PureWindowsPath
import re
from component_common import checked,pin,read,save
from eval_assets import preflight
from eval_runner import native_records,tiny_gate
from eval_native import witness,model_identity
from eval_transport import ReadTransport,parse_mappings

def build(profile_path,native_path,scope,name,tiny_path=None,supervision_paths=(),read_mappings=()):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',name):raise ValueError('Simple new trial name required')
    transport=ReadTransport(read_mappings);profile=read(transport.physical(profile_path));preflight(profile,transport.checked)
    native=transport.pin(native_path);_,native_summary=native_records(native,profile,scope,transport.checked)
    supervision=[transport.pin(p) for p in supervision_paths]
    if not native_summary.get('native_shard_summaries'):
        if not supervision:raise ValueError('Actual closed canary/native supervision receipt required')
        witness([native],supervision,transport.checked)
    tiny=transport.pin(tiny_path) if tiny_path else None
    if scope=='full484':tiny_gate(profile,tiny,transport.checked,model_identity(native_summary))
    base=PureWindowsPath(profile['results_root']) if PureWindowsPath(profile['results_root']).drive else Path(profile['results_root'])
    root=base/name
    if transport.physical(root).exists():raise ValueError('Preserve all previous/partial trial outputs')
    workers=[r for r in profile['bridge_sources'] if str(r['path']).replace('\\','/').rsplit('/',1)[-1]=='eval_runner.py']
    if len(workers)!=1:raise ValueError('Exactly one pinned deployed endpoint worker required')
    worker=workers[0];transport.checked(worker);profile_pin=transport.pin(profile_path)
    common=['--profile',profile_pin['path'],'--profile-sha256',profile_pin['sha256'],
      '--scope',scope,'--execute','--admission','{admission}','--admission-sha256','{admission_sha256}']
    steps=[]
    for variant in ('control','candidate'):
        out=root/variant
        args=['parse',*common,'--variant',variant,'--native-summary',native['path'],'--native-sha256',native['sha256'],'--output',str(out)]
        if tiny:args+=['--tiny-receipt',tiny['path'],'--tiny-sha256',tiny['sha256']]
        steps.append({'id':variant,'component':'endpoint-eval','worker':worker,'optimizer_updates_allowed':False,
          'maximum_seconds':600,'input_pins':[profile_pin,native]+supervision+([tiny] if tiny else []),'args':args,
          'summary_path':str(out/'COMPLETE.json'),'summary_equals':{'status':'COMPLETE','scope':scope,'variant':variant}})
    steps.append({'id':'paired_score','component':'endpoint-eval','worker':worker,'optimizer_updates_allowed':False,
      'maximum_seconds':600,'input_pins':[profile_pin,native]+supervision,
      'args':['score',*common,'--control',str(root/'control'),'--candidate',str(root/'candidate'),'--output',str(root/'score')],
      'summary_path':str(root/'score/RESULT.json'),'summary_equals':{'status':'COMPLETE','actual_scorer_invocations':2}})
    return {'contract':'document-ai-actual-native-paired-evaluation-steps.v1','executed':False,'source_profile':profile_pin,
      'native_summary':native,'scope':scope,'steps':steps,'required_supervisor_output_root':str(root),
      'actual_native_supervision':supervision or native_summary.get('actual_closed_supervision_receipts',[]),
      'preparation_code':pin(__file__),'read_transport_only':bool(read_mappings),
      'heavy_lane':'existing root serial supervisor/shared07b/CPU1/RAM/RSS policy',
      'new_OCR_calls':0,'new_model_calls':0,'production_activation':False,'full484_or_585_claim_if_tiny':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True)
    p.add_argument('--native-summary',type=Path,required=True);p.add_argument('--scope',choices=['tiny','full484'],required=True)
    p.add_argument('--name',required=True);p.add_argument('--tiny-receipt',type=Path)
    p.add_argument('--supervision',type=Path,action='append',default=[]);p.add_argument('--read-map',action='append',default=[])
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=build(a.profile,a.native_summary,a.scope,a.name,a.tiny_receipt,a.supervision,parse_mappings(a.read_map));save(a.output,result);print(pin(a.output))
