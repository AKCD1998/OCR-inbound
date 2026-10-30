# Experimental GLM-OCR component

This component adds an automated multimodal reader before the legacy table/header
acceptance gates. It retains the existing OCR engines and saved raw evidence.
It is opt-in and does not change production defaults.

The isolated HQ runtime uses llama.cpp/GGUF. Model labels such as `0.9B` and file
sizes are not runtime memory measurements. Validate decoder, vision projector,
KV cache, intermediate buffers and the owned process tree together. Do not
increase a resource cap implicitly or keep models resident between batches.

## Stages

1. `glm_prepare_worker.py` materializes pinned public artifacts and an isolated
   environment. It verifies archive paths and all selected hashes.
2. `glm_quantize_worker.py` can derive a smaller projector using the selected
   backend. A requantized projector is a lossy experimental derivative, not an
   official release. Tensor-name/shape validation does not establish accuracy.
3. `glm_native_worker.py` consumes a source-only plan, records the exact prepared
   image, request and raw response, and closes its server child after a short
   batch. Run it under the existing shared-lock resource supervisor on HQ.
4. `glm_evidence.py` keeps printed model output separate from business-corrected
   values. It checks source association and independent cached text evidence.
5. `glm_read_manifest.py` verifies the actual closed native run and its input and
   output lineage. The correction runner receives a static recipe plus a dynamic
   read manifest; growing the manifest must retain earlier records verbatim.

Missing headers or an unclassified document must not prevent a source page from
reaching the experimental reader. That permission does not approve receipt into
stock or permit an unverified field revision.

## Evidence and scoring

- Keep the source image/page/region, model and projector hashes, backend files,
  prompt, configuration, prepared input and raw answer.
- Preserve before/after for proposed changes, including nonempty existing values.
- Model confidence is not an OCR confidence measurement. Do not invent glyph
  coordinates from generated table markup. Text spans and measured cached boxes
  have separate provenance.
- A truncated or incomplete response is held. A returned table is not proof that
  all printed rows were transcribed or that downstream fields improved.
- The original per-page `recognition_run` describes the retained baseline only.
  Report upstream automated GLM calls separately and truthfully; parser-stage
  model calls may be zero while upstream calls are nonzero. The legacy provenance
  gate alone does not audit the new reader.
- Use the same frozen baseline, reference and evaluator. Complete a real tiny
  parser/evaluator/writer run before the fixed pilot. A full run requires a safe
  positive pilot result; report fixed, lost, newly wrong and labelled-absence
  false fills separately. Unlabelled fields are not verified correct.
- Development-set results are not unseen accuracy. Test new documents against a
  frozen version before using those documents for training.

## Measured status

The first HQ experiment on 30 October 2026 materialized its isolated runtime and
requantized the projector successfully. The first model canary reached its
240-second load deadline before any image-reading HTTP request. Its owned-tree
peak was 755,826,688 bytes, below the unchanged 1 GiB cap, and the supervisor
confirmed child closure and shared-lock release. There is **no GLM reading-quality
or downstream accuracy result from that attempt**. A load timeout is not evidence
of a Thai recognition failure or a proven inference memory fit.

Runtime receipts and private source documents stay outside Git. Consult the
local current-status index for newer experiments; do not restart a failed run or
infer success from a scheduled-task status.
