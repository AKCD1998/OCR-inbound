"""Run pinned-environment pip with automatic bounded-wait stack evidence.

This helper is invoked only by the root-admitted isolated installer. It imports
pip metadata/installation code, never Torch/Docling or document pixels.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import faulthandler
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import sys

HASH_READ_BYTES=8*1024*1024
_STDLIB_COPYFILEOBJ=shutil.copyfileobj

def exact_hash_chunks(stream,size=HASH_READ_BYTES):
    """Identical byte stream/digest, fewer reads than pip24's 8192-byte default."""
    while block:=stream.read(size):yield block

def exact_buffered_copy(source,dest,length=0):
    """Change call granularity only; ZipExtFile CRC and exact bytes are retained."""
    return _STDLIB_COPYFILEOBJ(source,dest,length if length else HASH_READ_BYTES)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--journal',type=Path,required=True)
    ap.add_argument('--bootstrap-pip-wheel',type=Path);ap.add_argument('--bootstrap-pip-wheel-sha256');ap.add_argument('pip_args',nargs=argparse.REMAINDER);a=ap.parse_args()
    args=a.pip_args[1:] if a.pip_args[:1]==['--'] else a.pip_args
    if not args or not any(x in args for x in ('install','check')):raise ValueError('Only explicit binary installation/metadata checks')
    if 'install' in args and not any(x in args for x in ('--dry-run','--require-hashes')):raise ValueError('Dry run or exact hash installation required')
    a.journal.write_text(json.dumps({'started_utc':datetime.now(timezone.utc).isoformat(),'phase':'PIP_ENTRYPOINT_STARTED','model_imports':0,'model_calls':0}),encoding='utf-8')
    faulthandler.enable();faulthandler.dump_traceback_later(20,repeat=True)
    if a.bootstrap_pip_wheel:
        digest=hashlib.sha256()
        with a.bootstrap_pip_wheel.open('rb') as stream:
            for block in exact_hash_chunks(stream):digest.update(block)
        if digest.hexdigest()!=a.bootstrap_pip_wheel_sha256:raise ValueError('Bootstrap pip publisher digest differs')
        sys.path.insert(0,str(a.bootstrap_pip_wheel.resolve()))
    # Scoped to this child only. No pip files are edited and require-hashes is
    # retained. Small read-call latency otherwise dominates large CPU wheels.
    from pip._internal.utils import hashes
    old_hash_reader=hashes.read_chunks;old_copy=shutil.copyfileobj
    hashes.read_chunks=exact_hash_chunks
    shutil.copyfileobj=exact_buffered_copy
    a.journal.with_name(a.journal.name+'.hash-policy.json').write_text(json.dumps({
        'hash_read_bytes':HASH_READ_BYTES,'copy_buffer_bytes':HASH_READ_BYTES,'all_original_bytes_verified':True,'hash_algorithm_unchanged':True,
        'bootstrap_pip_wheel':str(a.bootstrap_pip_wheel) if a.bootstrap_pip_wheel else None,
        'require_hashes_not_disabled':True,'pip_source_files_modified':False}),encoding='utf-8')
    sys.argv=['pip']+args
    try:runpy.run_module('pip',run_name='__main__')
    finally:
        hashes.read_chunks=old_hash_reader;shutil.copyfileobj=old_copy;faulthandler.cancel_dump_traceback_later()

if __name__=='__main__':main()
