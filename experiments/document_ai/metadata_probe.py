"""HQ inventory only: no model imports, downloads, image reads or training."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import socket
import sys

CONTROLLER_SHA256 = '07b918d7fe2cd8749f73c57aea6e8842aa2db93613788af90d2f2b40bb0bda4c'
RESOURCES = {'CPU_threads': 1, 'minimum_start_free_RAM_bytes': 1983628573,
             'stop_free_RAM_bytes': 1288490188,
             'maximum_own_process_tree_RSS_bytes': 1073741824}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def probe(controller, lock_path, cache_roots=()):
    if socket.gethostname().casefold() != 'server':
        raise ValueError('Metadata probe is reserved for 000 HQ / SERVER')
    controller = Path(controller).resolve()
    if sha(controller) != CONTROLLER_SHA256:
        raise ValueError('Shared 07b controller bytes differ')
    import psutil
    spec = importlib.util.spec_from_file_location('_docai_probe_shared_07b', controller)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    vm = psutil.virtual_memory()
    me = psutil.Process()
    own = {me.pid} | {p.pid for p in me.parents()}
    processes = []
    uncertain = []
    for p in psutil.process_iter(['pid', 'ppid', 'name', 'exe', 'create_time', 'cmdline', 'memory_info']):
        try:
            info = p.info
            if info['pid'] in own:
                continue
            name = (info['name'] or '').casefold()
            command = ' '.join(info['cmdline'] or [])
            if not any(x in name for x in ('python', 'tesseract', 'llama', 'paddle')):
                continue
            relevant = any(x in command.casefold() for x in ('ocr', 'qwen', 'docling', 'paddle', 'train', 'infer'))
            argv = info['cmdline'] or []
            module_name = None
            if '-m' in argv and argv.index('-m')+1 < len(argv):
                candidate = argv[argv.index('-m')+1]
                if re.fullmatch(r'[A-Za-z0-9_.-]+', candidate):
                    module_name = candidate
            ml_maps = []
            map_error = None
            try:
                for mapped in p.memory_maps(grouped=True):
                    basename = Path(mapped.path).name
                    if re.search(r'paddle|torch|onnx|llama|cudnn|nvinfer|tensorrt', basename, re.I):
                        ml_maps.append(basename)
            except (psutil.Error, OSError) as exc:
                map_error = type(exc).__name__
            parent_identity = None
            try:
                parent = p.parent()
                if parent:
                    parent_identity = {'pid': parent.pid, 'creation_time': parent.create_time(), 'name': parent.name()}
            except psutil.Error:
                pass
            item = {'pid': info['pid'], 'parent_pid': info['ppid'],
                    'name': info['name'], 'executable': info['exe'],
                    'creation_time': info['create_time'],
                    'rss_bytes': info['memory_info'].rss if info['memory_info'] else None,
                    'entrypoint': next((x for x in argv if x.endswith('.py')), None),
                    'module': module_name, 'parent_identity': parent_identity,
                    'loaded_ML_library_basenames': sorted(set(ml_maps)),
                    'memory_map_observation_error': map_error,
                    'classification': 'ML_libraries_loaded' if ml_maps else 'unknown_maps_unavailable' if map_error else 'no_known_ML_library_loaded',
                    'command_sha256': hashlib.sha256(command.encode()).hexdigest(),
                    'matches_model_or_training_terms': relevant}
            processes.append(item)
        except (psutil.AccessDenied, psutil.NoSuchProcess) as exc:
            uncertain.append({'pid': p.pid, 'error': type(exc).__name__})
    lock_available = False
    lock_error = None
    try:
        with module.exclusive_lock(lock_path):
            lock_available = True
    except OSError as exc:
        lock_error = type(exc).__name__
    packages = {}
    for name in ('paddleocr', 'paddlepaddle', 'paddlex', 'torch', 'transformers',
                 'docling', 'docling-ibm-models', 'onnxruntime', 'psutil',
                 'lightgbm', 'rapidfuzz', 'llama-cpp-python'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    caches = []
    for root in cache_roots:
        root = Path(root)
        caches.append({'root': str(root), 'exists': root.is_dir(),
                       'immediate_directories': sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []})
    return {'contract': 'document-ai-HQ-metadata-probe.v2',
            'observed_at_utc': datetime.now(timezone.utc).isoformat(),
            'hostname': socket.gethostname(), 'platform': platform.platform(),
            'python': sys.executable, 'python_version': platform.python_version(),
            'logical_cpus': psutil.cpu_count(), 'physical_cpus': psutil.cpu_count(logical=False),
            'RAM_total_bytes': vm.total, 'RAM_available_bytes': vm.available,
            'probe_RSS_bytes': me.memory_info().rss,
            'model_like_processes': processes, 'process_inventory_uncertain': uncertain,
            'all_other_model_like_processes_absent': not processes and not uncertain,
            'shared_lock_available': lock_available, 'shared_lock_error': lock_error,
            'controller': {'path': str(controller), 'sha256': CONTROLLER_SHA256},
            'lock_path': str(lock_path), 'packages': packages, 'model_cache_roots': caches,
            'resource_policy': RESOURCES, 'model_imports': 0, 'model_calls': 0,
            'image_decodes': 0, 'optimizer_updates': 0,
            'raw_commands_or_environment_secrets_recorded': False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--controller', type=Path, required=True)
    ap.add_argument('--lock', type=Path, required=True)
    ap.add_argument('--cache-root', action='append', default=[])
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    result = probe(args.controller, args.lock, args.cache_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({'complete': True, 'available_RAM_bytes': result['RAM_available_bytes'],
                      'model_like_process_count': len(result['model_like_processes']),
                      'shared_lock_available': result['shared_lock_available'], 'model_calls': 0}))


if __name__ == '__main__':
    main()
