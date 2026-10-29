# Finite Docling post-evaluation

`docling_post_eval.py` starts only after the separate PowerShell waiter observes
the native task **Ready, last result0, no running instances** and the actual
native `RESULT.json` is complete and safely closed. No Python process waits
beside the native models. Root owns publication and launch; this file does not
restart a failed task.

```text
python -X utf8 -B docling_post_eval.py --config <post-config.json> --config-sha256 <sha> --completion-receipt <actual-ready.json> --completion-sha256 <sha> --execute
```

Omitting `--execute` validates the static root configuration only. It does not
create result directories or start children. Root's finite waiter writes a
fresh completion receipt immediately before this invocation:

```json
{
  "contract": "document-ai-native-task-ready.v1",
  "task_name": "<exact selected OCR_DOCAI_ full-native task>",
  "state": 3,
  "last_task_result": 0,
  "running_instances": 0,
  "observed_at_utc": "<actual UTC ISO timestamp>",
  "native_config": {"path": "<native config>", "sha256": "<actual fixed SHA>"},
  "native_result": {"path": "<actual RESULT.json>", "sha256": "<actual SHA>"}
}
```

The receipt must be at most300seconds old, must name the exact selected task,
config and result, and cannot substitute for the native resource receipts.
The driver also checks the actual native config/driver, all fresh child
resources, source partitions, closed ownership and full484 completion.
Retained layout is taken only from explicit `retained_layout_shards` in that
immutable native config. Its `.RETAINED.json`, original summary/resource/worker
and source supervision are checked without relabelling old predictions as new
calls. A source root may have failed later while that particular layout child
completed and closed successfully. With64 retained layout pages the expected
fresh resources are15 (7layout+8table), fresh layout420, retained layout64,
and fresh table484. These inventories must form exact disjoint source partitions;
an invented16th fresh child or double counting is rejected.

The same explicit provenance path supports `retained_table_shards`. With both
layout64 and table64 retained, the new native job has14 fresh children:
7layout420 and7table420. `fresh_table_pages` and `retained_table_pages`, like
their layout counterparts, must form disjoint exact integer1..484 inventories.
Original table worker, options, model data, runtime/backend, page frames and
closed upstream layout chain are checked; original successful child resources
remain bound to their original source root even when that root later failed.

The frozen V4 merger requires a completed closure witness for every table.
For retained tables the new post config must explicitly set
`allow_composed_retained_table_source_witness:true`. The post driver emits
`COMPOSED_CLOSED_SOURCE_WITNESS.json` with a distinct verification-only contract.
Its `COMPLETE` means that closure verification finished, not that any old failed
job succeeded. It records every original root status/failure and exact root,
resource, summary and readback pins. Fourteen fresh native resources and one
pristine retained-table resource are distinguished; the old retained-layout
resource is recorded separately. Original worker and argv remain unchanged.
The composition starts zero children and zero model calls and changes no
frozen parser, reference, scorer, metric or original source file.
The selected table worker, four native options and actual backend proof remain
bound to the successful canary.

The private root config has these required fields; all records contain native
`path` and `sha256` values, not SMB client paths:

| Field | Value |
| --- | --- |
| `contract` | `root-HQ-docling-post-eval.v1` |
| `approved_by` | `root` |
| `driver` | exact deployed `docling_post_eval.py` pin |
| `source` | exact audited serial supervisor87714 pin |
| `pins` | original `controller`, `ownership`, `python`, `metadata_probe`; any additional immutable input pins |
| `resource_policy` | unchanged `component_common.RESOURCES` |
| `ordinary_external_processes` | root's source-backed ordinary-process classifications |
| `native_task_name` | exact full-native task name |
| `native_config` | exact root-frozen selected full-native config pin |
| `native_result_path` | the exact future native result path |
| `full_parent_plan` | unchanged full484 source plan7dad pin |
| `expected_table_worker_sha256` | exact native table worker SHA of the accepted positive canary and tiny |
| `selected_table_options` | `do_matching:false`, `evaluation_predictions_supplied:false`, `cpu_backend:"aten"`, `mkldnn_enabled:false` |
| `profile` | exact root-frozen endpoint profile pin; its frozen reference/scorer/control still must pass the V4 checks |
| `expected_profile_sha256` | explicit SHA of that selected profile, bound in this prospective root config |
| `tiny_score` | actual completed tiny score pin |
| `closed_tiny` | actual tiny serial parent result pin |
| `trial_name` | simple unique name below the V4 profile's result root |
| `preparation_root` | new isolated D-drive experiment directory outside that trial output |
| `maximum_total_seconds` | at most7200 |
| `production_activation_allowed` | `false` |

Under the original07b lock and620 ownership registry, pure metadata preparation
merges the actual table shards, checks the tiny model/options/source identity,
and builds the frozen V4 full plan. It then calls the original `run_stage` for
`control`, `candidate`, `paired_score`, with prospective limits1800/1800/600
seconds. Every stage gets a fresh ordinary-process gate and the original
CPU/RAM/RSS, deadline and owned-child cleanup rules. The coordinator uses one
CPU and bounds its inline metadata reads as well. There are no other child
launches, SDK imports, image reads, OCR calls or optimizer updates.

Preparation artifacts and a final resource result are saved under
`preparation_root`. The actual parser and scorer files are saved under the
V4 plan's `required_supervisor_output_root`; its final `RESULT.json` carries
the same resource record. Failure preserves partial outputs and stops without
retry. Numerical eligibility never activates production.

Full scoring keeps323/585 and the original602/329/57/18/prior323 cohorts.
Report484 model-processed sources separately from585 product-present reference
fields on105 images,191 images with any reference and293 with none. Counts of
native cells and completed pages do not establish field accuracy.

```text
python -B -W error::ResourceWarning -m unittest tests.test_document_ai_post_eval -v
```
