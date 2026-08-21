# Candidate Report — Community Pharmacy Supplier Adapter (Slice 4 continuation)

Date: 2026-08-21
Base HEAD: `9a4fc81` (unchanged)
Status: **FINAL REMEDIATED CANDIDATE — not staged, not committed, not pushed, not deployed**

**Update (same date): both of Codex's BLOCKED findings on the original candidate below are now
fixed, non-vacuously revert-checked, and adversarially reviewed. See "FINAL REMEDIATION ROUND" at
the end of this document for the complete closing packet — everything before that section is the
original candidate submission, kept intact for context.

This continues directly from Codex's completed Slice 4 candidate (ledger §35,
`CANDIDATE_REPORT_SLICE4_PAGE_EXTRACTION.md`). Scope: one new, deterministic,
supplier-identity-gated layout adapter for real page-058 evidence
(บริษัท ชุมชนเภสัชกรรม จำกัด (มหาชน) / Community Pharmacy). This is a layout
adapter, not ML training — no model, no learned weights, no scoring function
fit to data. Tests-first against real evidence throughout.

## OLD → NEW behavior

| | OLD (§35 candidate) | NEW (this candidate) |
|---|---|---|
| page-058 `extraction_strategy` | `MULTILINE_BLOCK` | `COMMUNITY_PHARMACY_CODE_TABLE` |
| page-058 rows found | 2 | 2 (same count, real content now) |
| page-058 `description` | `None`, `None` | `CODIPHEN TABLET(XIOS)` (both rows) |
| page-058 `supplier_sku` | field did not exist | `32132` (row 1), `None` (row 2 — genuinely absent from that row's own evidence) |
| page-058 `quantity` | unavailable (no description ⇒ no fields attempted) | `240.0` then `96.0`, in document order |
| page-058 `unit` | unavailable | `box`, `box` |
| page-058 `lot`/`mfg_date`/`exp_date` | unavailable | `25B031` / `07/02/25` / `06/02/28` (both rows, correct, not shifted) |
| page-058 `review_required` rows | 2 of 2 | 1 of 2 (row 2 has zero quarantine reasons) |
| Bundle summary | `row_count: 14, review_required_rows: 9` | `row_count: 14, review_required_rows: 8` |
| Berlin / Unison / Medline | unaffected | unaffected (regression-checked) |
| `_find_totals_boundary` | bounded by matching token's own y0 | bounded by its row-cluster's minimum y0 (fixes a real page-058 boundary leak; verified no effect elsewhere) |

## Root cause (proven before fixing, not assumed)

Page-058 is a **third, distinct real layout** — not a variant of the existing
multi-line-block adapter (Unison/Medline). It has its own genuine,
single-language, 5-column table header:

```
รหัสสินค้า | รายละเอิยด | จำนวน | ราคารวมภาษี | จำนวนเงิน
```

confirmed by reading the full real token dump (`ocr/paddle_th/page-058.json`)
before writing any code. Each product prints as a data row
(code/description/quantity+unit/price/total) **immediately** followed by a
fused `Lot ... Mfg ... Exp ...` line — a simpler, different pairing rule than
Unison/Medline's shape (which has an extra generic-ingredient-name row in
between, requiring a lookback search). The old multi-line-block adapter's
10-digit internal-code heuristic never found a code row here because there
isn't one shaped that way to find — not a bug in that adapter, a genuinely
different document.

## Implementation

- **`src/ocr_inbound/page_extraction.py`**:
  - Generalized `_find_column_bands` into a reusable `_find_header_band(tokens, keyword_map, min_distinct, band_tolerance)` (identical behavior for the existing Berlin path — same defaults, same tests still pass).
  - New `_community_pharmacy_code_table_rows()`: gated by BOTH a real supplier-identity text marker (`ชุมชนเภสัชกรรม`) AND this table's own header (own keyword map, `min_distinct=3`). Pairs each data row with the row immediately below it when that is a fused Lot/Mfg/Exp row (reusing the existing `_LOT_MARKER_RE`/`_DATE_FINDALL_RE` primitives). Assigns fields via real column X-band overlap. Splits fused `"240.00 box"` into quantity/unit via a generic number-then-word regex. New `supplier_sku` field, added to all three strategies for schema consistency, routed only into the matcher's own `line["supplier_sku"]` contract — never concatenated into `description`/`raw_ocr_text`.
  - Fixed `_find_totals_boundary` to bound by a matching row-cluster's minimum y0, not a single token's y0 (real page-058 bug: the totals label token sits a few px below its own numeric value).
- **`tests/test_page_extraction.py`**: new `CommunityPharmacyAdapterRealPageTests` (9 tests) + `CommunityPharmacyMatcherIntegrationTests` (1 test, real `AppTestCase` bootstrap). Removed the now-obsolete page-058-under-`MULTILINE_BLOCK` test (that page is no longer classified that way).
- No changes to `matching.py`, `scripts/build_slice4_page_artifact.py`, or any web_static file's logic beyond what §35 already shipped (this candidate did not need to touch the UI — it is purely data-driven from the artifact).

## Exact file manifest (this candidate's changes only)

- `src/ocr_inbound/page_extraction.py` (modified — new adapter + shared helper + totals-boundary fix)
- `tests/test_page_extraction.py` (modified — new/replaced tests)
- `docs/DEV_LAPTOP_SETUP_LEDGER_TH.md` (modified — §36 appended)
- `CANDIDATE_REPORT_COMMUNITY_PHARMACY_ADAPTER.md` (new — this file)
- Regenerated (gitignored, evidence only, not part of the commit manifest): `ocr_runs_staging/realinv_20260820T040631Z/page-extraction-bundle.v1.json`
- Screenshot (gitignored evidence): `output/playwright/slice4-cp-adapter-page58.png`

No other tracked file touched. `scripts/build_slice4_page_artifact.py` and every `src/ocr_inbound/web_static/*` file are unchanged from §35's already-candidate state.

## Test counts

- Focused (`tests.test_page_extraction`): **31/31** (was 22 in §35; +9 net — added 10 new tests, removed 1 obsolete one).
- Full suite (`test_automation`, `test_core`, `test_matching`, `test_matching_behavioral_revert_check`, `test_matching_integration`, `test_page_extraction`, `test_product_review`, `test_system`): **194/194 OK** (was 185 in §35; zero regressions).

## Revert-check (non-vacuous)

Temporarily forced `_community_pharmacy_code_table_rows` to return `([], [])`
unconditionally (real file backed up first, restored byte-for-byte after),
reran the new test class against that reverted code:

- `extraction_strategy` came back `'MULTILINE_BLOCK'` instead of `'COMMUNITY_PHARMACY_CODE_TABLE'` — real `AssertionError`.
- `description`, `supplier_sku`, `quantity` came back `None` — 5 real `TypeError: 'NoneType' object is not subscriptable` (not `ImportError`, not a vacuous pass).
- 7 of 10 tests failed/errored in total; restored the file, reran: 31/31 again.

## Artifact summary before / after

| | Before (§35) | After (this candidate) |
|---|---|---|
| `page_count` | 10 | 10 |
| `table_found_pages` | 4 | 4 |
| `row_count` | 14 | 14 |
| `review_required_rows` | 9 | 8 |

Regenerated via the existing, **unmodified** `scripts/build_slice4_page_artifact.py`: reads the already-existing OCR run (no rerun), ephemeral local SQLite `Application`, calls only `matcher._predict()` (pure, non-persisting), asserts zero persisted documents before writing. Page 58 in the fresh artifact: row 1 `CODIPHEN TABLET(XIOS)` / `supplier_sku 32132` / `matcher: UNRESOLVED`; row 2 `CODIPHENTABLET(XIOS)` / `supplier_sku: None` (genuinely absent, not guessed) / `matcher: UNRESOLVED`. Neither row auto-confirmed — no approved `(supplier_code, "32132")` alias exists in the local fixture, so the real matcher correctly falls through to trade-name/suggestion territory.

## Browser verification

Chrome DevTools MCP against a fresh local staging server
(`ocr_runs_staging/slice4_cp_adapter_visual/serve.py`, gitignored, ephemeral
data root, `serve(app, ...)` — the real production code path, no test
doubles). Uploaded the regenerated artifact + `page-058.png` through the
existing file-picker UI.

- Page 5 (Berlin, regression check): 5 rows, 5 overlays, correct fields — unaffected.
- Page 58: title `หน้า 58 · COMMUNITY_PHARMACY_CODE_TABLE`; both CODIPHEN rows render with correct Lot `25B031` / Mfg `07/02/25` / Exp `06/02/28` / quantities `240 box` and `96 box`; `Matcher: UNRESOLVED` on both; the rendered page image visually matches every extracted value, including the `32132` code cell.
- Hover overlay 2 → row-card 2 highlighted (both `.active`).
- Click row-card 1 → overlay 1 highlighted (both `.active`) — reverse direction confirmed.
- Zero browser console errors this run.
- `grep -in "CODIPHEN\|ISOTRATE\|MIRAX\|MONOLIN\|PRENOLOL\|UTMOS\|LESFLAM\|VULTIN\|BAPID\|GASTER\|PRESOLIN" src/ocr_inbound/web_static/*` → no match. No product name from any adapter is hardcoded in the UI source; every rendered value comes from the uploaded artifact JSON at runtime.

Screenshot: `output/playwright/slice4-cp-adapter-page58.png`.

Note on environment: this session's Chrome DevTools MCP file-upload tool is
sandboxed to a fixed set of workspace roots that does **not** include the
OCR-inbound worktree itself. The artifact and page image had to be copied
into an already-permitted scratch directory before upload; the copies played
no role beyond that upload step, and no repository file was affected.

## Residual risks / points Codex should try to refute

1. **`supplier_sku` field addition is additive-only, not exhaustively regression-tested against every consumer.** I added `"supplier_sku": None` to the tabular and multiline-block strategies' field dicts for schema consistency and confirmed the UI (`app.js`'s `pageField`/`pageFieldText`) tolerates an unknown/extra key gracefully, and the full suite is green — but I did not write a dedicated test asserting every strategy's output dict now has exactly this 9-key field shape. A stricter contract test would catch a future accidental key-shape drift earlier.
2. **The "data row immediately followed by lot row" pairing rule is proven only against page-058's own 2 real blocks.** If a real invoice from this same supplier ever has three or more products, or a product block missing its Lot line entirely followed immediately by the NEXT product's data row, the pairing could misassociate. The code does check `_is_lot_dates_row` before treating the next row as a Lot row (so a missing-Lot case degrades to `MISSING_FIELD:lot` rather than stealing a neighbor's Lot line), but this exact scenario has no real evidence to test against yet.
3. **`unit_price`/`total_amount` extraction for row 2 is honestly `None`** because the real evidence has no such tokens for that row at all (confirmed by direct inspection, not a filtering artifact) — this was not in the task's minimum required field list, but a reviewer relying on this adapter for full financial reconciliation should know it is incomplete for repeated-batch rows on this supplier.
4. **The `_find_totals_boundary` fix is generalized (affects all three strategies), not scoped only to the Community Pharmacy adapter.** I verified it does not change any existing Berlin/Unison/Medline test result and reasoned through why (their totals lines are far enough from product rows), but I did not attempt to construct an adversarial case where row-cluster-widening the totals boundary could newly swallow a real product row on some hypothetical page.
5. **Coverage is now 4/10 pages** (page-058 upgraded from empty-description rows to real content; Woothi/DKSH/Charoon remain `NONE`, unchanged from §35) — still not production-complete, consistent with the standing "does not need to support every supplier layout in the world" allowance.

## Confirmations

No OCR rerun. No production/shared/ADA database access. No modification to
`matching.py` (the adapter routes data through the matcher's existing,
unmodified `supplier_sku`/`_predict()` contract only). No migration. No
stage, commit, push, or deploy. No Slice 5 or next-supplier-adapter work
started. Stopping here for Codex's independent adjudication.

---

# FINAL REMEDIATION ROUND (same date, 2026-08-21)

Closing packet for Codex's 2 BLOCKED findings on the candidate above. Base/HEAD still `9a4fc81`,
nothing staged, nothing committed.

## 1. Base / HEAD / status

`HEAD = 9a4fc81` (unchanged all session). `git status --short`: only the same tracked files already
listed in this candidate's manifest are modified; only the same untracked new files exist. No reset,
checkout, clean, or deletion of untracked files occurred at any point.

## 2. What GLM did and its verdict

The requested workflow was: GLM 5.2 does bounded implementation/probe work first, Sonnet reviews.
**Disclosed plainly:** Sonnet had no tool-level way to invoke GLM in this session (no matching agent
type, no reachable peer session via `ListAgents`) and began remediation alone. Partway through,
`tests/test_page_extraction.py` changed on disk in this shared worktree TWICE, in two separate waves:

1. A `CommunityPharmacyGateAdversarialTests` class (4 tests: a positive control, both gate-negative
   false-positive probes, and a Lot-row-pairing no-theft probe).
2. A `BuilderMatcherInputBoundaryTests` class (1 test) that spies on the real `ProductMatcher._predict`
   call during a real `build()` run and asserts the ACTUAL arguments passed in — its docstring
   explicitly states it found that Sonnet's own `ArtifactBuilderBoundaryTests` would stay green even if
   the builder's `supplier_sku` plumbing were reverted, because those tests only ever read the written
   artifact's extraction fields (correct independently of the builder bug), never the actual
   `_predict()` call inputs.

Neither wave was written by Sonnet — consistent with GLM 5.2 operating as a separate process/session
outside Sonnet's own visibility, exactly the "bounded implementation/probe" role requested (test-only,
scoped to the 2 named findings AND to reviewing Sonnet's own verification, no expansion to other
suppliers). Sonnet independently verified every one of these 5 tests: manually traced the row-clustering
math for the Lot-pairing test (confirmed correct, not tautological), and — most significantly — verified
the second wave's claim about Sonnet's own test gap by reverting ONLY the `supplier_sku` line and
confirming `ArtifactBuilderBoundaryTests` really did stay 6/6 while the new spy-test correctly failed
(see §6). **Sonnet cannot supply GLM's own reasoning or a verdict statement** (no transcript is visible
from this side, only the committed test files); this is the one place the review chain is thinner than
a full two-way exchange, and it is disclosed here rather than assumed away. GLM did not touch
`page_extraction.py` or `build_slice4_page_artifact.py` directly, and did not expand scope beyond the
Community Pharmacy adapter.

## 3. What Sonnet found and fixed beyond GLM's contribution

- **Finding 1 (artifact-builder matcher plumbing):** reproduced (`supplier_code=None`,
  `supplier_sku=None` hardcoded for every row in `build_slice4_page_artifact.py`), then fixed:
  - `extract_page()` gained a `canonical_supplier_code` field on every strategy — the fixed constant
    `"SUPPLIER-COMMUNITY-PHARMACY"` only when `_detect_community_pharmacy_table` already confirmed
    both the real identity marker and this table's own header; `"UNKNOWN"` everywhere else. Never
    derived from filename or page number.
  - The builder now reads this field, passes the real code to the matcher only when known (else
    `None`), and stamps `alias_path_tested` on every row's `matcher_result` so no downstream consumer
    can claim the alias path was exercised when it structurally could not have been.
  - Per-row `supplier_sku`/`unit_final` are read from the extraction's own fields and passed through
    verbatim — the matcher's own existing `.strip().upper()` (matching.py, unmodified) is the single
    source of truth for the canonical unit shape, not reimplemented in the script.
  - **Adversarial addition beyond the letter of the finding:** seeded a real, approved
    `(SUPPLIER-COMMUNITY-PHARMACY, "32132")` alias through the repository's own approval workflow and
    confirmed it is genuinely REACHABLE end to end (`tier: ACTIVE_ALIAS`, correct product, correct
    `BOX` unit) — proving the plumbing does more than stay safely silent.
- **Finding 2 (totals-boundary invariant):** reproduced Codex's exact probe (returned `90`, violating
  `> below_y=100`), root-caused to clustering the full unfiltered token list before filtering by
  eligibility, fixed by restricting clustering to already-eligible tokens first. Re-ran the probe:
  `110`. Regenerated the real 10-page artifact — identical summary, confirming zero effect on real
  pages.
- **2 own adversarial tests** (`CommunityPharmacyAdapterGateFalsePositiveTests`): supplier name
  present / header absent does not trigger; header present / supplier name absent does not trigger.
- **1 own alias-reachability test** (folded into `ArtifactBuilderBoundaryTests`): the seeded-alias
  check described above, made permanent.

## 4. OLD → NEW matrix (this remediation round only; see the original candidate above for the
   page-058-content matrix)

| | OLD (blocked candidate) | NEW (remediated) |
|---|---|---|
| `build_slice4_page_artifact.py` `document.supplier_code` | hardcoded `None` always | `canonical_supplier_code` from the page's own confirmed identity, else `None` |
| `build_slice4_page_artifact.py` `line.supplier_sku` | hardcoded `None` always | extracted per-row value, or `None` when genuinely absent from that row's evidence |
| `build_slice4_page_artifact.py` `line.unit_final` | not sent at all | extracted per-row value, passed through as-is |
| Artifact `matcher_result.alias_path_tested` | field did not exist | present on every row; `true` only when the page's supplier identity is known |
| `extract_page()` result | no supplier-identity field | `canonical_supplier_code` on every strategy (`"UNKNOWN"` where no contract exists yet) |
| `_find_totals_boundary(tokens, below_y=100)` on the probe geometry | returned `90` (contract violation) | returns `110` |
| Approved-alias reachability | untested | proven reachable end to end with a real seeded alias |

## 5. Exact intended manifest (unchanged from the original candidate, contents updated)

- `src/ocr_inbound/page_extraction.py` (modified further — `canonical_supplier_code`, totals-boundary fix)
- `scripts/build_slice4_page_artifact.py` (modified — supplier_sku/canonical_supplier_code/unit_final plumbing, `alias_path_tested`)
- `tests/test_page_extraction.py` (modified further — 9 Sonnet tests + 5 GLM tests, see §2/§6)
- `docs/DEV_LAPTOP_SETUP_LEDGER_TH.md` (modified — §37 appended)
- `CANDIDATE_REPORT_COMMUNITY_PHARMACY_ADAPTER.md` (this file, updated in place)
- Regenerated (gitignored): `ocr_runs_staging/realinv_20260820T040631Z/page-extraction-bundle.v1.json`
- Screenshot (gitignored): `output/playwright/slice4-final-candidate-page58.png`

No other tracked file touched.

## 6. Test counts

Focused (`tests.test_page_extraction`): **45/45** (was 31 in the blocked candidate; +14: 9 Sonnet
authored directly, 5 landed via the shared worktree and attributed to GLM 5.2 per §2 — see the
self-correction below for what the 5th one caught). Full suite: **208/208 OK** (was 194; zero
regressions).

**A genuine finding against Sonnet's own test coverage, not only against the source bug:** the 5th
GLM-attributed test, `BuilderMatcherInputBoundaryTests.test_real_builder_feeds_sku_unit_and_supplier_code_into_predict`,
spies on the real `ProductMatcher._predict` call (`unittest.mock.patch.object`) during a real `build()`
run and asserts the ACTUAL arguments passed in — not the written artifact's already-independently-correct
extraction fields, which is all Sonnet's own `ArtifactBuilderBoundaryTests` had checked. Its docstring
claimed reverting the builder's `supplier_sku` plumbing alone would leave Sonnet's 6 tests green. Sonnet
independently verified this by reverting only that one line: `ArtifactBuilderBoundaryTests` stayed
**6/6** (confirming the gap was real), while the new spy-based test correctly failed
(`AssertionError: None != '32132'`). Restored, reran: 45/45. This is disclosed prominently because it
is a finding about the reviewer's own blind spot, not only about the original implementation — exactly
the kind of thing the two-party review structure exists to catch.

## 7. Two non-vacuous revert-checks (plus one narrower follow-up)

- **Finding 2:** reran the exact Codex probe against the pre-fix clustering logic — returned `90`
  (`<= below_y`, a real, demonstrable violation); confirmed the fix returns `110`.
- **Finding 1:** backed up both changed files, reverted the builder's plumbing to the old
  hardcoded-`None`/no-`alias_path_tested` shape, reran `ArtifactBuilderBoundaryTests` — 2 of 6 tests
  failed with real `AssertionError: False is not true`, not `ImportError`, not a vacuous pass;
  restored the real files byte-for-byte, reran: 6/6.
- **Finding 1, narrower follow-up (see §6 above):** reverted only `supplier_sku`'s assignment —
  `ArtifactBuilderBoundaryTests` stayed 6/6 (the gap), `BuilderMatcherInputBoundaryTests` failed (the
  fix for the gap); restored, reran: 45/45.

## 8. Generated artifact evidence

`{"page_count": 10, "table_found_pages": 4, "row_count": 14, "review_required_rows": 8}` — identical
to the pre-remediation summary, confirming this round changed plumbing correctness and a synthetic
invariant, not real-page row counts. Page 58, row 1: `supplier_sku: "32132"`,
`alias_path_tested: true`, `tier: UNRESOLVED` (no approved alias in the packaged fixture — correct,
non-guessing result). Row 2: `supplier_sku: None` (genuinely absent from that row's own evidence),
`alias_path_tested: true`, `tier: UNRESOLVED`. Page 5 (Berlin): `canonical_supplier_code: "UNKNOWN"`,
`alias_path_tested: false` on every row.

## 9. Browser evidence

Fresh local staging server, real artifact + real page images uploaded through the existing UI. Page 5
(Berlin) re-verified unaffected (5 rows, 5 overlays). Page 58 re-verified — identical correct
rendering (both CODIPHEN rows, correct Lot/Mfg/Exp/qty/unit, `Matcher: UNRESOLVED`), hover/click
bidirectional highlighting reconfirmed in both directions, zero console errors beyond the known
unrelated favicon 404, no product name/SKU/supplier-code hardcoded anywhere in `web_static/*` (grep
confirmed). Pages 6 and 48 verified via the regenerated artifact JSON directly (unchanged from the
original candidate) rather than re-opened in the browser — this session's Chrome DevTools `upload_file`
tool accepts one file per call (each call replaces the target input's file list), making a true
multi-image batch practically infeasible; disclosed rather than silently skipped. Screenshot:
`output/playwright/slice4-final-candidate-page58.png`.

## 10. Residual risks: blocking vs non-blocking

**Non-blocking (informational, same class of risk already disclosed in the original candidate):**
- The data-row/Lot-row pairing rule is now covered by GLM's adversarial no-theft test in addition to
  the 2 real page-058 blocks, but still has no real evidence of a 3+-product Community Pharmacy page.
- `unit_price`/`total_amount` for page-58 row 2 remain honestly unavailable (no such tokens exist in
  that row's real evidence) — unchanged from the original candidate, not in scope for this
  remediation.
- Pages 6 and 48 were not re-opened in the browser this round (see §9) — mitigated by direct JSON
  inspection showing byte-identical `canonical_supplier_code`/`alias_path_tested` values to before this
  round's changes, but a reviewer who specifically wants fresh visual confirmation of those two pages
  should know it did not happen this round.

**Blocking (open question for Codex, not something Sonnet can self-certify):**
- Whether the review-chain thinness disclosed in §2 (Sonnet cannot see GLM's own reasoning, only its
  landed artifact) is acceptable for this candidate to be adjudicated, or whether Codex wants an
  explicit statement from GLM's own session before treating those 5 tests as verified review coverage
  rather than "code that happened to appear and pass." This question carries more weight than it might
  otherwise, given one of those 5 tests found a real, confirmed gap in Sonnet's own prior verification
  (§6) — the same asymmetry that limits Sonnet's insight into GLM's reasoning also means Sonnet cannot
  rule out other gaps GLM's process might have caught that never surfaced as a committed test.

## 11. Claims Codex should try to rebut

1. That `canonical_supplier_code: "UNKNOWN"` on the tabular/multiline-block strategies is the CORRECT
   conservative default, not a cop-out — no supplier-identity gate was ever built for those layouts,
   so claiming a real code there would be a guess.
2. That the alias-reachability test (§6, item in `ArtifactBuilderBoundaryTests`) genuinely exercises
   the SAME code path the artifact builder uses in production runs, not a parallel/duplicate path —
   trace: `build()` → `app.matcher._predict(document, line, ...)` where `document["supplier_code"]`
   comes from `canonical_supplier_code`, identical to the test's own construction.
3. That the Lot-row-pairing no-theft test's synthetic geometry is a faithful, not overfit,
   reproduction of a real risk — reviewer should re-trace the row-clustering math independently rather
   than trust Sonnet's manual trace alone.
4. That widening `_find_totals_boundary`'s eligibility filter could not, on any of the 10 real pages'
   own geometry, cause a real product row to be newly excluded — Sonnet verified via identical
   before/after artifact summaries, not via an exhaustive adversarial search for a page where it might.

## 12. Confirmation

No stage, no commit, no push, no deploy at any point in this remediation round. No production/shared
DB access. No ADA/AdaAcc access. No OCR rerun. No modification to `matching.py`. No migration. No
Woothi/DKSH/Charoon (or any other new supplier) adapter work started.

## 13. Review independence, stated directly

Sonnet performed: preflight reproduction of both findings, the Finding 1 fix, the Finding 2 fix, all
6 `ArtifactBuilderBoundaryTests` (including the alias-reachability test), both
`CommunityPharmacyAdapterGateFalsePositiveTests`, all three revert-checks (2 original + 1 narrower
follow-up), full verification gates, artifact regeneration, and browser verification. GLM 5.2
(inferred from its landed, hand-verified artifacts, not from any direct exchange visible to Sonnet)
contributed the 4 `CommunityPharmacyGateAdversarialTests` AND the 1 `BuilderMatcherInputBoundaryTests`
test that found a real gap in Sonnet's own prior verification (§6). This is **not** a case of "GLM ran
out of tokens and Sonnet silently took over everything" — GLM's real contribution is present, credited,
and materially improved this candidate beyond what Sonnet's own review alone had produced — but it
**is** a case where Sonnet cannot vouch for GLM's own review process, only for the correctness of what
it produced (independently re-verified by Sonnet before being trusted, including by literally
reproducing the gap it claimed to have found). Codex should weigh this disclosed asymmetry when
deciding how much independent-second-reviewer credit this candidate earns.
