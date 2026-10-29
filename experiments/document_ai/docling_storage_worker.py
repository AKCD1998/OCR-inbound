"""Explicit modified-TableFormer arm with pinned native129 delegation.

The actual admission/summary worker is THIS wrapper; unchanged base129 remains
separately pinned. Layout applies no SDK variant. Tables use exactly the approved
two-clone implementation and record its actual imported origin before inference.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import sys
from component_common import checked,pin,read,require_HQ
from tableformer_storage_arm import BASE_WORKER_SHA,install,validate_arm


def delegate_namespace(base,wrapper_path,check=checked):
    """Keep the real admission function and explicitly lease this entry point."""
    if base['sha256']!=BASE_WORKER_SHA:raise ValueError('Exact original startup900 native129 delegate required')
    source=Path(check(base)).read_bytes()
    if hashlib.sha256(source).hexdigest()!=base['sha256']:raise ValueError('Actual delegated source buffer differs')
    namespace={'__name__':'_document_ai_native129_delegate','__file__':str(Path(wrapper_path).resolve()),'__package__':None}
    exec(compile(source,base['path'],'exec',dont_inherit=True),namespace)
    return namespace


def stage_output(arguments):
    values=[]
    for flag in ('--stage','--output'):
        if arguments.count(flag)!=1 or arguments.index(flag)+1>=len(arguments):
            raise ValueError('One explicit native stage and output required')
        values.append(arguments[arguments.index(flag)+1])
    if values[0] not in ('layout','tables'):raise ValueError('Explicit layout or tables stage required')
    return values[0],Path(values[1]).resolve()


class ProvenanceWriter:
    """Write source facts only; return every tensor/geometry value unchanged."""
    def __init__(self,original_save,base,stage,output,arm=None,finder=None):
        if stage not in ('layout','tables') or (stage=='tables')!=(arm is not None and finder is not None):
            raise ValueError('Only table stages may install and attest the SDK implementation')
        if stage=='layout' and (arm is not None or finder is not None):raise ValueError('Layout cannot apply the TableFormer variant')
        self.save=original_save;self.base=base;self.stage=stage;self.output=Path(output).resolve()
        self.arm=arm;self.finder=finder;self.started=False;self.origin_record=None
        if finder is not None:finder.on_loaded=self.record_import

    def record_import(self):
        if not self.started or self.stage!='tables' or self.origin_record is not None:
            raise ValueError('Actual implementation import must occur once inside its started output')
        observation=self.finder.observation()
        path=self.output/'ACTUAL_TABLEFORMER_IMPLEMENTATION.json'
        self.save(path,observation);self.origin_record=pin(path)

    def __call__(self,path,value):
        path=Path(path)
        if path.name in ('STARTED.json','SUMMARY.json'):
            if path.resolve()!=self.output/path.name:raise ValueError('Implementation provenance output differs from the native stage')
            if path.name=='STARTED.json':
                if self.started:raise ValueError('Native stage already started')
                self.started=True
            else:
                if not self.started:raise ValueError('Native summary requires its started stage')
                if self.stage=='tables':
                    if self.origin_record is None:raise ValueError('Actual implementation import proof is missing')
                    if read(checked(self.origin_record))!=self.finder.observation():raise ValueError('Actual implementation origin proof changed')
            value=dict(value,native_base_worker=self.base,native_implementation_arm=self.arm,
                       implementation_selected=self.stage=='tables',implementation_applied=self.origin_record is not None,
                       vanilla_sdk_claimed=False)
            if self.origin_record is not None:value['actual_tableformer_implementation']=self.origin_record
        return self.save(path,value)


def main():
    ap=argparse.ArgumentParser(add_help=False)
    ap.add_argument('--implementation-arm',type=Path);ap.add_argument('--implementation-arm-sha256')
    ap.add_argument('--base-worker',type=Path,required=True);ap.add_argument('--base-worker-sha256',required=True)
    a,remaining=ap.parse_known_args();stage,output=stage_output(remaining)
    require_HQ()
    base={'path':str(a.base_worker),'sha256':a.base_worker_sha256}
    namespace=delegate_namespace(base,__file__)
    arm=None;finder=None
    if stage=='tables':
        if not a.implementation_arm or not a.implementation_arm_sha256:raise ValueError('Root-approved table implementation arm required')
        arm={'path':str(a.implementation_arm),'sha256':a.implementation_arm_sha256}
        validate_arm(arm);finder=install(arm)
    # Layout neither validates/imports the TableFormer arm nor claims it ran.
    namespace['save']=ProvenanceWriter(namespace['save'],base,stage,output,arm,finder)
    sys.argv=[str(Path(__file__).resolve()),*remaining]
    namespace['main']()


if __name__=='__main__':main()
