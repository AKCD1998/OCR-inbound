# Verification and continuation — 28 October 2026

The code-only branch is `codex/document-ai-prototype-20261028`. Private documents,
catalogue, identity teachers, SQLite stores, OCR outputs and checkpoints remain
outside Git. The repository is public; Cloud can run the synthetic demo and
portable tests without these inputs. No production setting was activated.

## Verified code

- Final clean staged-tree checkout: **376 tests passed, 13 existing private-evidence skips**.
- Source compilation and browser JavaScript syntax passed.
- Existing secret/catalogue/default-live-flag scan passed; package build and
  package self-check/worker/launch smoke passed.
- GitHub Actions on source commit `063e93b` passed both the existing CI and new
  Document AI workflow (Ubuntu and Windows portable tests).
- Real-browser synthetic PDF flow passed approve → correct → completeness
  attestation → JSON download. Raw, normalized, catalogue and human-final
  authority remain separate. No ERP posting occurs.

The full-suite runs exposed Windows HTTP early-close problems for invalid
filenames and rejected JSON MIME types. The final code consumes size-admitted
bodies before those semantic checks. All errors flush the response, half-close
the write side, then discard at most 64 KiB for at most 0.25 seconds, following
[RFC 9112 section 9.6](https://www.rfc-editor.org/rfc/rfc9112.html#section-9.6).
Origin and size admission still precede processing. Split-body and rejected-origin
regressions verify complete JSON responses without retries or increased client
timeouts. The final 376-test result includes these repairs and the exclusion gates.

## Actual HQ ingress proof, separate from fixture replay

A generated synthetic one-page PDF was uploaded through the real local HTTP
endpoint. The durable transport published a new scheduled HQ job; the original
shared lock and owned-process/resource checks admitted it. HQ rendered the PDF,
ran Tesseract TSV in two bounded modes, parsed the source tokens and returned
hashed rendered assets and proposals to the local review store.

| Actual observation | Result |
| --- | --- |
| Worker elapsed time | 59.922 seconds |
| Peak owned process-tree RSS | 250,466,304 bytes |
| Minimum free RAM | 3,456,970,752 bytes |
| Native worker exit | 0 |
| Rendered pages / proposed goods / page context rows | 1 / 2 / 1 |
| OCR calls / optimizer updates / assistant transcription | 2 / 0 / 0 |
| Final review state | Three rows pending; export disabled |
| Worker closure / shared lock release | Both confirmed |
| Returned proposal bytes vs supervisor summary SHA | Match |
| Duplicate upload and completed-job reattachment | Reused original document/job; result unchanged; no new reader launch |

This proves the transport/reader/parser/review path works; **it is not a real
invoice accuracy measurement**. The generated document's answers were not
injected into the actual HQ OCR worker. The demo fixture replay is a different
mode and is labelled separately.

The two proposed goods rows are not two verified correct rows: this synthetic
check exposed a footer proposed as a product and a genuine row omitted. The
review interface now supports explicit, audited non-product exclusion as well
as missing-row entry. A real browser excluded the footer with a reason and added
the generated fixture's missing row: four rows total, two goods, one context and
one excluded row. Three remained pending and export stayed disabled. The excluded
OCR text remained intact; the manually added row kept raw OCR null and a distinct
attestation authority. No reader was rerun for these review actions.

Exclusion never certifies the excluded values as correct. Only approved/corrected
goods enter `goods_rows`; context and exclusions have separate audit collections.
An all-excluded or context-only document cannot export a goods handoff.

## Model decisions

The first product-ranker training round is retained but **HOLD**: test first-rank
accuracy rose from 75 to 82 of 104 known identities, while validation fell from
51 to 49 of 82 and wrong review proposals across partitions increased from 6 to
10. See the separate learning report for the actual 437 examples, 69,920 updates,
274 checkpoints and supplier/variant failure analysis. This is product identity
learning, not new glyph recognition, and it does not change the 484-page OCR score.

PP-DocLayout and Docling stopped during startup/dependency preparation, and Qwen
was rejected by the existing memory budget before download. Their endpoint
comparisons are **unmeasured**, not zero regressions or zero-percent accuracy.
See `../experiments/document_ai/TRIAL_RESULTS.md` for retained evidence and the
next runtime diagnostics. Do not repeat the same attempts without a concrete fix.

The retained 323/585 component baseline, separate fresh-reading 324 result, raw
OCR and references were not replaced. New documents must test a frozen model
before entering training. The web prototype is loopback, with named local
attestations; organization authentication/roles and a real ERP adapter remain
future work. Reviewed supplier-document facts do not automatically assert a
physical receipt at a branch.
