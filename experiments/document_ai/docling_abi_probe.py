"""Admitted native NumPy/OpenCV/Torch roundtrip in the exact new environment.

No images, model weights, model predictions or optimizer updates. --launch uses
the same pinned source/admission in a descendant running the installed venv.
"""
from __future__ import annotations
import argparse
import faulthandler
import os
from pathlib import Path
import subprocess
import sys
import time
from component_common import read,sha,pin,save,checked,verify_admission

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--install-result',type=Path,required=True);ap.add_argument('--install-result-sha256')
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--launch',action='store_true');ap.add_argument('--admission',type=Path,required=True);ap.add_argument('--admission-sha256',required=True);a=ap.parse_args()
    verify_admission(a.admission,a.admission_sha256,__file__,'docling-abi')
    if a.install_result_sha256 and sha(a.install_result)!=a.install_result_sha256:raise ValueError('Installation receipt changed')
    result=read(a.install_result)
    if result.get('status')!='COMPLETE' or result.get('frozen_runtime_modified') is not False or result.get('model_calls')!=0:raise ValueError('Finite exact installation completion required')
    python=checked(result['python'])
    if a.launch:
        argv=[str(python),'-X','utf8','-B',str(Path(__file__).resolve()),'--install-result',str(a.install_result),'--install-result-sha256',sha(a.install_result),
              '--output',str(a.output),'--admission',str(a.admission),'--admission-sha256',a.admission_sha256]
        completed=subprocess.run(argv,shell=False,check=False,timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if completed.returncode:raise SystemExit(completed.returncode)
        return
    if Path(sys.executable).resolve()!=python.resolve():raise ValueError('Actual new environment interpreter required')
    began=time.monotonic();faulthandler.enable();faulthandler.dump_traceback_later(30,repeat=True)
    try:
        import numpy as np
        import cv2
        cv2.setNumThreads(1)
        import torch
        torch.set_num_threads(1);torch.set_num_interop_threads(1)
        data=np.arange(4,dtype=np.int64).reshape(2,2);tensor=torch.from_numpy(data)
        if int(tensor.sum().item())!=6 or not np.array_equal(tensor.numpy(),data) or tensor.device.type!='cpu':raise ValueError('NumPy/Torch native roundtrip failed')
        resized=cv2.resize(np.arange(9,dtype=np.uint8).reshape(3,3),(6,6))
        if resized.shape!=(6,6):raise ValueError('Native OpenCV ndarray operation failed')
        binding={'torch_compute_threads':torch.get_num_threads(),'torch_interop_threads':torch.get_num_interop_threads(),'opencv_threads':cv2.getNumThreads(),'device':tensor.device.type}
        if binding!={'torch_compute_threads':1,'torch_interop_threads':1,'opencv_threads':1,'device':'cpu'}:raise ValueError('Actual native thread/device binding differs')
        save(a.output,{'contract':'document-ai-native-runtime-ABI-probe.v1','status':'COMPLETE','install_result':pin(a.install_result),'python':pin(sys.executable),
            'versions':{'numpy':np.__version__,'opencv':cv2.__version__,'torch':torch.__version__},'native_CPU_binding':binding,
            'native_array_checks_passed':True,'NumPy_Torch_roundtrip_sum':6,'OpenCV_resize_shape':[6,6],'elapsed_seconds':time.monotonic()-began,
            'source_image_decodes':0,'model_weight_loads':0,'model_calls':0,'optimizer_updates':0,'production_activation':False})
    except BaseException as exc:
        save(a.output,{'contract':'document-ai-native-runtime-ABI-probe.v1','status':'FAILED','error':type(exc).__name__,'message':str(exc),'install_result':pin(a.install_result),
            'model_calls':0,'source_image_decodes':0,'frozen_runtime_modified':False});raise
    finally:faulthandler.cancel_dump_traceback_later()

if __name__=='__main__':main()
