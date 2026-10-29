"""Finite HQ-only Docling shards; reuse 07b/620 and the frozen serial runner.

Each layout process must close before its table process. This coordinator never
loads an SDK, reads pixels, changes OCR answers, retries failed stages, or scores
layout coverage as field accuracy. The scheduled HQ task can finish offline.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import time
import traceback

from component_common import RESOURCES, checked, pin, read, require_HQ, save, sha, validate_task


def ranges(total, count):
    if total != 484 or type(count) is not int or not 1 <= count <= 64:
        raise ValueError('Fixed484 parent and explicit1..64 shard size required')
    return [(start, min(count, total-start)) for start in range(0, total, count)]


def replace_arg(args, key, value):
    args = list(args)
    if args.count(key) > 1:
        raise ValueError('Duplicate worker argument: '+key)
    if key in args:
        index = args.index(key)
        if index+1 == len(args) or args[index+1].startswith('--'):
            raise ValueError('Missing worker argument value: '+key)
        args[index+1] = str(value)
    else:
        args.extend([key, str(value)])
    return args


def tiny_closed(result, expected_stages):
    """Require actual control/candidate/scoring children, never a metadata probe."""
    if result.get('contract') != 'document-ai-HQ-serial-result.v1' or result.get('status') != 'COMPLETE':
        raise ValueError('Actual completed endpoint tiny serial result required')
    if result.get('cleanup', {}).get('confirmed_all_known_owned_exited') is not True or result.get('shared_lock_released_after_owned_closure') is not True:
        raise ValueError('Endpoint tiny physical closure required')
    resources = result.get('resources', [])
    if len(expected_stages) != 3 or len(set(expected_stages)) != 3 or [item.get('stage') for item in resources] != list(expected_stages):
        raise ValueError('Tiny must execute control, candidate and paired scorer')
    for index, item in enumerate(resources):
        if item.get('child_started') is not True or item.get('actual_exit_code') != 0 or item.get('failure') is not None or item.get('stop_reason') is not None:
            raise ValueError('Tiny contains an incomplete actual child')
        if item.get('worker_optimizer_updates_permission') is not False or item.get('cleanup', {}).get('confirmed_all_known_owned_exited') is not True:
            raise ValueError('Tiny optimizer authority or closure differs')
        summary = read(checked(item['worker_summary']))
        if index < 2:
            if summary.get('status') != 'COMPLETE' or summary.get('scope') != 'tiny' or summary.get('variant') != ('control', 'candidate')[index]:
                raise ValueError('Tiny must contain actual matched parser arms')
        elif summary.get('status') != 'COMPLETE' or summary.get('scope') != 'DIAGNOSTIC_TINY_NOT_FULL585' or summary.get('actual_scorer_invocations') != 2 or summary.get('writer_readback_verified') is not True:
            raise ValueError('Actual tiny paired scorer and output readback required')
    return resources


def positive_table_canary(summary, closed_result, page):
    """A successful empty route is not a positive TableFormer preflight."""
    if summary.get('status') != 'COMPLETE' or summary.get('component') != 'docling' or summary.get('stage') != 'tables' or summary.get('actual_completed_table_model_calls', 0) < 1:
        raise ValueError('Actual successful TableFormer call required')
    if closed_result.get('status') != 'COMPLETE' or closed_result.get('cleanup', {}).get('confirmed_all_known_owned_exited') is not True or closed_result.get('shared_lock_released_after_owned_closure') is not True:
        raise ValueError('Positive TableFormer supervisor must physically close')
    if summary.get('new_text_OCR_calls') != 0 or summary.get('optimizer_updates') != 0:
        raise ValueError('Positive geometry must preserve the recognition scope')
    options=summary.get('native_table_options',{})
    backend=read(checked(summary['actual_native_table_backend']))
    if backend.get('cpu_backend')!=options.get('cpu_backend') or backend.get('mkldnn_enabled') is not options.get('mkldnn_enabled') or type(backend.get('mkldnn_available')) is not bool:
        raise ValueError('Actual positive native backend proof differs from selected options')
    actual = [read(checked(record)) for record in summary['page_results']]
    selected = [item for item in actual if item['page'] == page]
    if len(selected) != 1 or selected[0].get('table_model_calls', 0) < 1 or not selected[0].get('cell_association', {}).get('cells'):
        raise ValueError('Tiny source page must exercise native table cells')
    return selected[0]


def accepted_worker_options(template, positive_summary):
    if positive_summary.get('worker', {}).get('sha256') != template['worker']['sha256']:
        raise ValueError('Full native worker must exactly match the actual positive canary source')
    if '--native-cell-matching' not in template['args']:
        raise ValueError('Explicit matching mode must bind the accepted positive canary')
    matching = template['args'][template['args'].index('--native-cell-matching')+1]
    if '--table-cpu-backend' not in template['args']:
        raise ValueError('Explicit CPU backend must bind the accepted positive canary')
    backend=template['args'][template['args'].index('--table-cpu-backend')+1]
    options = {'do_matching': matching == 'enabled', 'evaluation_predictions_supplied': False,
               'cpu_backend':backend,'mkldnn_enabled':backend=='native'}
    if matching not in ('enabled', 'disabled') or backend not in ('native','aten') or positive_summary.get('native_table_options') != options:
        raise ValueError('Full native matching options differ from accepted positive canary')
    selected_cache=positive_summary.get('runtime_cache')
    cache_flags=('--runtime-cache-manifest','--runtime-cache-manifest-sha256')
    if selected_cache:
        if any(flag not in template['args'] for flag in cache_flags):raise ValueError('Full must reuse the accepted verified runtime cache')
        actual={'path':template['args'][template['args'].index(cache_flags[0])+1],
                'sha256':template['args'][template['args'].index(cache_flags[1])+1]}
        if actual!=selected_cache:raise ValueError('Runtime cache identity differs from positive canary')
    elif any(flag in template['args'] for flag in cache_flags):raise ValueError('Runtime cache was not exercised by positive canary')
    return options


def lifecycle_tiny(config,positive_summary_pin,positive_summary,check=checked):
    """A source family cannot reuse a tiny from the old operational arm."""
    if config.get('lifecycle_equivalence') is None:return None
    from eval_lifecycle import validate_approval,validate_producer,context
    from eval_runner import tiny_gate
    lifecycle=validate_approval(config['lifecycle_equivalence'],check)
    if config['pins'].get('lifecycle_equivalence')!=config['lifecycle_equivalence']:
        raise ValueError('Lifecycle approval must remain in every immutable stage pin set')
    validate_producer(positive_summary,positive_summary_pin,lifecycle,'fresh')
    profile_pin=config.get('endpoint_profile')
    if not profile_pin or config['pins'].get('endpoint_profile')!=profile_pin:
        raise ValueError('Selected V5 endpoint profile must remain in the immutable stage pin set')
    selected_profile=read(check(profile_pin));context(selected_profile,check)
    if selected_profile.get('lifecycle_equivalence')!=config['lifecycle_equivalence']:
        raise ValueError('Full/tiny lifecycle profiles differ')
    actual_tiny=read(check(config['actual_closed_endpoint_tiny']))
    tiny_gate(selected_profile,actual_tiny['resources'][-1]['worker_summary'],check)
    for item in actual_tiny['resources'][:2]:
        complete=read(check(item['worker_summary']));manifest=read(check(complete['run_manifest']))
        if manifest.get('profile')!=profile_pin or manifest.get('native_summary')!=positive_summary_pin:
            raise ValueError('New V5 tiny must exercise the same actual positive900 source summary')
    return lifecycle


def retained_layout(entry, plan, parent_pin, registry_pin, expected, runtime_versions, materialization_pin):
    """Keep the original producer identity; never relabel retained calls as new."""
    from docling_stage_worker import actual_upstream
    summary_pin,resource_pin=entry['summary'],entry['resource']
    result=read(checked(entry['closed_source_supervision']))
    resource=read(checked(resource_pin))
    if result.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True or result.get('shared_lock_released_after_owned_closure') is not True:
        raise ValueError('Retained layout source run must have physically closed')
    if not any(item==resource and item.get('worker_summary')==summary_pin and item.get('actual_exit_code')==0 and item.get('failure') is None for item in result.get('resources',[])):
        raise ValueError('Retained layout has no successful source child witness')
    tasks=[t for t in plan['tasks'] if t['page'] in set(expected)]
    summary,_=actual_upstream(summary_pin['path'],summary_pin['sha256'],resource_pin['path'],resource_pin['sha256'],plan,registry_pin,tasks)
    if summary.get('runtime_versions')!=runtime_versions or summary.get('materialization')!=materialization_pin:
        raise ValueError('Retained layout runtime/model data differs from accepted canary')
    completed_pages(summary,parent_pin,expected,'layout')
    return summary,{'summary':summary_pin,'resource':resource_pin}


def retained_table(entry, plan, parent_pin, expected, upstream, positive,lifecycle_equivalence=None):
    """Reuse a pristine closed table child without rewriting its failed parent."""
    summary_pin,resource_pin=entry['summary'],entry['resource']
    origin=read(checked(entry['closed_source_supervision']))
    resource=read(checked(resource_pin));summary=read(checked(summary_pin))
    if (origin.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
      or origin.get('shared_lock_released_after_owned_closure') is not True
      or resource not in origin.get('resources',[]) or resource.get('worker_summary')!=summary_pin
      or resource.get('actual_exit_code')!=0 or resource.get('failure') is not None or resource.get('stop_reason') is not None
      or resource.get('child_started') is not True or resource.get('worker_optimizer_updates_permission') is not False
      or resource.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
      or resource.get('logs_finalized_after_owned_cleanup') is not True
      or not 0<resource.get('peak_owned_process_tree_RSS_bytes',0)<=RESOURCES['maximum_own_process_tree_RSS_bytes']
      or resource.get('minimum_free_RAM_bytes',0)<RESOURCES['stop_free_RAM_bytes']):raise ValueError('Retained table requires its pristine successful closed child')
    if lifecycle_equivalence is not None:
        from eval_lifecycle import Approval,validate_approval,validate_producer,recipe_identity
        approval=lifecycle_equivalence if isinstance(lifecycle_equivalence,Approval) else validate_approval(lifecycle_equivalence)
        allowed=approval.data['retained_table']
        if (any(entry.get(k)!=allowed[k] for k in ('summary','resource','closed_source_supervision'))
          or expected!=allowed['selected_pages'] or summary.get('worker')!=approval.data['original_worker']):
            raise ValueError('Only the explicitly approved original64b1d retained table may cross lifecycle sources')
        validate_producer(summary,summary_pin,approval)
        validate_producer(positive,{},approval,'fresh');recipe_identity(positive,approval)
    elif summary.get('worker',{}).get('sha256')!=positive['worker']['sha256']:
        raise ValueError('Retained table producer differs without explicit lifecycle authority')
    if (any(summary.get(k)!=positive.get(k) for k in ('registry','materialization','runtime_versions','native_table_options'))
      or not upstream or summary.get('upstream_layout_summary')!=upstream['summary']):raise ValueError('Retained table model/source/options or selected layout differs')
    checked(summary['worker']);completed_pages(summary,parent_pin,expected,'tables')
    abi=read(checked(summary['actual_runtime_ABI_proof']));cpu=read(checked(summary['actual_native_CPU_binding']))
    backend=read(checked(summary['actual_native_table_backend']));options=positive['native_table_options']
    if (abi.get('status')!='PASS' or abi.get('versions')!=summary['runtime_versions'] or abi.get('native_cpu_array_sum')!=6
      or abi.get('numpy_tensor_roundtrip') is not True or abi.get('model_calls')!=0 or abi.get('source_image_decodes')!=0
      or cpu!={'torch_compute_threads':1,'torch_interop_threads':1,'opencv_threads':1,'model_device':'cpu'}
      or backend.get('cpu_backend')!=options['cpu_backend'] or backend.get('mkldnn_enabled') is not options['mkldnn_enabled']
      or type(backend.get('mkldnn_available')) is not bool):raise ValueError('Retained table native ABI/backend/CPU differs')
    layout=read(checked(upstream['summary']));layout_pages={read(checked(p))['page']:p for p in layout['page_results']}
    checked(upstream['resource']);tasks={t['page']:t for t in plan['tasks']};calls=0
    if list(layout_pages)!=expected:raise ValueError('Retained table layout source partition differs')
    for record in summary['page_results']:
        page=read(checked(record));number=page['page'];task=tasks[number]
        layout_page=read(checked(layout_pages[number]));count=page.get('table_model_calls')
        if (page.get('contract')!='document-ai-original-frame-geometry.v1' or page.get('component')!='docling' or page.get('stage')!='tables'
          or page.get('source_image')!=task['source_image'] or page.get('source_size')!=task['source_size']
          or page.get('source_frame')!='original_image' or page.get('rotation_ccw')!=task.get('rotation_ccw',0)
          or page.get('new_text_OCR_calls')!=0 or page.get('assistant_image_transcription') is not False
          or page.get('upstream_layout_summary')!=upstream['summary'] or page.get('upstream_layout_resource')!=upstream['resource']
          or page.get('upstream_layout_observation')!=layout_pages[number] or page.get('regions')!=layout_page.get('regions')
          or page.get('native_table_options')!=options or type(count) is not int or count<0):raise ValueError('Retained table original frame, layout ownership or native count differs')
        calls+=count
    if summary.get('actual_model_predict_calls_started')!=calls or summary.get('actual_completed_table_model_calls')!=calls:
        raise ValueError('Retained table actual completed calls differ')
    return summary


def retained_partitions(entries,shards):
    selected={}
    for entry in entries:
        start,count=entry['slice_start'],entry['slice_count'];key=(start,count)
        if type(start) is not int or type(count) is not int or key not in shards or key in selected:
            raise ValueError('Retained stage must equal a unique integer source partition')
        selected[key]=entry
    return selected


def step_for(template, output, index, start, count, stage, upstream=None):
    if stage not in ('layout', 'tables') or template.get('component') != 'docling' or template.get('optimizer_updates_allowed') is not False:
        raise ValueError('Docling inference-only template required')
    step = copy.deepcopy(template)
    step['id'] = stage+'_'+str(index).zfill(3)
    native = Path(output)/step['id']
    for flag, value in (('--stage', stage), ('--output', native), ('--slice-start', start), ('--slice-count', count)):
        step['args'] = replace_arg(step['args'], flag, value)
    step['summary_path'] = str(native/'SUMMARY.json')
    step['summary_equals'] = {'status': 'COMPLETE', 'component': 'docling', 'stage': stage,
                             'pages_completed': count, 'complete_stage_shard': True,
                             'new_text_OCR_calls': 0, 'optimizer_updates': 0,
                             'complete_full_inventory': False}
    if stage == 'layout':
        step['summary_equals']['actual_completed_layout_model_calls'] = count
    else:
        if not upstream:
            raise ValueError('Actual physically closed layout pins required')
        for role, record in upstream.items():
            checked(record)
            flag = '--upstream-layout-summary' if role == 'summary' else '--upstream-resource'
            step['args'] = replace_arg(step['args'], flag, record['path'])
            step['args'] = replace_arg(step['args'], flag+'-sha256', record['sha256'])
            step.setdefault('input_pins', []).append(record)
    return step


def completed_pages(summary, parent_pin, expected, stage):
    if summary.get('status') != 'COMPLETE' or summary.get('plan') != parent_pin or summary.get('component') != 'docling' or summary.get('stage') != stage:
        raise ValueError('Completed shard source/stage differs')
    if summary.get('full_source_inventory_pages') != 484 or summary.get('selected_pages') != expected or summary.get('pages_completed') != len(expected):
        raise ValueError('Completed shard coverage differs')
    if summary.get('complete_stage_shard') is not True or summary.get('new_text_OCR_calls') != 0 or summary.get('optimizer_updates') != 0:
        raise ValueError('Partial or recognition/training shard cannot continue')
    pages = [read(checked(record))['page'] for record in summary['page_results']]
    if pages != expected:
        raise ValueError('Actual native page files do not equal selected source union')
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--config-sha256', required=True)
    args = parser.parse_args()
    require_HQ()
    if sha(args.config) != args.config_sha256:
        raise ValueError('Full driver config bytes differ')
    config = read(args.config)
    if config.get('docling_full_driver') != pin(__file__) or config.get('resource_policy') != RESOURCES:
        raise ValueError('Full driver source or resource policy differs')
    for record in config['pins'].values():
        checked(record)
    if config['pins'].get('full_plan') != config['full_parent_plan']:
        raise ValueError('Full parent must remain in the per-stage immutable pin set')
    full = read(checked(config['full_parent_plan']))
    if full.get('mode') != 'full' or full.get('component') != 'docling' or full.get('approved_by') != 'root' or len(full['tasks']) != 484:
        raise ValueError('Source-only frozen full484 parent plan required')
    for task in full['tasks']:
        validate_task(task)
    pages = [task['page'] for task in full['tasks']]
    if len(set(pages)) != 484:
        raise ValueError('Duplicate parent page')
    if config.get('endpoint_tiny_stage_ids') != ['control', 'candidate', 'paired_score']:
        raise ValueError('Actual fixed V3 endpoint tiny stage order required')
    tiny_closed(read(checked(config['actual_closed_endpoint_tiny'])), config['endpoint_tiny_stage_ids'])
    positive_summary_pin = config['actual_positive_table_summary']
    positive_result = read(checked(config['actual_closed_table_canary']))
    if not any(item.get('worker_summary') == positive_summary_pin and item.get('actual_exit_code') == 0 and item.get('failure') is None for item in positive_result.get('resources', [])):
        raise ValueError('Positive TableFormer summary is not bound to its real closed child')
    positive_summary = read(checked(positive_summary_pin))
    positive_table_canary(positive_summary, positive_result, config['actual_positive_table_page'])
    lifecycle=lifecycle_tiny(config,positive_summary_pin,positive_summary)
    supervisor_path = checked(config['source'])
    spec = importlib.util.spec_from_file_location('_frozen_docling_full_serial', supervisor_path)
    supervisor = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = supervisor
    spec.loader.exec_module(supervisor)
    output = supervisor.validate(config)
    if len(config['steps']) != 1:
        raise ValueError('Exactly one frozen full-layout step template required')
    template = config['steps'][0]
    accepted_worker_options(template, positive_summary)
    if template['maximum_seconds'] > 2400 or template['maximum_seconds'] <= 0:
        raise ValueError('Unbounded per-shard stage')
    if template['args'][template['args'].index('--plan')+1] != config['full_parent_plan']['path'] or template['args'][template['args'].index('--plan-sha256')+1] != config['full_parent_plan']['sha256']:
        raise ValueError('Template must use the unchanged full parent')
    if full.get('registry')!=positive_summary.get('registry'):
        raise ValueError('Full parent registry differs from accepted positive canary')
    for flag,role in (('--registry','registry'),('--materialization','materialization')):
        record=positive_summary[role]
        if template['args'][template['args'].index(flag)+1]!=record['path']:
            raise ValueError('Full model/data source differs from accepted positive canary')
        checked(record)
    shards = ranges(484, config['shard_size'])
    retained={'layout':retained_partitions(config.get('retained_layout_shards',[]),shards),
              'tables':retained_partitions(config.get('retained_table_shards',[]),shards)}
    import psutil
    ownership = supervisor.load('_docling_full_original620', config['pins']['ownership']['path'])
    probe = supervisor.load('_docling_full_fresh_metadata', config['pins']['metadata_probe']['path'])
    registry = ownership.OwnedRegistry(psutil)
    output.mkdir(parents=True, exist_ok=False)
    resources, layouts, tables, retained_pages, fresh_layouts = [], [], [], [], []
    retained_tables,fresh_tables=[],[]
    failure = None
    acquired = False
    started = time.monotonic()
    save(output/'STARTED.json', {'config': pin(args.config), 'driver': pin(__file__),
         'full_parent_plan': config['full_parent_plan'], 'started_utc': datetime.now(timezone.utc).isoformat(),
         'shard_size': config['shard_size'], 'shards': len(shards), 'model_calls_started': 0})
    try:
        with ownership.safe_owned_lock(ownership.LOCK, registry):
            acquired = True
            end = time.monotonic()+config['maximum_total_seconds']
            for index, (start, count) in enumerate(shards):
                expected = pages[start:start+count]
                upstream = None
                for stage, completed in (('layout', layouts), ('tables', tables)):
                    if (output/'STOP_REQUEST.json').exists() or time.monotonic() >= end:
                        raise RuntimeError('Stopped at a closed inference stage boundary')
                    if sha(args.config) != args.config_sha256:
                        raise ValueError('Config changed during full run')
                    for record in config['pins'].values():
                        checked(record)
                    if (start,count) in retained[stage]:
                        entry=retained[stage][(start,count)]
                        if stage=='layout':
                            origin,upstream=retained_layout(entry,full,config['full_parent_plan'],positive_summary['registry'],expected,positive_summary['runtime_versions'],positive_summary['materialization'])
                            retained_pages.extend(expected)
                        else:
                            origin=retained_table(entry,full,config['full_parent_plan'],expected,upstream,positive_summary,lifecycle)
                            retained_tables.extend(expected)
                        completed.extend(expected)
                        save(output/(stage+'_'+str(index).zfill(3)+'.RETAINED.json'),{
                            'origin_summary':entry['summary'],'origin_resource':entry['resource'],
                            'origin_closed_supervision':entry['closed_source_supervision'],
                            'origin_worker':origin['worker'],'selected_pages':expected,
                            'new_model_calls':0,'source_prediction_identity_relabelled':False})
                        continue
                    fresh = probe.probe(config['pins']['controller']['path'], ownership.LOCK)
                    reviewed = supervisor.ordinary_process_gate(fresh, config)
                    step = step_for(template, output, index, start, count, stage, upstream)
                    save(output/(step['id']+'.fresh_admission.json'), {'metadata': fresh, 'ordinary_processes': reviewed})
                    resource = supervisor.run_stage(step, config, output, ownership, registry, psutil, end)
                    resources.append(resource)
                    summary_pin = resource['worker_summary']
                    summary = read(checked(summary_pin))
                    if summary.get('worker', {}).get('sha256') != positive_summary['worker']['sha256'] or stage == 'tables' and summary.get('native_table_options') != positive_summary['native_table_options']:
                        raise ValueError('Actual full source/options changed from accepted canary')
                    if lifecycle and summary.get('runtime_cache')!=lifecycle.data['delivery_provenance']['selected_runtime_cache']:
                        raise ValueError('Fresh layout/table runtime cache differs from selected startup900 delivery')
                    completed.extend(completed_pages(summary, config['full_parent_plan'], expected, stage))
                    if stage=='layout':fresh_layouts.extend(expected)
                    else:fresh_tables.extend(expected)
                    resource_pin = pin(output/(step['id']+'.resource.json'))
                    if stage == 'layout':
                        upstream = {'summary': summary_pin, 'resource': resource_pin}
                    save(output/(step['id']+'.CLOSED.json'), {'summary': summary_pin, 'resource': resource_pin,
                         'selected_pages': expected, 'actual_source_plan': config['full_parent_plan'],
                         'actual_runtime_ABI_proof': summary['actual_runtime_ABI_proof'],
                         'actual_native_CPU_binding': summary['actual_native_CPU_binding'],
                         'model_coverage_is_not_endpoint_accuracy': True})
            if layouts != pages or tables != pages:
                raise ValueError('Actual completed layout/table union is not exact484')
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
              'full_parent_plan': config['full_parent_plan'], 'actual_layout_pages': layouts,
              'fresh_layout_pages':fresh_layouts,'retained_layout_pages':retained_pages,
              'fresh_table_pages':fresh_tables,'retained_table_pages':retained_tables,
              'actual_table_stage_pages': tables, 'complete_full_inventory': failure is None and layouts == pages and tables == pages,
              'elapsed_seconds': time.monotonic()-started, 'new_text_OCR_calls': 0,
              'optimizer_updates': 0, 'endpoint_score_status': 'NOT_EVALUATED',
              'endpoint_gain': None, 'production_activation': False}
    save(output/'RESULT.json', result)
    if failure or not safe:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
