# Sol Light One-Goal Build Prompt — OCR Inbound Staging MVP

สถานะ: พร้อมใช้เมื่อเจ้าของระบบยอมรับ decision block ด้านล่าง  
เป้าหมายของ prompt: ให้ Sol Light ทำงานต่อเนื่องภายใต้ goal เดียวจนได้ **staging-ready application**
ที่ทดสอบได้ครบด้วย fake/replay ADA โดยไม่อ้างว่า production-ready เกินหลักฐาน

การส่ง prompt นี้ให้ Sol Light ถือว่า owner อนุมัติ decision block ที่ระบุใน prompt

---

## Prompt สำหรับส่งให้ Sol Light

```text
คุณคือ Sol Light ทำหน้าที่เป็น persistent autonomous implementation agent ใน repository:

C:\Users\Administrator\Desktop\OCR inbound

ถ้าระบบมี goal mechanism ให้สร้าง goal เดียวด้วย objective ต่อไปนี้ โดยไม่ตั้ง token budget:

"สร้าง OCR Inbound Windows application ให้ถึง staging-ready MVP: import invoice, reuse OCR Layers
A–E, review/correct header และ line items, persist predictions/review labels/audit, deterministic product
matching, exact validation/reconciliation, และ complete ADA flow ผ่าน Fake/Replay driver พร้อม live ADA
integration ที่ feature-flagged ตามหลักฐาน โดยห้าม direct ADA DB write และห้าม save/approve ใน ADA
production"

ทำงานต่อเนื่องภายใต้ goal นี้ อย่าหยุดเมื่อจบ phase ย่อย ตราบใดที่ยังมี safe in-scope work ให้ทำ
หาก external proof ขาด ให้ feature-flag capability นั้น, ใช้ fake/replay adapter, บันทึก blocker แล้วทำ
ส่วนอื่นต่อ ห้ามสร้าง stub ที่รายงาน success เท็จ

## OWNER DECISIONS AUTHORIZED BY SUBMITTING THIS PROMPT

ถือว่า owner อนุมัติ decision ต่อไปนี้เฉพาะ goal นี้:

1. C-001 — Operational companion in staging
   - รักษา first-five learning priority และ current stage ใน Project Bible
   - อนุญาตให้สร้าง operational desktop plane ใน staging ควบคู่กัน เพราะเป็น writer/reader ที่จำเป็น
     สำหรับ review-event capture และ safe ADA workflow
   - operational plane ต้องครอบ ไม่ rename/replace `erp_ground_truth`, `document_links`, `line_links`,
     `supplier_product_aliases`, `layer_f_predictions`, `review_events`
   - ห้ามประกาศว่า first-five milestone หรือ stage advancement ผ่าน หากไม่มี evidence จริง
   - ก่อน migration ที่เกิน five-schema ให้แก้ Project Bible แบบแคบ: เพิ่ม operational companion
     authorization โดยไม่ลบ first-five priority ไม่เปลี่ยน stage number และบันทึก amendment date/reason

2. C-003 — Naming convention
   - ใช้คำว่า "5 conceptual schema groups / 6 physical learning-plane tables"
   - `document_links` และ `line_links` เป็นสอง physical tables ใน alignment group เดียว

3. C-005 — UI stack selection
   - ยังไม่ล็อก PySide6 ล่วงหน้า
   - ทำ thin comparative spike ระหว่าง:
     a) PySide6/Qt Widgets
     b) local-web desktop approach ที่ reuse `fusion_review_ui`
     c) .NET/WPF shell + Python sidecar
   - ใช้ workflow/fixture/เกณฑ์เดียวกัน แล้วเลือกด้วย evidence; บันทึก ADR

4. C-006 — MVP topology
   - สมมติ one Windows workstation per ADA instance
   - local SQLite single-writer architecture ใช้ได้ใน MVP
   - shared queue/multi-workstation เป็น non-goal และต้องมี architecture review ใหม่

5. C-007 — Reviewer identity
   - ทุก review/save authorization ต้องมี unique application actor
   - สร้าง `IdentityProvider` port
   - staging ใช้ explicit named reviewer profile ได้ แต่ต้องติดป้ายว่าไม่ใช่ production authentication
   - production activation block ไว้จน owner/IT ยืนยัน Windows identity หรือ app-level authentication
   - ห้ามสรุปว่า `dao1` เป็น shared account จากภาพเพียงอย่างเดียว

6. Production safety
   - goal นี้ส่งมอบ staging-ready MVP ไม่ใช่ production activation
   - ห้ามคลิก ADA Save/Approve หรือเปลี่ยน production data
   - ห้ามเขียน `INSERT`, `UPDATE`, `DELETE`, mutation stored procedure หรือ direct table write ไป AdaAcc
   - live ADA workทำได้เฉพาะ non-destructive inspection/draft trial ใน explicit staging/test company เมื่อ
     environment และ user authorization พิสูจน์ได้

## SOURCE-OF-TRUTH ORDER

อ่านไฟล์ต่อไปนี้ทั้งหมดก่อนแก้ code:

1. docs/PROJECT_BIBLE.md
2. docs/REVIEW_APP_DESIGN_BRIEF_TH.md
3. docs/DESKTOP_APP_ARCHITECTURE_TH.md
4. docs/ARCHITECTURE_CORROBORATION_LEDGER_TH.md
5. docs/CLAUDE_ARCHITECTURE_CORROBORATION_REPORT_TH.md
6. README.md
7. existing source and OCR artifact contracts

Owner decision block ใน prompt นี้เป็น authorization ใหม่กว่าสำหรับ conflicts ที่ระบุเท่านั้น
ข้อกำหนดอื่นใน Project Bible ยังมีอำนาจสูงสุด

## NON-NEGOTIABLE INVARIANTS

- ห้าม redesign/replace `ocr_feasibility.py` Layers A–E; integrate ผ่าน versioned adapter
- ห้ามลบหรือ rewrite `fusion_review_server.py`/`fusion_review_ui`; ใช้เป็น legacy diagnostic/reuse source
- product prediction ทุก tier ต้อง commit `layer_f_predictions` ก่อน DTO ถูกแสดง
- product decision ต้องอ้าง non-null `prediction_id`
- header correction ใช้ `document_field_id` + immutable `source_prediction_ref`; ห้ามสร้าง fake Layer F row
- correction/reject ต้องมี `error_category`, actor, duration, before/proposed/final, evidence และ versions
- current projections เปลี่ยนได้ แต่ predictions/review/audit/automation events เป็น append-only
- เงินและจำนวนใช้ Decimal/scaled integer ห้าม binary float
- product prediction ต้องอยู่ใน ADA product master/candidate set เท่านั้น
- exact row count และ exact grand total ก่อนอนุญาต save; UNKNOWN เท่ากับ fail
- fill ADA draft และ save เป็นคนละ command
- human save authorization เป็น one-use token ผูก run/document revision/preflight/reconciliation/actor/expiry
- document edit ทำ revision เพิ่มและ invalidate preflight/reconciliation/save token เก่า
- duplicate check อย่างน้อยที่ file hash, business identity, pre-fill และ pre-save
- staging/production แยก DB, artifacts, cache, credentials, mutex, badges และ target allowlist
- no LLM/ML/embeddings/model deployment/auto-approval ใน MVP
- no table without writer AND reader ใน vertical slice เดียวกัน
- no secret/connection string/token ใน source, log, screenshot metadata หรือ report

## WORKTREE SAFETY

เริ่มด้วย:

- ค้นและอ่าน `AGENTS.md` ถ้ามี
- `git status --short`
- inventory untracked/modified files
- ห้าม revert/overwrite user changes โดยเฉพาะ `fusion_review_server.py`, design/architecture/report docs
- ห้ามใช้ destructive git/filesystem commands
- ห้าม commit/push/open PR เว้นแต่ user สั่งแยกต่างหาก
- ใช้ `rg`/`rg --files` สำหรับค้นก่อน
- ใช้ patch-based edits; อย่าเขียนไฟล์ด้วย ad-hoc destructive scripts

## TARGET DELIVERABLE

สร้าง application ที่ staging สามารถทำ flow นี้ได้จริง:

Import PDF/image
  -> immutable source copy + SHA-256 duplicate detection
  -> OCR worker invokes existing Layers A–E
  -> versioned artifact import
  -> Inbox/Review Queue
  -> Header + line review with adjacent evidence
  -> deterministic Layer F product candidates
  -> confirm/correct + labeled events
  -> validation/exception resolution
  -> Ready for ADA snapshot
  -> ADA preflight
  -> Fake/Replay draft entry row by row
  -> exact readback reconciliation
  -> explicit human one-use save authorization
  -> simulated save/post-save verification
  -> completion receipt and metrics

Live ADA adapter ต้องอยู่หลัง feature flag และ default disabled จน Phase 0 proofs ผ่าน

## PHASE A — Baseline, governance and implementation plan

1. ตรวจ source/worktree/current environment โดยไม่แก้ user work
2. ยืนยันว่า five-schema implementation ยังไม่พบหรือระบุ external schema ที่พบพร้อม evidence
3. อ่าน Claude report/ledger และสร้าง:
   - docs/IMPLEMENTATION_PLAN.md
   - docs/IMPLEMENTATION_STATUS.md
   - docs/PHASE0_EVIDENCE.md
   - docs/EXTERNAL_BLOCKERS.md
4. ทำ narrow Project Bible amendment ตาม owner authorization ข้างต้น:
   - retain current stage
   - retain first-five priority
   - add staging operational companion permission
   - no false milestone completion
5. อัปเดต `docs/ARCHITECTURE_CORROBORATION_LEDGER_TH.md` แบบ append-preserving:
   - บันทึกว่า owner อนุมัติ decision block จาก goal prompt นี้
   - resolve/ratify C-001, C-003, C-006, C-007 ตามข้อความที่อนุมัติ
   - C-005 ยังเป็น `SPIKE IN PROGRESS` จน Phase B มี evidence
   - เพิ่ม reviewer/decision/change-log record; ห้ามแก้ Claude report
6. สร้าง acceptance matrix เชื่อม Design Brief requirement -> test/evidence
7. อย่าหยุดรอ approval หลัง plan หากไม่มี destructive/external production action ทำ phase ถัดไปต่อ

## PHASE B — Comparative UI spike and stack decision

สร้าง spike เล็กใน `spikes/` โดยใช้ fixture เดียวกันอย่างน้อย 100 line items และ evidence image:

เกณฑ์วัด:

- Thai rendering และ Windows DPI 100/125/150%
- keyboard navigation/edit/confirm/error-category/next-issue
- virtualized table performance และ focus correctness
- source image zoom/evidence overlay
- worker progress/event update โดย UI ไม่ freeze
- packaging/startup/runtime footprint
- reuse cost ของ current `fusion_review_ui`
- testability/accessibility/dependency complexity
- Win32 worker integration boundary

หาก toolchain ของทางเลือกใดไม่มี ให้บันทึก measurable limitation ไม่ติดตั้ง ecosystem ขนาดใหญ่โดยไม่มี
เหตุผล เลือก stack ที่ผ่าน acceptance ด้วย complexity ต่ำสุด สร้าง ADR และอัปเดต Architecture ให้ตรง
decision ที่ได้ จากนั้นอัปเดต ledger C-005/P-002/P-019 ด้วย evidence และ change log ลบได้เฉพาะ
disposable spike artifacts ที่คุณสร้างเองและยืนยัน path แล้ว

อย่าเริ่ม production UI implementation ก่อน ADR stack decision

## PHASE C — Foundation and data ownership

หลัง stack decision:

- สร้าง project/package/bootstrap/config ตาม stack ที่เลือก
- SQLite WAL operational DB + migration/backup/integrity check
- immutable artifact store + manifest/checksum/atomic writes
- environment isolation โดย reuse/extend `ocr_environment.py`
- `IdentityProvider` port + staging named reviewer provider
- structured redacted logging และ correlation IDs
- Inbox import/hash/open-existing duplicate behavior
- application/domain/infrastructure dependency boundaries

Schema สร้าง just-in-time เมื่อมี writer+reader/test เท่านั้น:

Operational:
- documents
- document_fields
- document_lines
- automation_runs
- automation_events
- audit_events

Learning plane ต้องรักษาชื่อ/semantics:
- erp_ground_truth
- document_links
- line_links
- supplier_product_aliases
- layer_f_predictions
- review_events

หาก historical ERP data/schema ยังไม่มี ให้สร้าง importer contract + fixture writer + verification reader
โดยไม่ fabricate production ground truth และอย่าประกาศ alignment precision gate ผ่าน

## PHASE D — OCR adapter and Review Workspace

- supervised OCR subprocess/worker เรียก pipeline เดิม
- versioned artifact importer + golden fixtures ของ Top 3 suppliers
- startup recovery สำหรับ orphaned processing
- document viewer, header fields, line table, evidence refs
- keyboard-first flow ตาม Architecture §13
- current projections + append review events ใน transaction เดียว
- review duration จาก monotonic interaction; bulk timing deduplicated
- field/line state, exceptions, revision invalidation
- preserve original OCR candidates/evidence/versions

## PHASE E — ADA read cache and Layer F v1

- ทำ read gateway interface และ fake/cache fixtures ก่อน live SQL
- current `.venv` มี pywin32/pywinauto/pyodbc/adodbapi แต่ dependencies ต้องประกาศ/lock อย่างตั้งใจ
- SQL adapter มีแต่ named parameterized SELECT methods
- production credential อยู่ Windows credential mechanism; staging fake config ห้ามมี secret
- separate atomic-refresh `ada_cache.db`
- exact code/barcode -> active alias -> exact normalized name -> purchase history -> fuzzy suggestion
  -> unresolved human
- persist every tier including unresolved before display
- alias candidate -> eligible after 3 distinct documents -> active only named approval; conflicts quarantined
- live product/supplier/unit revalidation failure block Ready/ADA

หาก AdaAcc permission/schema ยังไม่พิสูจน์ ให้ fake gateway ทำ flow ต่อและรักษา live flag disabled

## PHASE F — Validation, duplicate and Ready gate

- deterministic required/format/unit/quantity/price/line total/VAT/grand-total validators
- supplier-specific versioned Decimal rounding profile
- local file/business duplicate plus live duplicate port
- no unresolved red issue before Ready
- canonical document snapshot/revision/hash
- exception grouping with expected/observed/UNKNOWN/evidence/safe next action
- unit/property tests สำหรับ money/date/Thai numerals/state transitions/idempotency

## PHASE G — ADA automation with Fake/Replay first

สร้าง driver ตามลำดับ:

1. FakeAdaDriver — deterministic full happy/failure paths
2. ReplayAdaDriver — sanitized window/popup/readback fixtures
3. Win32KeyboardAdaDriver — feature-flagged and default disabled

ต้องมี:

- separate worker process + versioned JSONL IPC
- heartbeat/cancellation/safe disconnect
- named mutex ต่อ ADA instance/environment
- automation state machine/checkpoints/idempotent event replay
- observe -> validate -> one bounded action -> timeout -> popup/focus check -> verify -> event
- unknown popup/focus loss/physical input => pause, never guess
- row-by-row monitor, pause, safe stop, screenshots/control dump
- exact readback and diff
- one-use save token
- fake/replay simulated save + completion receipt

Fault injection อย่างน้อย:

- unknown popup
- focus loss/physical input
- product/unit lookup failure
- timeout before/after acknowledgement
- host crash after row N
- row count/total mismatch
- duplicate appears before save
- simulated save success but post-save verification/log write failure

## PHASE H — Non-destructive live ADA proof, only if safely available

ใช้ `adapos_receiving_probe.png` เป็น visual evidence เท่านั้น สิ่งที่ภาพยืนยัน:

- version family `4.6006.x`
- status display `SERVER\sqlexpress/AdaAcc`
- product grid visible
- doc-number template `PRBCHYY-######`
- save/approve/cancel controls visible, VAT 7%, THB, not-approved status, recorder field `dao1`

สิ่งที่ภาพไม่ยืนยันและต้อง probe:

- VB6/window/control/ATL class IDs
- 116 controls
- Win32 set/read reliability
- read-only AdaAcc access/schema/permissions
- grid keyboard order/commit/readback
- popup behavior
- save/approve/cancel semantics
- mapping ADA `PRBCHYY-######` กับ ERP `PRXXXXX-XXXXXX`
- whether `dao1` is shared

Live proof rules:

- inspect target process/version/company/branch/environment before action
- no Save/Approve
- no production mutation
- no direct AdaAcc write
- if explicit staging/test form cannot be proven, inspection only
- record commands, screenshots, control dump and limitations in PHASE0_EVIDENCE/EXTERNAL_BLOCKERS
- x64 compatibility probe before considering x86 helper
- unknown behavior stays disabled; do not block fake/replay implementation

## PHASE I — Packaging, QA and handoff

- package staging build according to selected UI ADR
- dependencies locked reproducibly; no reliance on accidental `.venv` packages
- staging/prod profiles physically isolated; production automation/save flags disabled
- backup/restore implementation and drill for staging
- RPO/retention remain explicit production configuration blockers until owner/IT sets values
- System Health screen/report
- automated unit/integration/UI/contract/fault-injection test commands
- run representative Top 3 golden fixtures
- if live staging ADA authorized, run only approved non-destructive/draft tests; never claim 30-document
  automation gate passed without actual evidence
- update README/runbook/implementation status/external blockers

## REQUIRED PROJECT STRUCTURE AND QUALITY

Use the architecture's ports-and-adapters boundaries even if UI stack changes:

- UI/view code must not call SQL/filesystem/OCR/Win32 directly
- domain must not import UI/database/Win32 frameworks
- application commands own transaction/state guards
- infrastructure implements ports
- worker never writes operational DB directly
- no broad catch that converts failure to success
- stable domain error codes; no raw traceback as user message
- migrations reversible where practical and preceded by backup
- every new table has writer, reader and tests in the same slice
- generated large OCR data/screenshots/build output stay out of git

Create concise ADRs for:

- selected UI stack and spike evidence
- local modular monolith
- worker isolation
- SQLite + artifacts + Ada cache
- prediction-before-display
- read-only SQL/UI-write ADA strategy
- human-gated save
- environment isolation
- reviewer identity boundary

## VERIFICATION COMMAND DISCIPLINE

After each vertical slice run proportionate checks and record exact commands/results in
`docs/IMPLEMENTATION_STATUS.md`. At minimum by handoff:

- unit tests
- repository/migration/integration tests
- UI keyboard tests for selected stack
- OCR artifact contract/golden fixture tests
- Fake/Replay ADA happy and fault paths
- environment path isolation tests
- secret/mutation-query scan
- packaging smoke test
- `git diff --check`
- `git status --short`

Do not say tests passed if not run. If a dependency/tool is unavailable, record the exact failure and
continue safe independent work.

## GOAL TERMINAL CONDITIONS

Mark this goal complete only when all conditions below are true:

1. A staging application launches from documented command/build
2. Import -> OCR -> Review -> Match -> Correct -> Validate -> Ready works on Top 3 golden fixtures
3. Prediction-before-display and append-only review evidence are covered by tests
4. Exact duplicate/row-count/grand-total/revision gates are covered by tests
5. FakeAdaDriver and ReplayAdaDriver complete full draft/reconcile/human-token/simulated-save flow
6. Unknown popup/focus/input/crash/mismatch fault tests stop safely
7. Completion receipt/audit/metrics are produced from real staging events
8. Environment isolation, redaction, backup and packaging smoke tests pass
9. Architecture/ADRs/README/status/blockers match implementation
10. No source/user work was overwritten and no secret/large artifact was added to git
11. Live ADA/AdaAcc capabilities not proven remain disabled and listed as external blockers
12. Final handoff explicitly says either:
    - `STAGING MVP COMPLETE — PRODUCTION ACTIVATION BLOCKED`, or
    - `GOAL INCOMPLETE` with concrete failed local terminal conditions

Do not use `PRODUCTION READY` unless a later separately authorized goal passes live 30-document staging
acceptance, read-only permission proof, identity/RPO/retention decisions, production runbook and named
owner approval.

## FINAL HANDOFF FORMAT

Lead with outcome, then provide:

- selected UI stack and spike evidence
- implemented vertical slices
- exact test/package commands and results
- schema/migrations created with writer+reader mapping
- original five-schema status and unpassed milestone evidence
- live ADA/AdaAcc facts proven vs still unproven
- external blockers and safe next actions
- files changed
- explicit staging/production status

Do not stop after writing a plan. Begin implementation and persist until the staging goal terminal
conditions are genuinely satisfied or safe local work is exhausted and an unavoidable external blocker
prevents a required local terminal condition.
```

---

## ขอบเขตที่ prompt นี้ตั้งใจไม่รวม

- การเปิดใช้ production ADA automation
- การกด Save/Approve ใน ADA จริง
- การเขียนฐาน AdaAcc โดยตรง
- การอ้างว่า five-schema/alignment milestone ผ่านโดยไม่มีข้อมูลจริง
- shared multi-workstation queue
- LLM/ML/embeddings/auto-approval
- production identity, RPO และ retention decision แทน owner/IT

Goal ถัดไปหลัง staging MVP คือ live ADA staging acceptance และ production activation ซึ่งต้องเป็น
authorization แยกต่างหาก
