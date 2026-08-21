# Slice 4 Candidate Report — Automatic Page/Row Extraction

Date: 2026-08-21  
Base HEAD: `9a4fc81`  
Status: **CANDIDATE — not staged, not committed, not pushed**

## Outcome in plain language

The existing OCR evidence can now be turned into a deterministic, versioned
page artifact and opened in the authoritative staging UI. The UI shows the
full page on the left, every extracted row on the right, and highlights the
real PaddleOCR bounding box and its row together on hover/click.

This candidate is intentionally not described as “all suppliers supported.”
All ten evidence pages are processed reproducibly, but the current conservative
extractors recover product rows from four pages only. Six pages stop with
`NONE/NO_TABLE_HEADER_FOUND` rather than inventing row relationships.

## Real ten-page result

| Page | Strategy | Rows | Review required | Honest result |
|---:|---|---:|---:|---|
| 005 | TABULAR_HEADER | 5 | 0 | Berlin: five rows in printed order |
| 006 | MULTILINE_BLOCK | 2 | 2 | Unison: duplicate block retained and quarantined |
| 013 | NONE | 0 | 0 | Woothi: unsupported layout |
| 014 | NONE | 0 | 0 | Woothi continuation: unsupported layout |
| 015 | NONE | 0 | 0 | Woothi: unsupported layout |
| 019 | NONE | 0 | 0 | DKSH tax invoice: unsupported layout |
| 030 | NONE | 0 | 0 | Charoon: embedded lot/expiry layout unsupported |
| 040 | NONE | 0 | 0 | DKSH credit note: classified correctly; rows unsupported |
| 048 | MULTILINE_BLOCK | 5 | 5 | Medline: descriptions/lot/dates found; numeric columns unavailable |
| 058 | MULTILINE_BLOCK | 2 | 2 | Community Pharmacy: no product description; no fabricated match |

Bundle summary: 10 pages, 4 pages with rows, 14 rows, 9 review-required rows.

## Implementation

- `page_extraction.py`: generic tabular extraction, conservative multiline
  block adapter, field provenance, quarantine reasons, deterministic bundle
  builder, SHA-256, and atomic JSON writer.
- `build_slice4_page_artifact.py`: reads the already-existing OCR run, extracts
  ten pages, invokes only the matcher's pure `_predict` method in an ephemeral
  local SQLite environment, proves no document was persisted, and writes the
  versioned artifact.
- Staging UI: local artifact/image picker, page navigation, full-page image,
  evidence overlays, bidirectional row highlighting, field values, matcher
  result, and quarantine warnings. It does not write SQLite or ADA.
- Rows without a description are explicitly `NOT_EVALUATED`; they are never
  sent into fuzzy matching.

Generated evidence (gitignored):
`ocr_runs_staging/realinv_20260820T040631Z/page-extraction-bundle.v1.json`.

## Verification

- Focused page extraction suite: **22/22**.
- Full suite: **185/185**, exit 0.
- `safety_scan.py`: pass; zero findings; ADA catalog SELECT-only; live flags off.
- Python compile, JavaScript syntax, and `git diff --check`: pass.
- Browser verification with real artifact and ten real page images:
  - Berlin page 005 rendered five rows and five overlays.
  - Hovering overlay 3 highlighted the MONOLIN card and bounding box together.
  - Page navigation reached Unison page 006 and displayed both quarantine rows.
  - Empty-description row displayed `Matcher: NOT_EVALUATED`.
- Screenshot: `output/playwright/slice4-page5.png` (local test evidence).
- The only browser console error was a missing optional `/favicon.ico` (404),
  unrelated to the review flow.

## Exact intended candidate manifest

- `src/ocr_inbound/page_extraction.py` (new)
- `scripts/build_slice4_page_artifact.py` (new)
- `tests/test_page_extraction.py` (new)
- `src/ocr_inbound/web_static/index.html`
- `src/ocr_inbound/web_static/app.css`
- `src/ocr_inbound/web_static/app.js`
- `docs/DEV_LAPTOP_SETUP_LEDGER_TH.md`

Pre-existing untracked `.playwright-cli/`, `environments/`, and
`docs/HANDOFF_SLICE2_TO_NEXT_SESSION_TH.md` are excluded.

## Residual risks / what the reviewer should try to refute

1. Coverage is **4/10 pages**, not production-complete. Supporting Woothi,
   DKSH, Charoon, and Community Pharmacy needs bounded layout adapters with
   new real-evidence tests; broadening current heuristics would be unsafe.
2. Multiline layouts deliberately omit quantity/unit/prices because those
   pages lack a reliable column contract. This is safe but increases human work.
3. Matcher results use the packaged local fixture, not the live full product
   master; `UNRESOLVED` is plumbing evidence, not a real-master accuracy claim.
4. Page image selection is manual in the staging UI. Packaging/automatic
   artifact-directory resolution remains separate production work.
5. Overlay boxes are unions of real field boxes, not table-row segmentation
   polygons. They contain no fabricated coordinates, but can span whitespace.

No OCR rerun, production/shared DB access, matcher modification, migration,
commit, push, deployment, or Slice 5 work occurred.
