"""Small synthetic CPU/Torch value+storage probe. No SDK/model/weights/images."""
from __future__ import annotations
import argparse
from pathlib import Path
import struct
import sys
from component_common import pin,require_HQ,save,verify_admission

def validate_bounds(steps,width=512):
    if type(steps) is not int or not 2<=steps<=64 or type(width) is not int or width!=512:
        raise ValueError('Synthetic probe bounded to2..64 steps and native feature width512')

def storage_probe(torch,steps=64,width=512):
    validate_bounds(steps,width)
    views=[];copies=[]
    with torch.no_grad():
        for size in range(1,steps+1):
            decoded=torch.arange(size*width,dtype=torch.float32,device='cpu').reshape(size,1,width)
            last=decoded[-1,:,:];copy=last.clone()
            if not torch.equal(last.view(torch.uint8),copy.view(torch.uint8)):raise ValueError('Last-feature bytes changed')
            if last.shape!=copy.shape or last.dtype!=copy.dtype or last.device!=copy.device:raise ValueError('Feature metadata changed')
            if last.untyped_storage().data_ptr()!=decoded.untyped_storage().data_ptr():raise ValueError('Expected actual basic-indexing view alias missing')
            if copy.untyped_storage().data_ptr()==decoded.untyped_storage().data_ptr():raise ValueError('Clone retained parent storage alias')
            if copy.untyped_storage().nbytes()!=width*4:raise ValueError('Clone did not own exactly one float32 feature row')
            views.append(last);copies.append(copy)
        # Compare a synthetic consumer of the retained features. This is not a
        # prediction from either the original or modified TableFormer model.
        a=torch.cat(views,dim=0);b=torch.cat(copies,dim=0)
        if not torch.equal(a.view(torch.uint8),b.view(torch.uint8)):raise ValueError('Downstream concatenated feature bytes changed')
        # Signed zero, infinities and NaN payloads test byte copies rather than
        # torch.equal(float) semantics (which regards NaN unequal to itself).
        patterns=(0x00000000,0x80000000,0x7f800000,0xff800000,0x7fc01234,0x3f800000)
        raw=b''.join(struct.pack('<I',x) for x in patterns)
        special=torch.tensor(list(raw),dtype=torch.uint8).view(torch.float32)
        special_copy=special.clone()
        if not torch.equal(special.view(torch.uint8),special_copy.view(torch.uint8)):raise ValueError('Special float bits changed')
    unique_views={t.untyped_storage().data_ptr():t.untyped_storage().nbytes() for t in views}
    unique_copies={t.untyped_storage().data_ptr():t.untyped_storage().nbytes() for t in copies}
    expected_views=steps*(steps+1)//2*width*4;expected_copies=steps*width*4
    if len(unique_views)!=steps or sum(unique_views.values())!=expected_views or sum(unique_copies.values())!=expected_copies:
        raise ValueError('Actual retained storage does not match the growing-view vs compact-copy model')
    return {'status':'PASS','synthetic_steps':steps,'feature_width':width,'feature_dtype':'torch.float32',
            'per_feature_bytes_bitwise_equal':True,'downstream_cat_bytes_bitwise_equal':True,
            'signed_zero_inf_nan_payload_bits_equal':True,'all_views_alias_decoded':True,'all_clones_have_independent_storage':True,
            'view_unique_storage_bytes':sum(unique_views.values()),'clone_unique_storage_bytes':sum(unique_copies.values()),
            'retained_storage_saved_bytes':sum(unique_views.values())-sum(unique_copies.values()),
            'storage_measurement_is_RSS':False,'actual_model_output_equivalence':'NOT_TESTED',
            'SDK_imports':0,'model_constructs':0,'images':0,'weights_loaded':0,'RNG_calls':0,'optimizer_updates':0}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--steps',type=int,default=64)
    ap.add_argument('--execute',action='store_true');ap.add_argument('--admission',type=Path);ap.add_argument('--admission-sha256');a=ap.parse_args()
    validate_bounds(a.steps)
    if a.output.exists():raise ValueError('New immutable synthetic probe output required')
    if not a.execute:print({'valid':True,'executed':False,'model_calls':0});return
    require_HQ();verify_admission(a.admission,a.admission_sha256,__file__,'docling')
    if any(n.startswith(('docling_ibm_models','transformers','PIL','cv2')) for n in sys.modules):raise ValueError('Probe must start without SDK/image/model imports')
    import torch
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if torch.__version__!='2.6.0+cpu' or torch.get_num_threads()!=1 or torch.get_num_interop_threads()!=1:
        raise ValueError('Exact accepted TorchCPU26/CPU1 runtime required')
    result=storage_probe(torch,a.steps)
    if any(n.startswith('docling_ibm_models') for n in sys.modules):raise ValueError('Synthetic probe imported the SDK')
    result.update(contract='document-ai-synthetic-torch-storage-probe.v1',worker=pin(__file__),torch_version=torch.__version__,
                  actual_CPU_threads=1,executed=True,source_image_decodes=0,production_activation=False)
    save(a.output,result);print({'result':pin(a.output),'status':result['status']})

if __name__=='__main__':main()
