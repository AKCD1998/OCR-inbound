# Paired endpoint evaluation, using retained OCR

`eval_assets.py`, `eval_geometry.py`, `eval_plan.py` and `eval_runner.py` are
isolated experiments. They neither decode invoices nor call OCR/model APIs.
They do not activate a production parser or alter the original frozen assets.

The fixed control is FINAL164 plus the saved C4 canonical bundle, **323/585**.
The separate fresh-reading **324/585** is never substituted. The original
reference, scorer, grouping helpers, source inventory and prior323 identities
are checked byte for byte. FINAL164's 48-file source seal and the retained
cache's older parser snapshots remain separate closures; matching a basename
does not make their bytes interchangeable.

`eval_geometry.py` consumes the actual original-frame native observations from
the component worker. The named `PP_REGION_SOURCE_HEADER_ROW` branch uses an
actual predicted table region to contain literal headers and at least two saved
goods anchors, then bounds reads by derived source-header columns and source-row
bands. These bands are explicitly `DERIVED_SOURCE_HEADER_ROW`, never native
cells, native topology or physical borders. No predicted table region, missing
anchors, ambiguous overlapping regions or established foreign owners abstain.
Docling content boxes are not physical table borders. Their cell role comes from
whole literal headers in retained OCR, with at least two distinct saved goods
anchors. Quantity/unit values require the unchanged independent-reader gates
(primary .95, secondary .70), complete words, unique source ownership, no
foreign existing field owner, and a missing old field. Native/matched model
text is never used as a recognition answer. Existing nonempty fields and row
count are conserved. Original source geometry is restored exactly once.

There is no result yet until a real native canary and the following stages run.
Geometry/cell counts are not endpoint accuracy.

## Root's serial HQ sequence

1. After a successful bounded model canary, create a **private** profile on HQ:

   ```text
   python -X utf8 -B eval_assets.py --evidence-root <old-outputs-root> --results-root D:/OCR-Experiments/<new-unique-endpoint-root> --component docling --tiny-page <actual-canary-page> --output <private-profile.json>
   ```

   This checks assets but performs no parsing/inference. The evidence root has
   `quantity_unit_164_20261024` and `ocr_engine_upgrade_20261025`. The supplied
   native page must actually be present in the component canary summary.
   For Docling use the completed `tables` stage, not layout-only readiness.
   If HQ's untouched original checkout has older source bytes, point
   `--final164-source-root` to an isolated exact 48-file snapshot with its
   `ocr_inbound/...` paths. Every SHA must still match FINAL164; never overwrite
   the original checkout to make the preflight pass.

2. Bind the actual completed native summary into the tiny plan:

   ```text
   python -X utf8 -B eval_plan.py --profile <private-profile.json> --native-summary <actual-native-canary-SUMMARY.json> --supervision <actual-closed-native-RESULT.json> --scope tiny --name tiny_v1 --output <private-tiny-steps.json>
   ```

   This does not launch. Root inserts its three `steps` into the existing
   serial-supervisor configuration with `output_root` equal to the emitted
   `required_supervisor_output_root`. Root supplies the existing 07b/620 pins,
   current external-process classification and exact interpreter, keeping CPU1,
   RAM/RSS and owned-child cleanup gates. Each step has a real result predicate.
   `endpoint-eval` is a pure component admission with optimizer permission off.
   A standalone worker `COMPLETE` without an actual matching, safely closed
   supervisor receipt cannot produce a plan. The worker comes from the deployed
   profile's exact pin, never an unrelated local planner folder. A local client
   may prepare metadata with repeated `--read-map <native-root>=<read-share>`
   arguments without starting an HQ process. Each transported file must match
   its native SHA; emitted arguments retain native paths. Transport writes no files.

3. Run those serial steps: control parser, candidate parser, then both frozen
   scorer calls and actual result-file readback. The tiny result is explicitly
   `DIAGNOSTIC_TINY_NOT_FULL585`. Its existence, both scorer invocations and
   current profile binding are required to admit a full evaluation.

4. Only after tiny success, run the component model across all 484 sources in
   the existing heavy lane. Then build the full endpoint plan:

   ```text
   python -X utf8 -B eval_plan.py --profile <same-private-profile.json> --native-summary <actual-full484-native-SUMMARY.json> --scope full484 --name full_v1 --tiny-receipt <tiny_v1/score/RESULT.json> --output <private-full-steps.json>
   ```

   Full evaluation refuses a one-page/partial native result. It uses the saved
   OCR and saved canonical control; changing report paths or queue code never
   triggers a new baseline OCR reading. Old/partial outputs are not overwritten.
   Components run as bounded nonempty partitions of1..64 images against one
   pinned484-task source plan. Root chooses partition size from actual canary
   latency and the unchanged resource/deadline limits; eight is not a required
   partition count and does not alter the metric.
   Use `eval_merge.py --shard <SUMMARY> ... --supervision <closed-RESULT> ...
   --output <aggregate-SUMMARY>` after every selected partition finishes. The checker requires
   the exact same plan, registry and model data, supervisor-witnessed summary
   hashes and closed workers, all 484 distinct sources, and zero duplicates.
   An individual shard's `COMPLETE` is only subset completion; only the verified
   union receives `complete_full_inventory=true`. This still claims no endpoint
   accuracy before parsing and scoring.

5. Run those three full steps under the same serial supervisor. The result
   includes fixed/lost identities, new wrong values on all602/critical329/code57,
   eighteen absence false fills, prior323 losses, residual164 diagnostics,
   every section of the frozen scorer comparison, and primary13 plus diagnostic
   issuer groups (including zero-reference groups). Both complete metric files
   and per-company assessments remain available, including raw/header/document
   and row-completeness sections.
   `coverage_summary` separates processed sources from reference coverage. The
   fixed reference has **585 product-present fields on 105 images**, any
   reference on **191 images**, **293 with no reference**, and **379 without
   product-present field labels**. Thus 323/585 is agreement on those labelled
   fields, not 55% of all content on all 484 images. The original scorer's
   `coverage` and `by_label_scope` calculations remain unchanged and exposed.

The supervisor's resource receipts supply actual wall time, peak owned RSS,
minimum free RAM and worker closure. Native model calls belong to their
separate native stage, not to the pure parser/scorer stage. Split Docling stages
retain and check the actual upstream-layout observation pin. Aggregate the
separate native summaries without double-counting pages or claiming OCR calls.
The split-stage checker binds layout/table to the same exact parent plan and
slice, registry/model data and runtime versions, actual NumPy/Torch ABI and CPU
proofs, and safely closed upstream resources. Each table shard keeps
its own proof pins; no one-page assumption is used. Layout and table calls are
counted once per unique upstream summary while original-image count remains484.

Profiles are immutable versions. A bridge upgrade uses a new folder and profile
SHA; historical V1 preflight remains V1. Tiny and full results must share one
profile SHA and actual component/model/runtime identity. Docling table summaries
and every table page carry exact `native_table_options`: `do_matching=false`,
`evaluation_predictions_supplied=false`, plus the explicit `cpu_backend` and
actual `mkldnn_enabled` flag. The selected profile is frozen after a successful
canary; its full option object, native table worker SHA and model/runtime must
match the full run. Missing options, mixed native matching/backend modes,
evaluation-prediction input and tiny/full option changes are rejected. The
actual backend proof is checked against the declared options. Layout remains
neutral to table-only options.
This is source-bound TableFormer geometry plus our retained-token association;
native or matched text still never supplies recognition answers. Changing only report
or transport paths does not authorize a fresh baseline or altered reference.

All 484 pages are a previously used, nonrandom development set with zero
human-confirmed gold labels in this benchmark. Future documents must test a
frozen candidate before being used for training. No automatic production
activation follows a passing numerical gate.

Run model-free tests with:

```text
python -B -W error::ResourceWarning -m unittest tests.test_document_ai_eval tests.test_document_ai_eval_interfaces -v
```

The optional private-helper test uses generated token/page dictionaries only.
It imports exact frozen pure helpers in a fresh process, opens no images,
imports no model runtime, and does not score real reference labels.
