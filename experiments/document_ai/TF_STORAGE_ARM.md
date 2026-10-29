# TableFormer storage experiment

This isolated experiment addresses a reproducible memory limit in the pinned
`docling-ibm-models` 4.0.4 TableFormer implementation. It does not train new
weights, change OCR text, or activate a production pipeline.

## Change and isolation

The original `TableModel04_rs.predict` keeps two kinds of last-row feature views
in `tag_H_buf`. Each view can retain the storage of its growing decoder output.
The experiment adds `.clone()` to exactly those two append arguments. The source
proof requires all other bytes and the normalized AST to remain identical.
Weights, prediction limits, beam settings and the table backend are unchanged.

The installed SDK remains read-only. A loader serves one exact module from a
separate, hash-checked source file and records its actual origin before model
inference. It verifies the final compiled buffer as well as the source proof.
The ordinary cache guards continue to apply to other modules.

`docling_storage_worker.py` remains the actual admitted entry point. It records
the separately pinned native delegate and implementation receipt; it does not
pretend to be the original worker or bypass its admission check. Layout stages
delegate without installing the TableFormer variant and explicitly record that
the variant was not applied.

## Measured milestones

The synthetic probe uses Torch 2.6 CPU, one thread and deterministic tensors. It
does not import the SDK, load model weights, read images or perform optimizer
updates. For 64 growing outputs of width 512, the retained unique storage was
4,259,840 bytes for views versus 131,072 bytes for copies. Last-row values,
downstream concatenated values, signed zero, infinities and NaN payload bits
were identical. These are tensor-storage measurements, not whole-process RSS
or a proof of end-to-end model equivalence.

A dense invoice ROI exceeded the existing 1 GiB process-tree RSS cap in both a
fresh original process and a separate no-optional-cache trial. With the isolated
two-clone implementation, two fresh model calls returned successfully with
peaks of approximately 708 and 712 MB. Their complete page-result JSON files
were byte-identical. The first parent run remains failed because its copied
summary predicate incorrectly expected no cache; a second prospectively correct
run completed and closed successfully. No failed receipt was rewritten.

The new implementation then passed an actual tiny control/candidate/evaluator/
writer run. The uniform, fresh 484-image experiment completed on 29 October
2026: all 16 native children closed successfully, with 484 layout model calls
and 184 table model calls. Table-stage processing covers all 484 images,
including images with no detected table. No old geometry was retained in this
implementation arm. Native elapsed time was 2,377.235 seconds; peak owned
process-tree RSS was 842,801,152 bytes under the unchanged 1 GiB cap.

Both full parsers and the paired evaluator/writer then completed and closed.
The frozen product-label score was **323/585 to 323/585 (55.21%)**. Fixes,
prior-correct losses, new wrong values and new absence false fills were all zero.
The evaluator ran twice and verified saved output by readback. There were no
new text OCR calls, training samples, optimizer updates or training checkpoints.

The candidate adapter made zero field changes. Its 484 page-level statuses
were 325 `NO_USABLE_NATIVE_CELL_TOPOLOGY`, 34
`NO_ESTABLISHED_INVOICE_SOURCE_FRAME`, and 125 `ABSTAINED`. These describe
pipeline admission outcomes, not independently verified errors in every model
table or every field on those pages. The memory repair makes this experiment
finish safely; the current adapter has not demonstrated a downstream score
gain. The component remains experimental and is not activated in production.

## Evaluation boundaries

The component control remains the retained RAW plus frozen parser baseline of
323/585. The 585 product labels cover 105 images, while the source inventory has
484 images. A complete processing run is not a measurement of every word or
field on those images. Labels are a known, nonrandom development set with no
independently human-confirmed gold set. Unknown labels are excluded rather than
counted correct.

Use the same reference, scorer, prior-correct identities, absence checks and
company axes. Report fixes, previously correct values lost, new wrong values
and false fills. Keep native geometry coverage separate from field scores.
The all-fresh implementation experiment does not relabel retained results from
older workers. New documents must test a frozen version before entering training.

## Sources and checks

- `tableformer_storage_arm.py`: exact two-site source proof and isolated loader.
- `tableformer_storage_probe.py`: bounded synthetic value/storage probe.
- `docling_storage_worker.py`: admitted delegate and actual-origin records.
- `storage_arm_publication.py`: preparation of the new profile, actual tiny and
  all-fresh full configuration; it cannot launch an HQ job itself.
- `tests/test_document_ai_storage_arm.py` and
  `tests/test_document_ai_storage_publication.py`: source, admission, loader,
  provenance and preparation regressions; they need no Torch or SDK installation.

Model work still uses the existing CPU, RAM, shared-lock and owned-process
controls. Native SHA values describe actual published bytes; Git line-ending
normalization can produce a different blob hash. Reuse verified assets and read
actual publication receipts. A path, report or newline change does not justify
reading the baseline OCR again.

Sources: [pinned SDK release](https://pypi.org/project/docling-ibm-models/4.0.4/),
[PyTorch tensor views](https://docs.pytorch.org/docs/2.6/tensor_view.html).
