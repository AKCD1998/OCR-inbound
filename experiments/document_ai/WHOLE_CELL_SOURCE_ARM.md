# Whole-cell source-reading canary

This is a new recognition experiment. It does not change canonical fields,
reference labels, acceptance thresholds or the original saved OCR cache.
Runtime use requires a new Root-approved serial job with the original
07b controller, 620 ownership monitor and 877 serial supervisor.

The first invocation reads exactly **one** request from a frozen source-only
inventory containing at most 60 contexts. Select the first geometry-valid
request deterministically; do not select requests using expected values or
candidate evaluation outcomes. A successful call or more detected boxes does
not demonstrate an endpoint accuracy gain. The same paired endpoint evaluator
must measure any later integration.

## Files and protocol

- `whole_cell_source.py`: pure validation, whole-word crop closure and exact
  right-angle coordinate mapping. No image/native dependencies.
- `whole_cell_source_worker.py`: HQ-only, admission-required native canary.
- `tests/test_document_ai_whole_cell_source.py`: invented fixtures only.

The plan is `{contract:'document-ai-whole-cell-source-plan.v1',
machine_only:true, requests:[...]}`. Each request has exactly these keys:

```json
{
  "request_id": "source_page_row_field",
  "page_number": 1,
  "row_index": 0,
  "field": "unit",
  "source_image": {"path": "SOURCE_IMAGE", "sha256": "SOURCE_SHA256"},
  "geometry": {"original_size": [1000,800], "upright_size": [1000,800], "orientation_ccw": 0},
  "source_band": [100,200,140,220],
  "row_barrier_interval": [190,230],
  "source_token_inventory": {"path": "SOURCE_TOKEN_GEOMETRY_JSON", "sha256": "SHA256"},
  "context_proof": {"path": "SOURCE_CONTEXT_JSON", "sha256": "SHA256"},
  "source_inputs": {
    "cache": {"path": "ORIGINAL_CACHE", "sha256": "SHA256"},
    "canonical": {"path": "SAVED_CANONICAL", "sha256": "SHA256"},
    "native": {"path": "SAVED_NATIVE_OBSERVATION", "sha256": "SHA256"}
  }
}
```

The token inventory has contract `document-ai-source-token-geometry.v1`,
`page_number`, `source_sha256`, the same `geometry`, and **all** cached machine
detections for that page as `tokens:[{token_id,engine,bbox}]`. It contains no
candidate or expected text. Source inventories must be derived from pinned
actual cache geometry, including every reader family. The source-context proof
has contract `document-ai-whole-cell-source-context.v1`, `request_binding`
equal to the request without its `context_proof` key, and a source-only
`derivation` audit with `recipe` equal to the config's pinned derivation recipe.
Before any decode, the worker calls the separately pinned
`whole_cell_source_derivation.reconstruct(request,context,check)`. That verifier
rebuilds the original page from frozen baseline prediction/content identity,
actual cache/native manifests and frozen source helpers. It reconstructs the
complete token inventory, logical band and row barriers. Self-consistent supplied
metadata is insufficient: omitted cache words, invented barriers, recipe
mismatches and explicit HOLD cannot be admitted. Context derivation preserves
every canonical neighbour, including protected/unknown rows, as negative barriers.

The worker expands 8px horizontally and 4px vertically, then reaches fixed-point
closure over every intersecting cached detection. It refuses any expansion
crossing a canonical row barrier or exceeding the finite source/ROI budgets.
It never cuts a source word to obtain a convenient cell crop. Only padding may
stop at image or row boundaries. Saved right-angle orientation is applied before
cropping, without EXIF reinterpretation, resampling or text-specific cleanup.

## Native recipe

The inspected local static models are explicitly selected:

| Role | Model | Parameter SHA256 |
| --- | --- | --- |
| NEW detector | PP-OCRv5_server_det | `183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d` |
| Thai reader | th_PP-OCRv5_mobile_rec | `45ec91f2322b58b8d30ba27d18fcfdbb8bf388b918dd978162d2af91e0c66d4b` |

No download, model export, training or SDK modification is performed. The
detector receives `limit_side_len=640`, `limit_type='max'`,
`max_side_limit=640` at both construction and prediction. Its actual runner must
show CPU1/paddle mode/CPU device; its actual resize must show type0/max/640.
The SDK's unused processor default may remain 4000: the predictor stores and
passes the explicit 640 override. Stride32 alignment can enlarge a tiny side to
32; there is no min-side upscaling to 640. Original detector postprocessing
thresholds remain unchanged.

Raw `dt_polys` and `dt_scores` are preserved before output validation. Polygons
are translated from physical crop to upright and original frames without
clipping. They are **text-region detections, not per-character boxes**. Thai
recognition reads the axis-aligned envelope of each actual detection. Its
literal text and actual `rec_score` remain tied to the original detector polygon;
the envelope is not substituted as measured glyph geometry. Excess detections,
invalid polygons and extreme recognition aspect ratios fail instead of being
truncated or filtered according to a desired answer.

The original pinned Tesseract reader's `command_for`, `run_owned_child` and
`parse_tsv` helpers read the same whole ROI using tha+eng/OEM1/PSM6. Every actual
TSV word span, line group and confidence is retained. New Paddle and cached
Paddle remain the same engine family; the same applies to Tesseract. This arm
does not create extra independent votes by renaming an engine.
The exact `configs/tsv` dependency (22 bytes, SHA256
`59d079bb75d8b3d7c839a3564580cb559e362c93a9d70f234e421c0c3e767e04`)
must exist under the same selected tessdata directory as the exact FAST tha/eng
weights. A missing or differently located configuration is refused before OCR.

The detector closes before the recognizer is created; the recognizer closes
before Tesseract starts. This reduces overlap but does **not** prove the combined
worker will fit. Only the actual original-supervisor resource receipt can prove
the canary stayed under the 1GiB owned RSS cap and 1.2GiB free-RAM floor. Stop on
resource failure; do not raise caps. CPU1 and the 1.85GiB native-start gate remain.
Limits are explicit in `LIMITS`: 480s SDK startup per model phase, 120s detector,
60s per recognition, 120s Tess and 2100s total worker. Root's outer stage remains
at most 2400s, including cleanup.

## Prospective config and invocation

`configuration_template(plan_pin, runtime_python_pin, model_directories,
sdk_inference_root, tess_reader_path, tess_executable_path, tessdata_dir,
derivation_runtime)`
constructs a source-only config without file IO or dispatch. The caller supplies
existing paths; all selected model, reader, executable, language and SDK source
hashes are fixed by the worker. Freeze the resulting JSON and its SHA. Include
the worker, protocol, common helper and every config/input pin in the original
serial job's source closure.
`derivation_runtime` is exactly `{module:PIN,recipe:PIN}`. The module is the
reviewed `whole_cell_source_derivation.py`; its recipe binds original
recognition/baseline/native sources and the transitive helper closure. Reference
labels and scorers are not derivation inputs.

The supervisor step component is `whole-cell-source`. Arguments are:

```text
--config NEW_CONFIG --config-sha256 CONFIG_SHA
--request-id DETERMINISTIC_FIRST_ELIGIBLE_ID --output NEW_ISOLATED_NATIVE_DIR
--admission {admission} --admission-sha256 {admission_sha256} --execute
```

Without `--execute`, only source/config/crop metadata is validated; no image or
model is opened. The outer serial publisher itself must also include its own
`--execute`. Suggested completion predicates include `status:COMPLETE`,
`executed:true`, `requests_selected:1`, `requests_completed:1`,
`optimizer_updates:0`. Before admitting further ROI work, separately inspect
`positive_detector_recognizer_path`, the actual polygons/observations, the
authoritative whole-tree resource receipt and physical task/child closure.

Raw detector/recognizer outputs, crop pins, source transforms, actual SDK CPU
proof, phase markers, Tess TSV/stderr/child receipt and observations remain in
the new isolated output. Started and completed OCR/model calls are distinct;
planned request count is never reported as executed inference. Partial/failure
artifacts remain. No canonical value is assigned or production mode activated.

## Exercised native and parser path

The first actual canary completed with one detector region, one Thai recognizer
call and one Tesseract call. The original supervisor measured 540,848,128 bytes
peak owned RSS and 40.813 seconds, with physical closure and shared-lock release.
The remaining 45 eligible requests then completed serially in 453.565 seconds;
their maximum owned RSS was 718,680,064 bytes. Total native execution was 46
detector calls, 70 recognizer calls and 46 Tesseract calls. The 14 source holds
were preserved. No optimizer ran.

The separately sealed fresh-source manifest binds every existing crop proof,
raw detector/recognizer/TSV artifact, worker summary and closed supervision
receipt. These raw artifact hashes are Root's post-closure seal; the worker
summary itself does not contain every raw hash. Adding crop-proof references
to a second manifest version did not rerun recognition or change the baseline.

`fresh_source_cells.py` and the optional correction-runner integration consume
those artifacts without SDK imports or image decoding. A successful one-page
parser/scorer/writer path was followed by the frozen 38-page paired evaluation:
148/256 before and after, with zero fixes, losses, new wrong values or labelled
absence false fills. Native execution success therefore did not establish an
endpoint accuracy gain. Full-484 evaluation and default adoption were withheld.
