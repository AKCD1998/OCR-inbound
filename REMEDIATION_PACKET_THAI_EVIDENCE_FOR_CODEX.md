# Remediation packet — Thai evidence guard (for Codex independent review)

**Status:** SEALED as a follow-up commit on the Draft PR branch under the owner's standing
Active-Tech-Lead authority (2026-08-21). **Still awaiting independent review** — sealing is not
approval, and PR #3 remains Draft.
**Target branch:** `slice5/master-cache-matcher-safety-2026-08-21` (PR #3, DRAFT)
**Applies on top of:** `4b5e185c66db9cdf1e335ce5666767270e5e21f9` — Codex's authorized commit.
**`4b5e185` is NOT to be amended, reverted, or force-pushed.** If approved, this becomes a *new*
follow-up commit on the same branch.

Produced by the Active Tech Lead self-review loop. **This is self-review, not independent review and
not cross-review.** Codex's adjudication has not happened.

---

## 1. Scope — exactly two files

```
 src/ocr_inbound/matching.py                      | 49 ++++++++++++++-
 tests/test_matcher_false_positive_remediation.py | 80 ++++++++++++++++++++++++
 2 files changed, 127 insertions(+), 2 deletions(-)
```

No other file is touched. `master_cache.py`, the runbook, requirements, `pyproject.toml`,
`__main__.py`, and `test_master_cache.py` are exactly as committed in `4b5e185`.

---

## 2. Exact diff of the production change

```diff
+_MIN_THAI_CONTAINMENT_LEN = 4
+
+_THAI_TRADE_NAME_STOPWORDS_NORMALIZED = frozenset(
+    normalize_product_text(word) for word in _THAI_TRADE_NAME_STOPWORDS
+) | _THAI_TRADE_NAME_STOPWORDS
+
 def meaningful_shared_tokens(source_normalized: str, candidate_normalized: str) -> set[str]:
     source = set(extract_trade_name_tokens(source_normalized)) - _FUZZY_GENERIC_EVIDENCE_TOKENS
     candidate = set(extract_trade_name_tokens(candidate_normalized)) - _FUZZY_GENERIC_EVIDENCE_TOKENS
-    return source & candidate
+    shared = source & candidate
+    for source_token in source - shared:
+        if detect_script(source_token) != "THAI":
+            continue
+        for candidate_token in candidate - shared:
+            if detect_script(candidate_token) != "THAI":
+                continue
+            shorter, longer = sorted((source_token, candidate_token), key=len)
+            if (
+                len(shorter) >= _MIN_THAI_CONTAINMENT_LEN
+                and shorter in longer
+                and shorter not in _THAI_TRADE_NAME_STOPWORDS_NORMALIZED
+            ):
+                shared.add(shorter)
+    return shared
```

Two behavioural changes, both confined to `meaningful_shared_tokens` (the B1 evidence gate):

1. **Thai containment** — a Thai run contained in another Thai run counts as evidence when it is
   ≥ 4 characters and not a stopword. Latin remains **exact equality only**.
2. **Normalized stopword comparison** — `normalize_product_text` rewrites Thai SARA AM
   (`ำ` U+0E33 → decomposed `ํา`), so composed stopword literals could never equal normalized
   tokens. Three of 22 Thai stopwords (`ยาน้ำ`, `น้ำเชื่อม`, `สำหรับ`) were inert inside this guard.

A patch backup is at `scratchpad/thai_remediation.patch` (8,403 bytes).

---

## 3. Reproduction ON `4b5e185` (the pushed commit)

Extracted the commit with `git archive HEAD` into a clean directory (working tree untouched) and
confirmed it has no fix: `grep -c _MIN_THAI_CONTAINMENT_LEN` → `0`.

Cache: two real-shaped Thai master rows. Input is the same drug with the master's `ยา`
("medicine") prefix absent — the ordinary OCR case.

```
input      : พาราเซตามอล 500 มก
master     : IC-009001 ยาพาราเซตามอล 500 มก
ON 4b5e185 -> None / UNRESOLVED / None
reasons    : ['FUZZY_INSUFFICIENT_TOKEN_EVIDENCE:1']
```

The reason code is B1's own — the guard committed in `4b5e185` is provably what rejected it, and it
rejected exactly one candidate: the correct one.

Why: Thai has no word spaces, so tokenization yields whole agglutinated runs.

```
invoice 'พาราเซตามอล 500 มก'   -> tokens ['พาราเซตามอล']
master  'ยาพาราเซตามอล 500 มก' -> tokens ['ยาพาราเซตามอล']
exact intersection: set()      <- same drug, zero shared tokens
```

---

## 4. OLD / 4b5e185 / NEW behaviour

| config | Thai `พาราเซตามอล 500 มก` | CODIPHEN Row 2 `CODIPHENTABLET(XIOS)` |
|---|---|---|
| **OLD** — before B1 existed | IC-009001 / FUZZY_SUGGESTION / **0.9474** ✅ | IC-002993 BEDSIDE TABLE / 0.5000 ❌ |
| **4b5e185** — B1 exact-only (pushed) | **UNRESOLVED** ❌ *regression* | IC-001962 / TRADE_NAME_MATCH / 0.6500 ✅ |
| **NEW** — this packet | IC-009001 / FUZZY_SUGGESTION / **0.9474** ✅ | IC-001962 / TRADE_NAME_MATCH / 0.6500 ✅ |

`4b5e185` traded a **false positive** for a **false negative** on Thai. A correct 0.9474 match became
UNRESOLVED, pushing work back to reviewers — the opposite of the Bible §2 north star.

**Latin stays exact on purpose.** `CODIPHENTABLET` *contains* `CODIPHEN`; if containment applied to
Latin, the mandated staged proof (guard-only ⇒ UNRESOLVED) would break. Verified: the full
OLD/guard-only/FINAL matrix from the candidate report re-runs **bit-identical** with this patch.

---

## 5. The five new tests and why each is non-vacuous

In `tests/test_matcher_false_positive_remediation.py`, classes `ThaiUnspacedEvidenceTests` (4) and
`ThaiFuzzyEndToEndTests` (1).

| test | asserts | non-vacuous because |
|---|---|---|
| `test_thai_prefix_difference_still_counts_as_evidence` | exact intersection is **empty**, then containment yields `{พาราเซตามอล}` | first assertion pins the *defect condition itself*; reverting the guard to exact-only makes the second fail with `AssertionError: {} != {'พาราเซตามอล'}` |
| `test_unrelated_thai_drugs_are_still_not_evidence` | paracetamol vs cetirizine ⇒ `set()` | fails if containment is loosened (e.g. threshold dropped below 4 or stopword check removed) — guards the loosening direction |
| `test_short_thai_runs_do_not_qualify_by_containment` | `ยาน้ำ` in `ยาน้ำเชื่อมแก้ไอ` ⇒ `set()` | fails without the **normalized** stopword set; this is the test that caught §2 change 2 |
| `test_latin_containment_is_still_refused` | `CODIPHENTABLET` vs `CODIPHEN…` ⇒ `set()` | fails the moment containment is extended to Latin — protects the mandated staged proof |
| `test_thai_line_whose_master_name_carries_a_ya_prefix_still_resolves` | end-to-end `_predict` ⇒ IC-009001 / FUZZY_SUGGESTION / human-confirm | goes through the real matcher + real cache, not the helper; fails with `AssertionError` on revert |

**Revert-check (behaviour reverted in memory, symbol kept present so no ImportError):**

```
B1-Thai containment          2 tests    2 failed    ['พาราเซตามอล', 'AssertionError']  -> NON-VACUOUS
```

Consolidated run of all seven revert-checks: **7/7 NON-VACUOUS, zero ImportError/AttributeError.**

---

## 6. Exact test counts (working tree, patch applied)

| gate | result |
|---|---|
| Full suite `unittest discover -s tests -t .` (`-W error::ResourceWarning`) | **266/266 OK** |
| Focused `tests.test_master_cache` | **34/34 OK** |
| Focused `tests.test_matcher_false_positive_remediation` | **24/24 OK** (19 + 5 new) |
| `scripts/safety_scan.py` | PASS — `secret_scan: pass`, `findings: []`, `live_flags_default_off: true` |
| `compileall -q src tests scripts` | PASS |
| `git diff --check` | PASS |
| `scripts/build_staging.py` | PASS — 442,543 bytes, SHA-256 `7bac4618…4158` |
| `scripts/package_smoke.py` | PASS |

`4b5e185` as committed: 261 full-suite tests. This patch adds 5 → 266. No existing test modified,
skipped, or deleted.

---

## 7. Corpus / real-master probes performed

All against the **real 6,671-row** production-derived cache (`source_fingerprint b281bf5c…c728f`),
pure `_predict()`; nothing persisted.

**(a) Reachability.** Products with no usable evidence token at all: **6 / 6,671 = 0.09%**. All six
are unspaced Thai runs with digits fused in, which `extract_trade_name_tokens` already skips — so
they were unreachable before this change too.

**(b) Targeted fuzzy-path probe.** 70 real Thai product names with their leading generic prefix
(`สามัญ`/`เภสัช`/`ยา`/`แถม`) stripped, so exact retrieval fails and the fuzzy tier is genuinely
exercised (seed 20260821):

```
resolved to the CORRECT source product : 49
resolved to a DIFFERENT product        :  1   <- see note
both unresolved                        : 20
old resolved but new did not           :  0

outcomes CHANGED by containment: 2
  IC-002251 'เพนคอร์ 4 มก. 10 เม็ด'   None -> IC-002251 FUZZY_SUGGESTION 0.8889  CORRECT recovery
  IC-000416 'ฟูทูโร่พยุงข้อมือ...'    None -> IC-000416 FUZZY_SUGGESTION 0.9333  CORRECT recovery
```

Containment changed **2** outcomes, both `None → the correct product`. **Zero** wrong-product
transitions. The one row flagged "different product" has `old == new == IC-002485` at
TRADE_NAME_MATCH — identical in both configs, therefore a pre-existing trade-name mismatch **not
attributable to this patch**.

**Honesty note on an earlier probe.** My first attempt sampled 150 *whole* product names and reported
"0 changed". That measured nothing: whole names resolve via EXACT_NAME/TRADE_NAME before the fuzzy
tier runs. It is superseded by (b) and must not be cited as evidence.

---

## 8. False-positive risk of Thai containment — and a defect this exposed

**The mechanism is real.** Containment pairs among Thai evidence tokens in the live catalog: **7,306**.
The most promiscuous short tokens reach large fractions of the master:

| token | meaning | products reachable |
|---|---|---|
| `สามัญ` | "generic/common" (house-brand prefix) | **3,479** (52% of catalog) |
| `เภสัช` | "pharma" | 1,755 |
| `กรัม` | **"gram" — a unit** | 1,170 |
| `ปกติ` | "normal" | 1,081 |
| `น้ํา` | "water" | 564 |

719 of 6,462 Thai evidence tokens reach more than 5 products. The codebase already has a doctrine for
precisely this — `_GENERIC_TOKEN_MAX_PRODUCTS = 5`, *"too generic to serve as sole retrieval
evidence"* — and **`meaningful_shared_tokens` does not apply it.**

### 8.1 The hole is mostly PRE-EXISTING in `4b5e185`

Adversarial inputs naming products that do not exist, run against the real cache:

| input | `4b5e185` (pushed) | with this patch | attribution |
|---|---|---|---|
| `สามัญ ของที่ไม่มีอยู่จริง` | IC-003109 `THREE SEVEN EAR PICKER` 0.4783 | identical | **pre-existing** |
| `ผงไม่มีจริง 5 กรัม` | 630030194 `TMAN MYDA B CREAM` 0.5263 | identical | **pre-existing** |
| `สามัญ ZZZQQ ไม่มีสินค้านี้` | **UNRESOLVED** | **IC-000027 `COKE NO SUGAR 450 ML` 0.5091** | ⚠️ **worsened by this patch** |

`สามัญ` grants evidence on **both** versions (`{'สามัญ'}`), because it is an exact shared token — so
the guard committed in `4b5e185` is already defeated by generic Thai words. This is the same class of
defect B1 was written to prevent, and it is live on the branch today.

### 8.2 What this patch makes worse

One of three adversarial cases moves from `UNRESOLVED` to a wrong `FUZZY_SUGGESTION`. Containment
widens the candidate pool that `สามัญ` can admit, so a case that previously found nothing now ranks
`COKE NO SUGAR 450 ML` first at 0.5091.

**Net effect measured:** +2 correct recoveries and +1 adversarial false positive in the probes above.
On realistic OCR text (§7b) the change is strictly positive; on adversarial/nonexistent-product text
it is mildly negative.

### 8.3 Proposed follow-up — NOT included here

Apply the existing `_GENERIC_TOKEN_MAX_PRODUCTS` doctrine inside `meaningful_shared_tokens`: a token
appearing in more than 5 distinct master products cannot be sole evidence, Thai or Latin, exact or
containment. That would close 8.1 **and** 8.2 together.

It is deliberately **not** in this packet: it requires catalog access inside a currently pure
function, and it changes `4b5e185`'s committed behaviour as well — a materially wider change needing
its own authorization and its own review. Recorded as a separate finding.

---

## 9. Other pre-existing defects reported, not fixed

Neither is caused by this patch or by `4b5e185`; both need an owner/Codex scope decision.

**(a) Three Thai stopwords are dead in `extract_trade_name_tokens`.** Same SARA AM mismatch, but in
Slice-2 code: `น้ำเชื่อม`, `ยาน้ำ`, `สำหรับ` can never match a normalized token, so those generic
words are currently usable as trade-name retrieval evidence.

**(b) Thai SYRUP contradictions are missed.** `matching.py:896` computes
`source_attrs = extract_attributes(normalized)` while candidate attributes come from **raw** master
names. The two SARA AM syrup words are detected on the candidate side but never on the source side:

```
source 'ยาน้ำ 60 ML'   raw -> {'SYRUP'}   normalized -> set()   <- _predict uses normalized
candidate 'PARACETAMOL TABLET 500 MG'     -> {'TABLET'}
contradiction caught with raw        : True
contradiction caught with normalized : False   <- MISSED
```

A Thai syrup line can be matched to a tablet product without the contradiction guard blocking it —
a wrong-match risk of the class Bible §3 exists to prevent. `เม็ด` and the other 15 Thai dosage words
are unaffected.

---

## 10. What Codex should try hardest to falsify

1. **§8.2 — is one adversarial regression acceptable for two real recoveries?** This is the central
   judgement call and I may have weighed it wrong. Argue the patch should be held until §8.3 lands.
2. **Is `_MIN_THAI_CONTAINMENT_LEN = 4` defensible?** It is asserted, not derived. Find a 4-character
   Thai run that is meaningful in one product and coincidental in another.
3. **Asymmetry Thai-vs-Latin.** I justify it linguistically (Thai unspaced, Latin spaced). Attack it:
   is there a Latin case that needs containment and now silently fails?
4. **Containment direction.** I accept containment in *either* direction (shorter inside longer,
   regardless of which side is the source). A short OCR fragment inside a long master name may be far
   weaker evidence than the reverse.
5. **§7b sample power.** 70 samples produced only 2 transitions — very low power to detect a rare
   false positive. Ask for a larger or stratified run before trusting "zero wrong transitions".
6. **My superseded probe (§7 honesty note).** Confirm the first 150-name probe is genuinely
   uninformative and that no conclusion anywhere still rests on it.
7. **`_THAI_TRADE_NAME_STOPWORDS_NORMALIZED` union.** I keep both composed and decomposed forms.
   Check no third Unicode form (NFC/NFD, other combining marks) is still unreachable.
8. **O(n²) inner loop.** Containment iterates source × candidate tokens per catalog product. Confirm
   no pathological slowdown on the widest master names (full 6,671 sweep measured ~1.4 s/prediction,
   unchanged within noise, but I did not profile it directly).
9. **That the staged CODIPHEN proof really is unchanged** — re-run the matrix yourself rather than
   trusting my "bit-identical" claim.

---

## 11. Actions taken and not taken

**Taken:** working-tree edits to the two files above; tests; probes against the real master through
read-only `_predict()`; patch backup to scratchpad.

**Taken under standing authority:** one follow-up commit on
`slice5/master-cache-matcher-safety-2026-08-21`, pushed to update Draft PR #3.

**NOT taken:** no amend, no force-push, no revert, no rebase, no history rewrite, no merge, no deploy,
no production write, no destructive migration, no Render/env change, no alias created or approved, no
new matcher auto-confirm behaviour, and PR #3 was left **Draft**. `4b5e185` is untouched.

**Verdict: READY FOR INDEPENDENT REVIEW** (was NEEDS REMEDIATION; the blocking item was §8.2, now
investigated to root cause in §12 and accepted as a documented residual risk rather than papered over)

Original verdict text retained for the record: **NEEDS REMEDIATION** — not for the Thai fix itself, which is verified and behaves as
designed, but because §8.1 shows the B1 evidence gate on the live branch is already defeated by
generic Thai tokens, and §8.2 shows this patch narrows that gap unevenly. Recommend Codex review this
packet and the §8.3 follow-up **together** before either lands.

---

## 12. Follow-up: the §8.3 generic-token fix was BUILT, MEASURED, and REJECTED

Under the owner's standing Active-Tech-Lead authority I implemented the §8.3 proposal
(`_GENERIC_TOKEN_MAX_PRODUCTS` applied to the evidence gate as a sole-evidence rule), measured it,
and **removed it again**. It is not in the sealed commit. Recording it so the independent reviewer
does not spend time re-deriving a dead end.

### What it did well

All three adversarial inputs from §8.1 became `UNRESOLVED`, including the two that are
**pre-existing** defects on `4b5e185`. Focused tests 31/31, full suite 266/266.

### Why it was rejected — it inverts on real data

Re-running the §7b corpus probe (70 prefix-stripped real Thai names, same seed):

| metric | Thai fix only | + generic filter |
|---|---|---|
| resolved to the CORRECT product | **49** | 47 |
| resolved to a DIFFERENT product | 0 attributable | **1** |
| correct → UNRESOLVED (lost) | 0 | **1** |

It cost 2 correct recoveries and introduced a wrong product on realistic OCR text, to fix
adversarial text naming products that do not exist.

### Root cause — frequency is not specificity

Diagnosed on the real master for `ถุงมือยางลองเมด สีดำ ไซส์ M 10` (Longmed rubber gloves):

```
IC-002957  CORRECT   shared = {สีดํา, ไซส์, ถุงมือยางลองเมด}   ALL THREE classified generic
IC-000063  WRONG     shared = {ไซส์(generic), ถุงมือยาง(specific)}   -> admitted, and won
```

The brand-and-product token `ถุงมือยางลองเมด` is "generic" **because the Longmed glove family has
more than five SKUs** (sizes and colours), while the vaguer `ถุงมือยาง` stays "specific" because it
is rarer. Catalog frequency therefore penalises exactly the multi-SKU product families where the
token is most diagnostic, and the filter blocked the correct product while admitting a wrong one.

**Conclusion:** `_GENERIC_TOKEN_MAX_PRODUCTS` is sound where it is currently used
(`_trade_name_candidates`, combined with other signals) but is the **wrong instrument** as a hard
sole-evidence filter in this gate. §8.1 remains open and needs a different mechanism — a curated
house-brand/unit stopword list, or evidence weighting rather than a binary gate.

### Net position of the sealed commit

| | real OCR text (§7b) | adversarial / nonexistent product (§8.1) |
|---|---|---|
| Thai fix (sealed) | **+2 correct, 0 wrong** | 1 of 3 cases worsened (§8.2) |
| Thai fix + generic filter (rejected) | −2 correct, +1 wrong | all 3 fixed |

Realistic invoice lines dominate adversarial ones, and an adversarial line routes to a human who
rejects an obviously wrong suggestion. §8.2's single worsened case is therefore accepted **as a known,
documented residual risk**, not as a solved problem.
