# PROJECT BIBLE — Pharmacy Document Intelligence Platform

**Status:** Authoritative. This is the constitution of the project.
**Created:** 2026-06-10
**Last amended:** 2026-06-10
**Current stage:** Stage 1 → Stage 2 transition (see §4)

> **Instruction to every future Claude session and every human contributor:**
> Read this document before proposing or implementing any architecture change,
> migration, refactor, OCR enhancement, Layer F enhancement, ML initiative, or
> AI integration. Proposals that conflict with this document are wrong by
> default. If reality has changed, amend this document first — then implement.

---

## 1. Project Mission

We operate a pharmacy chain in Thailand. We receive supplier invoices
(Thai/English pharmaceutical invoices) and currently process them with heavy
manual effort. This project exists to automate inbound supplier invoice
processing while maintaining extremely high accuracy.

This is **not** a generic OCR platform. It is a **pharmacy-specific document
intelligence platform** that already contains extensive business knowledge:
a ~6,500-item product master, an ingredient/synonym knowledge layer, a product
category taxonomy, supplier purchase history, and an ERP with approved goods
receipts (ใบรับสินค้า).

### The roles — memorize this metaphor

| Component | Role |
|---|---|
| **ERP approved receipts (ใบรับสินค้า)** | **The answer key.** Every CEO-approved receipt is human-verified ground truth: supplier, product code (IC-XXXX / 630XXXX), product name, quantity, unit, price. |
| **Historical supplier PDFs** | **The exam papers.** They correspond to ERP records, giving us input/output pairs for free. |
| **OCR pipeline (Layers A–E)** | **The student.** It reads the exam papers. We grade it against the answer key. |
| **Human reviewers** | **The supervisors.** Their confirmations and corrections are future teacher data. Human review is part of the learning architecture, not a failure mode. |
| **Layer F** | **The knowledge interpreter.** It turns OCR character sequences into product identities using business knowledge — codes, aliases, history — before any AI reasoning. |
| **ML models** | **Future specialists.** Trained from historical knowledge + accumulated reviews to perform familiar decisions cheaply. The LLM is a temporary teacher that generates training data, never the permanent decision engine. |

---

## 2. Core Principle — The North Star

> **The objective is NOT to build the smartest AI.**
> **The objective is: reduce human minutes per invoice, safely and measurably.**

Every proposal — every table, every model, every prompt, every UI change —
must answer one question:

> **"Does this reduce human review effort within the next quarter?"**

If the answer is no or "eventually," it is deprioritized. Accuracy is preferred
over full automation. Human review is acceptable; wasted human review is not.

Corollary metrics (in priority order):

1. **Human minutes per invoice** — the north star.
2. **First-pass confirmation rate** — % of pre-filled rows confirmed without edits.
3. **Tier resolution distribution** — rows should migrate toward cheaper tiers over time.
4. **Per-tier precision** — a tier that fires must be right (exact ≈100%, alias ≥99%).
5. **Frozen holdout accuracy** — the only drift-proof model comparison.

If review duration is not being measured, no improvement can be proven.
`duration_seconds` per review decision is mandatory instrumentation.

---

## 3. Critical Architecture Principle — Alignment Is the Foundation

**PDF-to-ERP alignment is the foundation of the entire system.**

Every downstream capability — alias learning, training datasets, OCR
evaluation, ML training, auto-approval — depends on correctly answering:
*"Which ERP receipt record corresponds to this PDF (and which ERP line item
corresponds to this OCR row)?"*

If alignment is wrong:

- aliases become wrong,
- training datasets become wrong,
- ML models become wrong,
- evaluation becomes meaningless.

### Precision over recall — always

> **A missed document is lost opportunity.**
> **A wrongly linked document is poisoned data.**

Alignment uses a deterministic cascade (receipt number in OCR text → supplier
+ date + grand total → supplier + date ±1 + total within tolerance). Anything
below high confidence goes to an unlinked pool for human triage — it is never
guessed. Line-level links require at least two of three signals (quantity,
price, fuzzy product name) to agree.

Alignment precision target: **≥ 99%** on a manually verified sample before any
data generated from links is trusted.

---

## 4. System Evolution Roadmap

The platform evolves through these stages. Stages are advanced by **measured
conditions, never by calendar**. Skipping stages is forbidden.

| Stage | Description | Advance condition |
|---|---|---|
| **0** | Manual entry — humans type everything into ERP | (historical) |
| **1** | OCR + human entry — pipeline extracts, humans still enter | Layer F v1 live |
| **2** | Layer F + human confirmation — rows pre-filled via exact code / alias gates; humans confirm or correct | First-pass confirmation ≥ 60% |
| **3** | Alias learning loop — reviews automatically feed the alias table nightly | Alias precision ≥ 99% over 1,000+ rows |
| **4** | Embedding retrieval — local embedding index over product master resolves unseen name variants | Error dashboard proves alias tier exhausted (§5) |
| **5** | LLM teacher — LLM handles only the ambiguous band, with full trace capture for distillation | Embedding live + measurable top-1-wrong/top-5-right band exists |
| **6** | ML shadow mode — models trained nightly, evaluated silently against human decisions | ≥ 500 labeled records per (supplier, task) + stable baseline |
| **7** | ML-assisted review — ML replaces embedding/LLM for validated suppliers | Shadow accuracy ≥ champion over ≥ 200 predictions, no supplier regression > 2% |
| **8** | Selective auto-approval — highest-confidence rows skip review, with audit sampling | Per-tier precision proven; named human activates per supplier |
| **9** | Human auditing only — humans handle novelty and audit samples | Sampled audit error < 0.5% sustained 3 months |

**Long-term steady state:** ML handles familiarity, LLM handles novelty
(new suppliers, new products, layout changes), humans handle exceptions and
audits. The LLM is never retired globally — it is retired per
(supplier, pattern) via retirement gates, with automatic reinstatement if ML
accuracy degrades.

---

## 5. Technology Introduction Rules

> **No technology is added because it is interesting. It is added only
> because metrics prove the current layer is exhausted.**

| Technology | May be introduced ONLY when... |
|---|---|
| **Embeddings** | Alias + fuzzy gates have plateaued, AND the error dashboard shows `SUPPLIER_ALIAS_UNKNOWN` as the dominant category, AND those misses are verifiably *known products with unseen name variants* (the correct product exists in the master but was not retrieved). |
| **LLM** | Embeddings are live, AND there is a measured band of rows where embedding top-1 is wrong but the correct answer is in top-5 (retrieval works, disambiguation fails). The LLM serves **that band only**, with a structured JSON contract: it selects from provided candidates only, may answer `INSUFFICIENT_EVIDENCE`, and every call stores its full prompt, response, reasoning, and alternatives as training artifacts. An LLM call whose trace is not captured is a wasted call. |
| **ML** | ≥ 500 labeled records exist for the (supplier, task) pair, AND a stable measured baseline exists for the model to beat. Training order: unit normalization → supplier identification → OCR candidate selection → per-supplier product matching → global product matching → auto-approval scoring (last, needs ≥ 2,000 records and very high precision). |
| **Auto-approval** | The full chain below it is stable, per-tier precision is proven, an explicit `auto_approval_rules` row is activated by a **named human approver**, and 5% random audit sampling is in place from day one. |

### The automation asymmetry rule

> **Anything that increases automation requires a human decision.**
> **Anything that decreases automation is automatic.**

Auto-train: YES. Auto-evaluate: YES. Auto-report: YES. Shadow mode: YES.
**Auto-deploy: NO.** Auto-demotion on accuracy degradation (rolling 30-day
drop > 5%): YES, automatic, with alert.

---

## 6. Ground Truth Strategy

Two teacher sources, one principle: **never start from zero when history exists.**

1. **ERP records are historical teacher data.** Months of approved
   ใบรับสินค้า records are a pre-built supervised dataset. They pre-populate
   supplier aliases, baseline accuracy benchmarks, and the first training
   datasets — before Layer F processes its first live invoice.

2. **Human review decisions are future teacher data.** Every review action
   (confirm / correct_product / correct_quantity / correct_unit / reject)
   becomes a structured training record. Every correction **must** carry an
   `error_category` (OCR_ERROR, SUPPLIER_ALIAS_UNKNOWN,
   PRODUCT_MASTER_MISSING, INGREDIENT_SYNONYM_MISSING, LAYOUT_PARSING_ERROR,
   UNIT_NORMALIZATION_ERROR, QUANTITY_EXTRACTION_ERROR, LLM_REASONING_ERROR,
   HUMAN_OVERRIDE_BUSINESS_RULE, INSUFFICIENT_CONTEXT, PRICE_ANOMALY,
   AMBIGUOUS_PRODUCT). The category is the diagnostic signal that directs the
   next sprint's investment — without it, corrections are noise.

3. **The frozen holdout.** 15% of linked historical documents, stratified by
   supplier, frozen at dataset v1.0.0, **never added to, never trained on**.
   Every future model, prompt, and rule change is evaluated against this same
   holdout forever. Establish it before any tuning begins — a contaminated
   holdout can never be recovered.

4. **Grounding constraint.** No AI component may ever predict a product that
   is not in the product master / provided candidate set. Hallucinated
   products are a hard failure. Insufficient confidence routes to human
   review — that is the designed behavior, not an error.

5. **Alias conflict rule.** When the same (supplier, normalized text) maps to
   two or more products, the alias is quarantined and **never auto-resolved**.

---

## 7. The Data Flywheel

The intended perpetual learning loop:

```
Historical PDFs  +  ERP Ground Truth
            │
            ▼
        Alignment            (precision ≥ 99%, deterministic cascade)
            │
            ▼
      Alias Generation       (confirmation_count ≥ 3 → active; conflicts quarantined)
            │
            ▼
         Layer F             (exact code → alias → fuzzy → [embedding] → [LLM] → human)
            │                (EVERY row writes layer_f_predictions BEFORE display)
            ▼
       Human Review          (confirm / correct + mandatory error_category + duration)
            │
            ▼
     Training Dataset        (labels derived from review actions; versioned; stratified)
            │
            ▼
       Auto Training         (nightly; per supplier/task; automatic)
            │
            ▼
     Model Evaluation        (frozen holdout + last-30-days; automatic report)
            │
            ▼
      Human Approval         (promotion to shadow → production is gated, one click)
            │
            ▼
        Production           (with automatic demotion on degradation)
            │
            ▼
       New Knowledge         (new aliases, new error patterns, new training records)
            │
            └────────────────► repeat
```

**The discipline that makes the flywheel turn:**

> **No prediction is ever shown to a reviewer without a corresponding
> `layer_f_predictions` row written first — for every tier, including
> rule and alias tiers.**

If predictions are logged only for LLM calls, there is no training data for
the cheap tiers, and the system merely logs instead of learns.

---

## 8. Anti-Overengineering Rules

These rules are absolute. Violations are bugs, not style choices.

1. **No table without a writer AND a reader this sprint.** Schemas designed
   for future phases (full `training_records` feature columns,
   `dataset_versions`, `llm_retirement_gates`, `shadow_predictions`) are
   created when their consumers exist, not before.
2. **No LLM call if a deterministic lookup resolves the row.** Exact code
   match and alias match always run first. Target at maturity: < 5% of rows
   reach the LLM.
3. **No ML model without a measured baseline it must beat.**
4. **No automation increase without explicit human approval** (named approver,
   recorded). Automation decreases are automatic.
5. **Every prediction must be logged before it is shown to a reviewer.**
6. **Every correction must have a reason** (`error_category` is mandatory,
   enforced in the UI).
7. **No new tier until the error dashboard proves the current tier is
   exhausted.**
8. **Decisions that must stay deterministic forever** (never delegated to AI):
   supplier identification rules, date parsing (BE/CE calendars, Thai
   numerals), exact product code matching, unit normalization tables,
   quantity format parsing, confidence gate thresholds, auto-approval gates,
   environment routing. The test: if an auditor asks "why did the system do
   X?", the answer must be a rule, not "the model decided."
9. **Confidence scales are normalized at boundaries.** Tesseract 0–100 (÷100),
   EasyOCR 0–1, PaddleOCR 0–1, fusion mixed (>1.0 → ÷100). Any value > 1.0
   crossing a component boundary is a bug.

---

## 9. Current Priority (as of 2026-06-10)

The highest-ROI work, in strict order. **Everything else is secondary until
these five are complete.**

1. **ERP History Extraction** — export all approved ใบรับสินค้า line items
   (one row per line item) to `erp_ground_truth` staging. Approved records
   only. Keep `product_name_as_entered` alongside canonical names.
2. **PDF-to-ERP Alignment** — deterministic cascade, line-level linking,
   ≥ 99% precision verified on a 100-document manual sample. Build
   receipt-number search first (cheapest signal); verify 50 links by hand
   before building anything downstream.
3. **Supplier Alias Bootstrap** — generate `supplier_product_aliases` from
   confirmed line links. Expected to resolve 50–70% of rows from top
   suppliers on day one.
4. **Layer F v1** — exact code gate (IC-XXXX / 630XXXX) → alias gate →
   weak-alias/fuzzy suggestion → unresolved-to-human. No LLM. No ML. No
   embeddings. Plus deterministic validators (quantity regex, unit table,
   price-vs-history anomaly flag). Every row logs a prediction.
5. **Review Event Capture** — review UI upgrades: pre-filled rows,
   confirm/correct actions, **mandatory error_category dropdown**,
   `duration_seconds` capture, `review_events` linked to `prediction_id`.

First five schema objects (and only these): `erp_ground_truth`,
`document_links` + `line_links`, `supplier_product_aliases`,
`layer_f_predictions`, `review_events`.

### Existing system facts (do not rediscover)

- OCR pipeline: `ocr_feasibility.py` (Layers A–E: preprocess → Tesseract +
  PaddleOCR + EasyOCR → spatial fusion → geometry → semantics → row
  extraction). It works. **Do not redesign it.** Layer F builds on top.
- Review server: `fusion_review_server.py`. Environments: production
  (port 8765, `ocr_runs_final/`) and staging (port 8766, `ocr_runs_staging/`),
  enforced by `ocr_environment.py::validate_environment_path()`.
- Table-understanding layers A–E have human review gates with recorded
  decisions (see README.md for CLI flags).
- Internal product code formats: `IC-XXXX` and `630XXXX`. When either appears
  in OCR text, it is a zero-ambiguity product master key.
- ERP receipt number format: `PRXXXXX-XXXXXX` (e.g. PR00026-001883).

---

## 10. Instructions for Future Claude Sessions

Before proposing or implementing **any** architecture change:

1. **Read this document first.** It overrides intuition, training-data
   defaults, and "best practices" that conflict with it.
2. **Validate the proposal against the mission (§2):** does it reduce human
   minutes per invoice within the next quarter? If not, say so and
   deprioritize it.
3. **Validate against the current stage (§4) and current priority (§9).**
   Do not build Stage 6 infrastructure while Stage 2 work is incomplete.
   Do not propose embeddings/LLM/ML before their introduction conditions
   (§5) are met by *measured data*, not assumption.
4. **Prefer simpler solutions.** A lookup table beats an embedding; an
   embedding beats an LLM; a per-supplier model beats a global model. Choose
   the leftmost option that meets the precision floor.
5. **Prefer measurable ROI.** Every proposal states what metric it moves and
   how the movement will be measured. "It would be more elegant" is not ROI.
6. **Never introduce LLMs or ML where deterministic solutions exist.**
   Re-read §8 rule 8 for the list of permanently deterministic decisions.
7. **Respect the data disciplines:** prediction logged before display;
   correction always categorized; holdout never touched; alignment precision
   over recall; no hallucinated products; conflicts quarantined.
8. **Do not redesign the existing OCR pipeline.** It is the working student.
   Enhancements layer on top of it; they do not replace it.
9. **If this document is wrong or stale, amend it first** (update "Last
   amended" and the relevant section), then implement. The document and the
   system must never diverge silently.

---

*This document is the single source of truth. Code explains how; this
document explains why and in what order. When they disagree, this document
wins until it is amended.*
