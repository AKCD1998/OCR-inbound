# OCR Inbound — Architecture Corroboration Ledger

Ledger ID: `OCR-INBOUND-ARCH-LEDGER-001`  
สร้างเมื่อ: 22 กรกฎาคม 2026  
สถานะ: `CROSS-REVIEWED — revise before implementation; awaiting owner decisions`  
วัตถุประสงค์: ให้ Codex, Claude และเจ้าของระบบตรวจข้อเท็จจริง ข้อกำหนด การตีความ และ
ข้อเสนอ architecture ด้วย claim ID และหลักฐานชุดเดียวกัน โดยไม่ทำให้ “สิ่งที่เสนอ” กลายเป็น
“สิ่งที่มีอยู่จริง” โดยอัตโนมัติ

---

## 1. วิธีอ่าน ledger นี้

Claim ทุกข้อถูกจัดเป็นหนึ่งในประเภทต่อไปนี้:

| ประเภท | ความหมาย |
|---|---|
| `SOURCE_REQUIREMENT` | ข้อกำหนดที่เขียนอยู่ใน Project Bible หรือ Design Brief |
| `REPO_FACT` | สิ่งที่ตรวจพบจากไฟล์/code/worktree ปัจจุบัน |
| `REPORTED_OBSERVATION` | ข้อเท็จจริงที่เอกสารรายงานว่าทดลองมาแล้ว แต่ผู้ตรวจรอบนี้ยังไม่ได้ทำซ้ำ |
| `INTERPRETATION` | ข้อสรุปจากการอ่าน source ซึ่งอาจต้องให้ owner ยืนยันความหมาย |
| `PROPOSAL` | Architecture/design decision ที่ยังไม่ได้ implement หรือ approve |
| `OPEN_PROOF` | สิ่งที่ต้องตรวจจาก external DB, ADA staging หรือเจ้าของระบบ |
| `CONFLICT` | source สองส่วนมี scope/date/ความหมายที่ต้อง reconcile |

Verdict ที่ผู้ตรวจใช้ได้:

| Verdict | ใช้เมื่อ |
|---|---|
| `VERIFIED` | หลักฐานตรงและทำซ้ำได้ |
| `VERIFIED_AT_SNAPSHOT` | จริงใน workspace/time snapshot ที่ระบุ แต่อาจเปลี่ยนตาม worktree/environment |
| `VERIFIED_VISUALLY` | ยืนยันได้เฉพาะสิ่งที่มองเห็นในภาพ ไม่รวม behavior/API/semantics |
| `VERIFIED_WITH_CAVEAT` | claim หลักจริง แต่มี context เพิ่มที่เปลี่ยนผลการตีความ |
| `PARTIALLY_VERIFIED` | ยืนยันได้เพียงบางส่วนหรือยืนยันได้แค่ว่าเอกสารกล่าวไว้ |
| `NOT_FOUND_IN_WORKSPACE` | ค้นใน workspace แล้วไม่พบ แต่ยังสรุปไม่ได้ว่าไม่มีภายนอก |
| `CONTRADICTED` | พบหลักฐานที่ขัดโดยตรง |
| `NEEDS_EXTERNAL_PROOF` | ต้องใช้ ADA, AdaAcc, credential, user decision หรือระบบภายนอก |
| `PROPOSAL_ACCEPTABLE` | ข้อเสนอเหมาะสมภายใต้ assumption ที่ระบุ |
| `PROPOSAL_ACCEPTABLE_WITH_SPIKE` | ข้อเสนอยอมรับได้เชิงทิศทาง แต่ต้องมี technical spike ก่อน commit |
| `PROPOSAL_REVISE` | ข้อเสนอควรแก้ก่อน implement |
| `OWNER_DECISION_REQUIRED` | เป็น priority/business authority ไม่ใช่เรื่องที่ code ตัดสินได้ |
| `RESOLVED` | conflict ได้รับคำตอบจากหลักฐานหรือ architecture contract แล้ว |
| `SUPERSEDED` | ถูกแทนที่ด้วย decision ที่ใหม่กว่าและมีบันทึกชัดเจน |

กฎการ corroborate:

1. ผู้ตรวจต้องอ่าน source files ก่อนอ่าน Codex conclusion เพื่อลด anchoring
2. ห้ามใช้ architecture document เป็นหลักฐานว่าสิ่งนั้น implement แล้ว
3. คำว่า “ไม่พบใน workspace” ห้ามยกระดับเป็น “ไม่มีอยู่จริงทุกระบบ”
4. ทุก `CONTRADICTED` ต้องมี file/line หรือ command output ที่ทำซ้ำได้
5. Architecture proposal ต้องประเมินทั้ง benefit, risk, simpler alternative และ stage gate
6. อย่าแก้ claim text เดิม ให้เพิ่ม verdict/report ใหม่เพื่อรักษาประวัติ

---

## 2. Source-of-truth precedence

เมื่อ source ขัดกัน ให้ใช้ลำดับนี้จนกว่า owner จะแก้เอกสาร authoritative:

1. `docs/PROJECT_BIBLE.md`
2. `docs/REVIEW_APP_DESIGN_BRIEF_TH.md`
3. `docs/DESKTOP_APP_ARCHITECTURE_TH.md`
4. `README.md`
5. Existing implementation และ artifacts

หมายเหตุ: implementation บอกว่า “ระบบทำอะไรอยู่” แต่ Project Bible บอกว่า “ระบบควรเดินไปทางไหน”
หากสองส่วนไม่ตรง ห้ามแก้เงียบ ๆ ต้องบันทึก conflict/amendment

---

## 3. Baseline workspace snapshot

Snapshot นี้เป็นข้อเท็จจริง ณ เวลาสร้าง ledger ไม่ใช่สถานะถาวร:

```text
git status --short
 M fusion_review_server.py
?? adapos_receiving_probe.png
?? docs/DESKTOP_APP_ARCHITECTURE_TH.md
?? docs/REVIEW_APP_DESIGN_BRIEF_TH.md
```

ข้อควรระวัง:

- ไฟล์ข้างต้นเป็นงานเดิม/งานใน session ห้ามผู้ตรวจลบหรือ revert
- ยังไม่พบ `AGENTS.md` ใน workspace ตอนตรวจครั้งแรก
- ยังไม่พบ `.db`, `.sqlite`, `.sqlite3`, `.sql`, `alembic.ini` หรือ migration file
- ยังไม่พบ code reference ของ five-schema names นอก `docs/` และ OCR artifacts ที่ exclude

คำสั่งทำซ้ำ:

```powershell
git status --short
rg --files -g 'AGENTS.md'
rg --files -g '*.db' -g '*.sqlite' -g '*.sqlite3' -g '*.sql' -g 'alembic.ini' -g '*migration*' -g '!ocr_runs*/**'
rg -n --glob '!docs/**' --glob '!ocr_runs*/**' --glob '!*.json' --glob '!*.csv' --glob '!*.html' 'erp_ground_truth|document_links|line_links|supplier_product_aliases|layer_f_predictions|review_events' .
```

หาก Claude พบฐานข้อมูลหรือ migrations เพิ่มภายหลัง ให้ลง timestamp/path/commit และเปลี่ยน verdict
ของ claim ที่เกี่ยวข้อง ห้ามลบ snapshot เดิม

---

## 4. Requirements and authority claims

| ID | Claim | ประเภท | หลักฐานตั้งต้น | Codex verdict | Claude verdict |
|---|---|---|---|---|---|
| R-001 | Project Bible ระบุ current stage เป็น Stage 1 → Stage 2 transition | `SOURCE_REQUIREMENT` | `docs/PROJECT_BIBLE.md:6` | `VERIFIED` | `VERIFIED` |
| R-002 | Current Priority วันที่ 10 มิ.ย. 2026 บอกให้งานห้าอันดับเสร็จก่อน งานอื่นเป็น secondary | `SOURCE_REQUIREMENT` | `docs/PROJECT_BIBLE.md:266-269` | `VERIFIED` | `VERIFIED` |
| R-003 | Bible ระบุ five-schema list ว่า `erp_ground_truth`, `document_links` + `line_links`, `supplier_product_aliases`, `layer_f_predictions`, `review_events` | `SOURCE_REQUIREMENT` | `docs/PROJECT_BIBLE.md:289-291` | `VERIFIED` | `VERIFIED` |
| R-004 | ห้ามแสดง Layer F prediction ก่อนเขียน `layer_f_predictions` row | `SOURCE_REQUIREMENT` | `docs/PROJECT_BIBLE.md:224-231` | `VERIFIED` | `VERIFIED` |
| R-005 | ห้ามสร้าง table ที่ sprint นี้ยังไม่มีทั้ง writer และ reader | `SOURCE_REQUIREMENT` | `docs/PROJECT_BIBLE.md:235-242` | `VERIFIED` | `VERIFIED` |
| R-006 | Current Layer F priority คือ exact code → alias → weak alias/fuzzy → human; ยังไม่ใช้ LLM/ML/embeddings | `SOURCE_REQUIREMENT` | `docs/PROJECT_BIBLE.md:281-287` | `VERIFIED` | `VERIFIED` |
| R-007 | MVP ต้องมีคนยืนยันก่อน save ADA และห้ามเขียนฐาน ADA โดยตรง | `SOURCE_REQUIREMENT` | `docs/REVIEW_APP_DESIGN_BRIEF_TH.md:350-371,447-455` | `VERIFIED` | `VERIFIED` |
| R-008 | MVP ต้อง reconcile row count และ grand total 100% ก่อน save | `SOURCE_REQUIREMENT` | `docs/REVIEW_APP_DESIGN_BRIEF_TH.md:309-314,423-430,447-456` | `VERIFIED` | `VERIFIED` |
| R-009 | MVP scope เริ่มจาก Top 3 suppliers และทีละหนึ่ง invoice | `SOURCE_REQUIREMENT` | `docs/REVIEW_APP_DESIGN_BRIEF_TH.md:20-28` | `VERIFIED` | `VERIFIED` |
| R-010 | Human correction ต้องเก็บ before/proposed/final, evidence, OCR confidence/versions, actor, duration และ error category | `SOURCE_REQUIREMENT` | `docs/REVIEW_APP_DESIGN_BRIEF_TH.md:208-279` | `VERIFIED` | `VERIFIED` |
| R-011 | Prediction/correction label ต้องถอนได้และ alias conflict ต้อง quarantine | `SOURCE_REQUIREMENT` | `docs/PROJECT_BIBLE.md:139-161`; Design Brief `:269-279` | `VERIFIED` | `VERIFIED` |
| R-012 | OCR Layers A–E เป็นของเดิมที่ทำงานอยู่และไม่ควรถูก redesign ในงานนี้ | `SOURCE_REQUIREMENT` | `docs/PROJECT_BIBLE.md:293-301,309-326`; `README.md` | `VERIFIED_AS_REQUIREMENT` | `VERIFIED` |

---

## 5. Current repository facts

| ID | Claim | ประเภท | หลักฐาน/วิธีทำซ้ำ | Codex verdict | Claude verdict |
|---|---|---|---|---|---|
| F-001 | Review prototype ใช้ Python stdlib `ThreadingHTTPServer` ไม่ใช่ packaged desktop app | `REPO_FACT` | `fusion_review_server.py:12,674-828` | `VERIFIED` | `VERIFIED` |
| F-002 | Prototype โหลด OCR artifacts จาก run directory เดียวที่ launch time | `REPO_FACT` | `fusion_review_server.py:560-579,809-826` | `VERIFIED` | `VERIFIED` |
| F-003 | Prototype เก็บ manual decisions ลง `review_decisions.json` และ `.csv` | `REPO_FACT` | `fusion_review_server.py:519-545,577-578,620-644` | `VERIFIED` | `VERIFIED` |
| F-004 | Environment helper มี production/staging roots และตรวจ path ไม่ให้ข้าม environment | `REPO_FACT` | `ocr_environment.py:12-100`; `fusion_review_server.py:819-825` | `VERIFIED` | `VERIFIED` |
| F-005 | README ระบุ Python 3.10/3.11 และ output contract ของ OCR artifacts | `REPO_FACT` | `README.md` sections Install, Output Contract | `VERIFIED` | `VERIFIED` |
| F-006 | `requirements.txt` ไม่ประกาศ PySide6, SQLAlchemy, Alembic, pyodbc, pywin32 หรือ pytest-qt; แต่ current `.venv` มีบาง package นอกไฟล์ requirements | `REPO_FACT` | `requirements.txt`; import probe + `pip freeze` 2026-07-22 | `VERIFIED_WITH_CAVEAT` | `VERIFIED_WITH_CAVEAT` |
| F-007 | ใน workspace snapshot ยังไม่พบ implementation/migration ของ five-schema names | `REPO_FACT` | คำสั่งใน §3 คืน no matches | `NOT_FOUND_IN_WORKSPACE` | `NOT_FOUND_IN_WORKSPACE` |
| F-008 | การไม่พบ five-schema ใน repo ยังพิสูจน์ไม่ได้ว่าไม่มี external DB หรือ branch อื่น | `REPO_FACT` | ขอบเขตการค้นมีเพียง current workspace | `NEEDS_EXTERNAL_PROOF` | `NEEDS_EXTERNAL_PROOF` |
| F-009 | Design Brief และ Architecture เป็น untracked files ณ snapshot; `fusion_review_server.py` มี user modification | `REPO_FACT` | `git status --short` ใน §3 | `VERIFIED_AT_SNAPSHOT` | `VERIFIED` |
| F-010 | Existing review server มี `confidence_to_unit()` ที่ normalizeค่ามากกว่า 1 ด้วยการหาร 100 | `REPO_FACT` | `fusion_review_server.py:548-557` | `VERIFIED` | `VERIFIED` |

F-006 environment detail ที่ Codex ตรวจซ้ำหลังอ่าน Claude report:

- พบ: `pywin32 312`, `pywinauto 0.6.9`, `pyodbc 5.3.0`; import `adodbapi` ได้จาก pywin32
- ไม่พบ: `PySide6`, `sqlalchemy`, `alembic`, `pytestqt`
- ข้อสรุป: เริ่ม Win32/ODBC spike ได้เร็วขึ้น แต่ dependency ยังไม่ reproducible จนกว่าจะ lock ใน project config

---

## 6. Reported ADA observations and current proof level

บาง claim ยกระดับได้จาก visual probe แล้ว แต่ต้องแยกสิ่งที่ “มองเห็นในภาพ” ออกจาก
behavior/API/control class/database permission ซึ่งยังต้อง repeatable machine-readable proof:

| ID | Claim | ประเภท | แหล่งรายงาน | Codex verdict | Claude verdict |
|---|---|---|---|---|---|
| A-001 | ADA POS Back exact version ตาม Brief คือ `4.6006.0030`; probe image แสดง `4.6006.30` | `REPORTED_OBSERVATION` | Brief `:352-360`; probe status bar | `PARTIALLY_VERIFIED` | `PARTIALLY_VERIFIED` |
| A-002 | ADA เป็น VB6 และ main class คือ `ThunderRT6MDIForm` | `REPORTED_OBSERVATION` | Design Brief `:354-356`; ภาพไม่แสดง class | `NEEDS_EXTERNAL_PROOF` | `NEEDS_EXTERNAL_PROOF` |
| A-003 | Receiving screen มีประมาณ 116 controls | `REPORTED_OBSERVATION` | Design Brief `:357`; ภาพนับ controls ไม่ได้ | `NEEDS_EXTERNAL_PROOF` | `NEEDS_EXTERNAL_PROOF` |
| A-004 | Receiving screen มี product grid; Brief รายงาน custom ATL class `ATL:034CF9A0` | `REPORTED_OBSERVATION` | Probe เห็น grid; class ต้อง control dump | `PARTIALLY_VERIFIED` | `PARTIALLY_VERIFIED` |
| A-005 | Compound claim เดิม: DB identity และ read-only data access | `REPORTED_OBSERVATION` | ถูกแยกเป็น A-005a/A-005b | `SUPERSEDED` | `SUPERSEDED` |
| A-005a | Status bar แสดง SQL instance `SERVER\sqlexpress` และ database `AdaAcc` | `REPORTED_OBSERVATION` | `adapos_receiving_probe.png` visual inspection โดย Claude + Codex | `VERIFIED` | `VERIFIED` |
| A-005b | App สามารถอ่าน product/supplier/history จาก AdaAcc แบบ read-only ได้ | `REPORTED_OBSERVATION` | Brief `:359-360`; ยังไม่มี query/permission proof | `NEEDS_EXTERNAL_PROOF` | `NEEDS_EXTERNAL_PROOF` |
| A-006 | Header controls จับผ่าน Win32 ได้ | `REPORTED_OBSERVATION` | Design Brief `:356,362-370`; ภาพไม่พิสูจน์ API access | `NEEDS_EXTERNAL_PROOF` | `NEEDS_EXTERNAL_PROOF` |
| A-007 | `adapos_receiving_probe.png` เป็น evidence ของค่าที่มองเห็น แต่ภาพเดียวไม่พิสูจน์ control IDs/readback/save semantics | `REPORTED_OBSERVATION` | visual inspection โดย Claude + Codex | `VERIFIED` | `VERIFIED` |
| A-008 | Form แสดง template เลขเอกสาร ADA `PRBCHYY-######` ซึ่งต่างจาก ERP receipt format `PRXXXXX-XXXXXX` ใน Bible | `REPORTED_OBSERVATION` | probe image; Bible `docs/PROJECT_BIBLE.md:305` | `VERIFIED_VISUALLY`; mapping/semantics ยังเปิด | `VERIFIED_VISUALLY` |
| A-009 | Probe แสดงปุ่มบันทึก/อนุมัติ/ยกเลิก, VAT 7.00%, THB, สถานะยังไม่อนุมัติ และ field ผู้บันทึก `dao1` | `REPORTED_OBSERVATION` | `adapos_receiving_probe.png` | `VERIFIED_VISUALLY`; behavior/shared-identity ไม่ได้พิสูจน์ | `VERIFIED_VISUALLY` |

---

## 7. Session interpretations that require corroboration

| ID | Interpretation | เหตุผล/หลักฐาน | Codex verdict | Claude verdict |
|---|---|---|---|---|
| I-001 | “First five schema objects” เป็นห้ากลุ่มเชิงงาน แต่ถ้านับชื่อ relation ตามตัวอักษรมีหกชื่อ เพราะ `document_links` และ `line_links` แยกกัน | Bible `:289-291` ใช้เครื่องหมาย `+` | `OWNER_DECISION_REQUIRED` | `OWNER_DECISION_REQUIRED` |
| I-002 | Five-schema เดิมเป็น knowledge/learning plane มากกว่า operational workflow plane | หน้าที่ของ ground truth, alignment, alias, prediction, review events ใน Bible | `INTERPRETATION` | `VERIFIED` |
| I-003 | Five-schema น่าจะยังเป็น target design ไม่ใช่สิ่งที่ implement ใน current workspace | F-007 + prototype ยังใช้ JSON/CSV | `NOT_FOUND_IN_WORKSPACE`; external caveat | `NOT_FOUND_IN_WORKSPACE` |
| I-004 | Review HTTP prototype ไม่เพียงพอเป็น production desktop backend ตาม requirement ใหม่ | ไม่มี queue DB/state machine/automation/idempotency และอ่าน run เดียว | `INTERPRETATION` | `VERIFIED` |
| I-005 | Desktop operational tables ควร “ครอบ” five-schema เดิม ไม่ rename/replace หรือเขียนทับ historical truth | ต้องแยก current projection จาก immutable learning/audit | `INTERPRETATION` | `PROPOSAL_ACCEPTABLE` |
| I-006 | Project Bible dated 10 มิ.ย. กับ Design Brief dated 21 ก.ค. มี priority transition ที่ owner ต้องรับรองก่อน migration เพิ่ม | Bible บอก first five only; Brief ต้องใช้ Document/Automation state | `OWNER_DECISION_REQUIRED` | `OWNER_DECISION_REQUIRED` |

---

## 8. Proposed architecture decisions

ข้อเหล่านี้มาจาก `docs/DESKTOP_APP_ARCHITECTURE_TH.md` และยังเป็น proposal จนกว่า owner/Claude
review จะรับรอง ไม่ใช่ repo fact

| ID | Proposal | จุดประสงค์ | Codex verdict | Claude verdict |
|---|---|---|---|---|
| P-001 | Windows-local offline-first modular monolith | ลด deployment/operations complexity สำหรับ workstation + ADA instance เดียว | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-002 | Python 3.11 x64 + PySide6 Qt Widgets | reuse OCR Python และใช้ `QTableView` สำหรับ keyboard-first review | `PROPOSAL` | `PROPOSAL_ACCEPTABLE_WITH_SPIKE` |
| P-003 | แยก host, OCR worker, ADA worker เป็นสาม process boundaries | ป้องกัน OCR/Win32 hang ทำ UI/DB เสียหาย และรองรับ safe stop | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-004 | `app.db` เป็น SQLite WAL operational source of truth | transaction, migration, recovery และ local deployment | `PROPOSAL` | `PROPOSAL_ACCEPTABLE`; ขึ้นกับ C-006 |
| P-005 | `ada_cache.db` แยกเป็น refreshable read-only cache และ live revalidate ก่อน ADA | search เร็วโดยไม่ถือ cache เป็น ADA truth | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-006 | Filesystem artifact store เก็บ immutable source/OCR/evidence/screenshots | ไฟล์ใหญ่ไม่ปน relational state และตรวจ checksum ได้ | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-007 | เพิ่ม `documents`, `document_fields`, `document_lines` | current projection, Inbox/Queue/Review state และ document revision | `PROPOSAL` | `PROPOSAL_ACCEPTABLE`; stage-gated C-001 |
| P-008 | เพิ่ม `automation_runs`, `automation_events` | preflight, row checkpoints, popup/failure, reconciliation, recovery | `PROPOSAL` | `PROPOSAL_ACCEPTABLE`; Phase 5–6 only |
| P-009 | เพิ่ม `audit_events` | safety/security action history ที่ไม่ควรปนกับ training label | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-010 | Current projections mutable แต่ predictions/review/automation/audit events append-only | รักษา UI current state พร้อม reproducible history | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-011 | `layer_f_predictions` เพิ่ม `document_id`/`document_line_id`; `document_lines.current_prediction_id` ชี้ล่าสุด | เชื่อม prediction กับ operational row โดยไม่ update prediction เก่า | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-012 | `review_events` รองรับ header/line targets, before/proposed/final, reversible label และ batch interaction timing | ทำ labeled dataset และ metrics ครบ | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-013 | Alias activation: candidate → eligible หลัง 3 distinct documents → active หลัง named approval | ป้องกัน one-off human error กลายเป็น permanent truth | `PROPOSAL_ALIGNED_WITH_BIBLE` | `PROPOSAL_ACCEPTABLE` |
| P-014 | ADA fill และ ADA save เป็นคนละ command; save ใช้ one-use token ผูก revision/reconciliation/actor | บังคับ human confirmation ทาง architecture ไม่ใช่แค่ UI wording | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-015 | Duplicate check ที่ file hash, หลัง extraction, ก่อน fill และก่อน save | ลด race/duplicate จากข้อมูลที่รู้ไม่พร้อมกัน | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-016 | Supplier profiles เริ่มเป็น immutable versioned JSON; สร้าง table เมื่อมี editor writer+reader จริง | ทำ deterministic Top 3 rules โดยไม่ฝ่าฝืน no-table-without-consumer | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-017 | PyInstaller `onedir` + installer; staging/prod แยก DB/artifacts/cache/credentials/mutex | deploy/recovery และ environment safety | `PROPOSAL` | `PROPOSAL_ACCEPTABLE` |
| P-018 | ไม่เพิ่ม dataset/model/shadow tables ใน MVP | เคารพ stage gates และ anti-overengineering | `PROPOSAL_ALIGNED_WITH_BIBLE` | `PROPOSAL_ACCEPTABLE` |
| P-019 | Phase 0 UI spike ต้องเปรียบเทียบ PySide6 กับ local-web ที่ reuse `fusion_review_ui` และ .NET/WPF ด้วย workload เดียวกัน | ลดการ commit stack จากความชอบก่อนมี performance/keyboard/packaging evidence | `PROPOSAL_FROM_CROSS_REVIEW` | `PROPOSAL_ACCEPTABLE_WITH_SPIKE` |

---

## 9. Impact ledger: proposed additions vs original five-schema

| Existing schema | สิ่งที่เสนอให้คงเดิม | สิ่งที่เสนอให้เพิ่ม/เปลี่ยน | ระดับผลกระทบ | Risk ที่ต้องตรวจ |
|---|---|---|---|---|
| `erp_ground_truth` | Approved ERP history เป็น historical truth ไม่ให้ live correction เขียนทับ | ให้ `document_links`/`line_links` อ้าง record IDs | ต่ำ | External schema/approval definition ยังไม่ตรวจ |
| `document_links` | Deterministic high-precision document alignment | เพิ่ม FK ไป `documents.id`; เก็บ method/version/evidence ต่อไป | ปานกลาง | Backfill ห้ามเดา; ≥99% precision gate |
| `line_links` | High-precision OCR-line ↔ ERP-line alignment | เพิ่ม FK ไป `document_lines.id` | ปานกลาง | Old row identifiers/layout changes |
| `supplier_product_aliases` | Supplier-specific alias + conflict quarantine | รับ candidate evidence จาก verified live `review_events` ผ่าน projector ไม่ใช่ UI direct activation | ต่ำ–ปานกลาง | Double counting, distinct-document rule, human approval |
| `layer_f_predictions` | Immutable prediction written before display | เพิ่ม document/line context, candidates/provenance/evidence/version | ปานกลาง | ห้าม update history; unresolved tier ต้อง log ด้วย |
| `review_events` | Append-only human labels linked to prediction | เพิ่ม header/line target, before/proposed/final, actor, duration, evidence, supersedes | ปานกลาง–สูง | Header OCR decision อาจไม่มี Layer F `prediction_id`; contract ต้องกำหนดให้ชัด |

ข้อเสนอสำหรับ `review_events` ที่ Claude ต้องวิจารณ์เป็นพิเศษ:

- Product decision: `prediction_id` ต้องไม่เป็น null
- Header extraction decision: อ้าง `document_field_id` + immutable OCR `source_prediction_ref`
- ใช้ CHECK constraint ให้ target เป็น field หรือ line อย่างถูกต้อง
- ห้ามบังคับสร้าง fake Layer F prediction สำหรับ header เพียงเพื่อให้ FK ผ่าน

---

## 10. Proposed migration and ownership plan

### Gate 0 — ตรวจของจริงก่อน

1. ตรวจว่า five-schema มีใน external database, private branch หรือเครื่องอื่นหรือไม่
2. ขอ DDL/schema dump แบบ read-only หากมี
3. ตรวจ milestone evidence ว่างานห้าอันดับใน Bible เสร็จจริงหรือยัง
4. Owner ตัดสินว่า Current Priority เปลี่ยนเป็น Desktop MVP แล้วหรือไม่
5. ถ้าเปลี่ยน ให้ amend Project Bible ก่อน migration ที่เกิน five-schema

### หาก five-schema ยังไม่มี implementation

ออกแบบ identifiers/foreign keys ให้สอดคล้องกันตั้งแต่ต้น แต่สร้าง migration แบบ vertical slice:

1. `documents`, `document_fields`, `document_lines` พร้อม Inbox/Review writer+reader
2. `layer_f_predictions`, `review_events`, `supplier_product_aliases` พร้อม matching/review writer+reader
3. `erp_ground_truth`, `document_links`, `line_links` เมื่อ historical importer/alignment verifier พร้อม
4. `automation_runs`, `automation_events`, `audit_events` เมื่อ ADA preflight/monitor พร้อม
5. `ada_cache.db` แยก physical database และ refresh แบบ atomic

ลำดับจริงต้อง reconcile กับ Project Bible priority; รายการนี้เป็น dependency order ของ software
ไม่ใช่อำนาจให้ข้าม historical alignment work

### หาก five-schema มีอยู่ภายนอกแล้ว

1. Backup/snapshot และตรวจ PK/type/constraints/index/data quality
2. สร้าง operational tables ใหม่โดยไม่ rename/drop ของเดิม
3. เพิ่ม nullable references ก่อน เช่น `document_id`, `document_line_id`
4. Backfill เฉพาะ exact/verifiable mappings พร้อม report unmatched
5. ตรวจ sample และ constraints ก่อนยกระดับเป็น `NOT NULL`/FK
6. Deploy writer และ reader ใน vertical slice เดียวกัน
7. ห้าม dual-source-of-truth ระหว่าง JSON/CSV กับ DB แบบไม่มีกำหนด

### Transaction ownership

- Desktop host เป็น writer ของ `app.db` เพียงรายเดียวใน proposal
- OCR/ADA workers ส่ง event/result กลับ ไม่เขียน operational tables ตรง
- การ update current field/line + increment document revision + insert review event ต้อง atomic
- Alias projector อ่าน verified events และ update candidate counters แบบ idempotent
- Automation อ่าน frozen document revision/snapshot; ห้ามแก้ review dataระหว่าง active run

---

## 11. Conflicts and decisions requiring owner

| ID | Conflict/decision | หลักฐาน | ผลถ้าไม่จัดการ | Proposed resolution | สถานะ |
|---|---|---|---|---|---|
| C-001 | Bible ยังบอก five-schema only แต่ Desktop architecture เสนอ operational tables เพิ่ม | Bible `:266-291`; Architecture §6 | Sonnet อาจฝ่าฝืน source of truth หรือหยุดงานกลางทาง | ตรวจ milestone แล้ว amend Bible โดย named owner | `OPEN` |
| C-002 | Design Brief กล่าวถึง long-term ML/dataset/shadow mode แต่ Bible ห้ามสร้างก่อน stage gates | Brief `:250-281`; Bible §§4-5,8-9 | Overengineering/poisoned data | MVP เก็บ labels เท่านั้น; defer model tables/UI | `RESOLVED` |
| C-003 | “five schema objects” แต่มี relation names หกชื่อเมื่อแยก links | Bible `:289-291` | Naming/count confusion ใน migration review | Owner ratify convention: five conceptual groups / six physical relations | `OWNER_DECISION_REQUIRED`; cosmetic |
| C-004 | Review events linked to prediction แต่ header correction ไม่ใช่ Layer F product prediction | Bible `:285-287`; Brief field corrections | เสี่ยง fake prediction หรือ null semantics ไม่ชัด | Product ใช้ non-null `prediction_id`; header ใช้ `document_field_id` + immutable `source_prediction_ref` + CHECK constraint | `RESOLVED` |
| C-005 | Architecture เลือก PySide6 แต่ repo ยังไม่มี dependency/prototype ของ Qt | requirements + Architecture §1; P-019 | Packaging/skills/accessibility/reuse tradeoff | Thin spike เปรียบเทียบ PySide6, local-web reuse และ .NET/WPF ด้วยเกณฑ์เดียวกัน | `OPEN — SPIKE REQUIRED` |
| C-006 | SQLite local assumption อาจไม่พอหากหลาย workstation ต้องแชร์ queue | Brief ระบุ Windows Desktop แต่ไม่ยืนยัน concurrency deployment | Data split/conflict ในอนาคต | Owner ยืนยัน one-workstation-per-ADA-instance และ shared-data roadmap | `OPEN` |
| C-007 | Architecture ใช้ Windows identity เป็น actor แต่ ADA probe แสดง field ผู้บันทึก `dao1`; ยังไม่รู้ว่าเป็นบัญชีเฉพาะบุคคลหรือ shared | Probe visual + Architecture §16 | Audit/per-reviewer metrics อาจผูกผิดคน | Owner/IT กำหนด unique reviewer identity, app sign-in หรือ operating policy ที่ตรวจสอบได้ | `OWNER_DECISION_REQUIRED` |

---

## 12. Open proof register

| ID | ต้องพิสูจน์ | วิธีพิสูจน์ขั้นต่ำ | Block อะไร | สถานะ |
|---|---|---|---|---|
| U-001 | Five-schema มีใน external DB/branch หรือไม่ | inventory + read-only DDL/schema dump | Migration plan | `OPEN` |
| U-002 | Five-priority milestone เสร็จตาม acceptance หรือยัง | artifacts, sample verification, metrics | Bible amendment/stage advance | `OPEN` |
| U-003 | ADA version/process/class/control IDs | repeatable probe + machine-readable control dump | Live driver profile | `OPEN` |
| U-004 | ATL grid keyboard order/commit/readback | staging scripted trials + screenshots/log | Draft line entry/resume | `OPEN` |
| U-005 | Product lookup/unit/popup behavior | popup fingerprints + fault cases | Safe automation | `OPEN` |
| U-006 | Reliable row count/grand total readback | 30-document staging observations | Reconciliation/save | `OPEN` |
| U-007 | Save/approve/cancel/document-number semantics และ mapping `PRBCHYY-######` ↔ ERP `PRXXXXX-XXXXXX` | staging runbook + before/after DB/UI observation | Human-gated save/recovery/completion receipt | `OPEN`; probe ยืนยันเพียงสิ่งที่มองเห็น |
| U-008 | AdaAcc schema และ duplicate query | SELECT-only schema/query review | Product cache/live duplicate check | `OPEN` |
| U-009 | Least-privilege read-only AdaAcc credential | permission test proving mutation denied | Production connection | `OPEN` |
| U-010 | x64 Python ควบคุม VB6/custom ATL ครบหรือไม่ | x64 worker probe; x86 helper only if required | Worker packaging | `OPEN` |
| U-011 | `ADACallAPI.dll` contract และควรใช้หรือไม่ | vendor docs/export/interface probe | Optional future adapter only | `OPEN` |
| U-012 | Workstation topology/multi-user policy | owner/IT decision | SQLite location, shared queue, locking | `OPEN` |
| U-013 | UI stack packaging/performance/Thai keyboard suitability | same 100+ row workflow spike บน PySide6/local-web/.NET, DPI 100/125/150% | UI stack approval | `OPEN` |
| U-014 | Unique reviewer identity เมื่อ Windows/ADA account อาจใช้ร่วมกัน | ทดลองกับผู้ใช้จริง + owner/IT policy + audit prototype | Per-reviewer metrics, correction attribution, save authorization | `OPEN` |
| U-015 | RPO, backup frequency, audit/artifact retention และ restore time | owner/IT/legal decision + restore drill | Production operations/runbook | `OPEN` |

---

## 13. Claude corroboration report contract

Claude สร้างรายงานแยกตาม contract แล้วที่:

`docs/CLAUDE_ARCHITECTURE_CORROBORATION_REPORT_TH.md`

รายงานต้องมี:

1. Reviewer/model/date/workspace commit or status
2. Files inspected และ commands run
3. Verdict ต่อ claim ID `R-*`, `F-*`, `A-*`, `I-*`, `P-*`, `C-*`, `U-*`
4. Evidence แบบ `file:line` และ command result
5. ข้อที่ Codex เล่าถูก, ถูกบางส่วน, เกินหลักฐาน หรือผิด
6. Architecture gaps/duplicate tables/simpler alternatives
7. ผลกระทบต่อ original five-schema
8. Proposed corrections แยกเป็น must/should/could
9. รายการที่ต้อง owner decision หรือ external proof
10. ห้าม implement app code ในรอบ verification

Codex ทำ reconciliation รอบสองตามขั้นตอนนี้แล้ว:

- อ่าน report โดยไม่แก้ report ของ Claude
- เพิ่ม cross-review record ใน §14
- resolve เฉพาะ claim ที่มีหลักฐานหรือ owner decision
- แก้ Architecture/Brief/Bible เป็น patch แยกตาม authority
- ledger claim เดิมไม่ลบ; ใช้ change log และ `SUPERSEDED`

---

## 14. Reviewer records

| Reviewer | Role | วันที่ | Report | สถานะ |
|---|---|---|---|---|
| Codex | Initial claim extraction and proposal author | 2026-07-22 | Architecture + ledger นี้ | `COMPLETE` |
| Claude | Independent cold-start verifier | 2026-07-22 | `docs/CLAUDE_ARCHITECTURE_CORROBORATION_REPORT_TH.md` | `COMPLETE — REVISE BEFORE IMPLEMENTATION` |
| Codex | Cross-review reconciler + independent probe/.venv recheck | 2026-07-22 | Ledger update; source docs unchanged | `COMPLETE` |
| Owner | Priority/business authority | — | Owner decisions for `C-*`/`U-*` | `PENDING` |

### Cross-review record — 2026-07-22

Agreements:

- Claude corroborated `R-001..R-012` and `F-001..F-010`; F-006 has environment caveat
- Five-schema implementation remains `NOT_FOUND_IN_WORKSPACE`, not “proven absent externally”
- No proposed architecture item P-001..P-018 was rejected; P-002 requires comparative spike
- C-004 is resolved without fake prediction: product and header evidence use separate references
- No Codex statement reached a Claude `MUST` correction

Stronger evidence accepted after Codex recheck:

- Probe visually confirms version family `4.6006.x`, SQL display
  `SERVER\sqlexpress/AdaAcc`, product grid presence, doc-number template `PRBCHYY-######`, visible
  save/approve/cancel controls, VAT 7.00%, THB, not-approved status and recorder field `dao1`
- Probe does **not** establish exact window/control classes, read-only query capability, popup/readback,
  button semantics, or that `dao1` is shared by multiple humans
- `.venv` contains pywin32/pywinauto/pyodbc and importable adodbapi, although these are not locked in
  `requirements.txt`; PySide6/SQLAlchemy/Alembic/pytest-qt remain absent

Cross-review final recommendation: `REVISE BEFORE IMPLEMENTATION` — retain architecture as a base,
but resolve governance C-001 and run Phase 0 proofs before implementing beyond an approved foundation
slice

---

## 15. Corroboration summary

สถานะปัจจุบัน:

- Source requirements และ current repo facts ผ่าน independent cross-review แล้ว
- Five-schema implementation ยัง `NOT_FOUND_IN_WORKSPACE`; external existence/milestone ยังเปิด
- ADA visual observations บางส่วนยกระดับแล้ว แต่ behavior/API/schema/permission ยังต้อง Phase 0 proof
- C-004 resolved; C-001/C-003/C-006/C-007 รอ owner และ C-005 รอ comparative UI spike
- Desktop architecture ผ่านเชิงทิศทาง แต่ verdict ยังเป็น `REVISE BEFORE IMPLEMENTATION`
- ยังไม่อนุมัติ patch ต่อ Bible/Brief/Architecture ใน ledger update นี้

---

## 16. Change log

| วันที่ | ผู้แก้ | การเปลี่ยนแปลง | เหตุผล/หลักฐาน |
|---|---|---|---|
| 2026-07-22 | Codex | สร้าง ledger version แรกจาก session และ current workspace inspection | ผู้ใช้ขอ cross-model corroboration artifact |
| 2026-07-22 | Claude | สร้าง independent report พร้อม verdict ทุก claim ID | Blind-first source review ตาม cold-start prompt |
| 2026-07-22 | Codex | Reconcile Claude report; split A-005, strengthen A-001/F-006, add A-008/A-009, P-019, C-007, U-014/U-015 และ reviewer record | Claude report + Codex visual probe and `.venv` import/package recheck |

---

## 17. Owner authorization and goal implementation record — 2026-07-22

Owner authority for this record is the submitted decision block in
`docs/SOL_LIGHT_ONE_GOAL_BUILD_PROMPT_TH.md`. It is limited to the staging MVP goal and does not
authorize production activation, direct AdaAcc writes, or ADA production Save/Approve.

| Decision | Superseding disposition for this goal | Evidence/status |
|---|---|---|
| C-001 | `RESOLVED — AUTHORIZED` | Operational staging companion may wrap the learning plane; Project Bible §9.1 added without changing stage or first-five priority. No first-five milestone is claimed. |
| C-003 | `RESOLVED — RATIFIED` | Use “5 conceptual schema groups / 6 physical learning-plane tables”; links are one conceptual alignment group and two physical tables. |
| C-005 | `SPIKE IN PROGRESS` | PySide6, local-web reuse, and .NET/WPF must use the same 100+ row fixture and evidence before ADR selection. |
| C-006 | `RESOLVED — RATIFIED FOR MVP` | One Windows workstation per ADA instance; local SQLite single writer; shared queue remains a non-goal requiring new review. |
| C-007 | `RESOLVED — STAGING BOUNDARY` | `IdentityProvider` required; named staging reviewer is allowed but is not production authentication. Production identity remains blocked for owner/IT. |

Reviewer/decision record:

| Reviewer | Role | วันที่ | Record | สถานะ |
|---|---|---|---|---|
| Owner | Goal-scoped business authority | 2026-07-22 | `SOL_LIGHT_ONE_GOAL_BUILD_PROMPT_TH.md` decision block | `AUTHORIZED AS LIMITED ABOVE` |
| Codex | Persistent implementation agent | 2026-07-22 | Goal `019f8845-c096-7621-85f7-803fcbfbfebc` | `IMPLEMENTATION IN PROGRESS` |

Change-log continuation:

| วันที่ | ผู้แก้ | การเปลี่ยนแปลง | เหตุผล/หลักฐาน |
|---|---|---|---|
| 2026-07-22 | Codex | Record goal-scoped owner decisions; resolve C-001/C-003/C-006/C-007 and keep C-005 at `SPIKE IN PROGRESS` | Submitted one-goal build prompt; Project Bible §9.1 |

### Phase B result — C-005 / P-002 / P-019

The same `ui-spike.v1` workload (120 Thai rows plus `evidence_invoice.svg`) was applied to all three
options. PySide6 could not execute because the dependency is absent (explicit exit 3); WPF could not
compile because the .NET SDK is absent (explicit exit 127); local-web executed with the existing
Python/browser toolchain, bounded DOM virtualization, keyboard commands, adjacent evidence, and no
new runtime dependency. Chrome headless screenshot capture failed and is not claimed as visual proof.

- C-005: `RESOLVED — LOCAL-WEB SELECTED FOR STAGING MVP`
- P-002: `SUPERSEDED FOR THIS GOAL` by ADR-002 local-web desktop
- P-019: `RESOLVED` with `spikes/ui_comparison/EVIDENCE.md`
- Revisit trigger: measured Thai/DPI/keyboard/accessibility acceptance failure in the packaged app.
