# Isolated document structure trials

These modules provide guarded component experiments. They do **not** activate a
new production engine. Development and tests run on ScProductDev; native model
inference, package setup and training run only on 000 HQ (`SERVER`). The
supervisor preserves the existing single-worker lock, CPU one thread, 1.85 GiB
inference start, 2.3 GiB optimizer start, 1.2 GiB free-memory floor and 1 GiB
owned process-tree RSS cap. An oversized candidate is stopped or rejected;
raising these limits requires a separately reviewed decision.

No assistant or subagent transcribes source images. The model worker may decode
pixels automatically. Planning, model artifact verification, geometry
association and scoring do not require a person to open images.

## Model registry and roles

`model_registry.json` contains publisher repository revisions, exact sizes,
SHA256 for large artifacts, Git blob SHA1 for small publisher files, licenses and
pinned download URLs. File size is not a runtime RAM prediction.

| Component | Selected native weights | What the trial produces |
| --- | ---: | --- |
| PP-DocLayout-M | 23,370,814 bytes | Layout regions, including candidate table regions |
| PP-DocLayout-L | 129,021,913 bytes | A separate larger layout arm |
| Docling Egret-medium + fast TableFormer | 223,764,672 bytes | Layout regions and native table cell/content envelopes |
| Qwen3-VL-2B-Instruct BF16 | 4,255,140,312 bytes | Rejected before model download/import under the current RSS cap |

Qwen's publisher metadata reports 2,127,532,032 BF16 parameters. Even an idealized
four-bit storage of all parameters would occupy 1,063,766,016 bytes, leaving
9,975,808 bytes under the current RSS cap before runtime, activations, vision
processing or quantization metadata. This arithmetic is a preflight lower bound,
not a tested quantized model or a claim that Qwen inference ran.

Primary sources: [Paddle M](https://huggingface.co/PaddlePaddle/PP-DocLayout-M),
[Paddle L](https://huggingface.co/PaddlePaddle/PP-DocLayout-L),
[Egret](https://huggingface.co/docling-project/docling-layout-egret-medium),
[TableFormer artifacts](https://huggingface.co/docling-project/docling-models),
[Docling SDK](https://github.com/docling-project/docling-ibm-models),
[Qwen](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct).

## Executable stages

1. `metadata_probe.py` imports no model and examines fresh RAM, packages,
   process creation identities, known ML library mappings and shared lock.
   The root must explicitly classify ordinary external applications; matching
   an executable name alone does not exempt a process.
2. `build_trial_plan.py` reads the existing pinned raw OCR cache. It restores
   quarter-turn geometry to the original image frame, preserves literal OCR
   text and records invalid/out-of-frame tokens without clipping them. It never
   reads normalized business values as recognition answers.
3. `materialize_models.py` streams only the registry's exact public artifacts
   into a new isolated D-drive experiment folder on HQ. Qwen is rejected before
   byte download. A mismatch preserves the existing or partial file and stops.
4. `serial_supervisor.py` holds the audited 07b global lock through worker
   cleanup, reusing the original 620 ownership registry. Every direct child has
   an immutable root admission and bounded deadline. A RAM/RSS violation,
   unknown external model process, failed summary or uncertain child closure
   stops the sequence.
5. `component_worker.py` defaults to metadata validation. `--execute` requires
   an active supervisor ancestor and the exact source/model/plan pins. It runs
   one page for a canary, at most sixteen pages for a pilot, or an explicit
   484-page full run. PP supplies no text or cells. Docling uses existing OCR
   tokens to match its table structure; native generated/matched text never
   replaces those OCR observations.

`prepare_component_data.py` combines stages 2–3 into a single admitted HQ data
job. It builds a source-selected page-two canary and a bounded pilot drawn from
distinct **machine-supplied** company keys. Those keys are diagnostic groupings,
not human-verified labels.

Example stage arguments, with paths and digests supplied by the root launcher:

```text
component_worker.py --registry REGISTRY --plan PLAN --plan-sha256 SHA256
  --materialization RECEIPT --output NEW_OUTPUT --execute
  --admission {admission} --admission-sha256 {admission_sha256}
```

The arguments are passed as a structured list by the supervisor, not through a
second shell. `scripts/hq_document_ai_job.py` publishes exact selected source
files and uses the existing hidden scheduled-task identity. It must use a new
`OCR_DOCAI_*` name, never restart an earlier failed or paused experiment.

## Isolated Docling dependencies

`docling_environment.json` fixes CPU Torch/torchvision wheel URLs and publisher
SHA256, plus explicit primary package versions. `install_docling_environment.py`
creates a new venv under an isolated experiment directory, resolves a complete
binary-wheel URL/SHA256 lock, installs only that lock, and records distribution
versions without importing Torch, Docling or a model. It keeps its cache and
temporary files under that new directory and never installs into the frozen
Paddle runtime. Each step has a timeout; the outer supervisor applies CPU/RAM
and child cleanup limits to pip and its descendants as well.

Use `component="docling-install"`, `optimizer_updates_allowed=false` for setup.
After setup, the inference stage can override `python` with the exact new venv
interpreter pin from the setup receipt. A failed setup is retained as an
unusable partial environment; do not silently reuse it.

`install_docling_environment_v2.py` separates a one-wheel, no-index metadata
probe from full dependency resolution. It can reuse an existing CPU wheel only
after verifying its publisher SHA256. `pip_stage_runner.py` adds periodic stack
evidence and uses larger streaming buffers without disabling SHA checks or ZIP
CRC validation; it modifies no installed pip files. Real installation uses
`--no-compile`, while a later native SDK call still has to pass its actual import
and forward path. Timeouts and memory limits are not extended by these changes.

The optional `docling_environment_cpu26.json` is an explicitly selected alternate
CPU runtime, not an automatic fallback. Its Torch/torchvision versions differ
from the original environment and must be reported as such. It was prepared
after the original Torch wheel's multi-gigabyte static library dominated
extraction; a smaller wheel is not evidence that model inference or NumPy ABI
compatibility has passed. Never select a newer-named file without the root's
exact pinned run configuration.

## Split Docling inference and full-source coverage

`docling_stage_worker.py` runs Egret layout and TableFormer in separate model
processes so that their weights do not need to coexist under the 1 GiB cap.
Each stage records actual Torch/OpenCV thread counts and CPU device binding,
and tests the native NumPy ↔ Torch array roundtrip before reading source pixels.
The table stage requires a source-matched layout summary and its physically
closed supervisor resource receipt. Its regions remain exactly those from the
upstream layout packet. Native matched strings still do not become OCR answers.

For full runs the parent plan remains the exact 484-task plan and SHA. Use
`--slice-start` and `--slice-count` to submit at most 64 existing tasks per model
process. Layout and table shards must have identical selected pages. Each shard
reports its actual selection and keeps `complete_full_inventory=false`; only a
verified merge of the unique complete 484-page union can claim full coverage.
SDK startup remains externally bounded, and each native prediction has its own
120-second watchdog. [EVALUATION.md](EVALUATION.md) describes the independent
parser/scorer boundary when that evaluation tooling is included.

`docling_full_driver.py` is the finite HQ continuation for a frozen full parent.
It uses the pinned serial runner's existing 07b lock and 620 child registry,
rechecks external process identities before each stage, and does not retry a
failed stage. The shard size is explicit (1–64), with each stage capped at
2,400 seconds and the whole job at the serial runner's existing twelve hours.
The coordinator requires both a physically closed positive TableFormer canary
on the tiny source page and the actual completed control/candidate/paired-score
tiny result, including the two scorer invocations and output readback. An empty
table route or a metadata probe cannot unlock the full job.

Each layout process closes before the corresponding table process is admitted;
the exact new layout summary and resource SHA are generated from actual files.
Each shard preserves the parent-plan SHA and selected source pages. The final
driver receipt contains model coverage only, with endpoint gain still null;
the independent full merger, parser and frozen scorer must subsequently finish.
The scheduled HQ task runs without the browser or laptop remaining connected.
Actual prediction-start and prediction-completion receipts separately measure
native call time; SDK startup remains a distinct budget.

The table worker makes the SDK's native cell matching explicit through
`--native-cell-matching enabled|disabled`. Disabling it still executes the real
TableFormer neural forward pass; it does not supply evaluation predictions.
Our retained whole-token association and ambiguity rules then apply to the
returned geometry. `--table-cpu-backend aten` selects PyTorch's documented CPU
fallback by disabling MKLDNN for that TableFormer process only. Neither option
changes Egret's model or the saved OCR. The selected options, actual backend
flags, CPU binding and worker SHA must match the accepted positive canary and
the eventual tiny/full comparison. First-call CNN and transformer boundary
hooks record progress while leaving all input and output tensors untouched.
The backend switch is present in the pinned
[PyTorch2.6 source](https://github.com/pytorch/pytorch/blob/v2.6.0/torch/backends/mkldnn/__init__.py).

## Benchmark interpretation

The component control is the previously verified **323/585** FINAL164 plus saved
C4 canonical output, with exactly the same raw OCR. The **324/585** fresh reading
is a different run and is not the component baseline or a training gain.

The worker deliberately records `endpoint_score_status="NOT_EVALUATED"`.
Detected regions, table boxes, cells, token coverage and successful model calls
are not endpoint accuracy. A useful canary only permits preparing the parser
adapter; it does not establish a score increase.

Before any full measurement, the root must bind a geometry adapter and the
existing frozen parser/evaluator/reference in a new experiment freeze, execute
a real tiny parser → scorer → result-writer preflight, then evaluate all 484
pages. The comparison must preserve the original 585 product-present labels,
602 all-present, 329 critical, 57 supplier-code and eighteen absence checks,
including the identities of the previously correct 323. Report fixed fields,
lost previously correct fields, new wrong values, false fills, per-company
results, real model calls, time and peak RAM. No label expansion or threshold
change may be presented as an engine gain.

Existing business corrections, literal printed weak labels and unconfirmed
examples remain separate. The 484 images are an already-used development set,
not an unseen accuracy estimate. New documents must first test a frozen model
before being admitted to subsequent training.

## Cloud development

Commit these source files, public model metadata and model-free tests only.
Original invoices, OCR caches, teacher answers, customer identifiers, machine
process inventories, checkpoints, models and experiment outputs remain private
and are not required for the unit tests. A cloud worker without HQ access can
run:

```text
python -B -m unittest discover -s tests -p test_document_ai_components.py -v
```

Reconstruct runtime input plans from private data only on an authorized host.
All native execution remains opt-in and HQ-gated. There is no automatic
production alias, ERP write, Ada write or StockDay write in this directory.
