# Component trial results — 28 October 2026

This is a sanitized account of actual guarded attempts on 000 HQ. Private
invoices, OCR text, process inventories, package caches and detailed receipts
remain on the authorized host. No assistant or subagent transcribed images.

**No component produced an accepted prediction in these attempts. Endpoint
accuracy is unmeasured (`null`), and none is adopted.** These outcomes do not
show that the underlying models are inaccurate: the attempts stopped before
usable model output or before their dependencies were ready.

## Actual attempts

| Attempt | Actual outcome | Time | Peak owned RSS | Minimum free RAM |
| --- | --- | ---: | ---: | ---: |
| PP-M data preparation | COMPLETE: exact publisher artifacts verified; canary/pilot plans built from retained OCR | 15.234 s | 49,963,008 B | See private resource receipt |
| PP-M canary V1 | Stopped at the 120 s deadline during SDK/model initialization; prediction was not started | 120.297 s | 281,030,656 B | 3,126,861,824 B |
| Docling data preparation | COMPLETE: Egret + fast TableFormer artifacts verified; source-only plans built | 36.562 s | 51,556,352 B | 3,412,070,400 B |
| Docling isolated CPU environment V1 | FAILED: binary dependency resolution timed out after 600 s; environment not accepted | 637.922 s including setup/cleanup | 726,077,440 B | 3,169,611,776 B |
| PP-M direct SDK diagnostic V2 | Stopped at the same 120 s deadline, before the Paddle SDK import phase | 120.313 s | 62,578,688 B | 3,465,793,536 B |
| Qwen3-VL-2B | Resource preflight rejected the selected native BF16 model before downloading/importing it | Metadata only | No model loaded | No memory-limit relaxation |
| PP-L | Registry prepared; inference not executed because the shared runtime prerequisite failed in the smaller PP-M arm | Not run | Not measured | Not measured |

All supervised attempt families were confirmed closed before releasing the
shared model lock. No attempt hit the RAM floor or RSS limit. No paused training
task was restarted, and no production/default/Ada/StockDay setting was changed.

## What the diagnostics establish

The PP-M V1 attempt reached initialization but created no prediction-start
receipt and no geometry result. V2 changed the trial entry point to the direct
static PaddleX API already used by the earlier audited SLANet worker, disabled
MKLDNN and added phase receipts plus a bounded automatic stack dump. It still
stopped in `cv2`/NumPy import, before the Paddle SDK phase. The retained stack
shows `importlib.get_data` while loading NumPy's library package. This identifies
runtime import/file-loading as the observed bottleneck; it does not by itself
prove a disk, antivirus or network root cause. No broad system changes were made.

Docling's two model artifacts were successfully materialized with their pinned
hashes. A new isolated venv was created outside the frozen Paddle runtime.
Dependency resolution downloaded a 619,392,861-byte CPU Torch wheel but did not
complete within its existing 600 s bound. A read-only observer saw low process
RSS and no CPU-time increase over its one-second sample. The partial environment
and archive were retained, not accepted or reused. Torch/Docling model inference
was not attempted. No package was installed into the frozen runtime.

Qwen's native weight artifact is 4,255,140,312 bytes, exceeding the approved
1,073,741,824-byte owned RSS cap before runtime overhead. Publisher metadata
reports 2,127,532,032 BF16 parameters; an idealized four-bit representation of
all parameters alone would leave less than 10 MB under that cap. No unverified
quantized substitute, memory-cap increase or model download was attempted.

## Benchmark status

The retained component control remains **323/585**, from FINAL164 plus the saved
C4 canonical output and the same raw OCR. The separate fresh-reading 324 result
is not substituted for it. No new baseline recognition was run for these trials.

```json
{
  "endpoint_status": "NOT_EVALUATED",
  "completed_layout_prediction_calls": 0,
  "completed_table_prediction_calls": 0,
  "new_text_OCR_calls": 0,
  "source_image_decodes_in_native_attempts": 0,
  "endpoint_comparisons_completed": 0,
  "endpoint_gain": null,
  "fixed_fields": null,
  "previously_correct_fields_lost": null,
  "new_wrong_values": null,
  "false_fills": null,
  "production_adoption": false
}
```

Zero completed prediction calls is not a zero-percent accuracy result. Null
comparison counters are not evidence of zero regressions. With no usable canary
geometry, a full 484-page model rerun or endpoint comparison would not provide
the requested component contrast and was withheld.

The plan-builder schema check accounted for all 484 retained cache pages,
73,082 primary machine tokens and 24 machine supplier keys. It recorded 31
invalid/out-of-frame tokens as excluded without clipping them. These are input
inventory statistics, not accuracy measurements or verified company identities.

## Casebook disposition and next decision

Record these cases under runtime import/startup and dependency resolution.
Character recognition, table quality, row/column association, quantity, unit and
acceptance quality remain **unassessed**, rather than being classified as model
recognition errors. The source-selected canary has a machine company hint; that
hint must not be treated as proof that a particular supplier's document format
caused the runtime failure.

Stop repeating the same model attempts. Investigate the retained import stack
and package-resolution wait first, then use one bounded canary after a concrete
runtime fix. A verified local wheel/cache can be investigated without downloading
the model artifacts again. Useful geometry must still pass a real parser → frozen
scorer → result-writer preflight before a full endpoint comparison. The existing
reference, thresholds and 585/602/329/57/18 cohorts remain unchanged.

## Frozen execution evidence

Private receipt identifiers:

- `OCR_DOCAI_PP_DATA_20261028_V1` / `components/pp-data-v1`
- `OCR_DOCAI_PP_CANARY_20261028_V1` / `components/pp-canary-v1`
- `OCR_DOCAI_DOCLING_SETUP_20261028_V1` / `components/docling-setup-v1`
- `OCR_DOCAI_PP_CANARY_20261028_V2` / `components/pp-canary-v2`

Relevant SHA256 pins:

- Public model registry: `adb937d4f49ab45d43ce1536097ce04602f106771b013b71dc91c2ad0322cd99`
- PP-M V1 worker: `c71189cd0e50affc3a4fd76ca843e8252906d4e0b804aa36933c9f3a4d35b63b`
- PP-M V2 worker: `c0f9ed872041f11c21ba41f3651914939a5284ac44161fa78f999d63d2cf4efc`
- Current serial supervisor: `8e99990398ec1933ca952bbf523f9960087aaa59e5b27a0880e61255fa3535a5`
- Isolated dependency installer: `f5184e55a55ca9dd1fb749a226daf6aba950b323668e28af3bb310f97861cdf0`
- CPU dependency specification: `a20512ad0c001cf8c0498b9e562bc8ca8f9cc44a7bb4384f6e7ab016c670427e`

The current component contract suite passes nineteen model-free tests, including
the training RAM gate, whole-token ownership, exact source-frame rotations,
artifact integrity and resource-receipt preservation after a malformed worker
summary. These tests validate contracts, not OCR accuracy.

## 29 October continuation: actual Docling model execution

This section supersedes the earlier runtime-only outcome for Docling. The
earlier failed attempts and their receipts remain unchanged.

The isolated CPU runtime was repaired and its native ABI verified: Torch
2.6.0+cpu, torchvision0.21.0+cpu, NumPy2.2.6, OpenCV4.12.0 and
docling-ibm-models4.0.4. The frozen Paddle runtime was not modified.

| Actual attempt | Returned model results | Time / peak owned RSS | Outcome |
| --- | --- | --- | --- |
| Egret canary, one page | One layout result; no table detected | 340.187s /555,827,200B | Complete, physically closed |
| Egret source-selected four-page pilot | Four layout results; one table region | 162.968s /695,758,848B | Complete, physically closed |
| TableFormer, native matching | One prediction started; no returned result | 79.765s /544,161,792B | Native access violation; physically closed |
| TableFormer, native matching disabled | One prediction started; no returned result | 52.672s /566,747,136B | Native access violation in CNN encoder/convolution; physically closed |
| TableFormer, matching disabled and ATen CPU backend | One actual neural table prediction returned; four pages routed | 36.328s /602,148,864B | Complete, physically closed |

The last attempt returned seventy content-envelope cells on the page with the
detected table. Forty-one retained whole OCR tokens had unique cell ownership;
the ownership check found zero ambiguous tokens and zero rejected boxes. These
counts do not establish correct product rows, physical cell borders or field
accuracy. The other three source-selected pages had no detected table and made
no TableFormer model call.

The failure code was Windows0xC0000005, with no RAM/deadline stop. The retained
Windows fault report identifies python311.dll; the second attempt's coherent
stack reaches the TableFormer CNN encoder and Torch convolution before cell
matching. [Upstream issue170](https://github.com/docling-project/docling-ibm-models/issues/170)
describes a similar failure class, but it does not prove the same cause here.
The documented no-matching route alone did not fix our failure. The ATen
fallback succeeded once under the unchanged CPU1/RAM policy; this is not proof
that all future inputs are safe.

Native table options for the successful attempt are explicit:

```json
{"do_matching": false, "evaluation_predictions_supplied": false,
 "cpu_backend": "aten", "mkldnn_enabled": false}
```

No SDK source file, model weight, raw OCR answer, reference or acceptance
threshold changed. Actual backend flags, CPU binding, native NumPy/Torch
roundtrip and first-call CNN/transformer boundaries were recorded. There were
zero optimizer updates and zero new text-recognition calls.

The paired endpoint comparison remains **not evaluated** at this checkpoint:
gain, fixed fields, lost correct fields, new wrong values and false fills are
null. The next gate is the real parser/control/candidate/scorer/writer tiny
preflight on the positive table page, followed by the exact484-source full
comparison against the frozen323/585 control. Full processing is not yet
claimed in this section. This is the already-used development set.

The subsequent full attempt completed and physically closed its first64-page
layout shard (224.391s; peak770,797,568B). Its first table process then crashed
during Torch import, before the ABI/backend/model phase, with no completed
TableFormer result (114.578s; peak230,240,256B). The full result is failed and
partial, not a484-page result. The closed layout shard retains its original
worker identity and is eligible for explicit provenance-checked reuse.

That closed layout shard also exposed a separate routing limit: one page had
five detected table regions while the worker imposed an arbitrary four-table
page cap. A prospective fix routes every valid detected table up to the exact
pinned Egret configuration's300-query bound. Per-call120s, per-stage2,400s,
CPU1, RAM thresholds and owned-child cleanup remain unchanged; tables are not
dropped or clipped to avoid the cap.

The import crash's stderr contains an incomplete periodic thread dump before
the native exception. CPython reports include
[a3.11 thread-dump crash](https://github.com/python/cpython/issues/116008) and
[a later code-metadata race](https://github.com/python/cpython/issues/158200).
These support testing a diagnostic race as a hypothesis, not identifying the
cause of this machine's crash. The prospective worker retains fatal exception
capture and phase evidence, removes only asynchronous repeating thread dumps,
and runs two bounded fresh-process canaries before another full attempt.

## Cache validation and retained progress

The first fatal-only repeat timed out during its unchanged480-second SDK startup
budget. A separate, model-free warmup then produced a source-bound bytecode cache
and passed the native ABI check (66.344s; peak363,057,152B). Two fresh cached
TableFormer canaries closed successfully in21.094s and18.750s. Each returned one
table prediction,70 cells and41 whole owned tokens; these are execution counts.
The real tiny control/candidate/parser/scorer/writer path completed under the
same frozen profile. It remains a diagnostic result, not a full585-field score.

The next full attempt completed and closed its first64-page table shard:
35 returned table calls,287.859s, peak709,832,704B, exit0. All five detected tables
on the page that exceeded the old four-table cap were routed and returned.
The following layout child then exceeded startup480seconds. Its phase receipts
show460.5seconds spent eagerly verifying all2,390 source/bytecode pairs before
the CV import. The supervisor closed the failed child and released its lock;
the full result is failed and partial, with no endpoint accuracy claim.

The next performance change verifies the exact source and bytecode bytes as
CPython actually loads them, including the paired source when a valid bytecode
timestamp would normally skip it. Unknown existing bytecode and changed bytes
are rejected. This changes verification I/O, not model weights or acceptance
thresholds. Completed64-page layout and table observations retain their original
worker and closure evidence. Reusing them must not be counted as fresh model
calls or change either original failed parent into a successful execution.

A separate queue-state defect was reproduced: PowerShell coerced a null .NET
backup-path argument into an empty string, preventing the second atomic state
write. The prospective waiter now passes an explicit null string. A real
three-write regression test exercises waiting, starting and terminal states.
The previously deployed failed waiter remains unchanged. No production setting
or frozen reference was modified.
