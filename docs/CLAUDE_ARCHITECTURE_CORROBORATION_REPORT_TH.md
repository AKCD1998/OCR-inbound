# Claude Independent Architecture Corroboration Report

Report ID: `OCR-INBOUND-ARCH-CLAUDE-REPORT-001`
สถานะ: `INDEPENDENT VERIFICATION COMPLETE — awaiting owner decisions on C-001/C-003/C-004/C-005/C-006`

> รายงานนี้เป็น first-pass verification อิสระตาม `docs/CLAUDE_COLD_START_VERIFICATION_PROMPT_TH.md`
> ผู้ตรวจอ่าน source (Bible, Brief, README, code, probe image) ก่อนเปิด Architecture/Ledger
> เพื่อลด anchoring แล้วจึงลง verdict ต่อ claim ID ทุกตัวใน ledger
> รายงานนี้ **ไม่แก้ source code** และไม่แก้ ledger/Bible/Brief/Architecture

---

## 1. Reviewer and workspace snapshot

| รายการ | ค่า |
|---|---|
| Reviewer | Claude (Anthropic) — model `claude-opus-4-8` |
| Role | Independent cold-start architecture/data-integrity/Windows-automation verifier |
| วันที่/เวลา | 2026-07-22, timezone Asia/Bangkok (+07:00) |
| Repository root | `C:\Users\Administrator\Desktop\OCR inbound` |
| Git branch | `main` |
| Git commit | `0dd50501c7985156c30ec8c028b8e5dd6e7f1bcc` |
| Git status (ก่อนเขียน report) | `M fusion_review_server.py`; untracked: `adapos_receiving_probe.png`, `docs/ARCHITECTURE_CORROBORATION_LEDGER_TH.md`, `docs/CLAUDE_COLD_START_VERIFICATION_PROMPT_TH.md`, `docs/DESKTOP_APP_ARCHITECTURE_TH.md`, `docs/REVIEW_APP_DESIGN_BRIEF_TH.md` |

### Files inspected

- `docs/PROJECT_BIBLE.md` (342 บรรทัด, อ่านทั้งไฟล์)
- `docs/REVIEW_APP_DESIGN_BRIEF_TH.md` (518 บรรทัด, อ่านทั้งไฟล์)
- `docs/DESKTOP_APP_ARCHITECTURE_TH.md` (1299 บรรทัด, อ่านทั้งไฟล์)
- `docs/ARCHITECTURE_CORROBORATION_LEDGER_TH.md` (347 บรรทัด, อ่านทั้งไฟล์)
- `docs/CLAUDE_COLD_START_VERIFICATION_PROMPT_TH.md` (250 บรรทัด)
- `README.md`, `requirements.txt`, `ocr_environment.py` (อ่านทั้งไฟล์)
- `fusion_review_server.py` (อ่าน persistence/bootstrap/env-validation sections + `git diff` ของ dirty change)
- `adapos_receiving_probe.png` (visual inspection)
- listing ของ `fusion_review_ui/` (`app.js`, `index.html`, `styles.css`)

### Commands run (scope/exclusions)

```text
git status --short ; git rev-parse --abbrev-ref HEAD ; git rev-parse HEAD
find . -name AGENTS.md                      # => ไม่พบ
grep -niE '<five-schema names>' <explicit source files: README, *.py, ocr_viewer.html>   # => 0 hit ใน source
grep (recursive, exclude ocr_runs*/__pycache__) '<five-schema names>'  # => hit เฉพาะใน docs/ 4 ไฟล์
find '*.db|*.sqlite|*.sql|*migration*|alembic.ini'   # => hit เดียวคือ .venv/.../pydantic/_migration.py (library)
grep 'sqlite3|sqlalchemy|alembic|CREATE TABLE|pyodbc|psycopg' <project code>  # => 0 hit ใน project code (hit ทั้งหมดอยู่ใน .venv)
sed/read fusion_review_server.py: lines 10-13, 519-583, 620-644, 672-700, 808-842
git diff fusion_review_server.py            # dirty change = Thai text reconstruction helpers เท่านั้น
```

**ขอบเขต:** ตรวจเฉพาะ current workspace บน branch `main` commit `0dd5050` เท่านั้น ไม่ได้เข้าถึง
external database, private branch, เครื่องอื่น หรือ ADA staging จริง — ข้อสรุปเรื่อง "ไม่พบ" จึงจำกัด
ที่ scope นี้

---

## 2. Executive verdict

1. **Ledger ของ Codex มีวินัยและซื่อสัตย์เป็นส่วนใหญ่** — จัดประเภท claim ถูกต้อง ไม่ยกระดับ
   "proposal" เป็น "fact" และ label การไม่พบว่า `NOT_FOUND_IN_WORKSPACE` (ไม่ใช่ "ไม่มีจริง")
   ผมยืนยัน Codex verdict ส่วนใหญ่และไม่พบการ overreach ที่เป็นสาระ
2. **Five-schema ยังเป็น target design ล้วน ๆ** — ชื่อ table ทั้งหกไม่ปรากฏใน application code เลย
   ระบบจริงยังเป็น OCR Layers A–E + table-understanding proof-of-concept และ review prototype ที่
   เก็บ decision เป็น JSON/CSV ต่อ run ไม่มี database ใด ๆ ในโค้ดโปรเจกต์ (F-007 ยืนยัน)
3. **Architecture ของ Codex สอดคล้องกับ Bible อย่างน่าประหลาดใจ** — เคารพ stage gates, no-table-
   without-consumer, human-gated save, no direct ADA write, Decimal money, prediction-before-display
   และแก้ปัญหา header-vs-product prediction (C-004) ได้ถูกทางด้วย `source_prediction_ref`/
   `document_field_id` โดยไม่สร้าง fake prediction
4. **ความเสี่ยงสูงสุดไม่ใช่เทคนิค แต่เป็น governance/priority** — Bible (10 มิ.ย.) ให้ priority #1–2 เป็น
   ERP extraction + PDF-to-ERP alignment (learning foundation) แต่ Desktop MVP (21–22 ก.ค.) ให้
   priority เป็น operational review + ADA data entry คนละโปรแกรมงานกัน owner ต้องตัดสินก่อน migration
   ใด ๆ ที่เกิน five-schema (C-001, I-006)
5. **ADA claims ทั้งหมดยังเป็น reported/visual เท่านั้น** — probe image ยกระดับได้เพียง 2 ข้อ
   (DB identity = SQL Server Express/AdaAcc, และ version family 4.6006.x) ส่วน VB6/ThunderRT6MDIForm,
   116 controls, ATL class, readback/save semantics ยัง `NEEDS_EXTERNAL_PROOF`
6. **จุดอ่อนที่ Codex ยังไม่ครอบ:** (ก) reviewer identity บน shared Windows login (probe เห็น user
   เดียว `dao1`) อาจทำให้ per-reviewer metric/audit เพี้ยน; (ข) ledger เทียบ UI stack แค่ PySide6 vs
   .NET แต่ยังมี "local-web UI reusing fusion_review_ui" เป็น simpler alternative ที่ยังไม่ถูกชั่ง;
   (ค) เลขเอกสาร ADA (`PRBCHYY-######` บน probe) ต่างจาก ERP receipt format ใน Bible (`PRXXXXX-XXXXXX`)
   — เป็นคนละ identifier ที่ต้อง map ให้ชัด
7. **คำแนะนำสุดท้าย: `REVISE BEFORE IMPLEMENTATION`** — architecture ดีพอจะเป็นฐาน แต่ต้องผ่าน
   Phase 0 governance (owner ยืนยัน priority + amend Bible), thin PySide6-vs-web spike, และ ADA staging
   probe ก่อนเขียน production code เกิน foundation slice

---

## 3. Blind preliminary findings (ก่อนเปิด Architecture/Ledger)

สรุปที่ได้จาก source โดยตรงก่อนอ่าน claim documents:

- **ไม่มี database ในโปรเจกต์** — `requirements.txt` มีแต่ OCR stack (PyMuPDF, Pillow, opencv,
  pytesseract, paddleocr, paddlepaddle, torch-cpu, easyocr, pdfplumber, camelot, openai) ไม่มี
  SQLAlchemy/Alembic/pyodbc/PySide6/pytest-qt; ไม่มีไฟล์ `.db/.sqlite/.sql`; ไม่มี `CREATE TABLE`/
  `sqlite3`/ORM ใน project code (hit ทั้งหมดอยู่ใน `.venv` library)
- **Persistence จริง = flat JSON/CSV ต่อ run** — `fusion_review_server.py` เก็บ
  `fusion/review_decisions.json` + `.csv` โดยแต่ละ decision มีเพียง `region_id, page,
  selected_candidate_engine, selected_candidate_text, review_status, review_notes, saved_at`
  (`fusion_review_server.py:519-545,577-578,620-644`)
- **การ review ปัจจุบันเป็นการเลือก OCR-region candidate (engine) ไม่ใช่ invoice header/line review**
  — ไม่มี `error_category`, ไม่มี `duration_seconds`, ไม่มี `prediction_id` linkage ⇒ Bible §2
  (`duration_seconds` mandatory) และ §9 priority 5 (`review_events` linked to `prediction_id`)
  **ยังไม่ถูก implement**
- **Environment isolation มีจริงและ enforce** — `ocr_environment.py::validate_environment_path()`
  กัน production↔staging path ข้ามกัน; server เรียกใช้ตอน `main()` (`ocr_environment.py:84-101`,
  `fusion_review_server.py:820`)
- **Pipeline จริงคือ Layers A–E + table understanding (A=bands, B=rows, C=columns/cells) พร้อม human
  gate** และ Layer D เป็น "readiness" เท่านั้น — ตรงกับ README output contract; Layer F ยังไม่มี
- **OpenAI second-reader มีอยู่แล้ว** (`--openai`) แต่เป็น OCR-reading/ disagreement flagging ไม่ใช่
  product-matching decision engine ⇒ ไม่ขัด Bible §5 (ซึ่งคุม LLM ใน matching plane) แต่ควรบันทึกว่ามี
- **Design Brief บรรยาย Desktop Review App + ADA POS automation ขนาดใหญ่ที่ยังไม่มีในโค้ด** — เป็น
  เอกสารส่งต่อ (handoff) ไม่ใช่ implemented state
- **ADA facts ใน Brief §8 เป็น reported observation ทั้งหมด**; มี `adapos_receiving_probe.png` เป็น
  หลักฐานภาพหนึ่งใบ

หลังเปิด ledger: preliminary findings ตรงกับ Codex snapshot §3 แทบทุกจุด ⇒ ยืนยันว่า ledger ไม่ได้
เขียนเกิน evidence

---

## 4. Claim-by-claim verdict

Evidence column ใช้ `file:line` หรือ command; absence claim ระบุ scope

### 4.1 Requirements (R-*)

| Claim ID | Verdict | Evidence | คำอธิบาย / Required action |
|---|---|---|---|
| R-001 | `VERIFIED` | `docs/PROJECT_BIBLE.md:6` | "Current stage: Stage 1 → Stage 2 transition" มีจริง |
| R-002 | `VERIFIED` | `docs/PROJECT_BIBLE.md:266-291` | Current Priority (10 มิ.ย.) ระบุ 5 งานต้องเสร็จก่อน ที่เหลือ secondary |
| R-003 | `VERIFIED` | `docs/PROJECT_BIBLE.md:289-291` | five-schema list ตรงตามอ้าง (ดู I-001 เรื่องนับ 5 vs 6) |
| R-004 | `VERIFIED` | `docs/PROJECT_BIBLE.md:224-231,249` | "No prediction shown without `layer_f_predictions` row written first" ทุก tier |
| R-005 | `VERIFIED` | `docs/PROJECT_BIBLE.md:239-242` | "No table without a writer AND a reader this sprint" |
| R-006 | `VERIFIED` | `docs/PROJECT_BIBLE.md:281-287` | Layer F v1 = exact code → alias → fuzzy → human; no LLM/ML/embeddings |
| R-007 | `VERIFIED` | `docs/REVIEW_APP_DESIGN_BRIEF_TH.md:28,366,453,483` | human confirm ก่อน save; ห้ามเขียนฐาน ADA ตรง |
| R-008 | `VERIFIED` | `docs/REVIEW_APP_DESIGN_BRIEF_TH.md:426-429,455` | reconcile row count + grand total 100% ก่อน save |
| R-009 | `VERIFIED` | `docs/REVIEW_APP_DESIGN_BRIEF_TH.md:22-28` | Top 3 suppliers, ทีละหนึ่ง invoice |
| R-010 | `VERIFIED` | `docs/REVIEW_APP_DESIGN_BRIEF_TH.md:208-231` | correction เก็บ before/proposed/final, evidence, versions, actor, duration, error_category |
| R-011 | `VERIFIED` | `docs/PROJECT_BIBLE.md:179-181`; Brief `:271-279` | alias conflict quarantine; label ถอนได้ |
| R-012 | `VERIFIED` | `docs/PROJECT_BIBLE.md:293-301,332-333`; `README.md` | Layers A–E เป็นของเดิม ห้าม redesign |

**สรุป R-*: ทั้ง 12 ข้อ Codex verdict ถูกต้อง** ผมยืนยัน `VERIFIED` ทุกข้อ (ตรงกับ ledger ที่ให้
`VERIFIED`/`VERIFIED_AS_REQUIREMENT`)

### 4.2 Repository facts (F-*)

| Claim ID | Verdict | Evidence | คำอธิบาย / Required action |
|---|---|---|---|
| F-001 | `VERIFIED` | `fusion_review_server.py:12,676,828,835` | ใช้ stdlib `ThreadingHTTPServer` ไม่ใช่ packaged desktop app |
| F-002 | `VERIFIED` | `fusion_review_server.py:560-579,812-826` | โหลด run directory เดียวตอน launch (`ReviewApp.__init__`, `main()`) |
| F-003 | `VERIFIED` | `fusion_review_server.py:519-545,577-578,620-644` | เก็บ decision เป็น `review_decisions.json`/`.csv` |
| F-004 | `VERIFIED` | `ocr_environment.py:76-101`; `fusion_review_server.py:820` | env helper กัน path ข้าม production/staging |
| F-005 | `VERIFIED` | `README.md` §Install, §Output Contract | Python 3.10/3.11 + OCR artifact contract |
| F-006 | `VERIFIED_WITH_CAVEAT` | `requirements.txt`; grep `.venv` | requirements.txt ไม่มี PySide6/SQLAlchemy/Alembic/pyodbc/pywin32/pytest-qt **จริง** — แต่ caveat: `.venv` **มี** `pywin32` (win32/win32com/pythonwin) และ `adodbapi` ติดตั้งอยู่แล้ว (transitive) แม้ไม่ประกาศใน requirements.txt |
| F-007 | `NOT_FOUND_IN_WORKSPACE` | grep five-schema names ⇒ hit เฉพาะ `docs/` 4 ไฟล์ (Bible/Brief-adjacent/Architecture/Ledger/Prompt), 0 hit ใน application code | five-schema ไม่ถูก implement ใน workspace นี้ |
| F-008 | `NEEDS_EXTERNAL_PROOF` | scope = current workspace only | ยังสรุปไม่ได้ว่าไม่มีใน external DB/branch อื่น (ดู U-001) |
| F-009 | `VERIFIED` | `git status --short` | Brief/Architecture untracked; `fusion_review_server.py` มี user modification |
| F-010 | `VERIFIED` | `fusion_review_server.py:548-557` | `confidence_to_unit()` หาร 100 เมื่อ >1.0 — corroborate Bible §8 rule 9 |

**สรุป F-*: ยืนยันทุกข้อ**; ปรับเพียง F-006 เป็น `VERIFIED_WITH_CAVEAT` เพราะ venv มี pywin32/adodbapi
ติดตั้งแล้ว (มีผลเชิงบวก: Win32/SQL-Server experimentation อาจเริ่มได้เร็วกว่าที่ ledger สื่อ)

### 4.3 Reported ADA observations (A-*)

หลักฐานใหม่จาก `adapos_receiving_probe.png` (visual inspection):

| Claim ID | Verdict | Evidence | คำอธิบาย / Required action |
|---|---|---|---|
| A-001 | `PARTIALLY_VERIFIED (upgraded)` | probe status bar `4.6006.30`; Brief `:354` `4.6006.0030` | version family ตรงด้วยภาพ; trailing-digit formatting ต่างเล็กน้อย ⇒ ยังต้อง machine-readable confirm exact build |
| A-002 | `NEEDS_EXTERNAL_PROOF` | probe title "เอด้าโพส-หลังร้าน 4.0 Hypermart" | ภาพไม่แสดง window class; VB6/`ThunderRT6MDIForm` พิสูจน์ไม่ได้จากภาพ (ต้อง Spy++/control dump — U-003) |
| A-003 | `NEEDS_EXTERNAL_PROOF` | — | นับ 116 controls จาก screenshot ไม่ได้ |
| A-004 | `PARTIALLY_VERIFIED` | probe: product grid มีจริง (teal alternating rows, คอลัมน์ รหัส/ชื่อ/หน่วย/จำนวน/ราคา/ส่วนลด/จำนวนเงิน) | grid *มีอยู่* แต่ class `ATL:034CF9A0` ยืนยันไม่ได้จากภาพ |
| A-005 | `PARTIALLY_VERIFIED (split)` | probe status bar `SQL: SERVER\sqlexpress/AdaAcc` | **DB identity (SQL Server Express, `AdaAcc`) ยืนยันด้วยภาพแล้ว**; แต่ "อ่าน product/supplier/history read-only ได้" ยังเป็น capability ที่ต้องพิสูจน์ (U-008/U-009) |
| A-006 | `NEEDS_EXTERNAL_PROOF` | — | Win32 header-control capture ยังไม่ probe จริง |
| A-007 | `VERIFIED (as stated)` | `adapos_receiving_probe.png` | ถูกต้องว่า "ภาพเดียวไม่พิสูจน์ control IDs/readback/save semantics" — ดู §9 |

**เพิ่มเติมจาก probe ที่ ledger ยังไม่บันทึก:** ปุ่ม `บันทึก`/`อนุมัติ`/`ยกเลิก` (save/approve/cancel)
*ปรากฏบน toolbar จริง*, VAT 7%, currency THB, สถานะ "เอกสาร ยังไม่อนุมัติ", user `dao1`, และ
**doc-number template `PRBCHYY-######`** (ต่างจาก Bible ERP receipt `PRXXXXX-XXXXXX` — คนละ identifier)

### 4.4 Interpretations (I-*)

| Claim ID | Verdict | คำอธิบาย |
|---|---|---|
| I-001 | `OWNER_DECISION_REQUIRED (แต่ความหมายชัด)` | Bible `:289-291` ใช้ `+` เชื่อม `document_links + line_links` เป็นหนึ่ง bullet ⇒ **5 conceptual groups = 6 physical relation names** ทั้งคู่จริงพร้อมกัน ไม่ใช่ความขัดแย้ง เป็นเพียง convention การนับ; owner แค่ ratify ว่า migration จะเรียก 5 หรือ 6 |
| I-002 | `VERIFIED (interpretation)` | five-schema เป็น knowledge/learning plane จริง (ground truth, alignment, alias, prediction log, review label) — ยืนยันจากบทบาทใน Bible §6-7,9 |
| I-003 | `NOT_FOUND_IN_WORKSPACE` | five-schema เป็น target design ไม่ใช่ implemented (F-007 + prototype ใช้ JSON/CSV) |
| I-004 | `VERIFIED (interpretation)` | HTTP prototype ไม่พอเป็น production backend: อ่าน run เดียว, ไม่มี DB/state-machine/idempotency/automation (`fusion_review_server.py:560-579`) — ตรงกับ Architecture §1.1 |
| I-005 | `PROPOSAL_ACCEPTABLE` | operational tables ควร "ครอบ" ไม่ rename/overwrite historical truth — เป็นหลักออกแบบที่ถูกและตรง Bible (learning truth immutable) |
| I-006 | `OWNER_DECISION_REQUIRED` | priority transition ระหว่าง Bible (10 มิ.ย.) กับ Brief/Architecture (21–22 ก.ค.) ต้อง owner รับรองก่อน migration เกิน five-schema — **นี่คือ decision ที่สำคัญที่สุด** |

### 4.5 Proposed architecture (P-*)

Verdict scale: `PROPOSAL_ACCEPTABLE` = เหมาะสมภายใต้ assumption ที่ระบุ; `PROPOSAL_REVISE` = ควรแก้ก่อน

| Claim ID | Verdict | คำอธิบาย / เงื่อนไข |
|---|---|---|
| P-001 | `PROPOSAL_ACCEPTABLE` | Windows-local modular monolith เหมาะกับ single-workstation-per-ADA (Architecture §2); ยืนยัน one-workstation assumption กับ owner (C-006) |
| P-002 | `PROPOSAL_ACCEPTABLE_WITH_SPIKE` | Python 3.11 x64 + PySide6 — reuse Python สมเหตุผล แต่ repo ยังไม่มี Qt prototype (C-005); ต้องทำ thin spike (U-013) และชั่งกับ local-web alternative ก่อน commit ระยะยาว |
| P-003 | `PROPOSAL_ACCEPTABLE` | 3-process boundary (host/OCR/ADA) แยก Win32/OCR hang ออกจาก UI/DB — safety design ที่ดี |
| P-004 | `PROPOSAL_ACCEPTABLE` | SQLite WAL operational DB เหมาะกับ local single writer; risk เฉพาะเมื่อหลาย workstation แชร์ queue (C-006/U-012) |
| P-005 | `PROPOSAL_ACCEPTABLE` | `ada_cache.db` read-only + live revalidation ก่อนส่ง — แยก cache จาก truth ถูกต้อง (Architecture §6.4) |
| P-006 | `PROPOSAL_ACCEPTABLE` | immutable artifact store + SHA-256/manifest — formalize สิ่งที่ pipeline ทำเป็นไฟล์อยู่แล้ว |
| P-007 | `PROPOSAL_ACCEPTABLE` | `documents/document_fields/document_lines` จำเป็นต่อ Inbox/Queue/Header/Line review; note: แม้ five-schema เองก็ implicit ต้องมี document entity (links อ้าง document) — แต่ต้องผ่าน governance ก่อนสร้าง (C-001) |
| P-008 | `PROPOSAL_ACCEPTABLE (stage-gated)` | `automation_runs/automation_events` จำเป็นต่อ ADA monitor/recovery/reconciliation แต่เป็น Phase 5-6; สร้างเมื่อ writer+reader พร้อม |
| P-009 | `PROPOSAL_ACCEPTABLE` | `audit_events` แยก security/safety action จาก training label — separation of concern ที่ถูก |
| P-010 | `PROPOSAL_ACCEPTABLE` | current projection mutable + events append-only — ตรง Bible (immutable prediction/label) |
| P-011 | `PROPOSAL_ACCEPTABLE` | เพิ่ม `document_id`/`document_line_id` ใน prediction + `current_prediction_id` pointer โดยไม่แก้ prediction เก่า — รักษา immutability |
| P-012 | `PROPOSAL_ACCEPTABLE` | `review_events` รองรับ header/line target + before/proposed/final + reversible + batch timing — ครบตาม R-010 |
| P-013 | `PROPOSAL_ACCEPTABLE` | alias candidate→eligible(3 distinct docs)→active(named approval) — ตรง Bible §6.5 (confirmation_count≥3, conflict quarantine) |
| P-014 | `PROPOSAL_ACCEPTABLE` | fill/save แยก command + one-use token ผูก revision/reconciliation/actor — บังคับ human confirm เชิงสถาปัตยกรรม เกินกว่าที่ Brief ขอ (ดีขึ้น) |
| P-015 | `PROPOSAL_ACCEPTABLE` | duplicate check 4 checkpoint (hash → business key → pre-fill live → pre-save) — ตรง Brief §4/§10 |
| P-016 | `PROPOSAL_ACCEPTABLE` | supplier profiles เป็น immutable JSON ก่อน แล้วค่อยทำ table เมื่อมี editor — เคารพ no-table-without-consumer อย่างถูกต้อง |
| P-017 | `PROPOSAL_ACCEPTABLE` | PyInstaller onedir + staging/prod แยก DB/artifacts/cache/credential/mutex — extend existing env pattern |
| P-018 | `PROPOSAL_ACCEPTABLE` | ไม่เพิ่ม dataset/model/shadow table ใน MVP — ตรง stage gates §4-5 |

**สรุป P-*: ไม่มีข้อใดควร reject** ข้อที่ต้องมีเงื่อนไขคือ P-002 (ต้อง spike + ชั่ง local-web) และ
ทุกข้อที่เพิ่ม table อยู่ใต้ governance gate ของ C-001

### 4.6 Conflicts (C-*)

| Claim ID | Verdict | จุดยืนของผม |
|---|---|---|
| C-001 | `OWNER_DECISION_REQUIRED` | จริงและสำคัญที่สุด: Bible five-schema-only vs Architecture operational tables Architecture *ไม่ได้* ฝ่าฝืนเงียบ ๆ — มันบอกให้ทำ Phase 0 + amend Bible ก่อน (Architecture §21) แต่ owner ต้องตัดสิน priority |
| C-002 | `PROPOSAL_RESOLUTION_ACCEPTABLE` | ML/dataset/shadow ถูก defer ถูกต้อง (Architecture §15,§23); MVP เก็บ label เท่านั้น — ไม่ขัด Bible |
| C-003 | `OWNER_DECISION_REQUIRED (cosmetic)` | 5 groups vs 6 relations — ดู I-001; ไม่ใช่ conflict เชิงเนื้อหา เป็น naming convention |
| C-004 | `RESOLVED_BY_ARCHITECTURE` | header correction ≠ Layer F product prediction — Architecture แก้ถูก: product ใช้ `prediction_id` (non-null), header ใช้ `document_field_id` + `source_prediction_ref`, มี CHECK constraint, ห้าม fake prediction (Architecture §6.2 `review_events`) นี่คือ minimal-schema solution ที่ถูกต้อง |
| C-005 | `OPEN — spike required` | PySide6 ยังไม่มี dependency/prototype ⇒ ต้อง thin vertical spike (U-013) และควรรวม local-web ในการเทียบ |
| C-006 | `OWNER_DECISION_REQUIRED` | SQLite local พอไหม ขึ้นกับ topology; owner ต้องยืนยัน one-workstation-per-ADA vs shared queue (U-012) |

### 4.7 Open proofs (U-*)

ทั้งหมดคง `OPEN`/`NEEDS_EXTERNAL_PROOF` ตาม ledger; probe image ให้ partial evidence เฉพาะบางข้อ

| Claim ID | Verdict | หมายเหตุจากการตรวจรอบนี้ |
|---|---|---|
| U-001 | `OPEN` | five-schema ใน external DB/branch — ต้อง inventory + read-only DDL |
| U-002 | `OPEN` | milestone ของ 5 priority เสร็จหรือยัง — ต้อง artifacts/metrics (block Bible amendment) |
| U-003 | `OPEN` | ADA version/process/class/control IDs — probe ให้เพียง version family + title |
| U-004 | `OPEN` | ATL grid keyboard order/commit/readback — probe เห็น grid ว่างเท่านั้น |
| U-005 | `OPEN` | product lookup/unit/popup behavior |
| U-006 | `OPEN` | row count/grand total readback reliability |
| U-007 | `OPEN` | save/approve/cancel/doc-number semantics — probe เห็นปุ่มมีอยู่ แต่ semantics ไม่ทราบ; note doc-number = `PRBCHYY-######` |
| U-008 | `OPEN` | AdaAcc schema + duplicate query — DB identity ยืนยันแล้ว (A-005) แต่ schema ยังไม่เห็น |
| U-009 | `OPEN` | least-privilege read-only credential |
| U-010 | `OPEN` | x64 Python ควบคุม VB6/ATL ครบไหม (Architecture §12.2 มีแผน x86 fallback) |
| U-011 | `OPEN` | `ADACallAPI.dll` contract — ยังไม่ควรใช้จนพิสูจน์ |
| U-012 | `OPEN` | workstation topology/identity policy — เกี่ยวกับ shared-login gap ใน §7 |
| U-013 | `OPEN` | PySide6 packaging/perf/Thai keyboard spike (100+ rows, DPI 100/125/150%) |

---

## 5. Five-schema interpretation

**รายการเดิม (Bible `:289-291`):** `erp_ground_truth`, `document_links` + `line_links`,
`supplier_product_aliases`, `layer_f_predictions`, `review_events`

- **Conceptual vs physical count:** 5 กลุ่มเชิงงาน = 6 relation names (เพราะ `document_links` และ
  `line_links` แยกกันแต่ถูกจับเป็นกลุ่มเดียวด้วย `+`) ทั้งสองคำอธิบายถูกพร้อมกัน (I-001/C-003)
- **Implemented vs not-found:** **not-found ใน workspace นี้** — 0 reference ใน application code,
  ไม่มี DB/migration (F-007) การไม่พบจำกัดที่ branch `main` commit `0dd5050` เท่านั้น (F-008/U-001)
- **Semantic responsibility ของแต่ละ table:**

| Table | Plane | หน้าที่ |
|---|---|---|
| `erp_ground_truth` | knowledge (historical truth) | approved ใบรับสินค้า line items = answer key; immutable |
| `document_links` | knowledge (alignment) | PDF ↔ ERP receipt link (deterministic, ≥99% precision) |
| `line_links` | knowledge (alignment) | OCR row ↔ ERP line link (≥2 of 3 signals) |
| `supplier_product_aliases` | knowledge (learned) | supplier text → product code; conflict quarantine |
| `layer_f_predictions` | prediction log | immutable prediction ก่อน display ทุก tier |
| `review_events` | label/audit | human confirm/correct + error_category + duration linked to prediction |

**ช่องว่างที่ Codex ระบุถูก:** five-schema ไม่มี *operational/current-state plane* (document status,
queue, automation run) ซึ่ง Brief §4/§9 ต้องใช้ ⇒ นี่คือเหตุผลที่ชอบธรรมของ P-007/P-008 แต่การเพิ่ม
ต้องผ่าน governance (C-001)

---

## 6. Impact of proposed operational schema

| Existing schema | Proposed relationship/change | Impact | Risk | Recommendation |
|---|---|---|---|---|
| `erp_ground_truth` | คงเป็น historical truth; links อ้าง record IDs | ต่ำ | นิยาม "approved" ใน external schema ยังไม่ตรวจ (U-008) | คงเดิม; ไม่ให้ live correction เขียนทับ |
| `document_links` | +FK → `documents.id`; คง method/version/evidence | ปานกลาง | backfill ห้ามเดา; ต้อง ≥99% gate | nullable FK ก่อน แล้ว verify sample ก่อน NOT NULL |
| `line_links` | +FK → `document_lines.id` | ปานกลาง | row identifier/layout เก่าเปลี่ยน | vertical slice เดียวกับ importer/verifier |
| `supplier_product_aliases` | รับ candidate จาก verified `review_events` ผ่าน projector (ไม่ activate จาก UI ตรง) | ต่ำ–ปานกลาง | double counting; distinct-document rule | idempotent projector; named approval ก่อน active |
| `layer_f_predictions` | +document/line context, candidates, provenance, evidence, version | ปานกลาง | ห้าม update history; unresolved tier ต้อง log ด้วย | immutable insert-only; test prediction-before-display |
| `review_events` | +header/line target, before/proposed/final, actor, duration, supersedes | ปานกลาง–สูง | header decision ไม่มี Layer F `prediction_id` | **แยก product `prediction_id` (non-null) กับ header `document_field_id`+`source_prediction_ref`** — Architecture แก้ถูกแล้ว (C-004) |

**คำวิจารณ์เฉพาะ `review_events` (ตามที่ ledger ขอ):** ข้อเสนอ Architecture §6.2 ถูกต้อง —
ใช้ตารางเดียวที่มี `prediction_id` nullable + target discriminator + CHECK constraint ให้ product
decision บังคับ `prediction_id` และ header decision ใช้ field FK เป็น minimal-schema solution;
ไม่ต้องสร้าง generic prediction table แยก และไม่ต้อง fake Layer F prediction สำหรับ header

---

## 7. Architecture critique

### What to keep (แข็งแรงและตรง Bible)
- Human-gated save ด้วย one-use token + fill/save แยก command (P-014) — เกินข้อกำหนด Brief ในทางที่ดี
- SELECT-only ADA gateway + startup mutation-keyword scan + DB permission เป็น safety ชั้นจริง (§12.1)
- Prediction-before-display เป็น transaction invariant (§9.2) — ตรง R-004
- Decimal/scaled-integer money + exact reconciliation (§10) — ตรง R-008 และ Bible §8 rule 9
- No-table-without-consumer เป็น just-in-time migration (§6.2) — เคารพ R-005
- Append-only events + supersedes สำหรับ retract (§6.1) — ตรง R-011
- Environment isolation extend `validate_environment_path()` เดิม (§16) — ต่อยอด F-004

### What to revise (ต้องแก้/เพิ่มเงื่อนไขก่อน)
1. **UI stack decision (P-002/C-005):** ต้อง thin spike ก่อน commit; และควรเทียบ **local-web UI**
   (FastAPI/stdlib + SQLite + browser, reuse `fusion_review_ui`) เป็นทางเลือกที่ ledger ยังไม่ได้ชั่ง
   ไม่ใช่แค่ PySide6 vs .NET/WPF — local-web ใช้ทักษะเดิมของทีมและ reuse UI ที่มีอยู่ ข้อเสียคือ
   keyboard-first high-density grid + Win32 focus/global-hotkey ทำใน native (PySide6) ได้ดีกว่า
2. **Reviewer identity gap:** §16 ใช้ Windows identity เป็น actor แต่ probe เห็น shared login `dao1`
   — ถ้าหลายพนักงานใช้ Windows session เดียว `reviewer_id` จะยุบเป็นคนเดียว ทำให้ per-reviewer
   metric/audit เพี้ยน ต้องมี app-level reviewer sign-in หรือ policy (โยงกับ U-012)
3. **ADA doc-number vs ERP receipt-number:** probe doc field = `PRBCHYY-######` ต่างจาก Bible ERP
   receipt `PRXXXXX-XXXXXX` — ต้องนิยามให้ชัดว่าเป็นคนละ identifier และ map อย่างไรใน reconciliation/
   duplicate (U-007)

### Simpler alternatives / tradeoffs
- **PySide6 vs local-web vs .NET/WPF:** ดูข้อ 1 ข้างบน — แนะนำให้ Phase 0 spike ตัดสินด้วยหลักฐาน
- **SQLite vs shared server DB:** SQLite พอสำหรับ 1 workstation; ถ้าหลายจุดรับของแชร์คิว ต้อง server DB
  (owner ตัดสิน — C-006/U-012)
- **JSON supplier profile vs DB:** JSON-first (P-016) เป็นทางที่ simpler และถูกต้องแล้ว

### Missing components / invariants
- Backup/retention มี mention (§17,§20) แต่ยังไม่มี explicit RPO/retention numbers
- Reviewer identity บน shared login (ข้อ 2)
- นิยาม ADA doc-number identifier (ข้อ 3)
- (เชิงบวก) OpenAI second-reader ที่มีอยู่ควรถูกบันทึกใน architecture ว่าเป็น OCR-reading เท่านั้น
  ไม่ใช่ matching-plane LLM เพื่อกันเข้าใจผิดว่าละเมิด §5

---

## 8. Governance and migration recommendation

### สิ่งที่ทำได้ก่อน amendment (ไม่ต้องรอ owner)
- Phase 0 proof: PySide6/local-web spike, ADA staging probe (U-003..U-011), read-only credential test
- เขียน adapter อ่าน OCR artifacts เดิม (ไม่แตะ pipeline)
- ออกแบบ identifier/FK ให้สอดคล้อง โดย**ยังไม่สร้าง migration**

### Milestone evidence ที่ต้องมีก่อนแก้ Bible (U-002)
- หลักฐานว่า 5 priority งาน (ERP extraction, alignment ≥99%, alias bootstrap, Layer F v1, review capture)
  เสร็จตาม acceptance — **หรือ** owner ประกาศเปลี่ยน priority อย่างเป็นทางการ
- ห้าม mark stage advanced หรือ mark first-five เสร็จโดยไม่มีหลักฐาน

### Amendment ที่เหมาะสม (เมื่อ owner ยืนยัน)
- เพิ่ม "operational plane" เป็น companion ที่ **ครอบ** ไม่ใช่แทน five-schema; ระบุว่า learning truth
  ยัง immutable; **ไม่เลื่อน stage number**; **ไม่ลบ first-five priority** — เพียงเพิ่มว่า Desktop MVP
  เป็น active work program คู่ขนาน (ถ้า owner เลือกเช่นนั้น)

### Safe migration order
- **ถ้า five-schema ยังไม่มี external impl:** vertical slice ตาม Architecture §21 (documents/fields/lines
  → predictions/review/alias → erp_ground_truth/links → automation → ada_cache) โดยลำดับจริงต้อง
  reconcile กับ Bible priority — ลำดับนี้เป็น software dependency ไม่ใช่อำนาจข้าม historical alignment
- **ถ้ามี external impl:** backup → สร้าง table ใหม่โดยไม่ rename/drop → nullable FK → backfill เฉพาะ
  exact/verifiable + report unmatched → verify sample → ยกเป็น NOT NULL/FK → deploy writer+reader
  พร้อมกัน → ห้าม dual-source-of-truth JSON/CSV↔DB แบบไม่มีกำหนด

---

## 9. ADA claims and external proof plan

**Verified จาก source/probe:**
- DB = SQL Server Express instance `SERVER\sqlexpress`, database `AdaAcc` (probe status bar) — A-005 (identity)
- ADA version family `4.6006.x` (probe) — A-001
- Receiving screen `ใบรับของ/ใบซื้อสินค้า` มีจริง; ปุ่ม save/approve/cancel และ product grid + VAT 7% มีจริง
- ผู้ใช้ที่เห็น = `dao1` (shared login signal)

**ยังต้อง probe จริง (staging) — machine-readable evidence:**
- VB6/`ThunderRT6MDIForm`, 116 controls, ATL class `034CF9A0` (U-003)
- ATL grid keyboard order/commit/readback (U-004)
- product lookup/unit/popup fingerprints (U-005)
- row count/grand total readback (U-006)
- save/approve/cancel + doc-number `PRBCHYY-######` semantics (U-007)
- AdaAcc schema + duplicate query + least-privilege credential (U-008/U-009)
- x64→VB6/ATL control feasibility (U-010); `ADACallAPI.dll` (U-011)

**หลักการ:** ห้ามรายงาน ADA capability ว่าผ่านจนแตะ staging ADA จริง; ใช้ Fake/Replay driver และ
feature-flag ปิด live capability จนมีหลักฐาน (ตรงกับ Architecture §19.4/§26)

---

## 10. Corrections to Codex statements

### MUST (ต้องแก้ก่อนถือว่าถูกต้อง)
- **ไม่มี** — ผมไม่พบ Codex statement ใดที่ผิดเชิงข้อเท็จจริงถึงระดับต้องแก้ ledger จัดประเภทและ verdict
  ได้ถูกต้อง

### SHOULD (ควรปรับให้แม่นขึ้น)
- **F-006:** ควรระบุ caveat ว่า `.venv` มี `pywin32`+`adodbapi` ติดตั้งแล้ว (แม้ไม่อยู่ requirements.txt)
  ⇒ ข้อความที่แม่นกว่า: "requirements.txt ยังไม่ประกาศ desktop/DB deps แต่ venv มี pywin32/adodbapi
  ติดตั้งเป็น transitive แล้ว"
- **A-005:** ควรแยกเป็นสองส่วน — DB **identity** `VERIFIED (visual)` vs read-only **access capability**
  `NEEDS_EXTERNAL_PROOF`
- **A-001:** ยกเป็น `PARTIALLY_VERIFIED (visual)` เพราะ probe แสดง `4.6006.30`

### COULD (เพิ่มได้เพื่อความครบ)
- บันทึก probe findings เพิ่ม: ปุ่ม save/approve/cancel ปรากฏจริง, doc-number `PRBCHYY-######`,
  shared user `dao1`, VAT 7%
- เพิ่ม claim ใหม่เรื่อง reviewer-identity-on-shared-login (governance/data-integrity gap)
- บันทึกว่ามี OpenAI second-reader อยู่แล้ว (OCR-reading, ไม่ใช่ matching LLM)
- เพิ่ม local-web UI เป็น alternative ใน C-005 tradeoff

---

## 11. Owner decisions required

1. **Priority (C-001/I-006) — สำคัญที่สุด:** Bible priority #1–2 คือ ERP extraction + alignment
   (learning foundation) แต่ Desktop MVP ให้ priority เป็น operational review + ADA entry
   → **ทางเลือก:** (ก) ทำ learning-foundation ก่อนตาม Bible เดิม; (ข) เปลี่ยน priority เป็น Desktop MVP
   แล้ว amend Bible ก่อน migration; (ค) ทำคู่ขนานโดยระบุ resource
   **ผลกระทบ:** กำหนดว่า table ชุดใดถูกสร้างก่อน และต้อง amend Bible หรือไม่
2. **Schema count convention (C-003/I-001):** เรียก "5 conceptual groups" หรือ "6 physical tables"?
   (cosmetic แต่ต้องล็อกก่อน migration review)
3. **UI stack (C-005):** PySide6 vs local-web (reuse `fusion_review_ui`) vs .NET/WPF — ตัดสินหลังเห็น
   ผล Phase 0 spike; **ผลกระทบ:** packaging, hiring/skill, accessibility, Win32 integration
4. **Workstation topology (C-006/U-012):** one-workstation-per-ADA หรือหลายจุดแชร์คิว?
   **ผลกระทบ:** SQLite local พอ หรือต้อง server DB + reviewer identity model
5. **Reviewer identity บน shared login:** ยอมรับ Windows-identity actor หรือบังคับ app sign-in?
   **ผลกระทบ:** ความถูกต้องของ per-reviewer metric/audit

---

## 12. Final recommendation

### `REVISE BEFORE IMPLEMENTATION`

**เหตุผล:** Architecture ของ Codex มีคุณภาพสูง สอดคล้อง Bible และแก้ปัญหายาก (C-004, human-gated save,
no-table-without-consumer) ได้ถูกทาง จึงเหมาะเป็นฐาน — แต่ยัง**ไม่ควรเขียน production code เกิน
foundation** จนกว่า:

1. **Owner ตัดสิน priority (C-001/I-006)** และ amend Bible ถ้าจำเป็น — มิฉะนั้นการสร้าง operational
   tables จะฝ่าฝืน source-of-truth (R-002/R-005)
2. **Phase 0 proofs ผ่าน:** PySide6/local-web spike (U-013) และ ADA staging probe (U-003..U-011)
   — capability ที่ยังไม่พิสูจน์ต้องเป็น explicit blocker/feature-flag ห้าม stub ที่รายงาน success
3. **ตรวจ external five-schema (U-001)** และ milestone (U-002) ก่อน migration/amendment

สิ่งที่เริ่มได้ทันทีโดยไม่ติด governance: OCR-artifact adapter, Phase 0 spikes/probes, identifier/FK
design (ยังไม่ migrate) ส่วน migration ที่เกิน five-schema **ต้องรอ owner decision**

---

## ก่อนจบ — integrity checks

- `git diff --check` (report file): ไม่มี whitespace error
- `git status --short` หลังเขียน: เพิ่มเฉพาะ `?? docs/CLAUDE_ARCHITECTURE_CORROBORATION_REPORT_TH.md`;
  ไฟล์เดิมที่ dirty (`fusion_review_server.py`) และ untracked อื่น ๆ **ไม่ถูกแตะ**
- ไม่มีการแก้ source code, Bible, Brief, Architecture หรือ ledger ในรอบนี้
- ADA capability ไม่มีข้อใดถูกรายงานว่า "ผ่าน" โดยไม่แตะ staging จริง; test ไม่มีการอ้างว่า run
- Report path: `docs/CLAUDE_ARCHITECTURE_CORROBORATION_REPORT_TH.md`
- Verdict หลัก: **REVISE BEFORE IMPLEMENTATION** — Architecture เป็นฐานได้ แต่ block ที่ governance
  (C-001) + Phase 0 proofs (U-*) ก่อนเขียน code เกิน foundation
