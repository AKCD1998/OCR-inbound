# Source-bound quantity and unit corrections

This isolated experiment revises existing quantity or unit fields, including
nonempty values. It does not activate an application adapter or change the
frozen reference, scorer, source OCR, model weights, document identity, product
identity, lot, receiving role, or row order.

The bridge requires literal printed headings, two established source-bound
product rows, unambiguous native body cells, and independent cached readers at
the existing 0.95/0.70 confidence gates. Whole-token native ownership retains
the 0.8 minimum overlap and 0.2 maximum competing overlap. No images are read
by the assistant; this arm makes no new recognition or model calls.

Each field must have its own complete source proof. A low-confidence companion
field does not invalidate an independently proven correction. A transaction
that vacates another field's mistaken token ownership still requires every
dependent correction to pass; otherwise the dependent revisions are withheld.
The previous field and its source evidence are retained for final review.

`correction_eligibility.py` distinguishes exact field-conflict diagnostics from
receiving semantics on a disposable copy. Diagnostic candidate values never
supply recognition answers. Free goods, sets, returns, nonreceipt rows,
unknown relationships, and malformed payloads remain protected; the canonical
row metadata is preserved.

Short centered headings can make midpoint column boundaries cut a longer
product name. The optional `SOURCE_HEADER_TEXT_GAP` route requires the entire
established name between both adjacent literal heading-text edges. Every
competing heading's whole box must remain outside that gap. This is a source
association proof, not a claim about physical cell borders or ownership of a
native header cell. Native ownership of the body name remains mandatory.

`correction_guard.py` independently verifies actual source tokens, headings,
geometry, row identity, reader independence, foreign token ownership, and each
explicit before/after snapshot. Projection copies only admitted fields back
onto the unchanged original-frame canonical page.

`correction_runner.py` separates parser and evaluation access. A parser panel
contains only page numbers and source hashes. Reference answers are available
only to the scoring stage. The source dependency closure is pinned, including
the eligibility module, and source-only tests exercise refusal paths and a
complete synthetic writer flow.

The full evaluation gate requires a completed, positively gaining pilot with
zero measured exact losses, new wrong values, or absence false fills; two
actual original-scorer calls, a verified result writer, and physical child
closure under the original serial resource supervisor are also required. A
new source revision invalidates the earlier pilot receipt.

## Evaluation scope

The fixed control is the retained 323/585 arm, not the distinct fresh-reading
324/585 arm. The 585 product labels cover 105 of the 484 images; 191 images have
some reference and 293 have none. Processing all images does not establish
accuracy for all their contents. The 602/329/57 scopes overlap and must not be
summed. All 18 absence labels concern lots, so their false-fill result does not
measure quantity/unit false fills on unlabelled data.

The first pilot used a prospectively frozen 20-page panel and all its 168
product-present labels. A later panel was frozen as the union of that entire
panel and every baseline page containing a nonempty wrong quantity/unit value:
38 pages, 256 product-present labels, and all 49 such wrong fields. No page was
chosen or removed using candidate outcomes. Cached OCR, native observations,
reference, scorer, and confidence thresholds stayed fixed. The bounded parser
panel limit is 64 pages; this does not change the full 585-label metric.

Results concern a known, nonrandom development set with zero independently
verified gold labels. New documents must test the frozen candidate before
becoming training data.

## Actual correction experiment results

| Arm | Pilot | Product exact before → after | Accepted field revisions |
| --- | --- | --- | --- |
| V1 source corrections | 20 pages | 94/168 → 94/168 | 0 |
| V3 diagnostic eligibility and description text gap | 20 pages | 94/168 → 94/168 | 0 |
| V4 independent field proofs and whole-heading ambiguity guard | 20 pages | 94/168 → 94/168 | 0 |
| V5 same bridge, complete baseline wrong-case coverage | 38 pages | 148/256 → 148/256 | 0 |

V2 was prepared and diagnosed from cached source data, without an HQ pilot.
Each actual pilot used two original-scorer calls, verified writes, and closed
all owned children under the original resource supervisor. Measured exact
losses, new wrong values, and labelled absence false fills were zero. The
eligible proposals observed on the original panel already matched its saved
printed-source values; removing adapter barriers did not establish a gain.

The positive-pilot gate therefore withheld the full 484-image correction arm.
These results support **no adoption** and a stop to further bridge relaxation.
Synthetic tests demonstrate correction capability and refusal behavior; they
do not establish improved document accuracy. The next experiment needs new
source evidence at the remaining reading or geometry boundary, rather than a
weaker threshold or a changed reference.

Current actual pilot and full-run results are recorded in the private run
receipts and living status documents. No experimental revision is automatically
adopted in production.

## Source cell and document components

Two optional, explicitly pinned components extend the same correction runner:

- `document_source_admission.py` checks literal whole titles and source table
  structure before admitting an otherwise unclassified document. Negative titles
  remain vetoes even when an older parser assigned their tokens to fields.
- `source_cell_association.py` derives logical cell regions from actual table
  regions or literal headings and existing source-matched rows. These are content
  regions, not claims of measured physical cell borders. All canonical neighbours,
  including protected or unknown rows, remain negative ownership barriers.

The guard reconstructs each source proof independently, preserves whole reader
detections and same-baseline ownership, and applies only accepted field changes.
Overlapping route proposals are deduplicated; disagreement abstains. The
original document, row order and non-admitted fields remain intact. These
components neither read new image text nor change the saved OCR cache.

Cell-only, document-only and combined arms each completed the frozen 38-page
paired evaluation: **148/256 before and after**, with zero fixes, losses, new
wrong values or labelled absence false fills. All owned children closed and
the shared lock was released. Classification eligibility alone and additional
cell proposals did not improve endpoint fields. The full 484-image gate stayed
closed for all three arms; they are experimental and are not adopted defaults.
