"""Isolated, explicitly modified TableFormer implementation; no SDK patch.

Only two retained last-row views become .clone() copies. Source proof is not
model-output equivalence or a claim that this fixes the observed RSS failure.
"""
from __future__ import annotations
import argparse
import ast
from copy import deepcopy
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
from component_common import checked,pin,read,save,sha

MODULE='docling_ibm_models.tableformer.models.table04_rs.tablemodel04_rs'
ORIGIN_SHA='559f01739685978b2b3f3bd453c1500ec4feb24ce8af257c80ce271b0e29cd21'
BASE_WORKER_SHA='129df26e2a56a3be213d322c2734fe2e7ecab862e1f2daec551e6fb30af57e25'
CONTRACT='document-ai-tableformer-two-clone-implementation.v1'
_VIEW=ast.dump(ast.parse('decoded[-1, :, :]',mode='eval').body,include_attributes=False)

def _append_nodes(tree,cloned=False):
    classes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TableModel04_rs']
    if len(classes)!=1:raise ValueError('Unique original TableModel04_rs class required')
    methods=[n for n in classes[0].body if isinstance(n,ast.FunctionDef) and n.name=='predict']
    if len(methods)!=1:raise ValueError('Unique original predict method required')
    calls=[n for n in ast.walk(methods[0]) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
           and isinstance(n.func.value,ast.Name) and n.func.value.id=='tag_H_buf' and n.func.attr=='append']
    if len(calls)!=2:raise ValueError('Exactly two original tag_H_buf append sites required')
    for call in calls:
        if len(call.args)!=1 or call.keywords:raise ValueError('Original single append argument required')
        value=call.args[0]
        if cloned:
            if (not isinstance(value,ast.Call) or not isinstance(value.func,ast.Attribute) or value.func.attr!='clone'
              or value.args or value.keywords):raise ValueError('Only no-argument clone() is allowed')
            value=value.func.value
        if ast.dump(value,include_attributes=False)!=_VIEW:raise ValueError('Only the original decoded last-row view may be copied')
    return sorted(calls,key=lambda n:(n.lineno,n.col_offset))

def variant_bytes(original):
    tree=ast.parse(original);calls=_append_nodes(tree);lines=original.splitlines(keepends=True);result=bytearray(original)
    for call in reversed(calls):
        arg=call.args[0];position=sum(len(line) for line in lines[:arg.end_lineno-1])+arg.end_col_offset
        result[position:position]=b'.clone()'
    return bytes(result)

def source_proof(original,variant):
    if variant_bytes(original)!=variant:raise ValueError('Bytes changed beyond the two exact .clone() insertions')
    old=ast.parse(original);new=ast.parse(variant);before=_append_nodes(old);after=_append_nodes(new,True)
    for call in after:call.args[0]=call.args[0].func.value
    a=ast.dump(old,include_attributes=False);b=ast.dump(new,include_attributes=False)
    if a!=b:raise ValueError('Normalized model AST differs beyond the two storage copies')
    return {'contract':'document-ai-two-clone-source-proof.v1','original_sha256':hashlib.sha256(original).hexdigest(),
            'variant_sha256':hashlib.sha256(variant).hexdigest(),'original_bytes':len(original),'variant_bytes':len(variant),
            'append_lines':[n.lineno for n in before],'only_inserted_bytes':'.clone() at two last-row append arguments',
            'all_other_bytes_identical':True,'normalized_AST_sha256':hashlib.sha256(a.encode()).hexdigest(),
            'normalized_AST_identical':True,'actual_model_output_equivalence':'NOT_YET_MEASURED',
            'model_constructs':0,'images':0,'weights_loaded':0}

def isolated_paths(origin,variant,receipt):
    """Keep every byte of the installed SDK/environment read-only."""
    origin=Path(origin).resolve();variant=Path(variant).resolve();receipt=Path(receipt).resolve()
    roots=[origin.parent]
    for parent in origin.parents:
        if parent.name.casefold()=='site-packages':roots.append(parent.parent.parent)
        if parent.name=='docling_ibm_models':roots.append(parent)
    if variant==receipt or any(p==origin or any(p.is_relative_to(root) for root in roots) for p in (variant,receipt)):
        raise ValueError('Isolated source/receipt must be outside the entire original SDK environment')
    return origin,variant,receipt

def prepare(original_record,variant_path,receipt_path,check=checked):
    original=Path(check(original_record)).read_bytes()
    if original_record['sha256']!=ORIGIN_SHA or hashlib.sha256(original).hexdigest()!=ORIGIN_SHA:
        raise ValueError('Exact installed SDK4.0.4 source559f required')
    origin_path,variant_path,receipt_path=isolated_paths(check(original_record),variant_path,receipt_path)
    if variant_path.exists() or receipt_path.exists():raise ValueError('New immutable source and receipt paths required')
    variant=variant_bytes(original);proof=source_proof(original,variant)
    variant_path.parent.mkdir(parents=True,exist_ok=True)
    with variant_path.open('xb') as stream:stream.write(variant)
    receipt={'contract':CONTRACT,'status':'PREPARED_REQUIRES_ROOT_APPROVAL','arm':'two-last-feature-clones-v1',
       'module':MODULE,'original_source':deepcopy(original_record),'variant_source':pin(variant_path),
       'source_proof':proof,'implementation_helper':pin(__file__),'original_sdk_modified':False,
       'vanilla_sdk_claimed':False,'weights_or_model_configuration_changed':False,
       'max_steps_or_beam_changed':False,'production_activation':False,
       'source_compatibility_does_not_prove_model_output_equivalence':True}
    save(receipt_path,receipt);return pin(receipt_path)

def validate_arm(record,check=checked,require_approval=True):
    data=read(check(record))
    if (data.get('contract')!=CONTRACT or data.get('module')!=MODULE or data.get('arm')!='two-last-feature-clones-v1'
      or data.get('original_sdk_modified') is not False or data.get('vanilla_sdk_claimed') is not False
      or data.get('weights_or_model_configuration_changed') is not False or data.get('max_steps_or_beam_changed') is not False
      or data.get('production_activation') is not False):raise ValueError('Explicit isolated non-vanilla two-clone implementation contract required')
    if require_approval and (data.get('status')!='ROOT_APPROVED_FOR_BOUNDED_TRIAL' or data.get('approved_by')!='root'):
        raise ValueError('Root must explicitly approve this new implementation arm')
    if data['implementation_helper']['sha256']!=sha(__file__):raise ValueError('Exact implementation helper source required')
    check(data['implementation_helper'])
    original=data['original_source'];variant=data['variant_source']
    if original['sha256']!=ORIGIN_SHA:
        raise ValueError('Original SDK identity must remain distinct and unchanged')
    isolated_paths(check(original),check(variant),check(record))
    proof=source_proof(Path(check(original)).read_bytes(),Path(check(variant)).read_bytes())
    if proof!=data['source_proof'] or proof['original_sha256']!=original['sha256'] or proof['variant_sha256']!=variant['sha256']:
        raise ValueError('Actual source bytes differ from the two-clone receipt')
    return data

class _SourceLoader(importlib.machinery.SourceFileLoader):
    def __init__(self,fullname,path,owner):super().__init__(fullname,str(path));self.owner=owner
    def get_code(self,fullname):
        if fullname!=MODULE or self.name!=MODULE:raise ImportError('Implementation loader cannot serve another module')
        data=validate_arm(self.owner.record,self.owner.check)
        actual=Path(self.owner.check(data['variant_source'])).resolve()
        if Path(self.path).resolve()!=actual:raise ImportError('Implementation loader source path differs')
        code=actual.read_bytes()
        if hashlib.sha256(code).hexdigest()!=data['variant_source']['sha256']:
            raise ImportError('Actual compiled implementation buffer differs from the pinned variant')
        # No bytecode-cache read/write and no substitution of original __file__.
        return compile(code,self.path,'exec',dont_inherit=True)
    def exec_module(self,module):
        if module.__name__!=MODULE:raise ImportError('Implementation loader cannot execute another module')
        super().exec_module(module)
        module.__document_ai_modified_implementation__=deepcopy(self.owner.record)
        self.owner.loaded+=1
        if self.owner.on_loaded is not None:self.owner.on_loaded()

class ImplementationFinder(importlib.abc.MetaPathFinder):
    def __init__(self,record,check=checked):
        self.record=deepcopy(record);self.check=check;self.data=validate_arm(record,check);self.loaded=0;self.on_loaded=None
    def find_spec(self,fullname,path=None,target=None):
        if fullname!=MODULE:return None
        if target is not None:raise ImportError('Reloading the implementation is not permitted')
        origin=Path(self.check(self.data['original_source'])).resolve()
        if path is None or {Path(p).resolve() for p in path}!={origin.parent}:raise ImportError('Exact original SDK parent package path required')
        variant=Path(self.check(self.data['variant_source'])).resolve()
        loader=_SourceLoader(fullname,variant,self)
        return importlib.util.spec_from_file_location(fullname,variant,loader=loader)
    def observation(self):
        validate_arm(self.record,self.check)
        module=sys.modules.get(MODULE)
        variant=Path(self.check(self.data['variant_source'])).resolve()
        if (self.loaded!=1 or module is None or Path(module.__file__).resolve()!=variant
          or not isinstance(module.__loader__,_SourceLoader) or module.__loader__.owner is not self
          or getattr(module,'__document_ai_modified_implementation__',None)!=self.record):
            raise ValueError('Actual imported isolated implementation proof is missing')
        self.check(self.data['original_source']);self.check(self.data['variant_source'])
        return {'contract':'document-ai-actual-tableformer-implementation.v1','arm_receipt':self.record,
                'actual_module':MODULE,'actual_module_file':pin(variant),'original_source':self.data['original_source'],
                'actual_load_count':self.loaded,'original_sdk_modified':False,'vanilla_sdk_claimed':False,
                'loader':'exact-module-verified-source-no-pyc',
                'cache_guard_for_other_modules_modified':False}

def install(record,check=checked):
    if MODULE in sys.modules:raise ValueError('Install implementation arm BEFORE importing the original SDK model module')
    if any(isinstance(f,ImplementationFinder) for f in sys.meta_path):raise ValueError('An implementation finder is already installed')
    finder=ImplementationFinder(record,check);sys.meta_path.insert(0,finder);return finder

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--original',type=Path,required=True)
    ap.add_argument('--variant',type=Path,required=True);ap.add_argument('--receipt',type=Path,required=True);a=ap.parse_args()
    print(prepare(pin(a.original),a.variant,a.receipt))
