# Cold-start Prompt — Independent Claude Architecture Verification

ใช้ prompt นี้กับ Claude ที่เปิด repository นี้ได้ แต่ยังไม่รู้บริบทจาก conversation เดิม

```text
คุณคือ independent principal software architect, data-integrity reviewer และ Windows automation
safety auditor คุณไม่เคยเห็น conversation ก่อนหน้านี้และต้องตรวจข้อกล่าวอ้างของ Codex อย่างอิสระ

Repository root:
C:\Users\Administrator\Desktop\OCR inbound

เป้าหมาย:
ตรวจสอบข้อเท็จจริง การตีความ schema ผลกระทบของ proposed desktop operational schema และ
architecture ทั้งหมดที่ Codex เสนอใน session ก่อนหน้า แล้วรายงานว่าส่วนใดถูก ถูกบางส่วน
เกินหลักฐาน ขัดกับ source of truth หรือควรออกแบบใหม่

นี่เป็น VERIFICATION-ONLY TURN:
- ห้าม implement/refactor application code
- ห้ามแก้ PROJECT_BIBLE, Design Brief, Architecture หรือ source code
- ห้ามลบ/revert/format งานเดิมของผู้ใช้
- อนุญาตให้สร้างไฟล์รายงานเดียว:
  docs/CLAUDE_ARCHITECTURE_CORROBORATION_REPORT_TH.md
- ตรวจ git status ก่อนและหลัง และรายงานไฟล์เดิมที่ dirty โดยไม่แตะต้อง

หลักสำคัญ:
- อย่าเชื่อ architecture document หรือ ledger ว่าเป็นข้อเท็จจริง
- แยก SOURCE_REQUIREMENT, REPO_FACT, REPORTED_OBSERVATION, INTERPRETATION,
  PROPOSAL, OPEN_PROOF และ CONFLICT
- “ค้นไม่พบใน workspace” ไม่ได้แปลว่าไม่มีใน external DB, private branch หรือเครื่องอื่น
- ข้อเท็จจริงเกี่ยวกับ ADA ที่เขียนใน brief ยืนยันได้เพียงว่า brief กล่าวไว้ จนกว่าจะมี repeatable
  probe/control dump/database evidence
- อย่าพยักหน้าตาม Codex หาก alternative ที่ง่ายกว่า/ปลอดภัยกว่าเหมาะกว่า

ทำงานตามลำดับต่อไปนี้เพื่อหลีกเลี่ยง anchoring:

PHASE A — Blind source inspection ก่อนอ่าน Architecture/Ledger

1. ตรวจ `git status --short`, file tree และค้น `AGENTS.md`
2. อ่านไฟล์เหล่านี้ทั้งหมดก่อน:
   - docs/PROJECT_BIBLE.md
   - docs/REVIEW_APP_DESIGN_BRIEF_TH.md
   - README.md
   - requirements.txt
   - ocr_environment.py
   - fusion_review_server.py
   - fusion_review_ui/index.html
   - ส่วนที่เกี่ยวข้องของ fusion_review_ui/app.js
3. Inspect existing OCR output contract และชื่อ artifacts จาก README/code โดยไม่ redesign pipeline
4. ค้น implementation ของ schema ต่อไปนี้ทั้ง workspace โดย exclude generated OCR artifacts
   ตามความเหมาะสม:
   - erp_ground_truth
   - document_links
   - line_links
   - supplier_product_aliases
   - layer_f_predictions
   - review_events
5. ค้น `.db`, `.sqlite`, `.sql`, migrations, ORM models และ connection/config references
6. ตรวจว่า review prototype ปัจจุบัน persist ข้อมูลอย่างไร รองรับกี่ run และมี state/transaction
   boundary อะไรจริง
7. ถ้าดู `adapos_receiving_probe.png` ได้ ให้บันทึกว่า “ภาพพิสูจน์อะไรได้/ไม่ได้” ห้าม infer
   control IDs, row readback หรือ save semantics จากภาพเกินหลักฐาน
8. จด preliminary findings ของคุณไว้ก่อนเปิด Architecture/Ledger

คำสั่งเริ่มต้นที่แนะนำบน PowerShell:

git status --short
rg --files -g 'AGENTS.md'
rg --files
rg -n 'erp_ground_truth|document_links|line_links|supplier_product_aliases|layer_f_predictions|review_events' .
rg --files -g '*.db' -g '*.sqlite' -g '*.sqlite3' -g '*.sql' -g 'alembic.ini' -g '*migration*'
rg -n 'ThreadingHTTPServer|review_decisions|write_json|write_csv|validate_environment_path' fusion_review_server.py ocr_environment.py

หลีกเลี่ยงการอ่าน generated OCR JSON/PDF จำนวนมากโดยไม่มีเหตุผล และใช้ `rg` ก่อนค้นแบบ recursive อื่น

PHASE B — Read claims after preliminary findings

จากนั้นอ่านทั้งหมด:
- docs/DESKTOP_APP_ARCHITECTURE_TH.md
- docs/ARCHITECTURE_CORROBORATION_LEDGER_TH.md

เปรียบเทียบ preliminary findings ของคุณกับ claim IDs ใน ledger ห้ามแก้ ledger ในรอบแรก

PHASE C — Questions that must be answered

1. Project Bible ระบุ “first five schema objects” ว่าอะไรแน่?
   - เป็น five conceptual groups หรือ six physical relations?
   - ข้อความต้นฉบับพิสูจน์ความหมายนี้ได้แค่ไหน และส่วนใดต้อง owner decision?
2. ใน current workspace five-schema ถูก implement จริงหรือเป็นเพียง target design?
   - ระบุ scope ของการค้นอย่างซื่อสัตย์
3. Five-schema ทำหน้าที่เป็น knowledge/learning plane ตามที่ Codex ตีความหรือไม่?
   - มี operational responsibility ที่ Codex มองข้ามหรือไม่?
4. Proposed additions ต่อไปนี้จำเป็น/ซ้ำซ้อน/ขาดอะไรหรือไม่?
   - documents
   - document_fields
   - document_lines
   - automation_runs
   - automation_events
   - audit_events
   - separate ada_cache.db
   - immutable artifact store
   - versioned supplier profiles
5. ประเมิน impact ต่อแต่ละ existing schema:
   - erp_ground_truth
   - document_links
   - line_links
   - supplier_product_aliases
   - layer_f_predictions
   - review_events
6. ตรวจประเด็น `review_events` โดยเฉพาะ:
   - product review ต้อง link prediction_id
   - header OCR correction ไม่ใช่ Layer F prediction
   - ควรใช้ document_field_id/source_prediction_ref หรือ generic prediction table?
   - วิธีไหนรักษา Project Bible โดยเพิ่ม schema น้อยที่สุด?
7. ตรวจ architecture decision ทุกข้อ:
   - Windows-local modular monolith
   - Python 3.11 x64 + PySide6 Qt Widgets
   - host/OCR/ADA three-process boundary
   - SQLite WAL operational DB
   - read-only AdaAcc cache/live revalidation
   - Win32/keyboard ADA UI driver
   - prediction-before-display
   - append-only review/audit events
   - one-use human save authorization
   - duplicate checkpoints/idempotency/recovery
   - staging/production isolation
8. ระบุ simpler alternatives และ tradeoffs โดยเฉพาะ PySide6 vs .NET/WPF + Python sidecar,
   SQLite vs shared server DB และ JSON profile vs DB profile
9. ตรวจว่าข้อเสนอใดขัดกับ:
   - no table without writer AND reader
   - current first-five priority
   - no redesign Layers A–E
   - no LLM/ML/embeddings before gates
   - no direct ADA DB writes
   - human confirm + exact reconciliation before save
10. ระบุ technical assertions เกี่ยวกับ ADA ที่ยังไม่มีหลักฐานเพียงพอ:
    VB6/ThunderRT6MDIForm, 116 controls, ATL grid class, x64/32-bit behavior,
    row/total readback, popup handling, save/approve/cancel, AdaAcc schema และ ADACallAPI.dll
11. Architecture มี data-integrity/security/recovery gap อะไรที่ Codex ยังไม่เห็น?
12. Project Bible ควรแก้เมื่อใดและแก้อะไร โดยห้ามแก้ให้ stage advanced หากไม่มี milestone evidence?

PHASE D — Verdict rules

ใช้ verdict ต่อ claim ID เท่านั้น:
- VERIFIED
- PARTIALLY_VERIFIED
- NOT_FOUND_IN_WORKSPACE
- CONTRADICTED
- NEEDS_EXTERNAL_PROOF
- PROPOSAL_ACCEPTABLE
- PROPOSAL_REVISE
- OWNER_DECISION_REQUIRED
- SUPERSEDED

สำหรับ proposal ห้ามใช้ VERIFIED เพียงเพราะเขียนไว้ละเอียด ต้องประเมินความเหมาะสม
สำหรับ reported ADA observation ถ้ายังไม่ได้ probe ซ้ำ ให้ใช้ PARTIALLY_VERIFIED หรือ
NEEDS_EXTERNAL_PROOF

PHASE E — Required report

สร้าง `docs/CLAUDE_ARCHITECTURE_CORROBORATION_REPORT_TH.md` ด้วยโครงสร้างนี้:

# Claude Independent Architecture Corroboration Report

## 1. Reviewer and workspace snapshot
- Claude model/version ถ้าทราบ
- วันที่/เวลา/timezone
- git branch/commit/status
- files inspected
- commands run และ scope/exclusions

## 2. Executive verdict
- 5–10 bullets: Codex ถูกเรื่องอะไร, เกินหลักฐานเรื่องอะไร, จุดเสี่ยงสูงสุด

## 3. Blind preliminary findings
- สิ่งที่สรุปได้ก่อนอ่าน Architecture/Ledger

## 4. Claim-by-claim verdict
ตาราง columns:
Claim ID | Verdict | Evidence file:line/command | Explanation | Required action

ต้องครอบคลุมทุก R-*, F-*, A-*, I-*, P-*, C-* และ U-* ใน ledger
สามารถ group VERIFIED claims ได้ แต่ห้ามละ claim ID

## 5. Five-schema interpretation
- รายการเดิม
- conceptual-vs-physical count
- implemented-vs-not-found
- semantic responsibility ของแต่ละ table

## 6. Impact of proposed operational schema
ตาราง existing schema | proposed relationship/change | impact | risk | recommendation

## 7. Architecture critique
- what to keep
- what to revise
- simpler alternatives/tradeoffs
- missing components/invariants

## 8. Governance and migration recommendation
- สิ่งที่ทำได้ก่อน amendment
- milestone evidence ที่ต้องมีก่อนแก้ Bible
- safe migration/backfill order สำหรับกรณี external schema มี/ไม่มี

## 9. ADA claims and external proof plan
- แยก claim ที่ verified จาก source vs ต้อง probe จริง

## 10. Corrections to Codex statements
แยก MUST / SHOULD / COULD พร้อมข้อความทดแทนที่แม่นกว่า

## 11. Owner decisions required
- คำถามสั้น ชัด และมีผลของแต่ละทางเลือก

## 12. Final recommendation
- APPROVE ARCHITECTURE AS-IS
- APPROVE WITH CHANGES
- REVISE BEFORE IMPLEMENTATION
- BLOCKED PENDING EVIDENCE
เลือกหนึ่งค่า พร้อมเหตุผล

คุณภาพหลักฐาน:
- อ้าง `file:line` ใกล้ claim
- บอก command ที่ใช้เมื่อเป็น absence claim
- ห้ามใช้ web/general best practice แทน evidence ของ repo
- หากค้น internet เพราะจำเป็น ให้แยก external recommendation จาก repo verification และใช้ primary sources
- อย่ารายงาน test ว่าผ่านหากไม่ได้ run
- อย่ารายงาน ADA capability ว่าผ่านหากไม่ได้แตะ staging ADA จริง

ก่อนจบ:
1. ตรวจ `git diff --check` เฉพาะ report
2. ตรวจ `git status --short`
3. ยืนยันว่าเปลี่ยนเฉพาะ report file
4. สรุป path ของ report และ verdict หลักให้ผู้ใช้
```

## วิธีใช้หลัง Claude ตอบ

1. ให้ Claude ทำงานใน workspace เดียวกันด้วย prompt ข้างต้น
2. ตรวจว่ามี `docs/CLAUDE_ARCHITECTURE_CORROBORATION_REPORT_TH.md`
3. กลับมาสั่ง Codex ว่า:

```text
อ่าน Claude corroboration report แล้ว reconcile กับ
docs/ARCHITECTURE_CORROBORATION_LEDGER_TH.md
ให้สรุปจุดเห็นตรง จุดขัดแย้ง หลักฐานที่หนักกว่า และเสนอ patch ต่อ Bible/Brief/Architecture
แต่อย่าแก้ source code จนฉันอนุมัติ architecture decisions
```

ขั้นตอนนี้ทำให้ Claude มี independent first pass และ Codex ทำ cross-review รอบสอง โดย owner
เป็นผู้ตัดสิน conflict ที่เป็น priority/business authority
