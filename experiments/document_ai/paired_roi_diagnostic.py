"""Run one fresh layout/table pair to diagnose a bounded per-ROI resource failure.

The native worker is unchanged. A new, physically closed one-page layout is
required because the native upstream contract deliberately rejects subsets of
an older 64-page child. Compare its geometry before running the table model.
"""
from __future__ import annotations
import argparse
import importlib.util
from pathlib import Path
import sys
import time
import traceback
from datetime import datetime, timezone

from component_common import checked, pin, read, require_HQ, save, sha
from docling_full_driver import completed_pages, retained_layout, step_for


def same_geometry(old, new):
    fields = ('contract', 'component', 'stage', 'page', 'source_image',
              'source_size', 'source_frame', 'rotation_ccw', 'regions',
              'rejected_native_geometry', 'layout_model_calls',
              'new_text_OCR_calls', 'assistant_image_transcription')
    if any(key not in old or key not in new or old[key] != new[key] for key in fields):
        raise ValueError('Fresh diagnostic layout differs from the retained source geometry')
    if new['stage'] != 'layout' or new['layout_model_calls'] != 1 or new['new_text_OCR_calls'] != 0 or new['assistant_image_transcription'] is not False:
        raise ValueError('One actual source-bound layout call required')
    return {'geometry_equal': True, 'compared_fields': list(fields),
            'new_model_calls_by_comparison': 0,
            'comparison_is_not_endpoint_accuracy': True}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--config-sha256', required=True)
    args = parser.parse_args()
    require_HQ()
    if sha(args.config) != args.config_sha256:
        raise ValueError('Diagnostic config bytes differ')
    config = read(args.config)
    if config['diagnostic_driver'] != pin(__file__) or config.get('diagnostic_page') != 160:
        raise ValueError('Explicit source-pinned page160 diagnostic required')
    supervisor = load('_roi_original_serial', checked(config['source']))
    output = supervisor.validate(config)
    if len(config['steps']) != 1:
        raise ValueError('One unchanged native worker template required')
    full = read(checked(config['full_parent_plan']))
    expected = full['tasks'][159:160]
    if len(full['tasks']) != 484 or [item['page'] for item in expected] != [160]:
        raise ValueError('Original full parent page160 required')
    origin = config['retained_layout_origin']
    original, _ = retained_layout(origin, full, config['full_parent_plan'],
        config['registry'], list(range(129, 193)), config['runtime_versions'], config['materialization'])
    old_records = [record for record in original['page_results'] if read(checked(record))['page'] == 160]
    if len(old_records) != 1:
        raise ValueError('One pristine retained layout page160 required')
    old_page = read(checked(old_records[0]))
    import psutil
    ownership = supervisor.load('_roi_original620', checked(config['pins']['ownership']))
    probe = supervisor.load('_roi_metadata', checked(config['pins']['metadata_probe']))
    registry = ownership.OwnedRegistry(psutil)
    output.mkdir(parents=True, exist_ok=False)
    save(output/'STARTED.json', {'config': pin(args.config), 'driver': pin(__file__),
        'utc': datetime.now(timezone.utc).isoformat(), 'diagnostic_page': 160,
        'native_worker': config['steps'][0]['worker'], 'old_layout_page': old_records[0],
        'new_text_OCR_calls': 0, 'optimizer_updates': 0})
    started = time.monotonic()
    resources = []
    failure = None
    acquired = False
    try:
        with ownership.safe_owned_lock(ownership.LOCK, registry):
            acquired = True
            end = started + config['maximum_total_seconds']
            upstream = None
            for stage in ('layout', 'tables'):
                if sha(args.config) != args.config_sha256:
                    raise ValueError('Diagnostic config changed during execution')
                for record in config['pins'].values():
                    checked(record)
                fresh = probe.probe(config['pins']['controller']['path'], ownership.LOCK)
                ordinary = supervisor.ordinary_process_gate(fresh, config)
                step = step_for(config['steps'][0], output, 0, 159, 1, stage, upstream)
                step['maximum_seconds'] = 1800 if stage == 'layout' else 1500
                save(output/(stage+'.fresh_admission.json'), {'metadata': fresh, 'ordinary_processes': ordinary})
                resource = supervisor.run_stage(step, config, output, ownership, registry, psutil, end)
                resources.append(resource)
                summary = read(checked(resource['worker_summary']))
                completed_pages(summary, config['full_parent_plan'], [160], stage)
                if summary['worker'] != config['steps'][0]['worker']:
                    raise ValueError('Actual diagnostic native worker differs')
                if stage == 'layout':
                    new_record = summary['page_results'][0]
                    comparison = same_geometry(old_page, read(checked(new_record)))
                    save(output/'GEOMETRY_COMPARISON.json', {**comparison, 'old_page': old_records[0],
                        'fresh_page': new_record, 'actual_closed_fresh_layout_summary': resource['worker_summary'],
                        'actual_closed_fresh_layout_resource': pin(output/(step['id']+'.resource.json'))})
                    upstream = {'summary': resource['worker_summary'], 'resource': pin(output/(step['id']+'.resource.json'))}
    except BaseException as exc:
        failure = {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}
        if 'step' in locals():
            receipt = output/(step['id']+'.resource.json')
            if receipt.is_file() and not any(item['stage'] == step['id'] for item in resources):
                resources.append(read(receipt))
    cleanup = registry.last_cleanup or registry.cleanup()
    safe = cleanup['confirmed_all_known_owned_exited'] is True
    result = {'contract': 'document-ai-HQ-serial-result.v1',
        'status': 'COMPLETE' if failure is None and safe else 'FAILED', 'failure': failure,
        'config': pin(args.config), 'driver': pin(__file__), 'resources': resources, 'cleanup': cleanup,
        'shared_lock_acquired': acquired, 'shared_lock_released_after_owned_closure': acquired and safe,
        'elapsed_seconds': time.monotonic()-started, 'diagnostic_page': 160,
        'new_text_OCR_calls': 0, 'optimizer_updates': 0,
        'endpoint_score_status': 'NOT_EVALUATED', 'endpoint_gain': None, 'production_activation': False}
    save(output/'RESULT.json', result)
    raise SystemExit(0 if result['status'] == 'COMPLETE' else 1)


if __name__ == '__main__':
    main()
