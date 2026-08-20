# Codex Handoff — OCR Inbound Invoice Intelligence System

You are the tech lead picking up an existing, working system. It is NOT a greenfield
project. Your first job is to READ, not to write. Do not propose architecture until you
have read the constitution document.

## 0. Where the code lives

The repo lives on a Windows Server 2019 box reachable over Tailscale:

    Host:   server (100.90.166.72)
    Path:   C:\Users\Administrator\Desktop\OCR inbound
    Branch: main (last commit 0dd5050 "Add OCR stages viewer, selected pages builder,
            and Project Bible")

Access it however you have set up (SSH over Tailscale, an SMB mount, or a synced clone).
If you cannot reach it, stop and say so — do not reconstruct the design from this prompt
alone. This prompt is a map, not a substitute for the source.

Note: a large `.venv/` sits in the repo root. Exclude it from every recursive grep or it
will dominate results.

## 1. Read in this order

1. `docs/PROJECT_BIBLE.md` — AUTHORITATIVE. Explicitly the "constitution": any proposal
   that conflicts with it is wrong by default; if reality changed, amend the Bible first,
   then implement. Read section 1 (the "answer key / exam papers / student / supervisor"
   metaphor) before anything else — it encodes the whole ML strategy.
2. `docs/DESKTOP_APP_ARCHITECTURE_TH.md` (1308 lines, Thai) — the full target architecture.
3. `docs/REVIEW_APP_DESIGN_BRIEF_TH.md` (518 lines, Thai) — the human review UI spec,
   including review grid columns and the correction/learning-dataset requirements.
4. `docs/IMPLEMENTATION_STATUS.md` — what is actually built and verified vs. what is not.
5. `docs/adr/ADR-001..ADR-009` — nine accepted decisions. These are binding constraints,
   not suggestions. The load-bearing ones:
   - ADR-005 ADA read-only SQL / UI write — never write to the POS DB directly
   - ADR-006 prediction-before-display — a match must be persisted before a human sees it
   - ADR-007 human-gated save — one-use token bound to run/revision/preflight/actor/expiry
   - ADR-008 production/staging isolation
6. `docs/ACCEPTANCE_MATRIX.md`, `docs/EXTERNAL_BLOCKERS.md`, `docs/STAGING_RUNBOOK.md`.

The `*_TH.md` documents are in Thai. Read them in Thai; do not work from a summary.

## 2. What the system is

A pharmacy chain in Thailand receives Thai/English supplier invoices as PDFs. The system
ingests them, OCRs them, extracts line items, resolves each line to a product in the
existing POS/ERP product master (ADA / AdaAcc, ~6,500 items), routes everything through a
human reviewer, and only then produces a goods receipt (ใบรับสินค้า).

It is deliberately NOT a generic OCR platform. Domain knowledge — the product master, the
ingredient/synonym layer, the category taxonomy, supplier purchase history, and
CEO-approved historical receipts used as ground truth — is the core asset. Accuracy beats
autonomy.

## 3. Pipeline layers

- **Layers A–E** — `ocr_feasibility.py` (repo root, ~5000 lines, monolithic, standalone).
  Preprocessing, multi-engine OCR, table band/row/column detection, column semantics
  (Layer D), line-item extraction (Layer E). Each layer writes immutable artifacts under
  `ocr_runs*/` and has its own human review gate (`tables/*_review_decisions.json`).
  Layer E output is only consumed if its decision is `accept` or `accept_with_flags`.
- **Layer F — product matching** — `src/ocr_inbound/matching.py`. Deterministic, tiered,
  master-only.
- **Ready / Save** — validation, duplicate detection, revision snapshot, human-gated save
  into ADA via UI automation (never a direct SQL write).

Layers A–E are treated as frozen and invoked through a versioned subprocess command adapter
(`src/ocr_inbound/ocr_adapter.py`, contract `ocr-inbound-artifact.v1`). Do not refactor
`ocr_feasibility.py` casually.

## 4. Application package — `src/ocr_inbound/` (~2200 lines, stdlib only, Python 3.11.9)

| File | Role |
|---|---|
| `matching.py` | Layer F product matcher |
| `db.py` | SQLite repository, single-writer, WAL |
| `migrations/0001_initial.sql` | schema |
| `ada_read.py` | read-only mirror of the POS master into a local cache DB |
| `ada_automation.py` | UI automation writer into ADA |
| `ocr_adapter.py` | Layer A–E command adapter + artifact importer |
| `validation.py`, `money.py` | exact validation; money is minor-unit integers only |
| `service.py`, `web.py`, `workers/` | orchestration, loopback web UI, worker processes |

No third-party runtime dependencies. PySide6 and .NET/WPF were evaluated and rejected
(ADR-002: Thai-first local web UI bound to loopback).

## 5. Layer F in detail — read `src/ocr_inbound/matching.py` closely

`ProductMatcher._predict()` builds source text from supplier SKU + final description + raw
OCR text, normalizes it (NFKC, uppercase, strip to digits / A-Z / Thai ก-๙), then resolves
in tier order:

| Tier | Method | Auto-confirmable |
|---|---|---|
| EXACT_CODE | internal code regex `IC-\d{4}` / `630\d{4}` | yes |
| EXACT_BARCODE | supplier SKU to barcode | yes |
| ACTIVE_ALIAS | per-supplier approved alias | yes |
| EXACT_NAME | unique normalized-name hit | human confirm |
| FUZZY_SUGGESTION | SequenceMatcher >= 0.45, +0.05 if in supplier purchase history, top 5 | human confirm |
| UNRESOLVED | nothing resolved | human must choose |

Invariants you must not break:

- The system can never select a product absent from the master (`OUT_OF_MASTER_BLOCKED`).
- Predictions are persisted with input hash, ruleset version, candidate set, and evidence
  BEFORE display (ADR-006).
- Unit codes are validated against that product's `product_units`; ambiguous resolves to
  null, never a guess.
- Corrections create supplier alias *candidates* requiring approval — never auto-activated.
- `RULESET_VERSION` must be bumped whenever matching behavior changes.

## 6. Known gap you are likely to be asked about: lot number and expiry date

Fully specified, completely unimplemented. Verified by reading the source:

- `docs/REVIEW_APP_DESIGN_BRIEF_TH.md:177-178` lists Lot number and Expiry date as review
  grid columns; line 217 lists them as reviewer-correctable; line 393 puts `lot/expiry` in
  the Document Line entity.
- `docs/DESKTOP_APP_ARCHITECTURE_TH.md:749` defines the rule
  "expiry not before invoice date เมื่อมี expiry".
- BUT: `document_lines` in `migrations/0001_initial.sql` has no lot or expiry column.
- `LAYER_D_LABEL_VOCABULARY` at `ocr_feasibility.py:4285` is
  `{line_number, product_code, description, unit, quantity, unit_price, amount, vat,
  discount, unknown}` — no lot or expiry label, so a lot column on an invoice classifies as
  `unknown` and is dropped.
- `LOT_RE` at `ocr_feasibility.py:2011` exists but only tags a text region as
  "lot_numbers" to steer OCR engine selection and quality focus. It never extracts a value
  into a field.
- `VersionedOcrArtifactImporter.from_existing_layer_e()` in `ocr_adapter.py` does not carry
  the fields either.

Implementing it touches four places: the Layer D vocabulary plus Thai/English keyword
patterns (`LOT`, `ล็อต`, `EXP`, `วันหมดอายุ`), two new `document_lines` columns via a NEW
migration (never edit `0001_initial.sql`), importer pass-through, and the
expiry-vs-invoice-date rule in `validation.py`. Confirm this against the source yourself
before quoting it.

## 7. Current state and hard limits

`docs/IMPLEMENTATION_STATUS.md` states: **STAGING MVP COMPLETE — PRODUCTION ACTIVATION
BLOCKED**. Scope is local Windows staging with Fake/Replay ADA only. No live ADA action, no
direct AdaAcc write, and no production save is claimed.

Test suite: 37/37 passing via `python -m unittest discover -s tests -t . -v` with
`PYTHONPATH=src`. Note the `-t .` — plain discover fails on relative imports. Staging
zipapp builds via `scripts/build_staging.py`.

`docs/EXTERNAL_BLOCKERS.md` lists what is blocked on people or systems outside the repo.
Read it before promising any timeline.

## 8. Your task

1. Read the documents in section 1, in order, from the actual repo.
2. Verify the claims in this prompt against the source — treat any discrepancy as this
   prompt being stale, and say which claim is wrong.
3. Then report back: your understanding of the architecture, which of the nine ADRs
   constrain the work in front of you, and the smallest correct change that achieves it.
4. Do not modify `ocr_feasibility.py`, do not edit an applied migration, do not introduce a
   third-party runtime dependency, and do not weaken a human review gate — without first
   proposing an amendment to `docs/PROJECT_BIBLE.md` and getting it accepted.
