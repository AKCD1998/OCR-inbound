# OCR Inbound — Dev Laptop Setup & CPU-only Fusion OCR Verification Ledger

Ledger ID: `OCR-INBOUND-DEVSETUP-LEDGER-001`
สร้างเมื่อ: 20 สิงหาคม 2026 (โดย Claude, ยังไม่มี Codex pass)
Scope: SCPRODUCTDEV laptop เท่านั้น — clone + isolated `.venv` (Python 3.11) + Tesseract/Poppler/
Ghostscript + smoke test + OCR run บนเอกสารตัวอย่าง synthetic หนึ่งฉบับ
สถานะ: `CLAUDE-ASSERTED — awaiting Codex corroboration`
วัตถุประสงค์: ให้ Codex ตรวจซ้ำ claim การติดตั้ง/การรัน OCR รอบนี้แบบเดียวกับ
[`ARCHITECTURE_CORROBORATION_LEDGER_TH.md`](ARCHITECTURE_CORROBORATION_LEDGER_TH.md) —
claim ID + หลักฐานที่ทำซ้ำได้ + verdict column แยกต่อคนตรวจ ไม่ใช่ prose summary
ที่เชื่อได้อย่างเดียว

ความสัมพันธ์กับ ledger อื่น: ไฟล์นี้ตรวจ **สภาพแวดล้อมเครื่อง + ผลลัพธ์ OCR ดิบ** เท่านั้น
ไม่แตะ architecture/schema claims ใน `ARCHITECTURE_CORROBORATION_LEDGER_TH.md` — ถ้า Codex
พบว่า claim ใดในไฟล์นี้เกี่ยวพันกับ decision ใน ledger นั้น ให้ cross-link ด้วย ID แทนการ copy เนื้อหา

---

## 1. วิธีอ่าน ledger นี้

ใช้ประเภท claim และ verdict vocabulary ชุดเดียวกับ
`ARCHITECTURE_CORROBORATION_LEDGER_TH.md` §1 (`SOURCE_REQUIREMENT`, `REPO_FACT`,
`REPORTED_OBSERVATION`, `INTERPRETATION`, `PROPOSAL`, `OPEN_PROOF`, `CONFLICT`; verdict
`VERIFIED` / `VERIFIED_AT_SNAPSHOT` / `VERIFIED_WITH_CAVEAT` / `PARTIALLY_VERIFIED` /
`NOT_FOUND_IN_WORKSPACE` / `CONTRADICTED` / `NEEDS_EXTERNAL_PROOF` ฯลฯ) เพิ่มอีกหนึ่ง
verdict สำหรับ ledger นี้โดยเฉพาะ:

| Verdict | ใช้เมื่อ |
|---|---|
| `SELF_REPRODUCED` | Claude รันคำสั่งซ้ำเองในรอบเดียวกันแล้วได้ผลตรงกับที่รายงาน (ยังไม่ใช่ independent corroboration) |

กฎเพิ่มเติมสำหรับ ledger นี้:

1. ทุก claim ต้องมีคำสั่งที่ Codex รันซ้ำได้บนเครื่องเดียวกัน (SCPRODUCTDEV) — ห้ามอ้างอิง
   "ผมเห็นแล้ว" โดยไม่มี command/log path
2. ทุก path ที่อ้างต้องเป็น absolute path บนเครื่องจริง ไม่ใช่ path สมมติ
3. Claude verdict ทั้งหมดในไฟล์นี้เป็น `SELF_REPRODUCED` เป็นอย่างมาก — ยังไม่มีคนอื่นตรวจซ้ำ
   ห้ามยกระดับเป็น `VERIFIED` จนกว่า Codex หรือ owner จะรันคำสั่งเองแล้วได้ผลตรงกัน
4. ถ้า Codex รันคำสั่งแล้วได้ผลต่าง ให้บันทึกเป็น `CONTRADICTED` พร้อม output จริง ห้ามแก้ claim เดิม

---

## 2. Baseline

```text
Repo:        C:\Users\scgro\Desktop\Webapp training project\OCR-inbound
origin/main: f3bea3fb41dd8592b1eb75533575488820a4c094  (HEAD ยังตรงกันหลังงานรอบนี้)
git status --short: ?? environments/   (ดู D-010)
Laptop:      SCPRODUCTDEV, Windows 11, Git 2.52.0, Python 3.12.10 (system) + 3.11.9 (ติดตั้งใหม่)
```

ไม่มีการ commit/push/แก้ requirements/source/docs ใน repo ระหว่างงานรอบนี้ (ก่อนสร้างไฟล์นี้) —
`HEAD` ยังเป็น commit เดียวกับตอน clone

---

## 3. Environment setup claims (S-)

| ID | Claim | ประเภท | หลักฐาน/คำสั่งทำซ้ำ | Claude verdict | Codex verdict |
|---|---|---|---|---|---|
| S-001 | Python 3.11.9 ติดตั้งแบบ per-user ที่ `C:\Users\scgro\AppData\Local\Programs\Python\Python311\python.exe`; Python 3.12.10 ที่เป็น default เดิมไม่ถูกแตะ | `REPO_FACT` | `& "C:\Users\scgro\AppData\Local\Programs\Python\Python311\python.exe" --version` → `Python 3.11.9`; `python --version` (default) → `Python 3.12.10` | `SELF_REPRODUCED` | |
| S-002 | `.venv` ใน repo สร้างจาก Python 3.11.9 ตัวที่ยืนยันแล้ว ไม่ใช่ 3.12 | `REPO_FACT` | `& ".\.venv\Scripts\python.exe" --version` → `Python 3.11.9` | `SELF_REPRODUCED` | |
| S-003 | `pip install -r requirements.txt` ติดตั้งครบ 95 packages ไม่มี dependency conflict, exit code 0, ใช้ CPU wheel ของ torch/torchvision/paddlepaddle เท่านั้น ไม่มี CUDA package | `REPO_FACT` | pip log บรรทัดสุดท้าย `Successfully installed ... [exited with code 0]`; ตรวจ `torch==2.2.2+cpu`, `torchvision==0.17.2+cpu`, `paddlepaddle==3.2.2` (ไม่ใช่ `paddlepaddle-gpu`) ใน `.venv\Lib\site-packages\*.dist-info` | `SELF_REPRODUCED` | |
| S-004 | `torch.cuda.is_available()` คืนค่า `False` บนเครื่องนี้ | `REPO_FACT` | `.\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"` → `False` | `SELF_REPRODUCED` | |
| S-005 | Tesseract 5.5.3 ติดตั้งที่ `C:\Program Files\Tesseract-OCR\tesseract.exe` ผ่าน `winget install tesseract-ocr.tesseract`; ตัว winget package ไม่ได้เพิ่ม PATH หรือแถม `tha.traineddata` มาด้วย | `REPO_FACT` | `& "C:\Program Files\Tesseract-OCR\tesseract.exe" --version` → `tesseract v5.5.3.20260724`; `Get-ChildItem "C:\Program Files\Tesseract-OCR\tessdata" -Filter *.traineddata` → มีแค่ `eng`, `osd` ตอนติดตั้งเสร็จใหม่ ๆ | `SELF_REPRODUCED` | |
| S-006 | `tha.traineddata` ถูกดาวน์โหลดจาก `https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/tha.traineddata` (1,072,600 bytes) มาไว้ที่ `C:\Users\scgro\AppData\Local\Tesseract-OCR\tessdata\` เพราะ `C:\Program Files\Tesseract-OCR\tessdata\` เขียนไม่ได้โดยไม่ elevate | `REPO_FACT` | `Get-Item "C:\Users\scgro\AppData\Local\Tesseract-OCR\tessdata\tha.traineddata"` → 1072600 bytes; write-test ไปที่ `C:\Program Files\Tesseract-OCR\tessdata\` คืน `Access denied` | `SELF_REPRODUCED` | |
| S-007 | `TESSDATA_PREFIX` ถูกตั้งแบบ persistent ที่ User scope ชี้ไปโฟลเดอร์ user tessdata ด้านบน และ `tesseract --list-langs` เห็นครบ `eng`, `osd`, `tha` เมื่อ env var ถูกตั้ง | `REPO_FACT` | `[Environment]::GetEnvironmentVariable("TESSDATA_PREFIX","User")`; `tesseract --list-langs` → 3 languages | `SELF_REPRODUCED` | |
| S-008 | Tesseract install directory ถูกเพิ่มเข้า **User** PATH (ไม่แตะ Machine PATH) เพราะ winget ไม่ได้เพิ่มให้อัตโนมัติ | `REPO_FACT` | `[Environment]::GetEnvironmentVariable("Path","User")` มี `C:\Program Files\Tesseract-OCR`; `[Environment]::GetEnvironmentVariable("Path","Machine")` ไม่มี | `SELF_REPRODUCED` | |
| S-009 | Poppler 25.07.0 ติดตั้งผ่าน `winget install oschwartz10612.Poppler`; winget เพิ่ม Machine PATH ให้เองสำเร็จ (ต่างจาก Tesseract) | `REPO_FACT` | winget output "Path environment variable modified"; `[Environment]::GetEnvironmentVariable("Path","Machine")` มี `...poppler-25.07.0\Library\bin` | `SELF_REPRODUCED` | |
| S-010 | Ghostscript ไม่มีบน winget community repo ภายใต้ publisher ใด ๆ ที่ค้นเจอ (`winget search ghostscript/Artifex/gs10071` ล้วน no match) | `REPORTED_OBSERVATION` | `winget search "Ghostscript"`, `winget search "Artifex"` ผลไม่มี official Ghostscript ID | `SELF_REPRODUCED` | |
| S-011 | Ghostscript 10.07.1 ติดตั้งจาก official installer ที่ดาวน์โหลดตรงจาก GitHub release `ArtifexSoftware/ghostpdl-downloads` tag `gs10071`, asset `gs10071w64.exe`; รันแบบ `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` ค้าง (คาดว่าติด elevation prompt ที่ non-interactive session ตอบไม่ได้) เกิน 120s window แรก แต่จบเองด้วย exit code 0 ในเวลาต่อมา และไฟล์จริงอยู่ที่ `C:\Program Files\gs\gs10.07.1\bin\gswin64c.exe` | `REPO_FACT` | background task log: `ExitCode: 0`; `& "C:\Program Files\gs\gs10.07.1\bin\gswin64c.exe" --version` → `10.07.1` | `SELF_REPRODUCED` | **ควรตรวจซ้ำเป็นพิเศษ** — Claude ไม่เห็น log ระหว่างช่วงที่ค้าง จึงไม่รู้แน่ชัดว่า process ผ่าน prompt ไปได้อย่างไร มีแค่ exit code 0 กับ binary ที่ใช้งานได้จริงเป็นหลักฐาน |
| S-012 | 7-Zip 26.02 ถูกติดตั้งผ่าน winget เป็นเครื่องมือช่วย (ใช้แค่ตรวจสอบว่า extract installer ได้โดยไม่ต้องรัน ก่อนรู้ว่า S-011 จบเองแล้ว); ไฟล์ที่ extract ด้วยมือถูกลบทิ้งหลังยืนยันว่า real installer สำเร็จแล้ว ไม่เหลือ `AppData\Local\Ghostscript` | `REPO_FACT` | `Get-ChildItem "C:\Program Files\7-Zip"` มี `7z.exe`; `Test-Path "C:\Users\scgro\AppData\Local\Ghostscript"` → `False` | `SELF_REPRODUCED` | |

---

## 4. Automated verification claims (V-)

| ID | Claim | ประเภท | หลักฐาน/คำสั่งทำซ้ำ | Claude verdict | Codex verdict |
|---|---|---|---|---|---|
| V-001 | Import smoke test ผ่านครบ 9 โมดูล (`torch, paddle, paddleocr, easyocr, cv2, pytesseract, fitz, pdfplumber, camelot`) exit code 0 | `REPO_FACT` | สคริปต์ทดสอบชั่วคราวรันแล้วลบทิ้ง (ไม่ commit); output แต่ละโมดูลพิมพ์ `OK` | `SELF_REPRODUCED` | |
| V-002 | `unittest discover -s tests -t .` กับ `-W error::ResourceWarning` และ `PYTHONPATH=src` ผ่าน 37/37, 20.4s, ไม่มี ResourceWarning | `REPO_FACT` | `Ran 37 tests in 20.431s / OK`, exit code 0 | `SELF_REPRODUCED` | |
| V-003 | `scripts\safety_scan.py` (ต้องมี `PYTHONPATH=src`) คืน `secret_scan: pass`, `findings: []`, `ada_query_catalog: pass`, `live_flags_default_off: true` — รันซ้ำสองครั้ง (หลัง pip install และหลัง OCR run จริง) ได้ผลเดิมทั้งสองครั้ง | `REPO_FACT` | JSON output ตรงกันทั้งสองรอบ | `SELF_REPRODUCED` | |
| V-004 | `git status` สะอาดตลอดงาน setup phase; ไม่มี PDF/ocr_runs/model cache/credential ถูก track โดย git | `REPO_FACT` | `git status --porcelain` ว่างก่อนรัน OCR; `git ls-files \| grep -iE "\.pdf$\|ocr_runs\|\.pt$\|credential\|secret\|\.env$"` ไม่มีผลลัพธ์ | `SELF_REPRODUCED` | |

---

## 5. Sample OCR run claims (R-)

**เอกสารตัวอย่าง:** ไม่มี PDF จริงในเครื่องหรือ session นี้ จึงใช้ synthetic fixture ที่มีอยู่แล้วใน
repo (`tests/fixtures/ocr_top3/woothi/invoice.svg`) ซึ่ง `docs/STAGING_RUNBOOK.md:36` เรียกไว้ชัดเจนว่า
"contract examples, not production ground truth" — ไม่มีข้อมูลลูกค้า/ซัพพลายเออร์จริงใด ๆ

| ID | Claim | ประเภท | หลักฐาน/คำสั่งทำซ้ำ | Claude verdict | Codex verdict |
|---|---|---|---|---|---|
| R-001 | `invoice.svg` render เป็น PNG ผ่าน headless Chrome แล้วแปลงเป็น PDF ด้วย PyMuPDF ก่อนป้อนเข้า `ocr_feasibility.py` — ไม่ได้แก้ fixture เดิม | `REPO_FACT` | `environments/staging/inbound/sample_invoice_woothi.{png,pdf}` (untracked, ดู D-010); fixture ต้นฉบับ `git status` ไม่แสดงว่าถูกแก้ | `SELF_REPRODUCED` | |
| R-002 | `ocr_feasibility.py .\environments\staging\inbound\sample_invoice_woothi.pdf --env staging --out .\ocr_runs_staging` จบด้วย exit code 0, ทุก engine status เป็น `ok` ยกเว้น `openai: disabled` | `REPO_FACT` | `ocr_runs_staging/sample_invoice_woothi_4fd1c7859c/report.md` §Engine Status | `SELF_REPRODUCED` | |
| R-003 | Pipeline ไม่เคยเรียก OpenAI/external LLM ระหว่างรันนี้ (`--openai` flag ไม่ได้ใช้, ไม่มี `OPENAI_API_KEY` ตั้งไว้ในรอบนี้) | `REPO_FACT` | คำสั่งที่รันจริงไม่มี `--openai`; `ocr/openai/openai.json` ว่างตาม report `OpenAI did not produce second-reader output: disabled` | `SELF_REPRODUCED` | |
| R-004 | ผลลัพธ์ raw ต่อ engine ตรงตามที่สรุปใน field-comparison artifact (ดู §6) — โดยเฉพาะ Tesseract ถูกต้อง exact บน 3/5 region, EasyOCR ไม่เคยสลับบรรทัดแต่ทำตัวพิมพ์เล็กและอ่าน `.`/`,` สลับกัน, PaddleOCR (en model) อ่าน Thai glyph เป็น Latin noise | `REPORTED_OBSERVATION` | ไฟล์ `.txt` ดิบใต้ `ocr_runs_staging/sample_invoice_woothi_4fd1c7859c/ocr/{tesseract,paddle,easyocr}/` — ดู path เฉพาะใน §6 | `SELF_REPRODUCED` | |
| R-005 | ไม่มีขั้นตอนใดใน session นี้เขียน/พยายามเขียนเข้า ADA, AdaAcc, หรือ production endpoint ใด ๆ | `REPO_FACT` | `git log`/`git status` ไม่มี commit ใหม่; ไม่มีการเรียก `ocr_inbound` CLI/`run_staging.ps1`/ADA worker ใน session นี้เลย — เฉพาะ `ocr_feasibility.py` ซึ่งเป็นคนละ layer จาก ADA companion app | `SELF_REPRODUCED` | |

---

## 6. Field-comparison artifact (T-)

| ID | Claim | ประเภท | หลักฐาน/คำสั่งทำซ้ำ | Claude verdict | Codex verdict |
|---|---|---|---|---|---|
| T-001 | Comparison table (ภาพจริง → OCR raw ต่อ engine → normalized → product candidate → คำตอบมนุษย์) เผยแพร่เป็น Claude Artifact ที่ `https://claude.ai/code/artifact/75f41c86-ee3a-4bd9-9590-03ffda40a0a1` — เป็น manual walk-through ของ Layer F exact-code/alias-gate logic ตาม Bible §9, **ไม่ได้เรียก Layer F service จริง** | `PROPOSAL` (ตัวอย่างการนำ logic ไปใช้ ไม่ใช่ implementation) | เปิด URL แล้วเทียบ crop image กับ `ocr_runs_staging/.../pages/page-0001.png` และ `.txt` ใต้ `ocr/{tesseract,paddle,easyocr}/` โดยตรง | `SELF_REPRODUCED` | |
| T-002 | Row 3 (เซทิริซีน) ไม่มีรหัสสินค้าพิมพ์อยู่บนภาพต้นฉบับเลย ต่างจาก row 1/2 ที่มีรหัส `630XXXX`; artifact จึงให้ verdict "ต้องตรวจสอบด้วยคน" สำหรับ row 3 เท่านั้น ตาม exact-code gate ใน Bible | `SOURCE_REQUIREMENT` + `REPO_FACT` | ต้นฉบับ SVG บรรทัดที่ 3 ไม่มี `630XXXX` prefix (เทียบกับบรรทัด 1–2); `docs/PROJECT_BIBLE.md` §6.5 alias conflict rule + §9 exact-code gate | `SELF_REPRODUCED` | |

---

## 7. Open items / caveats สำหรับ Codex

| ID | รายละเอียด | ประเภท |
|---|---|---|
| D-001 | S-011 (Ghostscript) เป็น claim ที่ Claude มั่นใจน้อยที่สุดในไฟล์นี้ — ไม่รู้กลไกที่ทำให้ installer ผ่าน elevation ไปได้เองแบบ non-interactive ขอให้ Codex (หรือ owner) รัน `gswin64c --version` เองอีกครั้งบนเครื่องเดียวกันเพื่อตัด edge case ที่ install ค้างครึ่งเดียว | `OPEN_PROOF` |
| D-002 | `environments/staging/inbound/sample_invoice_woothi.png` เป็น **untracked แต่ไม่ได้อยู่ใน `.gitignore`** ต่างจาก `.pdf` พี่น้องมันที่ถูก ignore แล้ว — ไม่มีความเสี่ยงจริงเพราะไม่มีการ `git add`/`commit` ใด ๆ ในรอบนี้ แต่ Codex ควรตัดสินใจว่าจะเพิ่ม pattern ใน `.gitignore` หรือปล่อยไว้ | `OPEN_PROOF` |
| D-003 | ทุก claim ในไฟล์นี้มาจาก session เดียวของ Claude ล้วน ๆ ยังไม่มี Codex หรือ owner รันคำสั่งใดซ้ำเลย — ห้ามอ้างว่า setup นี้ "verified" จนกว่า Codex column จะถูกเติม | `OPEN_PROOF` |
| D-004 | `run_staging.ps1` และ `ocr_inbound` CLI (ตัว staging companion app จริง) **ยังไม่ได้ถูกรันเลย** ใน session นี้ — สิ่งที่ทดสอบคือ `ocr_feasibility.py` (Layers A–E) เท่านั้น ถ้า Codex หรือ owner ต้องการ verify companion app แบบ end-to-end ต้องรันแยกตาม `docs/STAGING_RUNBOOK.md` | `OPEN_PROOF` |

---

## 8. Repro commands (สำหรับ Codex รันรวด)

```powershell
# S-001, S-002
& "C:\Users\scgro\AppData\Local\Programs\Python\Python311\python.exe" --version
cd "C:\Users\scgro\Desktop\Webapp training project\OCR-inbound"
& ".\.venv\Scripts\python.exe" --version

# S-004
& ".\.venv\Scripts\python.exe" -c "import torch; print(torch.cuda.is_available())"

# S-005 .. S-008
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --version
$env:TESSDATA_PREFIX = "C:\Users\scgro\AppData\Local\Tesseract-OCR\tessdata"
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs

# S-009
& "C:\Users\scgro\AppData\Local\Microsoft\WinGet\Packages\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe\poppler-25.07.0\Library\bin\pdftoppm.exe" -v

# S-011
& "C:\Program Files\gs\gs10.07.1\bin\gswin64c.exe" --version

# V-002, V-003
$env:PYTHONPATH = "src"
& ".\.venv\Scripts\python.exe" -W error::ResourceWarning -m unittest discover -s tests -t .
& ".\.venv\Scripts\python.exe" ".\scripts\safety_scan.py"

# V-004
git status --porcelain
git ls-files | Select-String -Pattern "\.pdf$|ocr_runs|\.pt$|credential|secret|\.env$"

# R-002 output ที่มีอยู่แล้ว (ไม่ต้องรันซ้ำเว้นแต่ต้องการ reproduce จากศูนย์)
Get-Content ".\ocr_runs_staging\sample_invoice_woothi_4fd1c7859c\report.md"
```

---

*ไฟล์นี้บันทึกโดย Claude เพียงฝ่ายเดียว ณ วันที่สร้าง — ทุก verdict เป็น `SELF_REPRODUCED`
ไม่ใช่ independent verification จนกว่า Codex จะเติมคอลัมน์ของตัวเอง ตามกฎเดียวกับ
`ARCHITECTURE_CORROBORATION_LEDGER_TH.md`*

## 9. Codex corroboration — Phase E against full product master (2026-08-20)

| ID | Claim | Evidence | Codex verdict |
|---|---|---|---|
| R-006 | Product master ที่ใช้ตรวจรอบนี้มาจาก Render PostgreSQL host `dpg-d6apu9i4d50c73c7sas0-a.virginia-postgres.render.com`, database `sc_drug_db`; session ถูกบังคับ read-only และตรวจ `transaction_read_only=on` แล้ว | read-only preflight จาก `DATABASE_URL` ใน PaaSRTSM admin-api โดยไม่พิมพ์ credential | CONFIRMED |
| R-007 | แหล่งข้อมูลที่เหมาะสมคือ `public.skus` ร่วมกับ `public.items` และ `public.barcodes`: 6,880 SKU ทั้งหมด, 6,477 active; export แบบ flattened ได้ 17,860 แถว SKU/barcode | read-only SQL count และ export สำหรับ cache ชั่วคราว | CONFIRMED |
| R-008 | ใช้ `ProductMatcher._predict()` เดิมกับ OCR 9 บรรทัด ได้ 0 auto-confirm, 1 plausible fuzzy suggestion ที่ยังต้องให้คนตรวจ, 2 wrong matches และ 6 unresolved | `FULL_MASTER_LAYER_F_RESULTS.json`, CSV/MD/HTML ใน run `realinv_20260820T040631Z` | CONFIRMED |
| R-009 | ปัญหาหลักรอบนี้ไม่ใช่ master ไม่มีสินค้า: master มี MINIDIAB=`IC-000648`, RELESTAT=`IC-004874`, LESFLAM=`IC-002137`, CODIPHEN=`IC-001962` แต่ matcher ยังเชื่อมชื่อการค้าอังกฤษกับชื่อไทยไม่ได้; regex internal-code ปัจจุบันยังไม่ครอบคลุม code จริงแบบ `IC-` 6 หลักและ `630` 9 หลัก | source read ของ `matching.py` + read-only lookup ใน full master | CONFIRMED |
| R-010 | ไม่มีการ rerun OCR, ไม่มี database write, ไม่มี ADA/AdaAcc contact, ไม่มี commit/push; เปลี่ยนเฉพาะ local evaluation artifacts และ ledger | scope/status verification | CONFIRMED |

หมายเหตุ: fuzzy suggestion `630010124` สำหรับยาแก้ไอน้ำดำ 120 มล. ถูกจัดเป็น “ต้องให้มนุษย์ตรวจ” ไม่ใช่ auto-confirm ส่วน `IC-000645` และ `IC-002801` เป็น wrong matches และห้ามนำไปบันทึกอัตโนมัติ

### Correction R-011 — product-name source used by the live branch-stock UI

R-008/R-009 ข้างต้นใช้ `public.skus.display_name` เป็นชื่อหลัก จึงไม่ใช่การจำลองหน้า production ที่ถูกต้องและให้ถือว่าผล 0/1/2/6 ถูกถอนแล้ว ภาพ production จากมนุษย์นำไปสู่การตรวจ source ซ้ำ พบว่า `GET /api/branch-stock` เลือก `COALESCE(bs.product_name_eng, p.product_name)` และข้อมูลจริงอยู่ใน `ada.branch_stock_snapshots.product_name_eng` จำนวน 6,661 จาก 6,665 แถว

รันใหม่ด้วย `ada.branch_stock_snapshots` แบบ read-only และ `ProductMatcher._predict()` เดิม ได้ผล: 0 auto-confirm, 1 correct-but-review (`IC-002137` LESFLAM), 5 wrong fuzzy matches และ 3 unresolved การมีชื่ออังกฤษแก้ catalog-coverage gap แต่ยังยืนยันว่า fuzzy ranking ปัจจุบันไม่ปลอดภัยพอสำหรับ auto-match โดยเฉพาะ MINIDIAB, ISOTRATE, PRESOLIN และ CODIPHEN

---

## 10. Sonnet corroboration — Layer F v2 trade-name matcher (2026-08-20)

**สถานะ: CANDIDATE — awaiting Codex corroboration.** รายงานฉบับเต็ม (สาเหตุ, algorithm,
OLD/NEW matrix, test counts, revert-check, residual risks) อยู่ที่
`ocr_runs_staging/realinv_20260820T040631Z/CANDIDATE_REPORT_TRADE_NAME_MATCHER.md`

| ID | Claim | Evidence | Claude verdict | Codex verdict |
|---|---|---|---|---|
| S-101 | เพิ่ม tier ใหม่ `TRADE_NAME_MATCH` ระหว่าง `EXACT_BARCODE` กับ `ACTIVE_ALIAS` ใน `src/ocr_inbound/matching.py`; tier นี้ไม่เคย auto-confirm (auto-confirmable set ยังเป็น `{EXACT_CODE, EXACT_BARCODE, ACTIVE_ALIAS}` เดิม ไม่ได้ขยาย); bump `RULESET_VERSION` เป็น `layer-f-v2` | `git diff src/ocr_inbound/matching.py` | SELF_REPRODUCED | |
| S-102 | แก้ `INTERNAL_CODE` regex ให้รองรับ `IC-` 4-6 หลัก และ `630` ตามด้วย 4-6 หลัก (เดิมรองรับแค่ 4 หลักคงที่ทั้งคู่) พร้อม test ป้องกัน partial-match ในสตริงเลขยาวต่อเนื่อง | `tests/test_matching.py::InternalCodeRegexTests` (7 tests, ผ่านหมด) | SELF_REPRODUCED | |
| S-103 | พบและแก้ bug เดิม (ไม่เกี่ยวกับงานที่ขอ แต่เจอระหว่างรัน Phase E จริง): `candidate_set[0]` เคยไม่ตรงกับ `proposed_product_code` ได้เมื่อ fuzzy pool คำนวณแยกจาก tier ที่ resolve จริง — เห็นชัดกับ master ~6,700 รายการ ไม่เห็นบน fixture เล็ก | `tests/test_matching.py::test_candidate_set_always_agrees_with_proposed_product_code` | SELF_REPRODUCED | |
| S-104 | รัน Phase E ซ้ำกับ 9 บรรทัดเดิม (ไม่ rerun OCR) ผ่าน `ocr_runs_staging/realinv_20260820T040631Z/rerun_layer_f_sonnet_v2.py` (ดัดแปลงจาก harness ของ Codex, read-only เหมือนเดิม) ได้ผล 0 auto / 6 correct-needs-review / 2 wrong / 1 unresolved (เทียบ baseline เดิม 0/1/5/3) — รหัสสินค้าจริงทั้ง 6 ตัวที่ Codex ยืนยันไว้ (ISOTRATE, PRESOLIN, MINIDIAB, RELESTAT, LESFLAM, CODIPHEN) ปรากฏเป็น candidate อันดับ 1 ถูกต้องครบ | `SONNET_TRADE_NAME_MATCHER_RESULTS.json`, `OCR_REAL_INVOICE_LINES.csv` | SELF_REPRODUCED | |
| S-105 | Full test suite เดิม + ใหม่ = 67/67 ผ่าน (`-W error::ResourceWarning`); `safety_scan.py` ผ่านครบ; revert-check ยืนยัน non-vacuous (คืน `matching.py` เดิมชั่วคราว → `tests/test_matching.py` ทั้งไฟล์ fail ด้วย `ImportError` ทันที → คืนไฟล์ที่แก้กลับ → 30/30 ผ่านเหมือนเดิม) | คำสั่งใน §8 ของไฟล์นี้ (เพิ่ม `tests.test_matching` เข้าไปด้วย) | SELF_REPRODUCED | |
| S-106 | ไม่มี production write, ไม่มี ADA/AdaAcc contact, ไม่มี commit/push/PR/merge/deploy ตลอดรอบนี้; ไฟล์ที่แก้จริงมีเฉพาะ `src/ocr_inbound/matching.py` และ `tests/test_matching.py` เท่านั้นใน source tree | `git status --porcelain`, `git diff --stat` | SELF_REPRODUCED | |

**Open items สำหรับ Codex** (รายละเอียดเต็มอยู่ในหัวข้อ 9 ของ candidate report):
ลำดับ gate ที่ TRADE_NAME_MATCH มาก่อน ACTIVE_ALIAS อาจสวนทาง safety ที่ดีกว่า (ยังไม่ได้ตัดสินใจ),
performance ของ `_trade_name_candidates` ยังไม่ได้ benchmark บน master เต็ม, ACTIVE_ALIAS logic
ไม่ได้ถูก exercise ด้วย test ใหม่เลย (ไม่มี alias จริงให้ทดสอบ)

---

## 12. Sonnet response to Codex BLOCKED verdict (2026-08-20) — candidate v2

**สถานะ: CANDIDATE v2 — awaiting Codex re-adjudication.** รายงานฉบับเต็มอยู่ที่
`ocr_runs_staging/realinv_20260820T040631Z/CANDIDATE_REPORT_TRADE_NAME_MATCHER_V2.md`
ตอบทั้ง 5 finding ใน §11 โดยตรง ไม่ข้ามข้อไหน:

| ID | Finding ที่ตอบ | สิ่งที่แก้ | Evidence | Claude verdict | Codex verdict |
|---|---|---|---|---|---|
| S-201 | (1) gate order | สลับให้ `ACTIVE_ALIAS` มาก่อน `TRADE_NAME_MATCH`; เพิ่ม `GateOrderTests` 2 tests พิสูจน์ alias ที่อนุมัติแล้วชนะเสมอ | `tests/test_matching.py::GateOrderTests` | SELF_REPRODUCED | |
| S-202 | (2) confidence contract | เลิกเขียน string คงที่ `"trade_name_match"`; คำนวณ numeric score จริงในช่วง [0, 0.90] จาก token-coverage + attribute-agreement | `tests/test_matching.py::ConfidenceContractTests` (2 tests); ผล Phase E rerun มี score จริง 0.6250-0.8500 | SELF_REPRODUCED | |
| S-203 | (3) dosage-form guard | เพิ่ม `_DOSAGE_FORM_MAP` + รวมเข้า `extract_attributes`/`attributes_conflict`; กัน TABLET จับ SYRUP/CREAM/DROPS | `tests/test_matching.py::DosageFormGuardTests` (4 tests) | SELF_REPRODUCED | |
| S-204 | (4) token กว้างเกินไป | เพิ่ม `_supplier_name_tokens()` ตัด token supplier ตัวเองออก; เพิ่ม `_GENERIC_TOKEN_MAX_PRODUCTS=5` กัน manufacturer-prefix ทั่วไป; เพิ่ม tie-detection ไม่เลือกอันดับหนึ่งเมื่อคะแนนเสมอ | `tests/test_matching.py::GenericTokenAndTieTests` (3 tests รวม `MEDLINE UNKNOWN ITEM` probe โดยตรง) | SELF_REPRODUCED | |
| S-205 | (5) revert-check อ่อน | สร้าง `tests/test_matching_behavioral_revert_check.py` ใหม่ทั้งไฟล์ — import เฉพาะ `ProductMatcher`/`normalize_product_text` (มีทั้งสองเวอร์ชัน) พร้อม decoy product จริงจาก live DB; คืน `matching.py` เดิมแล้วรันจริง → **import สำเร็จ, 5/6 fail ด้วย assertion จริง** (ไม่ใช่ ImportError) | คำสั่งใน §13 ของไฟล์นี้ | SELF_REPRODUCED | |
| S-206 | ผล Phase E rerun ล่าสุด | 6 CORRECT_NEEDS_REVIEW / 1 WRONG_MATCH / 2 PRODUCT_UNRESOLVED (ดีขึ้นจาก 6/2/1 — gauze ที่เคยเลือกผิดตอนนี้ปฏิเสธอย่างปลอดภัยแทน) | `SONNET_TRADE_NAME_MATCHER_RESULTS.json`, `OCR_REAL_INVOICE_LINES.csv` | SELF_REPRODUCED | |
| S-207 | Full suite + safety + scope | 84/84 ผ่าน (37 เดิม + 47 test_matching + 6 behavioral); `safety_scan.py` ผ่านครบ; ไม่มี commit/push/deploy; ไฟล์ที่แก้ยังมีแค่ `matching.py` + 2 ไฟล์ test | `git status --porcelain`, คำสั่งใน §13 | SELF_REPRODUCED | |

---

## 13. Repro commands สำหรับรอบ v2 (สำหรับ Codex รันรวด)

```powershell
cd "C:\Users\scgro\Desktop\Webapp training project\OCR-inbound"
$env:PYTHONPATH = "src"

# S-201..S-204: focused tests
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching -v

# S-205: behavioral revert-check (run against the FIXED matching.py first)
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching_behavioral_revert_check -v
# to reproduce the revert-check itself: temporarily restore the pre-fix matching.py
# content (see CANDIDATE_REPORT_TRADE_NAME_MATCHER.md section 1 for the exact original
# source), rerun the same command -- expect import to succeed and 5/6 tests to FAIL via
# assertion (wrong product code), then restore the fixed file and rerun to see 6/6 pass.

# S-206: Phase E rerun against the live read-only DB (does not touch OCR)
& ".\.venv\Scripts\python.exe" ".\ocr_runs_staging\realinv_20260820T040631Z\rerun_layer_f_sonnet_v2.py"

# S-207: full suite + safety scan
& ".\.venv\Scripts\python.exe" -W error::ResourceWarning -m unittest discover -s tests -t .
& ".\.venv\Scripts\python.exe" ".\scripts\safety_scan.py"
```

## 11. Codex independent adjudication of Layer F v2 candidate (2026-08-20)

**Verdict: BLOCKED — direction is promising, candidate is not ready to seal.** Codex independently reran 30/30 focused tests, 67/67 full tests, and the safety scan successfully, but found contract/safety defects not covered by those tests:

1. `TRADE_NAME_MATCH` currently runs before `ACTIVE_ALIAS`. This contradicts `PROJECT_BIBLE.md` §§7/9 and `DESKTOP_APP_ARCHITECTURE_TH.md` §13, which require exact code → approved supplier alias → weaker name/fuzzy evidence. A direct probe confirmed an ACTIVE alias to product B is ignored and the unapproved token match selects product A.
2. The candidate writes `confidence="trade_name_match"` and candidate score values with the same nonnumeric string. `DESKTOP_APP_ARCHITECTURE_TH.md` requires normalized confidence in `[0,1]` or null.
3. Dosage-form contradiction checking requested in the acceptance criteria was not implemented. Only strength and `AxB` pack dimensions are guarded.
4. The fallback from “all tokens” to “any token” can treat supplier/manufacturer words such as `MEDLINE` as product evidence and arbitrarily put one of several products first. A direct probe with `MEDLINE UNKNOWN ITEM` selected product A from two equally unsupported products.
5. The revert-check is weak: restoring old code causes ImportError because the new test imports new helper symbols. This proves file-shape dependency, not that behavioral assertions independently reject the old matcher.

Accepted portions: widened internal-code recognition and partial-code tests; the diagnosis of whole-string fuzzy ranking; the `candidate_set[0] == proposed_product_code` invariant; and the demonstrated improvement on six known invoice identities as review-only candidates. No source fix, commit, push, or production mutation was performed by Codex in this adjudication.

## 14. Codex independent adjudication of remediation candidate v2 (2026-08-20)

**Verdict: BLOCKED — all five prior findings are remediated, but one new safety defect remains.** Codex reran the actual suite: `test_matching.py` has 41 tests and the behavioral file has 6 (47 focused total); full discovery has 84 tests, all passing. Safety scan passed. The candidate report's breakdown “47 + 6” is an arithmetic/reporting error; the observed totals are 41 + 6 focused and 37 pre-existing + 41 + 6 = 84 full.

Independent probe found that `tie_key()` includes product-name length. Two candidates with identical token hits, identical attribute agreement, and identical numeric confidence are therefore not considered tied merely because one catalog name is shorter. Example: OCR `ALPHA 10 MG` over `ALPHA 10 MG` and `BRAND ALPHA 10 MG` selects the shorter product at confidence 0.8500 despite equal evidence.

More seriously, `TRADE_NAME_MATCH` still runs before `EXACT_NAME`. Example: OCR text exactly `ALPHA PLUS 10 MG`, master products `ALPHA PLUS 10 MG` (EXACT) and `ALPHA 10 MG` (SHORT). Because `PLUS` is a stopword and shorter name is used as a rank signal, the candidate selects SHORT through `TRADE_NAME_MATCH` and never reaches the deterministic exact-name gate. This contradicts the documented exact code → alias → exact normalized name → weaker/fuzzy cascade.

Required narrow remediation: move `EXACT_NAME` before `TRADE_NAME_MATCH`; remove product-name length from the evidence/tie key so equal hits + equal attribute agreement remain ambiguous; add both probes as regression tests; correct the test-count wording; rerun Phase E and all gates. No source fix, seal, commit, or production mutation was performed by Codex.

## 16. Codex independent adjudication of remediation candidate v3 (2026-08-20)

**Verdict: APPROVED TO SEAL locally; no push/deploy authority implied.** Codex independently confirmed the source order `EXACT_CODE → EXACT_BARCODE → ACTIVE_ALIAS → EXACT_NAME → TRADE_NAME_MATCH → FUZZY`, removal of name length from the evidence/tie key, and removal of `PLUS` from stopwords.

Fresh probes produced the required behavior: exact `ALPHA PLUS 10 MG` selected the exact product via `EXACT_NAME`; equal-evidence `ZYNOFAST` variants returned `UNRESOLVED` with no proposed code; generic `PLUS UNKNOWN 10 MG` over six PLUS products also returned `UNRESOLVED`. Fresh test results were 49/49 focused, 86/86 full discovery, and safety scan PASS. Phase E remained 6 correct-needs-review / 1 wrong / 2 unresolved, with zero auto-confirms.

Accepted residuals: Thai↔English cross-script aliases/transliteration are not solved; the two unresolved invoice lines remain human work; trade-name retrieval still scans the cached master and should be benchmarked before any high-volume production activation. An unresolved tie may carry a numeric top-candidate confidence while having no proposed code; the review UI must display this as ambiguity, not as an approved match. No source edit, seal, commit, push, or production mutation was performed by Codex in this adjudication.

---

## 15. Sonnet response to Codex BLOCKED verdict §14 (2026-08-20) — candidate v3

**สถานะ: CANDIDATE v3 — awaiting Codex re-adjudication.** รายงานฉบับเต็มอยู่ที่
`ocr_runs_staging/realinv_20260820T040631Z/CANDIDATE_REPORT_TRADE_NAME_MATCHER_V3.md`
ตอบทั้ง 4 ข้อใน §14 โดยตรง ไม่ข้ามข้อไหน ไม่แตะ 5 จุดที่ Codex ปิดไปแล้วในรอบ v2:

| ID | Finding ที่ตอบ | สิ่งที่แก้ | Evidence | Claude verdict | Codex verdict |
|---|---|---|---|---|---|
| S-301 | gate order: `EXACT_NAME` ต้องมาก่อน `TRADE_NAME_MATCH` | ย้ายบล็อก `EXACT_NAME` ไปอยู่ทันทีหลัง `ACTIVE_ALIAS` และก่อน trade-name retrieval ทั้งหมด — cascade ใหม่ตรงกับ `EXACT_CODE → EXACT_BARCODE → ACTIVE_ALIAS → EXACT_NAME → TRADE_NAME_MATCH → FUZZY_SUGGESTION` | `tests/test_matching.py::ExactNameBeforeTradeNameTests::test_exact_full_name_match_wins_over_shorter_trade_name_candidate` | SELF_REPRODUCED | |
| S-302 | ห้ามใช้ความยาวชื่อสินค้าตัดสิน tie | ตัด `len(product.get("name") or "")` ออกจาก `tie_key()` ทั้งหมด เหลือแค่ `(-len(hits), -agreement_count)`; `product_code` ยังใช้เป็น display-order tiebreaker เท่านั้น ไม่ถูกอ่านย้อนกลับเข้า `is_tied` | `tests/test_matching.py::ExactNameBeforeTradeNameTests::test_trade_name_tie_is_not_broken_by_shorter_product_name` | SELF_REPRODUCED | |
| S-303 | เพิ่ม regression test สำหรับทั้งสอง probe | เพิ่ม class `ExactNameBeforeTradeNameTests` 2 tests ตรงตาม probe ของ Codex เป๊ะ (ALPHA PLUS exact-vs-short และ equal-evidence-different-length tie) | ดูข้างต้น | SELF_REPRODUCED | |
| S-304 | correct test-count wording | รายงาน v2 ที่บอก `test_matching.py` = 47/47 เป็นตัวเลขผิด (47 คือผลรวม 41+6 ของสองไฟล์ ไม่ใช่ไฟล์เดียว) — v3 แก้เป็น `test_matching.py`=43 (41 เดิม + 2 ใหม่), behavioral=6, focused รวม=49, full suite=86 | `PYTHONPATH=src python -m unittest discover -s tests -t .` → `Ran 86 tests ... OK` | SELF_REPRODUCED | |
| S-305 | targeted revert-check เฉพาะ 3 จุดที่แก้รอบนี้ (ทำเพิ่มโดยสมัครใจ ไม่ได้ถูกขอตรง ๆ แต่ทำเพื่อพิสูจน์ test ไม่ใช่ tautology) | คืนโค้ดทั้งสามจุด (PLUS stopword, `len(name)` ใน tie_key, ลำดับ gate) กลับไปเป็นแบบเดิมชั่วคราวจากไฟล์สำรอง แล้วรัน 2 test ใหม่ → **ทั้งคู่ fail จริง** ด้วย assertion (ไม่ใช่ ImportError): test แรกได้ `TRADE_NAME_MATCH` แทน `EXACT_NAME`, test สองได้ `TESTLEN-002` (ชื่อสั้นกว่า) แทน `None`; คืนไฟล์ที่แก้แล้วกลับเข้าไป → 2/2 ผ่าน, full suite 86/86, behavioral 6/6 | บันทึกไว้ในเซสชันนี้ (ไม่มีไฟล์แยก — ทำผ่าน python inline script แล้ว diff กลับ) | SELF_REPRODUCED | |
| S-306 | Phase E rerun ล่าสุด (ไม่ rerun OCR) | 6 CORRECT_NEEDS_REVIEW / 1 WRONG_MATCH / 2 PRODUCT_UNRESOLVED — **เหมือน v2 เป๊ะ ไม่มี regression**; ไม่มีบรรทัดไหนใน 9 บรรทัดจริงเข้าเงื่อนไข ALPHA-PLUS-type bug อยู่แล้ว (บั๊กนี้พิสูจน์ผ่าน fixture ที่สร้างขึ้นเฉพาะ) | `SONNET_TRADE_NAME_MATCHER_RESULTS.json`, `OCR_REAL_INVOICE_LINES.csv` | SELF_REPRODUCED | |
| S-307 | Full suite + safety + scope | 86/86 ผ่าน (37 เดิม + 43 test_matching + 6 behavioral); `safety_scan.py` ผ่านครบ; ไม่มี commit/push/PR/merge/deploy; ไฟล์ที่แก้มีแค่ `matching.py` + `tests/test_matching.py` (เพิ่ม 1 class) | `git status --porcelain` | SELF_REPRODUCED | |

**Repro commands สำหรับรอบ v3:**

```powershell
cd "C:\Users\scgro\Desktop\Webapp training project\OCR-inbound"
$env:PYTHONPATH = "src"

# S-301..S-303: focused tests for this round's two new probes
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching.ExactNameBeforeTradeNameTests -v

# S-304: full counts
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching -v          # expect 43
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching_behavioral_revert_check -v  # expect 6
& ".\.venv\Scripts\python.exe" -W error::ResourceWarning -m unittest discover -s tests -t .  # expect 86

# S-306: Phase E rerun against the live read-only DB (does not touch OCR)
& ".\.venv\Scripts\python.exe" ".\ocr_runs_staging\realinv_20260820T040631Z\rerun_layer_f_sonnet_v2.py"

# S-307: safety scan
& ".\.venv\Scripts\python.exe" ".\scripts\safety_scan.py"
```

**หยุดที่นี่ตามคำสั่ง — รอ Codex ตรวจอิสระรอบสาม ไม่ seal ไม่ทำ git operation ใด ๆ เพิ่ม**

---

## 16. Sonnet Layer F Slice 1 — internal code / supplier SKU / barcode separation (2026-08-20)

**สถานะ: CANDIDATE — awaiting Codex adjudication. Scope: Slice 1 ONLY** (per explicit instruction --
Slice 2/3 not started). รายงานฉบับเต็มอยู่ที่
`ocr_runs_staging/realinv_20260820T040631Z/CANDIDATE_REPORT_SLICE1_IDENTIFIER_SEPARATION.md`

**บริบท:** หลังจาก Layer F v3 (§15) ผ่านการรีวิว trade-name matching แล้ว มนุษย์ให้ข้อมูลใหม่ว่า
candidate ปัจจุบันยังนำ `supplier_sku` ไปรวมใน source text ที่สแกนหา internal code และส่งเข้า
`find_by_barcode()` โดยตรง -- ทั้งสองเป็นการ conflate identifier สามชนิดที่ความหมายต่างกันเข้าด้วยกัน

| ID | Claim | Evidence | Claude verdict | Codex verdict |
|---|---|---|---|---|
| S-401 | ตัด `supplier_sku` ออกจาก internal-code scan text -- `EXACT_CODE` สแกนเฉพาะ `description_final`/`raw_ocr_text` | `tests/test_matching.py::SupplierIdentifierFieldContractTests` (2 tests: IC-shape, 630-shape) | SELF_REPRODUCED | |
| S-402 | ตัด `supplier_sku` ออกจาก `find_by_barcode()` เดิม -- เพิ่ม EXPLICIT BARCODE evidence tier ใหม่อ่านจาก `evidence_json["barcode_candidates"]` เท่านั้น (ไม่มี schema/migration change -- ใช้ column เดิม) | `tests/test_matching.py::BarcodeEvidenceTests` (4 tests) | SELF_REPRODUCED | |
| S-403 | เพิ่ม exact `(supplier_code, normalized_supplier_sku)` alias lookup path ก่อน substring-text path เดิม -- SKU เดียวกันจากคนละ supplier ชี้คนละสินค้าได้ | `SupplierIdentifierFieldContractTests::test_supplier_sku_active_alias_selects_the_confirmed_product`, `::test_same_sku_from_different_suppliers_can_point_to_different_products` | SELF_REPRODUCED | |
| S-404 | Barcode ที่ชี้สินค้าคนละตัว (conflict) ถูก quarantine เป็น `UNRESOLVED` พร้อม reason `BARCODE_CONFLICT_MULTIPLE_PRODUCTS`; quarantine ไม่ถูก override โดย tier ที่อ่อนกว่าแม้ชื่อจะตรงเป๊ะ | `BarcodeEvidenceTests::test_conflicting_barcode_candidates_quarantine_the_line`, `::test_conflicting_barcode_quarantine_is_not_overridden_by_a_matching_name` | SELF_REPRODUCED | |
| S-405 | Barcode ที่ไม่รู้จัก (ใหม่/ยังไม่อยู่ในฐาน) ไม่ auto-confirm อะไร cascade เดินต่อปกติ | `BarcodeEvidenceTests::test_unknown_barcode_does_not_get_guessed` | SELF_REPRODUCED | |
| S-406 | Layer F v3 acceptance เดิมทั้งหมดยังผ่าน ยกเว้น 1 test ที่ปรับ contract ตรงตามที่สั่งแก้ (`test_exact_barcode_still_resolves` เปลี่ยนจากใช้ `supplier_sku` เป็น `barcode_candidates`) | `PYTHONPATH=src python -m unittest discover -s tests -t .` → `Ran 95 tests ... OK` | SELF_REPRODUCED | |
| S-407 | `candidate_set[0]` ยังตรงกับ `proposed_product_code` เสมอ รวมถึง tier ใหม่ (SKU-exact ACTIVE_ALIAS, multi-candidate EXACT_BARCODE) | assertion ใน S-403/S-402 tests ข้างต้น | SELF_REPRODUCED | |
| S-408 | Targeted revert-check: คืน `matching.py` เป็นเวอร์ชันก่อน Slice 1 (v3) ชั่วคราวจากไฟล์สำรอง แล้วรัน 9 test ใหม่ -- **6/9 fail จริงด้วย assertion** (ไม่ใช่ ImportError): supplier-sku-shaped-IC, supplier-sku-shaped-630, supplier-sku-as-barcode, explicit-barcode-evidence, barcode-conflict-quarantine, barcode-conflict-not-overridden-by-name; อีก 3 ข้อ (SKU-exact-alias x2, unknown-barcode) ผ่านบนโค้ดเก่าโดยบังเอิญ (รายงานตรงไปตรงมาว่าไม่ใช่ regression-proof เท่ากันทั้ง 9 ข้อ) -- คืนโค้ดที่แก้แล้วกลับ → 95/95, behavioral 6/6, safety scan ผ่านครบเหมือนเดิม | ทำผ่าน python inline script ในเซสชันนี้ (backup/restore จากไฟล์ `matching_v3_backup.py`/`matching_slice1_fixed_backup.py` ใน scratchpad) | SELF_REPRODUCED | |
| S-409 | Phase E rerun ล่าสุด (harness ป้อน `supplier_sku` จริงจากใบแจ้งหนี้ทุกบรรทัด): **6 CORRECT_NEEDS_REVIEW / 1 WRONG_MATCH / 2 PRODUCT_UNRESOLVED เหมือน v3 เป๊ะ ไม่มี regression** -- ไม่มีบรรทัดจริงใน 9 บรรทัดที่เคย "ถูก" เพราะบั๊กที่เพิ่งแก้ | `SONNET_TRADE_NAME_MATCHER_RESULTS.json` | SELF_REPRODUCED | |
| S-410 | ไม่มี production write, ไม่มี ADA/AdaAcc contact, ไม่มี commit/push/PR/merge/deploy, ไม่มี migration/config/env change, ไม่แตะ Product Master, ไม่เริ่ม Slice 2/3 หรือ bilingual search/Admin UI | `git status --porcelain`, `git diff --stat` (เฉพาะ `src/ocr_inbound/matching.py` แก้; test files ยัง untracked) | SELF_REPRODUCED | |

**Repro commands:**

```powershell
cd "C:\Users\scgro\Desktop\Webapp training project\OCR-inbound"
$env:PYTHONPATH = "src"

# S-401..S-405, S-407: new Slice-1 focused tests
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching.SupplierIdentifierFieldContractTests tests.test_matching.BarcodeEvidenceTests -v

# S-406: full suite (expect 95)
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -t .

# S-408: revert-check -- temporarily restore the pre-Slice-1 matching.py content
# (see CANDIDATE_REPORT_SLICE1_IDENTIFIER_SEPARATION.md section 6 for exact source),
# rerun the same command above, expect 6/9 FAIL via assertion, then restore the fixed
# file and rerun to see 9/9 pass again.

# S-409: Phase E rerun against the live read-only DB (does not touch OCR)
& ".\.venv\Scripts\python.exe" ".\ocr_runs_staging\realinv_20260820T040631Z\rerun_layer_f_sonnet_v2.py"

# S-410: safety scan
& ".\.venv\Scripts\python.exe" ".\scripts\safety_scan.py"
```

**หยุดที่นี่ตามคำสั่ง — รอ Codex ตรวจอิสระ ไม่ seal ไม่ commit จนกว่า Codex verdict = APPROVED TO SEAL**

---

## 17. Codex independent adjudication of Layer F Slice 1 (2026-08-20)

**Verdict: BLOCKED — แนวทางแยก identifier ถูกต้อง แต่ boundary ของข้อมูลจริงยังไม่ถูกทดสอบและยังทำงานผิด 2 จุด**

Codex รัน Slice-1 focused tests ใหม่ได้ 9/9, full discovery 95/95 และ safety scan PASS แต่ probe ที่จำลองข้อมูลจริงพบว่า:

1. การตัดเฉพาะ field `supplier_sku` ออกจาก `code_scan_text` ยังไม่ตัด supplier SKU ที่พิมพ์อยู่ใน `description_final`/`raw_ocr_text` ออก บรรทัดทดสอบที่ OCR ดิบมี `630010124` ถูกเลือกเป็น internal product `630010124` ผ่าน `EXACT_CODE` แม้ exact `(supplier_code, supplier_sku)` ACTIVE alias จะชี้ไปสินค้า `IC-RIGHT` ที่ถูกต้อง ดังนั้น claim S-401 ยังไม่ปิด identifier conflation ในรูปเอกสารจริง ต้องใช้อินพุต internal-code ที่มี provenance ชัดเจน หรือแยก supplier-code region ออกจาก free OCR ก่อน auto-confirm; ห้ามสแกน digit pattern จากข้อความอิสระแล้วถือเป็น internal code โดยอัตโนมัติ
2. `document_lines.evidence_json` เป็นคอลัมน์ `TEXT`; importer เขียนด้วย `canonical_json(...)` และ `Repository.list_lines()` คืนค่า string เดิมโดยไม่ decode แต่ `_barcode_candidates()` รับเฉพาะ `dict` เท่านั้น Probe ที่ส่ง DB-shaped JSON string `{"barcode_candidates":["8851234567890"]}` จึงได้ `UNRESOLVED` แทน `EXACT_BARCODE` Test ปัจจุบันส่ง Python dict ตรง ๆ จึงข้าม persistence boundary และให้ผลเขียวลวง ต้องกำหนด decode boundary ที่ชัดเจนและเพิ่ม integration test แบบ import → list_lines → matcher

สิ่งที่ยอมรับแล้ว: ไม่ใช้ `supplier_sku` เป็น barcode โดยตรง, exact supplier-scoped alias เป็นทิศทางที่ถูก, barcode conflict quarantine ปลอดภัย, unknown barcode ไม่ถูกเดา และชุดทดสอบเดิมไม่ regression ตามผลที่รายงาน

Required narrow remediation: แก้ provenance ของ internal-code scan; รองรับ/normalize persisted `evidence_json` ที่ boundary เดียว; เพิ่มสอง regression probes ข้างต้นโดยให้ผ่านเส้นทางข้อมูลจริง; รัน 9 focused + full suite + safety scan + Phase E ใหม่ จากนั้นส่งกลับให้ Codex ตรวจอีกครั้ง ห้าม seal/commit และยังไม่เริ่ม Slice 2/3

Codex ไม่แก้ source, ไม่ stage, ไม่ commit, ไม่ push และไม่แตะ production ในรอบ adjudication นี้

---

## 18. Codex re-adjudication of Layer F Slice 1 remediation v2 (2026-08-20)

**Verdict: BLOCKED — persistence boundary ถูกแก้จริง แต่ free-text internal-code fallback ยังไม่ปลอดภัยพอสำหรับ auto-confirm**

Codex ยืนยันว่า `decode_line_evidence()` แก้ JSON-TEXT boundary ได้ตรงจุด, integration tests ผ่านเส้นทาง `Application → SQLite → list_lines → matcher` จริง และรัน full discovery ได้ 100/100 พร้อม safety scan PASS อย่างไรก็ตาม independent probes พบสองช่องว่าง:

1. Exclusion ปัจจุบันทำงานเฉพาะเมื่อ parser เติม `supplier_sku` ได้ถูกต้อง หาก OCR ดิบมี wholesaler code `630010124` แต่ `supplier_sku` ว่าง/แยกไม่สำเร็จ ระบบยัง auto-confirm สินค้า internal code `630010124` ผ่าน `EXACT_CODE` ทันที นี่เป็น failure mode ที่สมเหตุสมผลของ OCR และพิสูจน์ว่า arbitrary free-text digit scan ยังไม่มี provenance เพียงพอ การกรองด้วย equality ต่อ field ที่อาจหายจึงไม่ปิดความเสี่ยงเดิม
2. `internal_code_candidates` หลายค่าที่ resolve ไปคนละสินค้าเลือกค่าตัวแรกตามลำดับ array แทนที่จะ quarantine ความขัดแย้ง Probe `[IC-000001, IC-000002]` เลือก `IC-000001` แบบ auto-confirm โดยไม่มี conflict reason ซึ่งไม่ปลอดภัยและไม่สอดคล้องกับกติกา barcode conflict ที่ Slice เดียวกันเพิ่งวางไว้

Required narrow remediation: ให้ `EXACT_CODE` auto-confirm ได้จาก explicit-provenance `internal_code_candidates` เท่านั้น หรือ downgrade free-text regex hit เป็น review-only candidate; explicit internal-code candidates ที่ resolve มากกว่าหนึ่ง product ต้อง quarantine เป็น `UNRESOLVED`; เพิ่ม real-boundary tests สำหรับ missing/unparsed supplier SKU และ multi-product internal-code conflict; รัน full suite, safety scan และ Phase E ใหม่ ห้าม seal/commit และยังไม่เริ่ม Slice 2/3

Accepted portions: JSON TEXT decoding boundary, real SQLite integration harness, supplier-scoped exact alias path, barcode evidence/conflict behavior และผล non-regression 100/100

Codex ไม่แก้ source, ไม่ stage, ไม่ commit, ไม่ push และไม่แตะ production ในรอบ re-adjudication นี้

---

## 19. Codex re-adjudication of Layer F Slice 1 remediation v3 (2026-08-20)

**Verdict: BLOCKED — matching safety defects from §18 are fixed, but prediction version/hash contract is now stale.**

Codex independently confirmed the requested behavior: free-text code hits are review-only `INTERNAL_CODE_TEXT_MATCH`; missing `supplier_sku` cannot auto-confirm; explicit multi-product internal-code evidence quarantines; candidate lists and `human_confirmation_required` are correct. Full discovery passed 106/106 and safety scan passed.

One release-blocking audit defect remains. Slice 1 materially changes matching behavior and introduces `barcode_candidates` / `internal_code_candidates` as decision inputs, but `RULESET_VERSION` remains `layer-f-v3` (the same version already used by the pre-Slice-1 matcher), while `input_hash` still hashes only supplier, line id, normalized text, and ruleset. Independent probe using identical text/line/supplier produced `UNRESOLVED` without evidence and `EXACT_CODE → IC-000001` with explicit internal-code evidence, yet both predictions had the exact same SHA-256 input hash and ruleset `layer-f-v3`. Thus immutable prediction rows cannot distinguish materially different inputs/logic through the fields intended for traceability.

Required narrow remediation: bump the ruleset for Slice 1 (do not reuse pre-Slice-1 `layer-f-v3`); include canonicalized decision-relevant identifier evidence in `input_hash` (at minimum normalized barcode/internal-code candidate lists, with deterministic ordering/duplicate handling explicitly defined); add tests proving same semantic evidence yields stable hash regardless of JSON representation/order policy, while changed decision evidence changes the hash; rerun full suite, safety scan, and Phase E. No further matching-tier redesign is requested. Do not seal/commit and do not start Slice 2/3 yet.

Codex did not edit source, stage, commit, push, or access production during this adjudication.

---

## 21. Codex final adjudication of Layer F Slice 1 remediation v5 (2026-08-20)

**Verdict: APPROVED TO SEAL locally — no push/merge/deploy authority implied.**

Codex independently confirmed `RULESET_VERSION = layer-f-v5`; normalized `unit_final` changes the hash and selected unit as required; `description_final` and `raw_ocr_text` are hashed independently; equivalent identifier evidence represented as dict or persisted JSON string, with different list ordering or duplicates, produces a stable semantic hash. Direct probes confirmed all four properties.

Fresh verification: full discovery 116/116 PASS, safety scan PASS, and `git diff --check` clean. The identifier-separation behavior accepted in §§17–20 remains intact: supplier SKU is not internal code/barcode evidence; free-text code hits require human confirmation; explicit code/barcode conflicts quarantine; real SQLite JSON-TEXT persistence is decoded correctly; exact supplier-scoped aliases remain supported.

Seal instructions: stage only the intentional Slice-1 cumulative source/test/audit files by exact path; do not use `git add -A`; exclude `.playwright-cli/`, `environments/`, OCR run outputs, model caches, source documents, credentials, and candidate-report artifacts. Re-run 116/116, safety scan, secret scan, `git diff --cached --check`, and exact staged manifest after committing. Local seal only; push and later Slice 2 require separate authorization.

Codex did not edit source, stage, commit, push, or access production during this adjudication.

---

## 20. Codex re-adjudication of Layer F Slice 1 remediation v4 (2026-08-20)

**Verdict: BLOCKED — identifier evidence hashing is correct, but the stated full prediction-input hash contract still omits an outcome-changing line input.**

Codex confirmed `RULESET_VERSION = layer-f-v4`; barcode/internal-code evidence is normalized as sorted sets; dict-vs-JSON-string, different ordering, casing normalization (internal code), whitespace normalization (barcode), and duplicates produce the same semantic hash. Changed identifier evidence changes the hash as required. Full discovery passed 110/110 and safety scan passed.

Independent probe found that `unit_final` remains absent from `input_payload`. With the same document, line, text, ruleset, selected product and identifier evidence, changing `unit_final` from `BOX` to `EACH` changed `proposed_unit_code` from `BOX` to `EACH` while `input_hash` remained identical. This directly contradicts the candidate's new source contract that the hash changes whenever an input capable of changing the prediction outcome changes.

Required final narrow remediation: define the per-line hash contract explicitly and include normalized `unit_final`; because matching treats `description_final` specially for `EXACT_NAME` while also reading `raw_ocr_text`, hash these normalized fields separately rather than relying only on their combined `source_text`; add unit-change and description/raw-boundary tests plus the previously requested semantic-evidence order/string-vs-dict regression test. Reference/master state versioning may remain a separately documented future concern; no catalog/schema redesign is requested in Slice 1. Rerun full suite, safety scan, and Phase E, then return for final seal verdict. Do not start Slice 2/3.

Codex did not edit source, stage, commit, push, or access production during this adjudication.

---

## 18. Sonnet Layer F Slice 1 remediation v2 — real-data boundary fixes (2026-08-20)

**สถานะ: CANDIDATE v2 — awaiting Codex re-adjudication. Scope: Slice 1 remediation ONLY** (Slice 2/3
not started). รายงานฉบับเต็มอยู่ที่
`ocr_runs_staging/realinv_20260820T040631Z/CANDIDATE_REPORT_SLICE1_IDENTIFIER_SEPARATION_V2.md`
ตอบทั้ง 2 finding ใน §17 โดยตรง:

| ID | Finding ที่ตอบ | สิ่งที่แก้ | Evidence | Claude verdict | Codex verdict |
|---|---|---|---|---|---|
| S-501 | (1) supplier SKU ที่ echo อยู่ใน `raw_ocr_text`/`description_final` (ไม่ใช่แค่ field `supplier_sku`) ยังถูกอ่านเป็น `EXACT_CODE` แม้มี ACTIVE alias ที่ถูกต้องอยู่ | เพิ่ม exclusion filter ใน EXACT_CODE fallback: ปฏิเสธ candidate ที่ normalize แล้วตรงกับ `supplier_sku` ของบรรทัดเดียวกันเป๊ะ; เพิ่ม explicit-provenance path `evidence_json["internal_code_candidates"]` (ความน่าเชื่อถือสูงสุด ข้าม free-text scan ทั้งหมด) | `tests/test_matching.py::test_supplier_sku_echoed_in_free_ocr_text_does_not_shadow_active_alias` (unit) + `tests/test_matching_integration.py::test_supplier_sku_echoed_in_real_persisted_ocr_text_does_not_shadow_a_real_active_alias` (integration, ผ่าน real Repository + real alias promotion path `record_alias_observation`x3 → `approve_alias`) | SELF_REPRODUCED | |
| S-502 | (2) `evidence_json` เป็น JSON string จริงตอนอ่านจาก `Repository.list_lines()` (`document_lines.evidence_json` เป็น `TEXT` column) แต่ `_barcode_candidates()` เดิมรับเฉพาะ `dict` — EXACT_BARCODE ใช้งานจริงไม่ได้เลย | เพิ่ม `decode_line_evidence()` เป็น decode boundary จุดเดียว รองรับทั้ง dict (in-process caller) และ JSON string (real DB read-back); `_barcode_candidates()`/`_internal_code_candidates()` ใหม่ทั้งคู่เรียกผ่านจุดนี้ | `tests/test_matching.py::test_barcode_evidence_resolves_when_evidence_json_is_a_persisted_json_string` (unit, JSON string ตรง ๆ) + `tests/test_matching_integration.py::test_barcode_evidence_resolves_through_a_real_import_persist_readback_cycle` (integration, ผ่าน `Application.bootstrap()` → import → persist → `list_lines()` อ่านกลับ → matcher จริง) | SELF_REPRODUCED | |
| S-503 | integration test ใหม่ทั้งไฟล์ `tests/test_matching_integration.py` ตามที่ Codex ขอ ("integration test แบบ import → list_lines → matcher") | 2 test ผ่าน real `Application`/SQLite `Repository` ไม่ใช่ test double | ดู S-501/S-502 | SELF_REPRODUCED | |
| S-504 | Full suite + focused + safety scan | `tests/test_matching.py` 55/55; `tests/test_matching_behavioral_revert_check.py` 6/6; `tests/test_matching_integration.py` 2/2 (ใหม่); focused รวม 63/63; full discovery **100/100**; `safety_scan.py` ผ่านครบ | `PYTHONPATH=src python -m unittest discover -s tests -t .` → `Ran 100 tests ... OK` | SELF_REPRODUCED | |
| S-505 | Targeted revert-check เฉพาะ 2 integration test ใหม่ (ทำเพิ่มโดยสมัครใจเพื่อพิสูจน์ non-vacuous) | คืน `matching.py` กลับไปเป็น candidate v1 (ที่ Codex เพิ่ง block) ชั่วคราวจากไฟล์สำรอง รัน 2 integration test → **ทั้งคู่ fail จริง** ด้วย assertion (ไม่ใช่ ImportError): barcode test ได้ `TRADE_NAME_MATCH` แทน `EXACT_BARCODE`; SKU-echo test ได้ `EXACT_CODE` แทน `ACTIVE_ALIAS`; คืนไฟล์ที่แก้แล้วกลับ → full suite 100/100 เหมือนเดิม | บันทึกไว้ในเซสชันนี้ (ทำผ่าน python inline script, backup/restore จากไฟล์ `matching_slice1_fixed_backup.py`/`matching_slice1_remediated_backup.py` ใน scratchpad) | SELF_REPRODUCED | |
| S-506 | Phase E rerun ล่าสุด | 6 CORRECT_NEEDS_REVIEW / 1 WRONG_MATCH / 2 PRODUCT_UNRESOLVED เหมือนรอบก่อนทุกประการ ไม่มี regression | `SONNET_TRADE_NAME_MATCHER_RESULTS.json` | SELF_REPRODUCED | |
| S-507 | ไม่มี production write, ไม่มี ADA/AdaAcc contact, ไม่มี commit/push/PR/merge/deploy, ไม่มี migration/config/env change, ไม่แตะ Product Master, ไม่เริ่ม Slice 2/3 | `git status --porcelain` (เฉพาะ `src/ocr_inbound/matching.py` แก้; test files ยัง untracked; 1 ไฟล์ test ใหม่ `tests/test_matching_integration.py`) | SELF_REPRODUCED | |

**Repro commands:**

```powershell
cd "C:\Users\scgro\Desktop\Webapp training project\OCR-inbound"
$env:PYTHONPATH = "src"

# S-501, S-502: new unit-level focused tests
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching.SupplierIdentifierFieldContractTests tests.test_matching.BarcodeEvidenceTests -v

# S-503: real persistence-boundary integration tests
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching_integration -v

# S-504: full counts
& ".\.venv\Scripts\python.exe" -W error::ResourceWarning -m unittest discover -s tests -t .  # expect 100

# S-505: revert-check -- temporarily restore the candidate-v1 matching.py content (the
# version Codex blocked in section 17), rerun tests.test_matching_integration, expect
# 2/2 FAIL via assertion, then restore the remediated file and rerun to see 2/2 pass.

# S-506: Phase E rerun against the live read-only DB (does not touch OCR)
& ".\.venv\Scripts\python.exe" ".\ocr_runs_staging\realinv_20260820T040631Z\rerun_layer_f_sonnet_v2.py"

# S-507: safety scan
& ".\.venv\Scripts\python.exe" ".\scripts\safety_scan.py"
```

**หยุดที่นี่ตามคำสั่ง — รอ Codex ตรวจอิสระ ไม่ seal ไม่ commit จนกว่า Codex verdict = APPROVED TO SEAL**

---

## 19. Sonnet Layer F Slice 1 remediation v3 — explicit-provenance-only auto-confirm (2026-08-20)

**สถานะ: CANDIDATE v3 — awaiting Codex re-adjudication. Scope: Slice 1 remediation ONLY** (Slice 2/3
not started). รายงานฉบับเต็มอยู่ที่
`ocr_runs_staging/realinv_20260820T040631Z/CANDIDATE_REPORT_SLICE1_IDENTIFIER_SEPARATION_V3.md`
ตอบทั้ง 2 finding ใน §18 โดยตรง:

| ID | Finding ที่ตอบ | สิ่งที่แก้ | Evidence | Claude verdict | Codex verdict |
|---|---|---|---|---|---|
| S-601 | (1) exclusion filter รอบก่อนป้องกันได้แค่ตอน parser ดึง `supplier_sku` สำเร็จ -- ถ้า `supplier_sku` เป็น `None` (parser ล้มเหลว) รหัสในข้อความอิสระยัง auto-confirm ผิดได้ | เปลี่ยนเป็น structural fix: `EXACT_CODE` auto-confirm ได้จาก explicit-provenance evidence เท่านั้น; free-text scan (ไม่มี explicit evidence) ลดระดับเป็น tier ใหม่ `INTERNAL_CODE_TEXT_MATCH` ที่ไม่เคย auto-confirm ไม่ว่า `supplier_sku` จะมีค่าหรือไม่ | `tests/test_matching.py::InternalCodeTextMatchTests::test_missing_supplier_sku_free_text_code_hit_is_never_auto_confirmed` (unit) + `tests/test_matching_integration.py::test_missing_supplier_sku_free_text_code_hit_is_never_auto_confirmed_through_real_persistence` (integration, DB จริง) | SELF_REPRODUCED | |
| S-602 | (2) `internal_code_candidates` หลายค่าที่ resolve คนละสินค้าเลือกตัวแรกเงียบ ๆ | mirror ของ barcode conflict: `matched_internal_code_products` เป็น dict คีย์ด้วย product_code; ถ้ามากกว่า 1 distinct product ให้ `quarantined=True` + reason `INTERNAL_CODE_CONFLICT_MULTIPLE_PRODUCTS` แสดงทั้งคู่; บล็อกทุก tier ที่เหลือ (แก้ guard ของ barcode block เพิ่ม `not quarantined` ด้วย) | `tests/test_matching.py::InternalCodeTextMatchTests::test_explicit_internal_code_conflict_quarantines_the_line` + `::test_explicit_internal_code_conflict_is_not_overridden_by_a_matching_name` (unit) + `tests/test_matching_integration.py::test_explicit_internal_code_conflict_quarantines_through_real_persistence` (integration, DB จริง) | SELF_REPRODUCED | |
| S-603 | Full suite + focused + safety scan | `tests/test_matching.py` 59/59; `tests/test_matching_behavioral_revert_check.py` 6/6; `tests/test_matching_integration.py` 4/4 (2 เดิม + 2 ใหม่); focused รวม 69/69; full discovery **106/106**; `safety_scan.py` ผ่านครบ | `PYTHONPATH=src python -m unittest discover -s tests -t .` → `Ran 106 tests ... OK` | SELF_REPRODUCED | |
| S-604 | Targeted revert-check เฉพาะ 6 test ใหม่ (4 unit + 2 integration) | คืน `matching.py` กลับไปเป็น v2 (ที่ Codex เพิ่ง block รอบสอง) ชั่วคราวจากไฟล์สำรอง รันทั้ง 6 test → **6/6 fail จริง** ด้วย assertion (ไม่ใช่ ImportError) รวม 2 ตัวที่ผ่าน real DB round trip เต็มรูปแบบ; คืนไฟล์ที่แก้แล้วกลับ → full suite 106/106 เหมือนเดิม | บันทึกไว้ในเซสชันนี้ (backup/restore จากไฟล์ `matching_slice1_remediated_backup.py`/`matching_slice1_v3_remediated_backup.py` ใน scratchpad) | SELF_REPRODUCED | |
| S-605 | Phase E rerun ล่าสุด | 6 CORRECT_NEEDS_REVIEW / 1 WRONG_MATCH / 2 PRODUCT_UNRESOLVED เหมือนทุกรอบก่อนหน้าเป๊ะ ไม่มี regression (harness ไม่มีบรรทัดที่ supplier_sku เป็น None จึงไม่ exercise residual-risk scenario ในข้อมูลจริง 9 บรรทัดนี้โดยตรง -- พิสูจน์ผ่าน test เท่านั้น) | `SONNET_TRADE_NAME_MATCHER_RESULTS.json` | SELF_REPRODUCED | |
| S-606 | ไม่มี production write, ไม่มี ADA/AdaAcc contact, ไม่มี commit/push/PR/merge/deploy, ไม่มี migration/config/env change, ไม่แตะ Product Master, ไม่เริ่ม Slice 2/3 | `git status --porcelain` (เฉพาะ `src/ocr_inbound/matching.py` แก้; test files ยัง untracked) | SELF_REPRODUCED | |

**Contract change ที่ตั้งใจ (ไม่ใช่ regression):** `CharacterizationOriginalCascade::test_exact_code_still_resolves_seven_digit_630_code`
เปลี่ยนชื่อเป็น `test_exact_code_still_resolves_with_explicit_provenance` และเปลี่ยนไปใช้
`internal_code_candidates=["6300001"]` แทนการพึ่ง free-text scan ตรงตามที่ narrow remediation
กำหนด (free-text scan ไม่ auto-confirm อีกต่อไป)

**Repro commands:**

```powershell
cd "C:\Users\scgro\Desktop\Webapp training project\OCR-inbound"
$env:PYTHONPATH = "src"

# S-601, S-602: new unit-level focused tests
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching.InternalCodeTextMatchTests -v

# S-601, S-602 (real DB): new integration tests
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching_integration -v

# S-603: full counts
& ".\.venv\Scripts\python.exe" -W error::ResourceWarning -m unittest discover -s tests -t .  # expect 106

# S-604: revert-check -- temporarily restore the v2 (Codex-blocked) matching.py content,
# rerun tests.test_matching.InternalCodeTextMatchTests + tests.test_matching_integration,
# expect 6/6 FAIL via assertion, then restore the remediated file and rerun to see 6/6 pass.

# S-605: Phase E rerun against the live read-only DB (does not touch OCR)
& ".\.venv\Scripts\python.exe" ".\ocr_runs_staging\realinv_20260820T040631Z\rerun_layer_f_sonnet_v2.py"

# S-606: safety scan
& ".\.venv\Scripts\python.exe" ".\scripts\safety_scan.py"
```

**หยุดที่นี่ตามคำสั่ง — รอ Codex ตรวจอิสระ ไม่ seal ไม่ commit จนกว่า Codex verdict = APPROVED TO SEAL**

---

## 20. Sonnet Layer F Slice 1 remediation v4 — audit/version contract fix (2026-08-20)

**สถานะ: CANDIDATE v4 — awaiting Codex re-adjudication. Scope: Slice 1 audit/version fix ONLY**
(matching logic ไม่เปลี่ยน; Slice 2/3 not started). รายงานฉบับเต็มอยู่ที่
`ocr_runs_staging/realinv_20260820T040631Z/CANDIDATE_REPORT_SLICE1_IDENTIFIER_SEPARATION_V4.md`
ตอบทั้ง 3 ข้อใน §19 โดยตรง:

| ID | Finding ที่ตอบ | สิ่งที่แก้ | Evidence | Claude verdict | Codex verdict |
|---|---|---|---|---|---|
| S-701 | (1) `RULESET_VERSION` ยังเป็น `layer-f-v3` เหมือนก่อน Slice 1 ทั้งที่กฎเปลี่ยนไปมากแล้ว | bump เป็น `"layer-f-v4"` พร้อมคอมเมนต์อธิบายว่ารอบนี้เป็น audit-contract fix ล้วน ๆ | `src/ocr_inbound/matching.py::ProductMatcher.RULESET_VERSION` | SELF_REPRODUCED | |
| S-702 | (2) `input_hash` ไม่รวม barcode/internal-code evidence -- audit ย้อนหลังแยกไม่ออกว่าผลต่างเพราะ input ใด | `input_payload` เพิ่ม `supplier_sku` (normalized), `barcode_evidence` (`sorted(set(...))`), `internal_code_evidence` (`sorted({normalize_product_text(c) ...})`) | `tests/test_matching.py::InputHashAuditContractTests` (4 test) | SELF_REPRODUCED | |
| S-703 | (3) เพิ่ม tests ยืนยัน evidence เหมือนกัน→hash เดิม, evidence เปลี่ยน→hash เปลี่ยน | 4 test: identical-evidence positive control, no-evidence-vs-internal-code (reproduce Codex's exact probe), no-evidence-vs-barcode, different-supplier-sku | ดู S-702 | SELF_REPRODUCED | |
| S-704 | Full suite + focused + safety scan | `tests/test_matching.py` 63/63; `tests/test_matching_behavioral_revert_check.py` 6/6 (ไม่แตะ); `tests/test_matching_integration.py` 4/4 (ไม่แตะ); focused รวม 73/73; full discovery **110/110**; `safety_scan.py` ผ่านครบ | `PYTHONPATH=src python -m unittest discover -s tests -t .` → `Ran 110 tests ... OK` | SELF_REPRODUCED | |
| S-705 | Targeted revert-check เฉพาะ 4 test ใหม่ | คืน `matching.py` กลับไปเป็น v3 (ที่ Codex เพิ่ง block รอบที่สาม) ชั่วคราวจากไฟล์สำรอง รันทั้ง 4 test → **2/4 fail จริงด้วย assertion จริง** ตรงกับ probe ของ Codex ตัวอักษรต่ออักษร (hash เดียวกันเป๊ะ `39f840cca35f80ab2e205fbebff4aac6336709f5b6d40eef26a8a4da533187da` ระหว่าง no-evidence กับ explicit-evidence ทั้ง internal-code และ barcode); อีก 2 ข้อผ่านบนโค้ดเก่า (1 เป็น positive control ตามที่ตั้งใจ, 1 ผ่านบังเอิญเพราะ `supplier_sku` เคยรวมอยู่ใน `source_text`/`text` field ของ hash เดิมอยู่แล้วผ่านทางอ้อม); คืนไฟล์ที่แก้แล้วกลับ → full suite 110/110 เหมือนเดิม | บันทึกไว้ในเซสชันนี้ (backup/restore จากไฟล์ `matching_slice1_v3_remediated_backup.py`/`matching_slice1_v4_audit_backup.py` ใน scratchpad) | SELF_REPRODUCED | |
| S-706 | Phase E rerun ล่าสุด | 6 CORRECT_NEEDS_REVIEW / 1 WRONG_MATCH / 2 PRODUCT_UNRESOLVED เหมือนทุกรอบก่อนหน้าเป๊ะ ไม่มี regression (คาดไว้แล้ว -- ไม่แตะ matching logic) | `SONNET_TRADE_NAME_MATCHER_RESULTS.json` | SELF_REPRODUCED | |
| S-707 | ไม่มี production write, ไม่มี ADA/AdaAcc contact, ไม่มี commit/push/PR/merge/deploy, ไม่มี migration/config/env change, ไม่แตะ Product Master, ไม่เริ่ม Slice 2/3 | `git status --porcelain` (เฉพาะ `src/ocr_inbound/matching.py` แก้; test files ยัง untracked) | SELF_REPRODUCED | |

**Repro commands:**

```powershell
cd "C:\Users\scgro\Desktop\Webapp training project\OCR-inbound"
$env:PYTHONPATH = "src"

# S-701..S-703: new audit-hash focused tests
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching.InputHashAuditContractTests -v

# S-704: full counts
& ".\.venv\Scripts\python.exe" -W error::ResourceWarning -m unittest discover -s tests -t .  # expect 110

# S-705: revert-check -- temporarily restore the v3 (Codex-blocked-round-3) matching.py
# content, rerun tests.test_matching.InputHashAuditContractTests, expect 2/4 FAIL via
# assertion (both no-evidence-vs-explicit-evidence hash comparisons), then restore the
# remediated file and rerun to see 4/4 pass.

# S-706: Phase E rerun against the live read-only DB (does not touch OCR)
& ".\.venv\Scripts\python.exe" ".\ocr_runs_staging\realinv_20260820T040631Z\rerun_layer_f_sonnet_v2.py"

# S-707: safety scan
& ".\.venv\Scripts\python.exe" ".\scripts\safety_scan.py"
```

**หยุดที่นี่ตามคำสั่ง — รอ Codex ตรวจอิสระ ไม่ seal ไม่ commit จนกว่า Codex verdict = APPROVED TO SEAL**

---

## 21. Sonnet Layer F Slice 1 remediation v5 — final audit hash fix (2026-08-20)

**สถานะ: CANDIDATE v5 — awaiting Codex re-adjudication. Scope: Slice 1 audit fix ONLY** (matching
logic ไม่เปลี่ยน; Slice 2/3 not started). รายงานฉบับเต็มอยู่ที่
`ocr_runs_staging/realinv_20260820T040631Z/CANDIDATE_REPORT_SLICE1_IDENTIFIER_SEPARATION_V5.md`
ตอบทั้ง 3 ข้อใน §20 โดยตรง:

| ID | Finding ที่ตอบ | สิ่งที่แก้ | Evidence | Claude verdict | Codex verdict |
|---|---|---|---|---|---|
| S-801 | `unit_final` ไม่เคยอยู่ใน `input_hash` แม้กำหนด `proposed_unit_code` โดยตรง -- "BOX"→"EACH" เปลี่ยน output แต่ hash เดิม | ย้าย `raw_unit = (line.get("unit_final") or "").strip().upper()` ออกมานอก `if selected:` แล้วใส่ค่าเดียวกันเป๊ะลง `input_payload["unit_final"]` | `tests/test_matching.py::InputHashAuditContractTests::test_unit_final_change_alone_changes_hash_and_proposed_unit` | SELF_REPRODUCED | |
| S-802 | `description_final`/`raw_ocr_text` ถูกผสมเป็นสตริงเดียว (`text`) ก่อน hash -- เปิดช่อง collision จริง (`"FOO BAR"+"BAZ"` กับ `"FOO"+"BAR BAZ"` ต่อกันได้สตริงเดียวกัน) | ตัด field `text` ออก แทนที่ด้วย `description_final`/`raw_ocr_text` hash แยกอิสระจากกัน | `::test_description_final_and_raw_ocr_text_boundary_shift_does_not_collide` (พิสูจน์ collision จริงบนโค้ดเก่า) | SELF_REPRODUCED | |
| S-803 | เพิ่ม regression tests ตามที่ขอ (unit, field boundary, JSON dict/string, ลำดับ evidence) | 6 test ใหม่ใน `InputHashAuditContractTests` | ดู S-801/S-802 + `test_description_final_change_alone_changes_hash`, `test_raw_ocr_text_change_alone_changes_hash`, `test_evidence_json_as_dict_or_persisted_json_string_produce_the_same_hash`, `test_evidence_list_order_does_not_change_hash` | SELF_REPRODUCED | |
| S-804 | Bump RULESET_VERSION อีกครั้ง (audit-contract เปลี่ยนอีกรอบ) | `"layer-f-v4"` → `"layer-f-v5"` | `src/ocr_inbound/matching.py::ProductMatcher.RULESET_VERSION` | SELF_REPRODUCED | |
| S-805 | Full suite + focused + safety scan | `tests/test_matching.py` 69/69; behavioral 6/6 (ไม่แตะ); integration 4/4 (ไม่แตะ); focused รวม 79/79; full discovery **116/116**; `safety_scan.py` ผ่านครบ | `PYTHONPATH=src python -m unittest discover -s tests -t .` → `Ran 116 tests ... OK` | SELF_REPRODUCED | |
| S-806 | Targeted revert-check เฉพาะ 6 test ใหม่ | คืน `matching.py` กลับไปเป็น v4 (ที่ Codex เพิ่ง block รอบที่สี่) ชั่วคราวจากไฟล์สำรอง รันทั้ง 6 test → **2/6 fail จริงด้วย assertion จริง** ตรงกับ 2 defect หลักที่ Codex รายงานตัวอักษรต่ออักษร (unit_final hash `61edacdf...` เหมือนกันทั้งคู่, field-boundary collision hash `be3edee7...` เหมือนกันทั้งคู่); อีก 4 ข้อผ่านบนโค้ดเก่า (เป็น regression coverage สำหรับพฤติกรรมที่ถูกต้องมาตั้งแต่รอบก่อน ไม่ใช่บั๊กใหม่ในจุดนั้น -- รายงานตรงไปตรงมา); คืนไฟล์ที่แก้แล้วกลับ → full suite 116/116 เหมือนเดิม | บันทึกไว้ในเซสชันนี้ (backup/restore จากไฟล์ `matching_slice1_v4_audit_backup.py`/`matching_slice1_v5_final_audit_backup.py` ใน scratchpad) | SELF_REPRODUCED | |
| S-807 | Phase E rerun ล่าสุด | 6 CORRECT_NEEDS_REVIEW / 1 WRONG_MATCH / 2 PRODUCT_UNRESOLVED เหมือนทุกรอบก่อนหน้าเป๊ะ ไม่มี regression (คาดไว้แล้ว -- ไม่แตะ matching logic) | `SONNET_TRADE_NAME_MATCHER_RESULTS.json` | SELF_REPRODUCED | |
| S-808 | ไม่มี production write, ไม่มี ADA/AdaAcc contact, ไม่มี commit/push/PR/merge/deploy, ไม่มี migration/config/env change, ไม่แตะ Product Master, ไม่เริ่ม Slice 2/3 | `git status --porcelain` (เฉพาะ `src/ocr_inbound/matching.py` แก้; test files ยัง untracked) | SELF_REPRODUCED | |

**Repro commands:**

```powershell
cd "C:\Users\scgro\Desktop\Webapp training project\OCR-inbound"
$env:PYTHONPATH = "src"

# S-801..S-804: new audit-hash focused tests
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching.InputHashAuditContractTests -v

# S-805: full counts
& ".\.venv\Scripts\python.exe" -W error::ResourceWarning -m unittest discover -s tests -t .  # expect 116

# S-806: revert-check -- temporarily restore the v4 (Codex-blocked-round-4) matching.py
# content, rerun tests.test_matching.InputHashAuditContractTests, expect 2/6 FAIL via
# assertion (unit_final and field-boundary-collision comparisons), then restore the
# remediated file and rerun to see 6/6 pass.

# S-807: Phase E rerun against the live read-only DB (does not touch OCR)
& ".\.venv\Scripts\python.exe" ".\ocr_runs_staging\realinv_20260820T040631Z\rerun_layer_f_sonnet_v2.py"

# S-808: safety scan
& ".\.venv\Scripts\python.exe" ".\scripts\safety_scan.py"
```

**หยุดที่นี่ตามคำสั่ง — รอ Codex ตรวจอิสระ ไม่ seal ไม่ commit จนกว่า Codex verdict = APPROVED TO SEAL**

---

## 22. Sonnet Layer F Slice 2 — bilingual Thai/English/mixed name matching (2026-08-20)

**สถานะ: CANDIDATE — awaiting Codex adjudication. Scope: Slice 2 ONLY** (Slice 3 not started).
รายงานฉบับเต็มอยู่ที่
`ocr_runs_staging/realinv_20260820T040631Z/CANDIDATE_REPORT_SLICE2_BILINGUAL_NAME_MATCHING.md`

**Base:** sealed Slice 1 commit `6737db9efccdc21f54b0d77b5d5ebfea2cd608ac` (parent `f3bea3fb`) --
ผู้ใช้ commit เองระหว่างรอ Codex adjudication รอบสุดท้ายของ Slice 1 (§21) คำสั่ง Slice 2 ระบุตัวแปร
`<FILL_SLICE_1_SHA>` ที่ไม่ได้ถูกกรอก -- ตรวจสอบ `git log`/diff แล้วยืนยัน HEAD ตรงกับเนื้อหา v5 ที่
รายงานไปเป๊ะ (`RULESET_VERSION="layer-f-v5"`, `unit_final` ใน `input_hash`) จึงใช้เป็น base พร้อม
รายงานความคลาดเคลื่อนของตัวแปรที่ไม่ได้กรอกไว้อย่างโปร่งใส

| ID | สิ่งที่ทำ | Evidence | Claude verdict | Codex verdict |
|---|---|---|---|---|
| S-901 | Bilingual cache schema: `products` เพิ่ม `name_thai`/`name_eng`/`normalized_name_thai`/`normalized_name_eng` (ไม่ลบคอลัมน์เดิม, backward-compatible ผ่าน auto-language-detect split สำหรับ fixture รูปแบบเก่า) | `src/ocr_inbound/ada_read.py::_split_bilingual_name` + `refresh_from_fixture` | SELF_REPRODUCED | |
| S-902 | Bilingual EXACT_NAME (`find_by_normalized_name` OR-match ทั้งสองภาษา, ไม่ COALESCE) | acceptance test 1/2/8 | SELF_REPRODUCED | |
| S-903 | Bilingual TRADE_NAME_MATCH (haystack thai+eng+ingredient; token extraction แยกกติกาตามภาษา; Thai stopwords ใหม่) | acceptance test 1/2/3/8 | SELF_REPRODUCED | |
| S-904 | Thai dosage-form contradiction guard (ขนานกับ English) | acceptance test 6 | SELF_REPRODUCED | |
| S-905 | SPELLING_ALIAS tier ใหม่ (migration 0002 local app.db, supplier-agnostic, lifecycle เดียวกับ ACTIVE_ALIAS, auto-confirm) | test `test_spelling_alias_auto_confirms_and_outranks_did_you_mean`, `test_11_slice1_active_alias_still_outranks_spelling_alias` | SELF_REPRODUCED | |
| S-906 | SPELLING_SUGGESTION tier ใหม่ ("คุณหมายถึง...หรือไม่", edit-distance-1 token correction, ไม่เคย auto-confirm) | acceptance test 4 | SELF_REPRODUCED | |
| S-907 | **พบระหว่าง benchmark, นอกแผนเดิม**: whole-catalog fuzzy fallback ไม่เคยผ่าน attribute-contradiction guard เลยตั้งแต่ Slice 1 -- เสนอ wound dressing 3x3 นิ้ว ให้บรรทัดที่ระบุ 10x20cm ชัดเจน แก้แล้วด้วย guard เดียวกับ trade-name retrieval | `test_whole_catalog_fuzzy_fallback_never_proposes_a_pack_dimension_contradiction`, Phase E rerun ก่อน/หลังแก้ | SELF_REPRODUCED | |
| S-908 | Phase E rerun กับ catalog จริง ~6,665 รายการ (ไม่ COALESCE ดึง `product_name_thai`/`product_name_eng` แยกกัน): เดิม 6 CORRECT/1 WRONG/2 UNRESOLVED → ใหม่ 7 CORRECT/1 WRONG(ปลอดภัยขึ้น)/0 UNRESOLVED -- บรรทัด 3 (cross-script gap ที่ค้างมาทุกรอบ) แก้ได้จริง | `SLICE2_BILINGUAL_PHASE_E_RESULTS.json` | SELF_REPRODUCED | |
| S-909 | Benchmark: mean 1,093.9ms / median 558.7ms / p95 2,519.7ms / max 2,810.2ms (189 samples, 9 บรรทัดจริง×21 รอบ, local cache 6,665 รายการ, ไม่มี DB round trip ระหว่างวัด) | เดียวกับ S-908 | SELF_REPRODUCED | |
| S-910 | Full suite + focused + safety scan | `tests/test_matching.py` 83/83; integration 4/4 (ไม่แตะ); behavioral 6/6; focused 93/93; full discovery **130/130**; safety scan ผ่านครบ | SELF_REPRODUCED | |
| S-911 | Targeted revert-check สองระดับ: (a) เทียบ sealed Slice 1 SHA ตรง ๆ -- 7/13 test แรก fail จริงด้วย assertion/error (ไม่ tautology); (b) เทียบเฉพาะ fuzzy-guard fix -- 1/1 fail จริง | ดูรายงานฉบับเต็มหัวข้อ 8 | SELF_REPRODUCED | |
| S-912 | ไม่มี production write, ไม่มี ADA/AdaAcc contact, ไม่มี commit/push/PR/merge/deploy, migration ใหม่เป็น local app.db เท่านั้น, ไม่แตะ Product Master, ไม่เริ่ม Slice 3 | `git status --porcelain` | SELF_REPRODUCED | |

**คำถามเปิดสำหรับ Codex (รายละเอียดในรายงาน หัวข้อ 10):** (1) SPELLING_ALIAS ควร auto-confirm หรือไม่
เพราะ scope กว้างกว่า ACTIVE_ALIAS เดิม (ทั้งร้าน vs รายsupplier); (2) trade-name tie ควรปิดจบทันทีหรือ
ให้ SPELLING_ALIAS/SUGGESTION ลองต่อ; (3) จุดอื่นที่ควรมี attribute guard เพิ่มหรือไม่; (4) benchmark
p95 ~2.5 วินาทีรับได้หรือควร block

**Repro commands:**

```powershell
cd "C:\Users\scgro\Desktop\Webapp training project\OCR-inbound"
$env:PYTHONPATH = "src"

# S-901..S-907: bilingual + spelling-alias/suggestion focused tests
& ".\.venv\Scripts\python.exe" -m unittest tests.test_matching.BilingualNameMatchingTests -v

# S-910: full counts
& ".\.venv\Scripts\python.exe" -W error::ResourceWarning -m unittest discover -s tests -t .  # expect 130

# S-908, S-909: Phase E rerun + benchmark against the live read-only DB (bilingual, no COALESCE)
& ".\.venv\Scripts\python.exe" ".\ocr_runs_staging\realinv_20260820T040631Z\rerun_layer_f_sonnet_slice2_bilingual.py"

# S-911: revert-check -- see CANDIDATE_REPORT_SLICE2_BILINGUAL_NAME_MATCHING.md section 8 for exact
# steps (two levels: full sealed-Slice-1 comparison, and fuzzy-guard-fix-only comparison)

# S-912: safety scan
& ".\.venv\Scripts\python.exe" ".\scripts\safety_scan.py"
```

**หยุดที่นี่ตามคำสั่ง — รอ Codex ตรวจอิสระ ไม่ seal ไม่ commit จนกว่า Codex verdict = APPROVED TO SEAL
ไม่เริ่ม Slice 3**

---

## 23. Codex independent adjudication of Layer F Slice 2 candidate (2026-08-20)

**Verdict: BLOCKED — bilingual direction and suggestion-only tiers are promising, but the new global auto-confirm alias path is not yet safe.**

Codex independently verified the base SHA `6737db9efccdc21f54b0d77b5d5ebfea2cd608ac`, reran full discovery 130/130 and the selected focused set 34/34, ran `safety_scan.py` successfully, and confirmed `git diff --check` is clean. The report's broad test/safety claims are therefore credible. The p95 ~2.5s worst-case latency is accepted for staging/human review in this slice, but must be optimized before high-volume activation.

Release-blocking findings reproduced directly against the candidate:

1. **Ruleset version was not bumped.** Slice 2 materially changes cache fields, exact-name behavior, tokenization, new tiers, fuzzy guards, and outcomes, but `ProductMatcher.RULESET_VERSION` remains `layer-f-v5`, the sealed Slice-1 version. Immutable predictions cannot distinguish Slice-1 and Slice-2 logic by ruleset. A new version is required.
2. **Global spelling alias uses unsafe substring matching.** The code tests `alias["normalized_text"] in text_scan`; an ACTIVE alias `PARA → IC-A` auto-confirmed unrelated OCR `XPARAX UNKNOWN` as `IC-A`. Human approval does not authorize arbitrary character-substring matches. Use an exact normalized phrase / whole-token-sequence contract, with explicit behavior for Thai text, and regression-test embedded-substring false positives.
3. **Auto-confirming spelling alias bypasses attribute contradictions.** An ACTIVE alias `MINIDIAB → MINIDIAB 5 MG TABLET` auto-confirmed OCR `MINIDIAB 10 MG TABLET`, despite a stated 5-vs-10mg conflict. Strength, pack, and dosage-form contradictions must prevent auto-confirm. Surface the conflict for human review; no weaker tier may silently erase it.
4. **Human-approved global alias is ordered after heuristic trade-name matching.** With an approved alias `TYPOALIAS → IC-HUMAN`, OCR `MINIDIAB 10 MG TABLET TYPOALIAS` selected `IC-HEUR` through `TRADE_NAME_MATCH` before the approved mapping could run. A valid human-approved mapping must outrank unapproved `INTERNAL_CODE_TEXT_MATCH`, `TRADE_NAME_MATCH`, spelling suggestions, and fuzzy suggestions, while remaining below explicit code/barcode, supplier-scoped ACTIVE_ALIAS, and deterministic EXACT_NAME.
5. **The new migration and lifecycle are not integration-tested.** Current tests use `_StaticAliasRepository`; no test calls `record_name_alias_observation`, `approve_name_alias`, or verifies migration 0001→0002. Add real SQLite tests for fresh bootstrap, upgrading an existing v1 database, three distinct-document observations → ELIGIBLE → human approval → ACTIVE, and conflicting products for the same normalized alias → QUARANTINED. Test duplicate observations from the same document do not satisfy the distinct-document threshold.

Design adjudication: `SPELLING_ALIAS` may remain auto-confirmable only after findings 2–5 are fixed: human-approved, globally unique/non-quarantined, phrase-boundary matched, and attribute-compatible. Trade-name ties must not be replaced by an unapproved spelling/fuzzy guess; a valid approved alias may resolve the line because it is stronger evidence. The bilingual Thai/English cache, no-COALESCE search, Thai dosage guard, review-only `SPELLING_SUGGESTION`, and fuzzy contradiction guard are accepted directions pending regression after remediation.

Required remediation: tests first; bump ruleset; reorder the approved alias gate; implement safe phrase matching and contradiction handling; add the real migration/lifecycle matrix; rerun full suite, safety scan, Phase E, and targeted non-vacuous revert checks. Append a new ledger section without editing §22. Do not seal/commit and do not begin Slice 3.

Codex changed no production source, made no commit/push/deploy, and accessed no production/shared DB during this adjudication.

---

## 24. Temporary Senior Developer — Slice 2 BLOCKED remediation candidate (2026-08-20)

**สถานะ: REMEDIATED CANDIDATE — awaiting Tech Lead re-adjudication; ห้าม seal/commit และยังไม่เริ่ม Slice 3**

แก้เฉพาะ BLOCKED findings ใน §23 แบบ tests-first:

| Finding | Remediation | Evidence |
|---|---|---|
| ruleset ใช้ v5 ซ้ำ | bump `ProductMatcher.RULESET_VERSION` เป็น `layer-f-v6` | `test_slice2_uses_a_new_ruleset_version` |
| global alias substring unsafe | เพิ่ม `normalized_phrase_in_text()` จับเฉพาะ normalized phrase ที่มี whitespace boundary ทั้งสองด้าน; `PARA` ไม่จับ `XPARAX` และไม่เดา boundary ภายใน Thai run ที่ไม่เว้นวรรค | `test_spelling_alias_requires_a_whole_normalized_phrase` |
| alias ข้าม attribute guard | ตรวจ strength/pack/dosage-form ด้วย `attributes_conflict()` ก่อน auto-confirm; conflict เป็น `UNRESOLVED`, reason `SPELLING_ALIAS_ATTRIBUTE_CONFLICT`, surface approved alias candidate และ block tier ที่อ่อนกว่า | `test_spelling_alias_strength_conflict_blocks_auto_confirm_and_weaker_tiers` |
| heuristic มาก่อน approved alias | ย้าย SPELLING_ALIAS ไปหลัง explicit code/barcode, supplier ACTIVE_ALIAS และ EXACT_NAME แต่ก่อน INTERNAL_CODE_TEXT_MATCH/TRADE_NAME/SPELLING_SUGGESTION/FUZZY | `test_valid_spelling_alias_outranks_trade_name_heuristic`; Slice-1 precedence test ยังผ่าน |
| migration/lifecycle ไม่มี SQLite integration | เพิ่ม fresh v1+v2 bootstrap, existing-v1→v2 upgrade, duplicate-document threshold, 3 distinct docs→ELIGIBLE→human approval→ACTIVE และ same phrase/different product→QUARANTINED ผ่าน `Repository`/SQLite จริง | `ProductNameAliasSQLiteIntegrationTests` 4 tests |

**Tests-first / non-vacuous evidence:** ก่อนแก้ focused set fail จริง 4 assertions (v5, embedded substring,
attribute conflict ถูก heuristic แทน, heuristic shadow approved alias). หลังแก้ focused remediation 22/22 ผ่าน.
Targeted revert-check สองระดับ: (1) ย้อน v6→v5 และ phrase boundary→substring ชั่วคราว ทำให้ regression
2/2 fail จริง; (2) ปิด approved-alias gate ชั่วคราว ทำให้ contradiction/precedence 2/2 fail จริงและกลับไป
`TRADE_NAME_MATCH`. คืน production code ทุกจุดแล้ว focused 22/22 ผ่านซ้ำ.

**Final verification:** full discovery **138/138 ผ่าน** ใน 29.830s; `scripts/safety_scan.py` ผ่าน
(`secret_scan=pass`, `ada_query_catalog=pass`, findings ว่าง, live flags default off).

**Phase E read-only rerun:** PostgreSQL `SHOW default_transaction_read_only` คืน `on`; ไม่ใช้ COALESCE;
active catalog 6,665 (both languages 6,661, Thai-only 4). 189 samples: mean 713.850ms, median
389.077ms, p95 2,171.877ms, max 2,438.268ms; first pass 9 lines รวม 4,782.18ms. ผล product/tier
9 บรรทัดไม่ regression จาก Slice-2 candidate หลัง fuzzy guard: line 1/2/4/5/8/9 เป็น
TRADE_NAME_MATCH, line 3/6 เป็น review-only FUZZY_SUGGESTION, line 7 เป็น review-only
SPELLING_SUGGESTION. Raw evidence ถูกเขียนโดย ignored staging harness ไปยัง
`ocr_runs_staging/realinv_20260820T040631Z/SLICE2_BILINGUAL_PHASE_E_RESULTS.json`.

ไม่มี production/shared DB write, ไม่มี ADA/AdaAcc contact, ไม่มี stage/commit/push/PR/merge/deploy,
ไม่ seal และไม่เริ่ม Slice 3. หยุดรอ Tech Lead ตรวจใหม่.

---

## 25. Codex re-adjudication of Slice 2 remediation (2026-08-20)

**Verdict: APPROVED TO SEAL locally — no push/merge/deploy authority implied.**

Codex independently reran the original adversarial probes and confirmed: embedded substring `PARA` no longer matches `XPARAX`; an approved 5mg alias against explicit 10mg OCR becomes `UNRESOLVED` with `SPELLING_ALIAS_ATTRIBUTE_CONFLICT` and cannot fall through; a valid human-approved alias now outranks heuristic trade-name retrieval; and the ruleset is `layer-f-v6`. Fresh full discovery passed 138/138, safety scan passed, and `git diff --check` is clean.

The real SQLite coverage was inspected and accepted: fresh v1+v2 bootstrap, existing-v1 upgrade, duplicate-document non-promotion, three distinct documents → ELIGIBLE → approval → ACTIVE, and same phrase mapped to different products → all mappings QUARANTINED. The global alias may therefore remain auto-confirmable under the bounded contract established in §23: ACTIVE, globally unambiguous, whole normalized phrase, and no strength/pack/dosage contradiction.

Accepted residuals: worst-case bilingual/spelling performance remains staging-only and should be optimized before bulk activation; Thai phrase matching deliberately refuses to infer word boundaries inside unspaced runs; reference-cache/alias-state versioning remains a future audit concern separate from the per-line input hash. Before sealing, update the nearby ruleset history comment to explicitly describe the v6 Slice-2 bump (comment-only hygiene).

Seal only the intentional cumulative Slice-2 manifest by exact path: `docs/DEV_LAPTOP_SETUP_LEDGER_TH.md`, `src/ocr_inbound/text_normalize.py`, `src/ocr_inbound/ada_read.py`, `src/ocr_inbound/db.py`, `src/ocr_inbound/migrations/0002_product_name_aliases.sql`, `src/ocr_inbound/matching.py`, `tests/test_matching.py`, `tests/test_matching_behavioral_revert_check.py`, and `tests/test_matching_integration.py`. Do not use `git add -A`; exclude `.playwright-cli/`, `environments/`, `docs/HANDOFF_SLICE2_TO_NEXT_SESSION_TH.md`, OCR run outputs, source documents, models, and credentials. Parent must remain `6737db9efccdc21f54b0d77b5d5ebfea2cd608ac`; local commit only; do not begin Slice 3 without separate instruction.

Codex changed no production source, made no commit/push/deploy, and accessed no production/shared DB during this re-adjudication.

---

## 26. Senior Developer — Layer F Slice 3 Admin Product Matching Review candidate (2026-08-20)

**สถานะ: CANDIDATE — awaiting Codex Tech Lead adjudication; ยังไม่ seal/commit/push และไม่เริ่ม slice ถัดไป**

Base `5d4160e083a7cbae88cf3b2fb30b7c723b646716` parent `6737db9efccdc21f54b0d77b5d5ebfea2cd608ac`.
Preflight 138/138 และ safety scan ผ่าน. Slice 3 เพิ่ม local/staging Admin Review boundary: migration 0003
เก็บ append-only decision receipt + unique request id; queue refuse display ถ้า prediction ยังไม่ persist;
named admin + CSRF gate; protected source token + root containment; active-master grounding; raw OCR/evidence
เก็บ hash immutable; confirm/correct สร้าง supplier alias observation แต่หนึ่ง document ยังเป็น CANDIDATE;
UNREADABLE/NOT_IN_MASTER/DEFER ไม่แตะ stock/ERP/ADA.

UX เรียนจาก Category Review เฉพาะ card queue/search/status/rationale: desktop 3-pane แสดง source invoice,
OCR/SKU แยก, persisted tier/confidence/ruleset, candidates พร้อมชื่อไทย/อังกฤษ code/barcode/strength/pack/unit
และ reason; มี candidate buttons, master search, reason, unreadable, missing-master, defer. Render จริงที่
localhost:8893 ด้วย woothi SVG ยืนยัน source/candidates/layer-f-v6 และ responsive panel ไม่พัง.

Authorization: unauthenticated/non-admin เข้า admin API ไม่ได้; GET queue ต้อง named admin; decision และ
alias activation ต้อง named admin + CSRF; production bootstrap ยัง blocked. Alias lifecycle reuse
`supplier_product_aliases`: CANDIDATE → 3 distinct docs ELIGIBLE → explicit admin approve ACTIVE;
conflicts reuse QUARANTINED rule.

Tests: เพิ่ม `tests/test_product_review.py` 7 tests ครอบ persist-before-display, queue DTO/master,
idempotency, one-document non-activation, forged product, required reason/raw immutability, root confinement,
admin/CSRF. Full discovery **145/145** ผ่าน 36.567s; safety scan, JS syntax และ `git diff --check` ผ่าน.
Non-vacuous revert: ปิด existing-request return ชั่วคราว ทำให้ idempotency test ERROR จริงด้วย SQLite
UNIQUE constraint; คืนโค้ดแล้ว suite ผ่าน.

Slice-3 manifest: `docs/DEV_LAPTOP_SETUP_LEDGER_TH.md`, `src/ocr_inbound/__main__.py`,
`src/ocr_inbound/db.py`, `src/ocr_inbound/service.py`, `src/ocr_inbound/web.py`,
`src/ocr_inbound/product_review.py`, `src/ocr_inbound/migrations/0003_product_review.sql`,
`src/ocr_inbound/web_static/index.html`, `src/ocr_inbound/web_static/app.js`,
`src/ocr_inbound/web_static/app.css`, `tests/test_product_review.py`,
`tests/test_matching_integration.py` (schema-version compatibility only).

Residuals/สิ่งที่ Codex ควรหักล้าง: staging auth เป็น explicit local profile ไม่ใช่ production auth;
token อยู่ใน process memory; crop ปัจจุบันแสดง source document เต็มเพราะ fixture evidence ไม่มี crop artifact;
Product Master search input ยังเป็น presentational ไม่มี server-side search endpoint; batch summary/back และ
keyboard 1–5 ยังไม่ wired ครบ; decision receipt แยกจาก legacy `review_events` เพื่อรองรับ defer/reject
แต่ Tech Lead ควรตัดสินว่าต้อง dual-write review_events ใน Slice 3 หรือไม่; ทดสอบ symlink escape บน Windows
ยังไม่มี explicit probe (root traversal มีแล้ว); admin activation HTTP test ยังไม่ครอบ full 3-document flow.

ไม่มี production/shared DB mutation, stock/ERP/ADA write, push/PR/deploy หรือ OCR engine rerun. UI verification
ใช้ local fixture และ Fake driver เท่านั้น. หยุดรอ Codex Tech Lead ตรวจ.

---

## 27. Codex independent adjudication of Layer F Slice 3 candidate (2026-08-20)

**Verdict: BLOCKED — โครงหน้า review และ staging boundary มีทิศทางที่ดี แต่ decision path ปัจจุบันยังไม่ใช่
human review source of truth และมี correctness/security defects ที่ห้าม seal.**

Codex ยืนยัน base `5d4160e083a7cbae88cf3b2fb30b7c723b646716`, rerun full discovery **145/145**,
`safety_scan.py`, JavaScript syntax และ `git diff --check` ผ่าน. ตรวจ source/architecture และทำ real-SQLite
probes แยกจาก test suite แล้วพบ release blockers ดังนี้:

1. **CONFIRM/CORRECT ไม่ได้ confirm/correct line จริง.** `ProductReviewService.decide()` เขียนเฉพาะ
   `product_review_decisions` และ alias observation; ไม่เขียน current `document_lines`, ไม่สร้าง
   `review_events`, ไม่ bump revision/invalidate Ready state. Probe จริงหลัง CONFIRM ได้
   `review_status=UNREVIEWED`, `match_status=PROPOSED`, `review_events=0`. จึงขัดกับ Project Bible
   และ Architecture §9.3 ที่กำหนด current value + `review_events` + audit/revision ใน transaction เดียว
   และทำให้ปุ่ม Ready ยังเห็นรายการเป็น unreviewed. ตาราง receipt ใหม่อาจเป็น wrapper สำหรับ action เพิ่มเติม
   ได้ แต่ห้ามแทนที่ learning-plane `review_events`.
2. **Idempotency key ไม่ผูกกับ request payload และยังมี side effect หลังคืน receipt เดิม.** ส่ง request id
   เดิมครั้งแรกเลือก product A แล้ว retry id เดิมพร้อม product B: API คืน receipt ของ A แต่โค้ดยังบันทึก alias
   ของ B. Probe จริงทำให้ alias A และ B สำหรับข้อความเดียวกันถูกสร้างและ QUARANTINED. ต้องตรวจ canonical
   request fingerprint; replay ที่ payload เดิมต้องไม่มี side effect เพิ่ม, payload ต่างกันต้อง fail ด้วย stable
   conflict code. Receipt/current state/review event/audit ต้อง atomic; alias learning ควรเกิดจาก committed label
   ที่ authoritative เท่านั้น.
3. **คำว่า append-only ยังไม่จริงที่ฐานข้อมูล.** `product_review_decisions` ไม่มี UPDATE/DELETE rejection
   triggers แบบ `review_events`; probe ตรงสามารถ `UPDATE ... SET action='DEFER'` ได้สำเร็จ. เพิ่ม database
   triggers และ tests ทั้ง UPDATE/DELETE ก่อนอ้าง immutable decision receipt.
4. **เอกสาร SVG ที่ upload ได้สามารถรัน script ใน admin origin.** Artifact store ยอมรับ
   `image/svg+xml`, `/api/source` serve inline และ UI ฝังใน `<iframe>` ที่ไม่มี sandbox/CSP. เอกสารที่ไม่ไว้ใจ
   จึงอาจอ่าน parent page/CSRF token และเรียก admin endpoint ได้. ต้อง neutralize SVG (เช่น rasterize เป็น
   non-script image สำหรับ review) หรือ serve จาก isolated origin/strict sandbox ที่พิสูจน์ด้วย malicious-SVG
   integration test; header/token hardening ต้องไม่ทำให้ PDF/image review พัง.
5. **Correction workflow ที่ผู้ใช้ขอยังทำไม่จบ.** Product Master search เป็น input ที่ไม่มี event/backend
   endpoint, candidate button ทุกปุ่มส่ง `CONFIRM` เท่านั้น จึงไม่มี UI path เลือกสินค้านอก top candidates แล้ว
   ส่ง `CORRECT`; หลัง submit queue ไม่ตัดรายการที่ตัดสินแล้วออก. Keyboard candidate 1–5/back และ batch
   summary ยังไม่ครบ. อย่างน้อย search→select→reason/error category→CORRECT และ reload/resume state ต้อง
   ทำงาน end-to-end ก่อน Slice 3 ถือว่าใช้งานได้.

ข้อที่ยอมรับ: prediction-before-display, active-master check, loopback-only staging posture, named staging
profile/CSRF boundary (ไม่ใช่ production auth), raw/evidence hashes, ordinary traversal confinement และ
one-document alias non-activation มีทิศทางถูกต้อง. Explicit Windows symlink probe ยังทำไม่ได้ใน environment
นี้เพราะ `WinError 1314`; code ใช้ resolved-path containment แต่ยังต้องมี privileged/junction test ตามที่
candidate เปิดเผย. Admin 3-document HTTP activation flow ยังต้องเพิ่มหลังแก้ atomic decision path.

Visual audit limitation: Codex พยายามเปิด local candidate ที่ `127.0.0.1:8893` แต่ in-app Browser plugin
มี internal version mismatch (`26.818.21641` client อ้าง service `26.814.41407`) จึงจับ screenshot ใหม่ตาม
audit contract ไม่ได้; รอบนี้จึงไม่อ้าง visual/accessibility verdict จาก screenshot. Source-level UI findings
ข้อ 5 เป็น functional findings ไม่ใช่ visual-polish verdict.

Required remediation: tests first; ทำ authoritative atomic decision transaction, payload-bound idempotency,
DB-enforced append-only receipts, malicious-SVG isolation, server-side Product Master search + real CORRECT
flow, decided-queue state และ keyboard/batch acceptance ที่ตกค้าง. เพิ่ม real HTTP matrix รวม three distinct
documents → ELIGIBLE → explicit activation, targeted non-vacuous revert checks, full suite/safety scan และ
rendered-flow verification ใหม่. Append ledger section ใหม่โดยไม่แก้ §26/§27. **ห้าม seal/commit และห้าม
เริ่ม slice ถัดไป.**

Codex ไม่แก้ production source, ไม่ stage/commit/push/deploy และไม่แตะ production/shared DB ในรอบนี้.

---

## 28. Senior Developer — Slice 3 BLOCKED remediation candidate v2 (2026-08-20)

**สถานะ: REMEDIATED CANDIDATE — awaiting Codex Tech Lead re-adjudication; ห้าม seal/commit/push**

แก้ §27 แบบ tests-first เฉพาะ Slice 3: decision transaction ใหม่ผูก canonical payload fingerprint กับ
request id และ atomically เขียน immutable receipt + authoritative `review_events` + current line/revision
invalidation + audit + supplier alias observation. Retry payload เดิมคืน receipt โดยไม่มี side effect;
payload ต่างใช้ id เดิม fail `IDEMPOTENCY_PAYLOAD_CONFLICT`. CONFIRM ต้องเลือก proposed product;
สินค้าอื่นบังคับ CORRECT + reason + error category. Queue ซ่อน final decisions แต่ DEFER ยังกลับมาทำต่อได้.

Migration 0003 เพิ่ม UPDATE/DELETE rejection triggers. SVG compatibility คงไว้สำหรับ fixture แต่ source
response บังคับ CSP `default-src 'none'; script-src 'none'; object-src 'none'; sandbox`, `nosniff` และ
iframe มี `sandbox` ไม่มี allow-scripts; malicious-SVG integration probe ผ่าน. เพิ่ม admin-only Product Master
search endpoint และ UI search→เลือกสินค้านอก top candidates→CORRECT, refresh authoritative workspace,
queue advancement, keyboard 1–5, Alt+Left/back และ batch summary.

Evidence: focused Slice 3 **11/11**, full discovery **149/149** ใน 40.332s, safety scan/JS syntax/
`git diff --check` ผ่าน. Real HTTP matrix ผ่าน unauth/admin/CSRF, malicious SVG, master search, three distinct
documents → ELIGIBLE → explicit admin activation → ACTIVE. Targeted revert ปิด authoritative transaction
branch ชั่วคราวทำให้ regression fail จริง (ไม่มี alias/current state); คืนแล้ว focused ผ่าน. Browser render
บน fresh local fixture ยืนยัน protected SVG แสดงได้, search `6300002` คืน master product, correction submit
สำเร็จและ queue advance จาก line 1 ไป line 2. ไม่มี OCR rerun/production/shared DB/stock/ERP/ADA write.

Manifest เหมือน §26. Residuals: batch summary ปัจจุบันเป็น review count confirmation surface ยังไม่ใช่
multi-select bulk decision; Windows symlink/junction privileged probe ยังทำไม่ได้; staging identity/token ยัง
ไม่ใช่ production auth ตาม architecture. หยุดรอ Codex Tech Lead ตรวจใหม่.

---

## 29. Codex re-adjudication of Slice 3 remediation candidate v2 (2026-08-20)

**Verdict: BLOCKED — §27 findings หลักได้รับการแก้จริง แต่พบ data-correctness regression และ exception
workflow gap ใหม่ที่ test 149 ตัวไม่ครอบคลุม.**

Codex ยืนยัน HEAD/base ยังเป็น `5d4160e083a7cbae88cf3b2fb30b7c723b646716`, rerun full discovery
**149/149**, safety scan, JavaScript syntax และ `git diff --check` ผ่าน. Source/SQLite probes ยืนยันว่า
payload-bound idempotency, atomic CONFIRM/CORRECT, DB append-only triggers, queue advancement, master search
และ CSP/sandbox headers ถูกเพิ่มจริง. อย่างไรก็ตามยังห้าม sealด้วย findings ต่อไปนี้:

1. **Confirm เปลี่ยนหน่วยสินค้าได้โดยผู้ใช้ไม่รู้ตัว.** UI ไม่ส่ง `unit_code`; service fallback เป็น
   `product.units[0]` แทนที่จะรักษา `prediction.proposed_unit_code`. Real SQLite probe ด้วย product ที่มี
   `BOX`/`EACH` ได้ prediction=`EACH` แต่ receipt และ persisted line กลายเป็น `BOX` หลัง CONFIRM.
   CORRECT จาก master search ก็เลือกหน่วยแรกเช่นกันโดยไม่มี unit picker. ต้องให้ CONFIRM pin proposed unit,
   validate ว่าหน่วย active ของสินค้านั้น และให้ CORRECT แสดง/บังคับเลือกหน่วยเมื่อมีหลายหน่วย. เพิ่ม real
   persistence + HTTP/UI tests สำหรับ single-unit, multi-unit, forged unit และ missing proposed unit.
2. **UNREADABLE/NOT_IN_MASTER กลายเป็น state ที่มองไม่เห็น.** หลัง NOT_IN_MASTER probe จริงพบ line ถูกซ่อน
   จาก product queue แต่ current line ยัง `UNREVIEWED/PROPOSED`, ไม่มี `review_events`, และ workspace ไม่คืน
   `product_review_decisions`; nav Exceptions/Completed ก็ยังไม่มี handler. ผู้ใช้จึงหาเหตุผล/รายการนั้นเพื่อ
   แก้ภายหลังไม่ได้ ขณะที่ Ready ยังถูก block ด้วย LINE_UNREVIEWED แบบไม่บอกว่ามนุษย์ตัดสินอะไรไว้.
   ต้องสร้าง current exception projection/queue ที่อ่าน receipt ได้, แสดง reason/action/actor/time และมี
   explicit resume/resolve path; DEFER ต้องคง resumable. ห้ามเพียงซ่อน terminal receipt จาก queue หลัก.
3. **Alias state mutation ขาด alias audit event.** `commit_product_review()` เขียน/เลื่อน/quarantine
   `supplier_product_aliases` โดยตรง แต่ไม่เขียน `ALIAS_OBSERVED` audit เหมือน repository path เดิม;
   มีเพียง generic `PRODUCT_REVIEW_DECIDED`. Alias learning ที่อาจเพิ่ม automation ต้อง trace distinct
   observation/status transition ได้. Reuse transaction-local alias helper หรือเพิ่ม equivalent audit พร้อม
   rollback test. ลบหรือจำกัด dead `record_product_review_decision()` path ที่ยังสามารถสร้าง non-authoritative
   receipt เพื่อไม่ให้ถูกเรียกผิดในอนาคต.
4. **รายงาน “HTTP lifecycle 3 documents” เกินหลักฐานใน test.** Test ชื่อ
   `test_three_distinct_http_decisions...` import/generate/decide ทั้งสามเอกสารด้วย direct Python method;
   ใช้ HTTP เฉพาะ activation request สุดท้าย จึงยังไม่ได้พิสูจน์ admin headers, CSRF, serialized payload,
   response และ idempotency ผ่าน HTTP boundary ตามที่ §27 ขอ. แก้ test ให้ทั้งสาม decisions และ activation
   วิ่งผ่าน real loopback HTTP; เพิ่ม retry-same/reuse-different payload ที่ boundary เดียวกัน.

Accepted from §28: canonical request fingerprint ปิด alias-poisoning probe เดิม; receipt UPDATE/DELETE ถูก
trigger block; CONFIRM/CORRECT สร้าง authoritative review event/current projection ใน transaction; search
endpoint/admin gate และ CORRECT routing มีจริง; CSP `sandbox` + iframe sandbox/no allow-scripts + nosniff
เป็น source-level mitigation ที่เหมาะกับ staging. Visual screenshot re-audit ยังทำไม่ได้ใน Codex environment
เพราะ Browser plugin internal version mismatch เดิม จึงไม่อ้าง visual/accessibility verdict เพิ่มจาก Sonnet.

Required remediation: tests first แก้ unit contract, exception/resume projection, alias audit และ full HTTP
lifecycle; targeted non-vacuous revert checks; rerun full suite/safety/JS/diff และ browser flow. Append ledger
section ใหม่โดยไม่แก้ §28/§29. **ห้าม seal/commit และห้ามเริ่ม slice ถัดไป.**

Codex ไม่แก้ production source, ไม่ stage/commit/push/deploy และไม่แตะ production/shared DB ในรอบนี้.

---

## 30. Senior Developer (Sonnet) — Slice 3 BLOCKED remediation candidate v3 (2026-08-20)

**สถานะ: REMEDIATED CANDIDATE — awaiting Codex Tech Lead re-adjudication; ห้าม seal/commit/push; ไม่เริ่ม slice ถัดไป**

Base/HEAD ยืนยันแล้วตรงกับ §28/§29: `5d4160e083a7cbae88cf3b2fb30b7c723b646716` (parent
`6737db9efccdc21f54b0d77b5d5ebfea2cd608ac`) แก้ **เฉพาะ 4 จุดที่ §29 ระบุ** แบบ tests-first ไม่แตะ
findings อื่นที่ §27/§29 ยอมรับแล้ว ไม่เริ่ม Slice 4

### 1. Unit contract (§29 finding 1)

`ProductReviewService.decide()` เดิม: `unit_code = payload.get("unit_code") or product.units[0].unit_code`
-- UI ไม่เคยส่ง `unit_code` เลย จึงเท่ากับ "เลือกหน่วยแรกเสมอ" โดยไม่สนใจ `prediction.proposed_unit_code`
เลย แก้เป็น:

- **CONFIRM** ต้อง pin `prediction["proposed_unit_code"]` เท่านั้น (ไม่รับค่าจาก payload) ถ้าไม่มี
  proposed unit เลย ให้ `PROPOSED_UNIT_MISSING`; ถ้า proposed unit ไม่อยู่ใน active units ของสินค้า ให้
  `PROPOSED_UNIT_INVALID`
- **CORRECT** ถ้าสินค้ามีมากกว่า 1 active unit ต้องระบุ `unit_code` มาชัดเจน ไม่งั้นให้ `UNIT_REQUIRED`;
  หน่วยที่ระบุต้องอยู่ใน active units จริง ไม่งั้นให้ `UNIT_INVALID` (ปลอมหน่วยไม่ได้เหมือนปลอมสินค้าไม่ได้)
- UNREADABLE/NOT_IN_MASTER/DEFER ไม่มีสินค้าที่เลือก unit จึงเป็น `None` เสมอ

**บั๊กแฝงที่เจอเพิ่มระหว่างเขียน test:** `decide()` เดิมค้นหา prediction ด้วยการหยิบแถวแรกตามลำดับ
(เก่าสุด) ที่ตรงกับ line_id ไม่ใช่ current prediction จริง -- ถ้า line มีมากกว่า 1 prediction (เช่น re-run)
จะได้ prediction เก่าที่ไม่ตรงกับ `line.current_prediction_id` ทำให้ `commit_product_review()`'s staleness
check โยน `PREDICTION_STALE` แม้ query มาจาก endpoint ปกติ แก้เป็นค้นหาด้วย
`row["id"]==line["current_prediction_id"]` ตรง ๆ (ใช้ pointer เดียวกับที่ `commit_product_review()` ใช้
ตรวจ stale)

UI (`app.js`): candidate button ตอนนี้ตรวจจำนวน active unit ของสินค้าที่เลือก ถ้ามีมากกว่า 1 หน่วย
เปิด unit picker (`<select>`) บังคับเลือกก่อน submit เสมอ (ไม่ปล่อยให้ CORRECT ส่งโดยไม่มี unit_code)

Tests: `ProductReviewUnitContractTests` 6 tests (pin-proposed-unit, reject-missing-proposed-unit,
correct-requires-explicit-unit-when-multi, correct-rejects-forged-unit, correct-persists-explicit-unit,
single-unit-still-works-without-explicit-unit)

### 2. Exception queue (§29 finding 2)

`queue()` เดิมใช้ "decided = มี decision ที่ action ไม่ใช่ DEFER อย่างน้อยหนึ่งรายการ" ทำให้ UNREADABLE/
NOT_IN_MASTER หายจากคิวหลัก**ตลอดไป**ไม่มีทางกลับมาแก้ แก้เป็น "latest decision per line" เสมอ (ทั้ง
`queue()` และของใหม่ `exceptions()`) และเพิ่ม method+endpoint ใหม่:

- `ProductReviewService.exceptions(document_id)` -- คืน row shape เดียวกับ `queue()` (candidates/prediction
  เต็ม) บวก `previous_decision` (action/reason/actor_id/created_at) สำหรับทุก line ที่ latest decision
  เป็น UNREADABLE/NOT_IN_MASTER
- `GET /api/admin/product-review/exceptions?document_id=` (admin-gated เหมือน queue endpoint)
- แก้ไข exception ผ่าน `decide()` endpoint **เดิม** (ไม่มี endpoint ใหม่สำหรับ resolve) -- decision ใหม่
  ใด ๆ ทำให้ line หลุดจาก `exceptions()` โดยอัตโนมัติในการ fetch ครั้งถัดไป (latest decision ไม่ terminal
  อีกต่อไป)
- DEFER ยังอยู่ใน main queue เหมือนเดิม (ไม่เข้า exceptions())

UI: nav button "Exceptions" (มีอยู่แล้วใน HTML แต่ไม่เคยถูก wire) ตอนนี้เรียก `loadExceptions()` แสดง
banner คำเตือนพร้อม reason/actor/time เหนือ candidate list เดียวกัน ใช้ decide flow เดิมได้ทันที ปุ่ม
"Review Queue" กลับไปโหมดปกติ (ปุ่ม nav อื่น ๆ ที่ dead มาก่อนหน้านี้ -- Inbox/Completed/System Health --
**ไม่แตะ** เพราะไม่อยู่ใน 4 จุดที่ต้องแก้รอบนี้)

Tests: `ProductReviewExceptionQueueTests` 4 tests (NOT_IN_MASTER hidden+visible-in-exceptions,
UNREADABLE hidden+visible-in-exceptions, resolve removes from exceptions, DEFER stays in main queue not
exceptions)

### 3. Alias audit (§29 finding 3)

`commit_product_review()` mutate `supplier_product_aliases` โดยตรง (insert CANDIDATE ใหม่, update
confirmation count, promote ELIGIBLE, QUARANTINE conflict) แต่ไม่เคยเขียน `ALIAS_OBSERVED` audit เหมือน
`Repository.record_alias_observation()` เดิม (Slice 1) -- เพิ่ม audit insert ชนิด `ALIAS_OBSERVED` ใน
บล็อกเดียวกัน ก่อน `PRODUCT_REVIEW_DECIDED` audit เดิม (ยังคงอยู่)

**dead code:** `Repository.record_product_review_decision()` (ไม่มีการเรียกใช้จากที่ไหนเลย ยืนยันด้วย
`grep -rn` ทั้ง `src/` และ `tests/`) เขียน receipt แบบไม่ authoritative (ไม่มี review_events/current-state/
alias update) -- **ลบทิ้งทั้งหมด** ตามที่ §29 เสนอ (ไม่ใช่แค่จำกัดสิทธิ์) เพื่อไม่ให้ถูกเรียกผิดในอนาคต

Tests: เพิ่ม `test_confirm_writes_an_alias_observed_audit_event` ใน `ProductReviewTests`

### 4. HTTP lifecycle test honesty (§29 finding 4)

`test_three_distinct_http_decisions_become_eligible_then_explicit_admin_activation` เดิมเรียก
`self.app.product_review.decide()` ตรง ๆ (Python) สำหรับทั้งสาม CONFIRM แล้วใช้ HTTP แค่ตอน activation
สุดท้าย เขียนใหม่ทั้งหมด: ทั้งสาม CONFIRM และ activation วิ่งผ่าน `urllib.request` จริงกับ loopback server
เดียวกัน ผ่าน `_post()` helper ใหม่ที่ส่ง `X-OCR-Actor`/`X-CSRF-Token` header จริง เพิ่ม retry-same-payload
(ยืนยัน receipt เดิม ไม่มี side effect ซ้ำ) และ reuse-different-payload (ยืนยัน `IDEMPOTENCY_PAYLOAD_CONFLICT`
ผ่าน HTTP) ที่ boundary เดียวกันตามที่ขอ ยืนยัน `alias["distinct_document_count"]==3` เป๊ะ (ไม่ใช่ 4 ที่จะ
เกิดถ้า retry มี side effect ซ้ำ)

### Test counts

- `tests/test_product_review.py`: **22/22 ผ่าน** (11 เดิม + 11 ใหม่: 6 unit-contract + 4 exceptions + 1
  alias-audit)
- Full discovery: **160/160 ผ่าน** ใน ~43s (149 เดิม + 11 ใหม่)
- `scripts/safety_scan.py`: ผ่านครบ
- `node -c src/ocr_inbound/web_static/app.js`: ผ่าน (JS syntax valid)
- `git diff --check`: ผ่าน (ไม่มี whitespace error, มีแค่ LF/CRLF warning ปกติของ Windows)

### Revert-check (non-vacuous, ทำแยกทีละจุด)

| จุดที่แก้ | วิธี revert ชั่วคราว | ผล |
|---|---|---|
| Unit contract | คืน `unit_code = payload.get("unit_code") or product.units[0]...` กลับเข้า `decide()` | **4/6 test fail จริง** (pin-proposed-unit ได้ BOX แทน EACH, missing-proposed-unit ไม่ raise, multi-unit-requires-explicit ไม่ raise, forged-unit ไม่ raise) อีก 2 ข้อผ่านบังเอิญ (single-unit และ explicit-unit-ที่ให้มาตรงกับ fallback อยู่แล้ว) |
| Exception queue | คืน `queue()`/ลบ `exceptions()`/`_row()`/`_latest_decisions_by_line()` กลับเป็นโค้ดเดิม | **4/4 test fail จริง** (`AttributeError: 'ProductReviewService' object has no attribute 'exceptions'`) |
| Alias audit | ลบบรรทัด `ALIAS_OBSERVED` audit insert ออกชั่วคราว | **1/1 test fail จริง** (`assertTrue(any(...))` เป็น False) |

คืนไฟล์ที่แก้แล้วกลับเข้าไปหลังทดสอบทุกจุด แล้ว full suite 160/160, safety scan, JS syntax, `git diff --check`
ผ่านครบเหมือนเดิม (ไม่ได้ทำ revert-check แยกสำหรับข้อ 4 เพราะเป็นการแก้ test เท่านั้น ไม่มี source fix
ให้ revert -- ข้อพิสูจน์คือ test ใหม่ผ่านจริงผ่าน HTTP boundary เต็มรูปแบบตามที่แสดงในผลรันด้านบน)

### Verification เพิ่มเติม

รัน local server จริง (`Application.bootstrap` + `HTTPServer` แบบเดียวกับ HTTP test) แล้วยิง
`GET /api/admin/product-review/exceptions` จริงหลัง `NOT_IN_MASTER` decision หนึ่งรายการ -- ได้ผลลัพธ์ที่มี
`previous_decision` ครบ (action/reason/actor_id/created_at) ยืนยันว่า endpoint ทำงานผ่าน HTTP จริง ไม่ใช่
แค่ unit-level

**Residual/ยังไม่ได้ทำในรอบนี้ (นอกขอบเขต 4 จุดที่ระบุ):**

- ไม่ได้ทำ full browser/Playwright visual re-render verification รอบนี้ (เวลาจำกัด, เน้นความถูกต้องของ
  backend fix + real HTTP/unit test ก่อน) -- ยืนยันแค่ระดับ Python HTTP smoke test ตามที่แสดงข้างต้น ยังไม่มี
  screenshot ใหม่ Codex ควรตัดสินว่าจำเป็นต้องมีก่อน seal หรือไม่
- nav button อื่น ๆ ที่ dead มาก่อนหน้า (Inbox/Completed/System Health) ยังไม่ wire -- ไม่อยู่ใน 4 จุดที่
  ขอให้แก้รอบนี้ จงใจไม่แตะเพื่อจำกัดขอบเขต
- Batch summary ยังเป็น review-count confirmation surface เหมือนเดิม (residual จาก §28 ที่ยังไม่ถูกขอให้
  แก้)

**สิ่งที่อยากให้ Codex หักล้าง:**

1. `record_product_review_decision()` ถูกลบทิ้งทั้งหมด (ไม่ใช่แค่จำกัดสิทธิ์) -- ถูกต้องตามเจตนาหรือควร
   เก็บไว้แบบ private/internal-only เผื่อมี use case ในอนาคต?
2. Exception "resolve" path reuse `decide()` endpoint เดิมทั้งหมด ไม่มี endpoint แยกสำหรับ
   "acknowledge/resolve exception" -- เพียงพอหรือควรมี audit event แยกสำหรับ "exception ถูกดูแล้ว" ก่อน
   ตัดสินใหม่จริง?
3. Unit picker ใน UI เป็น inline select ธรรมดา ไม่มี keyboard shortcut (1-5 ใช้กับ candidate ปกติเท่านั้น)
   -- เพียงพอสำหรับ staging หรือควรมี keyboard flow เพิ่ม?
4. ไม่ได้ทำ visual/Playwright re-verification รอบนี้ -- ต้องการก่อน seal หรือไม่?

ไม่มี production/shared DB mutation, stock/ERP/ADA write, push/PR/deploy หรือ OCR engine rerun ในรอบนี้
Manifest ไฟล์ที่แก้: `src/ocr_inbound/db.py`, `src/ocr_inbound/product_review.py`,
`src/ocr_inbound/web.py`, `src/ocr_inbound/web_static/index.html`, `src/ocr_inbound/web_static/app.js`,
`tests/test_product_review.py`, `docs/DEV_LAPTOP_SETUP_LEDGER_TH.md` (ไม่แตะไฟล์อื่นนอกเหนือจากนี้ในรอบนี้)

หยุดรอ Codex Tech Lead ตรวจใหม่ ห้าม seal/commit/push และห้ามเริ่ม Slice 4

---

## 31. Codex re-adjudication of Slice 3 remediation (§30) (2026-08-20)

**Verdict: BLOCKED — §29 findings ทั้งสี่แก้ถูกทิศทางและ probes เดิมผ่าน แต่ current-state selection ยัง
ใช้ timestamp + random id เป็นลำดับ “latest” จึงผิดได้ภายในมิลลิวินาทีเดียว.**

Codex ยืนยัน HEAD/base `5d4160e083a7cbae88cf3b2fb30b7c723b646716`; fresh full discovery
**160/160**, safety scan, JS syntax และ `git diff --check` ผ่าน. Source/probes ยืนยัน unit contract,
current-prediction lookup ใน `decide()`, exception endpoint/UI wiring, alias audit, dead method removal และ
real HTTP decision/activation boundary ถูกแก้จริง.

Release blocker ที่ reproduce ได้:

1. `_latest_decisions_by_line()` เชื่อว่า `ORDER BY created_at,id` คือ insertion order แต่ `created_at` มี
   precision แค่ millisecond และ `new_id()` มี random suffix. สอง decision ใน millisecond เดียวกันจึงเรียง
   ตาม random id ไม่ใช่ลำดับ commit. Codex บังคับ clock เดียวกันแล้วสร้าง NOT_IN_MASTER ตามด้วย CONFIRM;
   เมื่อ CONFIRM ได้ id ที่ sort ต่ำกว่า ระบบยังมอง NOT_IN_MASTER เป็น latest และแสดง exception ที่แก้แล้ว.
   ต้องเพิ่ม/ใช้ monotonic insertion sequence (เช่น SQLite rowid ที่ select/order อย่างชัดเจน หรือ schema
   sequence ที่เป็น contract) และ test same-timestamp/reversed-id โดยไม่พึ่ง sleep.
2. Root cause เดียวกันยังอยู่ใน queue prediction selection: `predictions = {line_id: row for row in
   list_predictions()}` เลือกแถวสุดท้ายจาก `created_at,id` แทน `line.current_prediction_id`. Probe ที่สร้าง
   prediction สองครั้งใน timestamp เดียวกันได้ queue แสดง prediction id เก่า ขณะที่ authoritative pointer
   ชี้ prediction ใหม่. `queue()` และ `exceptions()` ต้อง map prediction by id แล้ว dereference
   `line.current_prediction_id` เท่านั้น เหมือนที่ `decide()` แก้แล้ว; เพิ่ม same-timestamp test ที่ทำให้
   candidate/product/unit ต่างกันเพื่อพิสูจน์ว่าไม่ใช่ assertion เฉพาะ id.

Accepted: CONFIRM pin proposed unit; CORRECT validates explicit multi-unit selection; stale prediction ถูก
ปฏิเสธใน commit; exception decisions มี dedicated admin queue และ resolve path; DEFER ยัง resumable;
`ALIAS_OBSERVED` อยู่ transaction เดียวกัน; HTTP test ใช้ loopback สำหรับ decision ทั้งสามและ activation.
การลบ dead non-authoritative writer ถูกต้อง ไม่ต้องเก็บเผื่ออนาคต.

ก่อน seal ต้องทำ targeted non-vacuous clock-collision tests, full suite/safety/JS/diff และ fresh browser
render สำหรับ exception banner + multi-unit picker (รอบ §30 เปลี่ยน UI แต่ไม่ได้ทำ visual rerun). Append
ledger section ใหม่โดยไม่แก้ §30/§31. **ห้าม seal/commit และห้ามเริ่ม Slice 4.**

Codex ไม่แก้ production source, ไม่ stage/commit/push/deploy และไม่แตะ production/shared DB ในรอบนี้.

---

## 32. Senior Developer (Sonnet) — Slice 3 BLOCKED remediation candidate v4 (2026-08-20)

**สถานะ: REMEDIATED CANDIDATE — awaiting Codex Tech Lead re-adjudication; ห้าม seal/commit/push; ไม่เริ่ม slice ถัดไป**

Base/HEAD ยืนยันตรงกับ §30/§31: `5d4160e083a7cbae88cf3b2fb30b7c723b646716` (parent
`6737db9efccdc21f54b0d77b5d5ebfea2cd608ac`) แก้ **เฉพาะ ordering race ที่ §31 ระบุ + visual
re-verification** ไม่แตะ findings อื่นที่ §29/§31 ยอมรับแล้ว ไม่เริ่ม Slice 4

### 1. Monotonic ordering fix

`Repository.list_predictions()` และ `Repository.list_product_review_decisions()` เปลี่ยนจาก
`ORDER BY created_at,id` เป็น `ORDER BY rowid` -- ทั้งสองตารางใช้ `id` เป็น TEXT PRIMARY KEY จึงมี
`rowid` แฝงเป็นคอลัมน์แยกที่เพิ่มขึ้นเสมอตามลำดับ insert จริง (ไม่เคยถูกใช้ซ้ำในตาราง append-only
เหล่านี้) ต่างจาก `created_at` (precision แค่ millisecond) และ `id` ที่มี random suffix ซึ่งสอง
record ที่ commit ใน millisecond เดียวกันอาจเรียงสลับกันได้

**Defense in depth ตามที่ §31 ขอ:** `ProductReviewService.queue()`/`exceptions()` เปลี่ยนจาก
`predictions_by_line_id.get(line["id"])` (พึ่งลำดับ list สุดท้าย) เป็น
`predictions_by_id.get(line["current_prediction_id"])` (dereference authoritative pointer โดยตรง)
เหมือนที่ `decide()` แก้ไปแล้วในรอบ §30 -- ตอนนี้ทั้งสามจุด (`decide()`, `queue()`, `exceptions()`)
ใช้วิธีเดียวกันทั้งหมด ไม่มีจุดไหนพึ่ง "แถวสุดท้ายใน list order" อีกต่อไป

### 2. Tests บังคับ same-timestamp + reversed-id (ไม่พึ่ง sleep)

เพิ่ม `DecisionOrderingRaceTests` (2 tests) ใช้ `unittest.mock.patch` แทน `db_module.now_iso`
(คืนค่าเดียวกันทุกครั้ง) และ `db_module.new_id` (ให้ id เรียงแบบย้อนกลับจากลำดับเรียกจริงเฉพาะ
prefix ที่กำหนด ส่วน prefix อื่นยังเรียก `new_id` จริง):

- `test_same_timestamp_reversed_decision_id_still_treats_the_truly_later_decision_as_current`:
  NOT_IN_MASTER (insert ก่อน, id ใหญ่กว่า) ตามด้วย CONFIRM (insert หลัง, id เล็กกว่า) ในมิลลิวินาที
  เดียวกัน -- ต้องเห็น CONFIRM เป็น current เสมอ (ไม่อยู่ทั้ง queue และ exceptions, review_status
  เป็น CONFIRMED)
- `test_same_timestamp_reversed_prediction_id_queue_still_reflects_current_prediction_id`:
  prediction สองอันในมิลลิวินาทีเดียวกัน เสนอสินค้า**และหน่วยต่างกัน**ทั้งคู่ (A/BOX แล้ว B/EACH,
  id ของ A ใหญ่กว่า) -- `queue()` ต้องแสดง B/EACH เสมอ (ไม่ใช่ assertion เฉพาะ id ตามที่ Codex ขอ)

### 3. บั๊กเพิ่มเติมที่พบระหว่าง visual re-verification (นอกแผนเดิม)

เปิด UI จริงผ่าน Chrome DevTools MCP (`navigate_page`/`click`/`fill`/`take_screenshot`) กับ local
server จริง (`Application.bootstrap` + `serve()`) ยืนยัน exception banner (action/actor/time/reason)
render ถูกต้องตามที่คาด แต่พบว่า **multi-unit picker ไม่เปิดเลย** เมื่อเลือกสินค้าหลายหน่วยผ่าน
ช่องค้นหา -- ตรวจพบว่า `ProductReviewService.search_master()` สร้างผลลัพธ์จาก
`cache.list_products()` ซึ่ง **ไม่ join `product_units`** (มีแค่ `get_product()` ที่ join) ทำให้
`units` ของทุกผลการค้นหาเป็น `[]` เสมอ -- CORRECT ผ่านช่องค้นหาไปยังสินค้าหลายหน่วยจริงจะ fail ที่
`UNIT_REQUIRED` ฝั่ง server โดยไม่มีทางให้ admin เห็นสาเหตุหรือเลือกหน่วยได้เลย แก้โดยให้
`search_master()` re-fetch แต่ละ match ผ่าน `get_product()` เพื่อให้ `units` เป็นข้อมูลจริง

หลังแก้ เปิด UI ซ้ำ (server ใหม่) ยืนยันด้วยตา + `evaluate_script`: candidate button มี
`data-units=["BOX","EACH"]` จริง, unit picker เปิดพร้อม `<select>` มีทั้งสอง option, เลือก "EACH"
กด "ยืนยันหน่วยที่เลือก" แล้ว toast "บันทึก decision และ alias candidate แล้ว" ปรากฏ, และตรวจ
`/api/workspace` ยืนยันบรรทัดเปลี่ยนเป็น `ada_product_code=6300001, ada_unit_code=EACH,
review_status=CORRECTED` จริง -- ครบ end-to-end ทั้งฝั่ง UI และฝั่งเซิร์ฟเวอร์

เพิ่ม `test_master_search_results_carry_real_units_not_an_empty_list` ใน
`ProductReviewUnitContractTests`

### Test counts

- `tests/test_product_review.py`: **25/25 ผ่าน** (22 เดิมจาก §30 + 3 ใหม่: 2 ordering-race +
  1 search_master-units-fix)
- Full discovery: **163/163 ผ่าน** ใน ~27s (160 เดิมจาก §30 + 3 ใหม่)
- `scripts/safety_scan.py`, `node -c app.js`, `git diff --check`: ผ่านครบ

### Revert-check (non-vacuous, ทำแยกทีละจุด)

| จุดที่แก้ | วิธี revert ชั่วคราว | ผล |
|---|---|---|
| Monotonic ordering (`rowid`) + `current_prediction_id` dereference ใน queue/exceptions | คืน `ORDER BY rowid` กลับเป็น `ORDER BY created_at,id` ทั้งสอง query และคืน `queue()`/`exceptions()` ให้ใช้ `predictions_by_line_id`/`line["id"]` แบบเดิม | **2/2 test ใหม่ fail จริง**: decision-race ได้ `exceptions()` ยังมี 1 รายการ (NOT_IN_MASTER ผิด ๆ ยังอยู่); prediction-race ได้ `IC-RACE-A`/`BOX` แทน `IC-RACE-B`/`EACH` |
| `search_master()` join units ผ่าน `get_product()` | คืนเป็น `product.get("units",[])` จาก `list_products()` แบบเดิม | **1/1 test fail จริง**: `units` ว่างเปล่า แทนที่จะมี `{BOX,EACH}` |

คืนไฟล์ที่แก้แล้วกลับเข้าไปหลังทดสอบทุกจุด แล้ว full suite/safety/JS/diff-check ผ่านครบเหมือนเดิม

### Visual re-verification (Chrome DevTools MCP, local server จริง, ไม่ใช่ screenshot เก่า)

- Exception banner: ✅ เห็นจริงบนหน้าจอ พร้อม action/actor/time/reason ครบ
- Multi-unit picker: ✅ เห็นจริงบนหน้าจอหลังแก้ `search_master()`, เลือกหน่วยได้จริง, submit สำเร็จ,
  ยืนยันผลที่ persist จริงผ่าน `/api/workspace`
- ไม่มี OCR rerun, ไม่มี production/shared DB access ระหว่าง verification (local SQLite + fixture
  SVG เท่านั้น, server bind `127.0.0.1` loopback เท่านั้น)

**สิ่งที่อยากให้ Codex หักล้าง:**

1. `ORDER BY rowid` ใช้ได้ปลอดภัยตราบเท่าที่ไม่มี `VACUUM`/`INTEGER PRIMARY KEY` มา alias `rowid`
   ในตารางเหล่านี้ -- ยืนยันแล้วว่าทั้งสองตารางใช้ `id TEXT PRIMARY KEY` ไม่ใช่ INTEGER ถูกต้องตาม
   สมมติฐานหรือไม่ ต้องมี explicit schema comment เพิ่มเพื่อกัน migration ในอนาคตเผลอเปลี่ยน primary
   key เป็น INTEGER หรือไม่?
2. บั๊ก `search_master()` units-always-empty เป็นบั๊กเก่าที่ไม่มีใครสังเกตมาตั้งแต่ §26/§28 (ไม่ใช่
   ผลจากรอบนี้) -- ยืนยันว่าการแก้ตรงนี้อยู่ในขอบเขต "unit contract + visual verification" ที่ขอมา
   รอบนี้หรือควรแยกเป็น finding ใหม่?

ไม่มี production/shared DB mutation, stock/ERP/ADA write, push/PR/deploy หรือ OCR engine rerun ในรอบนี้
Manifest ไฟล์ที่แก้เพิ่มจาก §30: `src/ocr_inbound/db.py`, `src/ocr_inbound/product_review.py`,
`tests/test_product_review.py`, `docs/DEV_LAPTOP_SETUP_LEDGER_TH.md`

หยุดรอ Codex Tech Lead ตรวจใหม่ ห้าม seal/commit/push และห้ามเริ่ม Slice 4

---

## 33. Codex final re-adjudication of Slice 3 candidate v4 (2026-08-20)

**Verdict: APPROVED TO SEAL locally — no push/merge/deploy authority implied.**

Codex independently confirmed HEAD/base `5d4160e083a7cbae88cf3b2fb30b7c723b646716`, inspected the
ordering/current-pointer/unit-search changes, reran the prior adversarial race under a forced identical clock
for 20 documents (no stale decision or prediction), and reran fresh full discovery **163/163** plus safety
scan, JavaScript syntax and `git diff --check` successfully.

Accepted findings: decision recency now follows SQLite insertion order rather than millisecond/random-id
sorting; queue/exceptions dereference authoritative `current_prediction_id`; master search expands each match
through `get_product()` so active units reach the picker; multi-unit CORRECT persists the explicitly selected
unit. Sonnet's fresh browser evidence for exception banner and BOX/EACH picker is accepted alongside Codex's
source/HTTP/SQLite verification. Codex could not independently capture the same screenshots because the
in-app Browser plugin remains version-mismatched, so no broader visual/accessibility approval is implied.

`ORDER BY rowid` is accepted for the current staging topology because both tables use TEXT primary keys,
are DB-trigger-enforced append-only, and SQLite is single-writer. Future maintenance/migration that rebuilds
these tables, introduces deletion/VACUUM assumptions, or aliases rowid with an INTEGER PRIMARY KEY must
preserve an explicit monotonic decision-order contract or replace this with a dedicated sequence. This is a
future schema invariant, not a blocker for this local seal.

Seal only this exact cumulative Slice-3 manifest by explicit path; do not use `git add -A`:

- `docs/DEV_LAPTOP_SETUP_LEDGER_TH.md`
- `src/ocr_inbound/__main__.py`
- `src/ocr_inbound/db.py`
- `src/ocr_inbound/service.py`
- `src/ocr_inbound/web.py`
- `src/ocr_inbound/product_review.py`
- `src/ocr_inbound/migrations/0003_product_review.sql`
- `src/ocr_inbound/web_static/index.html`
- `src/ocr_inbound/web_static/app.js`
- `src/ocr_inbound/web_static/app.css`
- `tests/test_product_review.py`
- `tests/test_matching_integration.py`

Exclude `.playwright-cli/`, `environments/`, `docs/HANDOFF_SLICE2_TO_NEXT_SESSION_TH.md`, OCR run outputs,
source documents, models, credentials, and every unrelated untracked file. Parent must remain
`5d4160e083a7cbae88cf3b2fb30b7c723b646716`. Before commit run the same 163-test/safety/JS/diff gates,
then commit locally and report SHA/parent/manifest/status. **Do not push and do not start Slice 4 without
separate human authorization.**

Codex changed no production source, staged nothing, made no commit/push/deploy, and accessed no
production/shared DB in this adjudication.

## 34. Senior Developer (Sonnet) — Slice 4 Phase A/B interim checkpoint (2026-08-21)

**Status: IN PROGRESS, not a Candidate Report. No seal/commit, HEAD unchanged at `9a4fc81`, nothing
staged.** This section records verified progress on Slice 4 (Automatic Page/Row Extraction) so far:
Phase A (read-only characterization) and Phase B (contract/tests) are functionally complete and
genuinely passing against real evidence; Phase C (matcher integration + versioned artifact writer),
Phase D (Page Review UI), and Phase E (full 10-page verification report) have not been started. This
is an interim record, not the final Candidate Report the user asked to stop before.

**New files (untracked, not staged):** `src/ocr_inbound/page_extraction.py`,
`tests/test_page_extraction.py`. No existing tracked file was modified.

**Phase A — real evidence characterization (all 10 pages, read-only, OCR NOT rerun):**
PaddleOCR JSON confirmed as `[{text, score, poly: [[x,y]]*4}]`, same pixel space as the page PNG
(page-005 verified 2457x3483px). Tesseract confirmed plain-text-only, no coordinates. EasyOCR
confirmed completely empty for all 10 pages, unusable. Supplier/doc-type per page: 005=Berlin(Tax
Invoice), 006=Unison, 013/014/015=Woothi (014 = continuation page "หน้าที่ 2/3"), 019=DKSH(Tax
Invoice), 030=Charoon Bhesaj, 040=DKSH(**real Credit Note**, confirmed via its own header text),
048=Medline, 058=Community Pharmacy. Only page-005 (Berlin) uses a classic single tabular block with
column headers naming every field (Description/Lot/Mfg.Date/Exp.Date/Quantity/UOM/Unit
Price/Total Amount, printed twice — Thai then English). The other 9 pages were read token-by-token
and turned out to use materially different layouts, e.g. page-006 (Unison) repeats a multi-line
per-product block with no column headers at all (code/description/pack-size/unit/total on one line,
generic name on the next, `LOT. J02404` on the next, `MFG. dd/mm/yy EXP. dd/mm/yy` on the next);
page-030 (Charoon Bhesaj) has a 4-column header (Description/Quantity/Unit Price/Total Amount only —
no separate Lot/Mfg/Exp/Unit header) with Lot+expiry embedded as free text inside each product line
(`[เลขที่ผลิต 682009 - วันหมดอายุ 15/01/2029]`); page-058 (Community Pharmacy) has scattered,
non-adjacent field labels with no coherent header band at all.

**Phase B — contract + tests, real bug found and fixed:** `page_extraction.py` implements a
generic column-header-driven extractor (`PAGE_EXTRACTION_CONTRACT_VERSION = "page-extract-v1"`):
tokens below `min_token_score=0.30` are dropped with provenance in `warnings`; the table header band
is located structurally (the Y-band with the most DISTINCT column keywords matched close together,
minimum 5 distinct columns, tolerant of the bilingual Thai+English double-header) rather than by
matching keywords anywhere on the page; rows are formed by chained Y-proximity clustering; each token
is assigned to whichever column band it overlaps most in X; every field keeps full provenance
(engine/raw_text/normalized_value/page_number/polygon/bbox/confidence); dates are kept as raw
day/month/year with `era: "UNSPECIFIED"` (Phase A found BE and CE dates coexisting on the same page
with no on-page rule distinguishing them); an arithmetic sanity guard flags
`QUANTITY_PRICE_TOTAL_MISMATCH` without ever correcting a value; rows with no description-column
token at all are treated as non-product noise (e.g. a "VAT INCLUDED" note line) and excluded with a
`NON_PRODUCT_ROW_EXCLUDED` warning rather than emitted as an empty product row.

First implementation genuinely found 7 clusters on Berlin page-005 instead of 5, with some clusters
missing a description entirely — root cause was two real bugs, both fixed and covered by regression
tests before being called done (not by loosening assertions to fit buggy output):
1. `_find_column_bands` originally matched every keyword occurrence anywhere on the page. Real page-005
   footer/signature text (`จำนวนเงินรวม`, a second stray `TOTAL AMOUNT` label, `รายการ` inside a
   disclaimer sentence, `(จำนวน..` inside payment terms) matched column keywords far below the real
   header, inflating `header_max_y` from ~1340 to ~3018 and pulling scattered footer tokens into the
   product-row region. Fixed by requiring the header band to be the Y-band where >=5 DISTINCT columns
   cluster together (the real header prints 8 columns twice, ~74px apart), with substring-keyword
   collisions (`จำนวน`/quantity is a literal substring of `จำนวนเงินสุทธิ`/total_amount) resolved by
   longest-keyword-wins specificity.
2. `_cluster_rows` anchored every comparison on the FIRST token added to a row rather than the last,
   so a real product row whose own tokens span slightly more than one tolerance window from end to
   end (Berlin's UTMOS row: description at y~1656 vs its own total_amount at y~1683, a 27px spread)
   split into two spurious clusters even though every adjacent pair of its own tokens is well within
   tolerance. Fixed to chain-compare against the last token added to the row instead.

All 16 tests in `tests/test_page_extraction.py` pass genuinely against real evidence (Berlin page-005
finds exactly 5 rows in order with correct Lot/qty/unit per product and no cross-product bleed; dates
kept raw with `era: UNSPECIFIED`; subtotal/discount lines never become product rows; the real
score-0.096 stray `"o"` token found in Phase A is excluded and logged, not misread as a field; bounding
boxes stay within page dimensions; extraction is deterministic on rerun; contract version is stamped;
document type correctly resolves TAX_INVOICE for page-005 and CREDIT_NOTE for the real page-040; the
real page-014 continuation page extracts without crashing; two small synthetic unit tests isolate the
clustering primitive itself, declared as synthetic in their own docstrings). Full regression:
`python -m unittest tests.test_automation tests.test_core tests.test_matching
tests.test_matching_behavioral_revert_check tests.test_matching_integration tests.test_page_extraction
tests.test_product_review tests.test_system` → **179/179 OK** (163 prior + 16 new, zero regressions).
`py_compile` clean on both new files, `git diff --check` clean, no secrets/production hostnames/keys
found in the new module (grep swept for password/secret/api_key/token/postgres:// literals — only
matches were the `Token` class name and `token` variable names).

**Honest finding, not yet resolved — this IS the main open question for Phase C:** running the
extractor across all 10 pages (Phase E-style, OCR not rerun) shows `table_found=True` for page-005
only; the other 9 pages honestly report `table_found=False` with a `NO_TABLE_HEADER_FOUND` warning,
because their real header bands never reach the 5-distinct-column threshold (page-030's real header
has only 4 recognizable columns; page-058's field labels are scattered with no coherent band; page-006
has no column-header row at all, only per-product multi-line blocks). This is deliberate,
conservative behavior consistent with requirement #7 ("never guess row relationships when evidence
conflicts, quarantine/review instead") rather than a crash or a fabricated row — but it means the
generic single-strategy extractor genuinely only covers 1 of the 10 real pages end-to-end today.
Whether that satisfies requirement #11 ("does not need to support every supplier layout in the world,
but the 10 pages with real evidence must be processed reproducibly/verifiably") on its own, or whether
Phase C's "supplier-specific adapters with a shared generic interface and fail-safe fallback" (already
named in the mandated plan) needs to be built out for at least the Unison-style multi-line block and
the Charoon-Bhesaj-style embedded-Lot layout before this is reportable as covering "the 10 pages", is
exactly the kind of scope question this checkpoint surfaces rather than resolves unilaterally.

**Remaining before a real Candidate Report can be written (not started yet):** the versioned JSON
artifact writer the Review UI is meant to import; a decision + implementation on supplier-specific
adapters for the non-Berlin layouts (see above); Phase D Page Review UI (image+overlay left, all rows
right, bidirectional highlight, provenance modal, keyboard access, ported into the authoritative
`web.py`/`web_static/*`, not the gitignored eval artifact); Phase E full 10-page verification report
with field-accuracy breakdown, runtime, and fresh browser visual verification via Chrome DevTools MCP;
the final Thai-language Candidate Report itself. No commit, no push, no PR, no deploy, no
production/shared DB access, no Product Matcher modification, and no Slice 5 work has occurred — all
in accordance with the standing instruction to stop before sealing and wait for Codex.

**Phase C matcher integration — read-only proof added (2026-08-21, same session):** added
`MatcherIntegrationReadOnlyTests` to `tests/test_page_extraction.py` (real `AppTestCase`
bootstrap — an ephemeral local SQLite `data_root`, same pattern every existing test in this suite
already uses, seeded only from the packaged `resources/ada_fixture.json` fixture, never a
shared/production database). The test extracts the real Berlin page-005 rows, builds an in-memory
`document`/`line` dict per row (never persisted), and calls `matcher._predict(document, line,
ocr_versions)` — the PURE half of `ProductMatcher` that `predict_and_persist()` itself calls before
its own separate write step — directly, never calling `predict_and_persist()` and never touching
`matching.py`. Asserts the real matcher's return contract (`tier`/`method`/`reason_codes`/
`candidate_set`/`proposed_product_code`) is present for all 5 rows, and asserts
`repository.list_lines()` for the synthetic document_id is empty afterward, proving nothing was
written. All 5 Berlin rows correctly return `UNRESOLVED`/`NO_MASTER_CANDIDATE_RESOLVED` against the
fixture's unrelated product names — this is the honest, expected result (the fixture was never meant
to contain real Berlin drug names) and is not evidence of a matching defect; it demonstrates the
plumbing works, not that real matches would be found without real master data. Also exercised
manually via a one-off, explicitly gitignored probe script
(`ocr_runs_staging/slice4_matcher_probe.py`, confirmed via `git check-ignore -v`) that prints
per-row tier/candidates for visibility; not imported by any production or test code. Suite after this
addition: **180/180 OK** (163 baseline + 17 Slice 4 tests, up from 16). `safety_scan.py` still passes
(`secret_scan: pass`, `ada_query_catalog: pass`, `live_flags_default_off: true`), `py_compile` and
`git diff --check` clean, HEAD unchanged at `9a4fc81`, nothing staged.

Still not started: the versioned JSON artifact writer, supplier-adapter decision, Phase D UI, Phase E
full report, and the Candidate Report itself.

## 35. Codex continuation — Slice 4 candidate completed after Sonnet connection loss (2026-08-21)

Sonnet's preceding process ended with `ECONNRESET` after its 183-test verification; Codex inspected the
shared worktree and resumed without restarting or discarding its work. Codex added the deterministic
`page-extraction-bundle.v1` builder and atomic writer, a ten-page read-only build script, and the
authoritative staging Page Review UI. The UI accepts the page artifact plus local page images and
renders full-page evidence, real Paddle bounding-box overlays, every extracted row, matcher result,
and quarantine reasons with bidirectional hover/click highlighting.

Fresh evidence bundle result: 10 pages processed, 4 pages with extracted rows, 14 rows total, 9 rows
requiring review. Page 005 yields five Berlin rows; page 006 yields two Unison blocks (both quarantined
as duplicates); page 048 yields five Medline blocks with quantity/unit/price explicitly unavailable;
page 058 yields two Community Pharmacy blocks with no description and therefore `NOT_EVALUATED` by
the matcher. Pages 013/014/015/019/030/040 remain honest `NONE` results. This is meaningful partial
coverage, not a claim of production-complete extraction.

Verification: focused 22/22; full 185/185; safety scan pass; Python compile, JS syntax, and diff check
clean. Playwright opened the real staging server, uploaded the generated bundle and ten page images,
verified five Berlin overlays/rows, hover-linked MONOLIN row 3, navigated to Unison page 006, and
observed quarantine plus `NOT_EVALUATED` for the empty description. Screenshot:
`output/playwright/slice4-page5.png`. The only console error was an unrelated missing favicon 404.

Full report: `CANDIDATE_REPORT_SLICE4_PAGE_EXTRACTION.md`. No stage/commit/push/deploy, production or
shared DB access, OCR rerun, matcher change, migration, or Slice 5 work occurred.

## 36. Senior Developer (Sonnet) — Community Pharmacy supplier adapter candidate (2026-08-21)

**Status: CANDIDATE, not sealed.** Base/HEAD unchanged at `9a4fc81`. Continues directly from §35
(Codex's completed Slice 4 candidate) per explicit instruction: add a THIRD, deterministic,
supplier-identity-gated layout adapter for real page-058 (บริษัท ชุมชนเภสัชกรรม จำกัด (มหาชน) /
Community Pharmacy) evidence. This is a layout adapter, not ML training — no model, no learned
weights, tests-first against real evidence per the standing "no hand-copied fixture called automatic
extraction" rule.

**Root cause of §35's honest-but-empty page-058 result (proven before fixing):** the generic
multi-line-block adapter's 6-digit-then-10-digit internal-code heuristic never found a real product
code row on page-058 because there isn't one to find with that heuristic -- page-058 is a genuinely
different, THIRD real layout with its own single-language 5-column table header
(`รหัสสินค้า`/`รายละเอิยด`/`จำนวน`/`ราคารวมภาษี`/`จำนวนเงิน`) that the multi-line-block adapter was
never designed to read. Confirmed by re-reading the real token dump (not by guessing): supplier's own
5-digit code `32132`, description `CODIPHEN TABLET(XIOS)` printed twice, quantity+unit fused per row
(`240.00 box`, `96.00 box`), and Lot/Mfg/Exp fused onto one line per block, immediately following its
own data row with no intervening generic-name row (unlike Unison/Medline's shape).

**New adapter (`_community_pharmacy_code_table_rows`, `src/ocr_inbound/page_extraction.py`):**
selected only when BOTH a real supplier-identity marker (`ชุมชนเภสัชกรรม`, found anywhere in the
page's own text) AND this table's own column header (>=3 distinct concepts from a dedicated keyword
map, reusing the same longest-keyword-wins/Y-band-clustering primitives the generic tabular strategy
already uses via a newly generalized `_find_header_band` helper) are both found -- never selected by
filename or page number, and Berlin page-005 was checked to confirm it does NOT trigger this adapter.
Pairs each data row with the row immediately below it when that row is a fused Lot/Mfg/Exp marker
(reusing `_LOT_MARKER_RE`/`_DATE_FINDALL_RE`); assigns fields by real column X-band overlap, not
heuristic "longest token" guessing; splits fused quantity+unit text via a generic number-then-word
pattern; adds a new `supplier_sku` field (present on all three strategies now, for schema
consistency) that is NEVER folded into `description`/`raw_ocr_text` -- it is routed only into the
matcher's existing `line["supplier_sku"]` contract (matching.py, unmodified), which the matcher
already treats as exact-alias-lookup-only evidence, never internal-code text-scan evidence. Real
evidence explicitly shows the SAME Lot/Mfg/Exp on two rows with DIFFERENT quantities (240.00 vs
96.00) and distinct geometry, so this adapter deliberately does NOT run the generic adapter's
same-Lot duplicate-quarantine rule -- both rows stand on their own.

Also fixed, as a direct consequence of exercising `_find_totals_boundary` against this new real page:
the totals-boundary search bounded the product-row region by the matching TOTALS-keyword token's own
y0 only, but page-058's real totals line has its label token sitting a few px BELOW its own numeric
value in the same row (OCR baseline noise) -- letting that numeric value leak in as a spurious third
row. Fixed to bound by the whole row-cluster's minimum y0; re-verified this only tightens the cut and
does not affect Berlin/Unison/Medline (their totals lines are >>25px from the nearest real product
row in every case examined).

**Tests (all against real page-058 evidence, `CommunityPharmacyAdapterRealPageTests` +
`CommunityPharmacyMatcherIntegrationTests`):** exactly 2 rows in document order; both read CODIPHEN;
supplier SKU `32132` never becomes an internal code (asserted against the real `INTERNAL_CODE` regex
shape and confirmed absent from the description field); Lot/Mfg/Exp identical and correct on both rows
without shifting; quantities `240.0` then `96.0` in order, same Lot NOT flagged duplicate; every field
bbox within the real page's dimensions; deterministic rerun; a gate-negative check that Berlin page-005
never triggers this adapter; and a real, non-persisting `matcher._predict()` integration test (same
`AppTestCase` ephemeral-SQLite pattern as the existing `MatcherIntegrationReadOnlyTests`) proving
`tier` is never `EXACT_CODE`/`ACTIVE_ALIAS` (no approved alias exists yet) and nothing is written to
the repository. Focused suite: **31/31** (was 22, net +9 after replacing 1 now-obsolete
page-058-under-the-wrong-adapter test). Full suite:
`tests.test_automation tests.test_core tests.test_matching tests.test_matching_behavioral_revert_check
tests.test_matching_integration tests.test_page_extraction tests.test_product_review tests.test_system`
→ **194/194 OK** (was 185, zero regressions in Berlin/Unison/Medline or any other suite).

**Revert-check (non-vacuous, real AssertionError/TypeError, not ImportError):** temporarily forced
`_community_pharmacy_code_table_rows` to return `([], [])` unconditionally (backed up the real file
first, restored byte-for-byte after) and reran the new test class: `extraction_strategy` came back
`'MULTILINE_BLOCK'` instead of `'COMMUNITY_PHARMACY_CODE_TABLE'`, `description`/`supplier_sku`/
`quantity` came back `None` causing real `TypeError: 'NoneType' object is not subscriptable` on 5 of
the 10 tests and two direct `AssertionError`s on the rest -- 7 failures/errors total, confirming these
tests exercise the real fix. Restored the file, reran the full new test class: 31/31 again.

**Artifact regenerated (gitignored, `ocr_runs_staging/realinv_20260820T040631Z/page-extraction-bundle.v1.json`):**
`{"page_count": 10, "table_found_pages": 4, "row_count": 14, "review_required_rows": 8}` (was 9 before
this change -- page-058's own review-required count dropped from 2 to 1, since row 2 now has zero
quarantine reasons; row count per page is unchanged at 14 total, only page-058's content quality
changed from 2 empty rows to 2 real CODIPHEN rows). Rebuilt via the existing, unmodified
`scripts/build_slice4_page_artifact.py` (read-only OCR run, ephemeral local SQLite, pure
`matcher._predict()` only, asserts zero persisted documents before writing the artifact) --
`page_number 58` in the fresh artifact: row 1 `CODIPHEN TABLET(XIOS)` / sku `32132` / matcher
`UNRESOLVED`; row 2 `CODIPHENTABLET(XIOS)` / sku `None` (genuinely absent from this row's own real
evidence, not guessed) / matcher `UNRESOLVED`.

**Browser verification (Chrome DevTools MCP against a fresh local staging server,
`ocr_runs_staging/slice4_cp_adapter_visual/serve.py`, gitignored):** uploaded the regenerated
artifact and `page-058.png` through the existing file-picker UI (had to stage both files inside this
session's permitted MCP filesystem roots first -- the OCR-inbound worktree itself is outside the
chrome-devtools tool's own allowed upload roots in this environment; files were copied, uploaded, then
the temporary copies' role ended, no repo files were affected). Confirmed on page 5: five Berlin
overlays/rows render correctly (regression check). Jumped to page 58: title reads
`หน้า 58 · COMMUNITY_PHARMACY_CODE_TABLE`; both CODIPHEN rows render with correct Lot/Mfg/Exp/qty/unit
and `Matcher: UNRESOLVED`; the real page image shows the actual printed table matching every extracted
value including the visible `32132` code cell. Hovering overlay 2 set both overlay 2 and row-card 2
`.active` (bidirectional); clicking row-card 1 set both row-card 1 and overlay 1 `.active` (reverse
direction confirmed). Zero browser console errors this run. Confirmed via `grep` across
`web_static/*.{html,js,css}` that no product name (CODIPHEN or any name from any other adapter) is
hardcoded anywhere in the UI source -- every value rendered is read from the uploaded artifact JSON at
runtime. Screenshot: `output/playwright/slice4-cp-adapter-page58.png`.

Safety scan pass (`secret_scan: pass`, `ada_query_catalog: pass`, `live_flags_default_off: true`),
`py_compile` and `git diff --check` clean, HEAD unchanged at `9a4fc81`, nothing staged. No
production/shared/ADA DB access, no matcher-source modification, no OCR rerun, no migration, no
commit/push/deploy, no Slice-5 or next-supplier-adapter work. Full report:
`CANDIDATE_REPORT_COMMUNITY_PHARMACY_ADAPTER.md`. Stopping here for Codex's independent adjudication.

## 37. Senior Developer (Sonnet) — remediation of Codex's 2 BLOCKED findings on §36 (2026-08-21)

**Status: FINAL REMEDIATED CANDIDATE, not sealed.** Base/HEAD unchanged at `9a4fc81`. Both BLOCKED
findings from Codex's review of §36 fixed, reproduced first, non-vacuously revert-checked, and
adversarially self-reviewed (plus a genuine, independently-landed GLM 5.2 contribution -- see the
review-independence note below) before this packet.

**Review chain actually used, stated plainly:** the workflow asked for GLM 5.2 to do bounded
implementation/probe work first, with Sonnet reviewing. Sonnet did not invoke GLM through any tool
call available in this session (no matching agent type, no reachable peer session) and initially
disclosed GLM as unreachable. While Sonnet was mid-remediation, `tests/test_page_extraction.py`
changed on disk under a shared worktree with a new `CommunityPharmacyGateAdversarialTests` class (4
tests: a positive control, both gate-negative false-positive probes, and a Lot-row-pairing
no-theft probe) that Sonnet did not write. This is consistent with GLM 5.2 operating outside Sonnet's
own tool surface in this environment (a separate process/session Sonnet cannot see via `ListAgents`).
Sonnet verified these 4 tests by hand (manual row-clustering trace confirmed the no-theft test's
result is correct, not tautological) before trusting them, confirmed `page_extraction.py`'s own line
count/function list was untouched by anything else, and is folding this real contribution into the
final count below. Net effect: the review chain was NOT thinned to Sonnet-only, but Sonnet cannot
provide GLM's own reasoning/verdict text (only its committed artifact) -- this is disclosed rather
than assumed away, per the standing instruction to report review independence honestly either way.

**Finding 1 (artifact-builder matcher plumbing) — reproduced, then fixed:** confirmed
`scripts/build_slice4_page_artifact.py` hardcoded `supplier_code=None`/`supplier_sku=None` for every
row regardless of what the Community Pharmacy adapter actually extracted. Fixed:
- `extract_page()` now returns a `canonical_supplier_code` field on every strategy's result --
  `"SUPPLIER-COMMUNITY-PHARMACY"` (a fixed constant) ONLY on the branch where
  `_detect_community_pharmacy_table` already confirmed both the real identity marker AND this
  table's own header; `"UNKNOWN"` on every other branch (Berlin/Unison/Medline/no-table), never
  derived from `page_number` or the source filename.
- The builder script reads this field, passes the real code to the matcher only when it is not
  `"UNKNOWN"` (else `None`, matching the matcher's own documented "no supplier context" behavior),
  and stamps a new `alias_path_tested` boolean on every row's matcher_result so nothing downstream can
  claim the exact-supplier-alias path was exercised for an UNKNOWN-supplier page.
- Per-row `supplier_sku` and `unit_final` are now read from the extraction's own `fields.supplier_sku`
  / `fields.unit` (never fabricated, never inherited from a sibling row) and passed through to
  `matcher._predict()` verbatim -- `unit_final`'s canonical uppercase shape is produced by the
  matcher's own existing `.strip().upper()` (matching.py, unmodified), not re-implemented here.

**Finding 2 (global totals-boundary invariant) — reproduced, then fixed:** Codex's exact probe
(`below_y=100`, an ordinary token at y=90, a TOTAL token at y=110 chained into the same row cluster)
reproduced the violation directly: `_find_totals_boundary` returned `90`, i.e. `<= below_y`. Root
cause: the function clustered the FULL, unfiltered token list (including ineligible tokens with
`y0 <= below_y`) before taking a matching row's own minimum y0. Fixed by restricting clustering to
tokens that are already eligible (`y0 > below_y`) before the row-grouping step, so no ineligible token
can ever pull the boundary back to or below the header. Re-ran the exact probe: now returns `110`.
Regenerated the real 10-page artifact: identical summary before/after
(`table_found_pages: 4, row_count: 14`), confirming zero effect on real Berlin/Unison/Medline/
Community-Pharmacy pages -- this was purely a synthetic-edge-case fix.

**New tests (Sonnet, 9; GLM, 5 -- 14 total, all genuine, none tautological):**
- `TotalsBoundaryInvariantTests` (1): Codex's exact probe geometry, asserts the return is never
  `<= below_y`.
- `ArtifactBuilderBoundaryTests` (6, including 1 added after adversarial review below): imports and
  calls the REAL `scripts/build_slice4_page_artifact.py`'s `build()` function end to end (not a
  hand-built matcher line) -- confirms page-58 row 1's `supplier_sku` reaches the written artifact
  with `alias_path_tested: true`; row 2 (no printed SKU) stays `None`, never inherited from row 1;
  Berlin page-5 reports `canonical_supplier_code: "UNKNOWN"` and `alias_path_tested: false` on every
  row; `unit_final` passes through as-extracted (`"box"`, not pre-uppercased); and -- the adversarial
  addition -- a real approved `(SUPPLIER-COMMUNITY-PHARMACY, "32132")` alias, seeded through the
  repository's own `record_alias_observation`/`approve_alias` workflow (3 distinct-document
  observations to reach ELIGIBLE, then approve), is GENUINELY reachable end to end: `tier` resolves to
  `ACTIVE_ALIAS`, `proposed_product_code` to the real fixture product, `proposed_unit_code` to `BOX`.
  This proves the plumbing is not merely correctly silent when no alias exists -- it actually resolves
  one when it does.
- `CommunityPharmacyAdapterGateFalsePositiveTests` (2, Sonnet): supplier name present with no real
  column header nearby does not trigger; column header present with no supplier name nearby does not
  trigger.
- `CommunityPharmacyGateAdversarialTests` (4, landed via the shared worktree, attributed to GLM 5.2
  per the disclosure above, verified by hand): a positive control (both conditions present, gate
  fires) that the two gate-negative tests below depend on to rule out vacuous passes; identity present
  but header below the distinct-column threshold does not activate; full header present but identity
  absent does not activate; and a genuine edge case Sonnet had flagged as an open residual risk in the
  §36 report -- a data row with NO Lot row of its own, immediately followed by a DIFFERENT product's
  data row (which itself has its own Lot row one row further down) -- correctly leaves the first row's
  `lot` field `None`/quarantined and does NOT let it steal the second product's Lot. Manually
  re-traced the row-clustering/pairing logic against this exact synthetic geometry before trusting the
  test; the result matches the code's actual behavior.

Focused suite: **45/45**. Full suite (`test_automation`, `test_core`, `test_matching`,
`test_matching_behavioral_revert_check`, `test_matching_integration`, `test_page_extraction`,
`test_product_review`, `test_system`): **208/208 OK**, zero regressions.

**Important self-correction, found by the same shared-worktree contributor (attributed to GLM per the
disclosure above) reviewing Sonnet's OWN test coverage, not just the source fix:** a 5th test appeared,
`BuilderMatcherInputBoundaryTests.test_real_builder_feeds_sku_unit_and_supplier_code_into_predict`,
which spies on the real `ProductMatcher._predict` call (via `unittest.mock.patch.object`) DURING a
real `build()` run and asserts the actual arguments `_predict` received, rather than reading the
written artifact's already-independently-correct extraction fields. Its docstring claimed Sonnet's
own `ArtifactBuilderBoundaryTests` (6/6) would keep passing even if the builder's `supplier_sku`
plumbing were reverted to always-`None`, because those tests only ever inspected
`row["fields"]["supplier_sku"]` (populated by the EXTRACTOR, correct independently of the builder bug)
and `matcher_result["alias_path_tested"]` (a separate flag), never the actual `line["supplier_sku"]`
value the builder passed into `_predict()`. Sonnet independently verified this claim: reverted only
the builder's `supplier_sku` assignment line (leaving `canonical_supplier_code`/`alias_path_tested`
fixed), reran `ArtifactBuilderBoundaryTests` -- **6/6 still passed**, a real, confirmed gap in Sonnet's
own coverage. The new spy-based test correctly fails in that state (`AssertionError: None != '32132'`)
and passes against the real fix. This is disclosed here as a genuine finding against Sonnet's own
verification, not only against the original source bug -- the review loop caught a reviewer's own
blind spot, which is exactly what the two-party structure is for.

**Revert-checks (both non-vacuous, real assertion failures, not `ImportError`):**
- Finding 2: reran the exact probe against the pre-fix logic path -- returned `90` (a real,
  demonstrable contract violation), confirmed fixed returns `110`.
- Finding 1: backed up both changed files, reverted the builder script's plumbing to the old
  hardcoded-`None`/no-`alias_path_tested` shape, reran `ArtifactBuilderBoundaryTests` -- 2 of 5 tests
  failed with real `AssertionError: False is not true` (`alias_path_tested` false when it should be
  true), restored the real files byte-for-byte, reran: 6/6 (after the alias-reachability test was
  added).
- Finding 1, narrower revert (the self-correction above): reverted ONLY the builder's `supplier_sku`
  assignment line (kept `canonical_supplier_code`/`alias_path_tested` fixed) -- `ArtifactBuilderBoundaryTests`
  stayed 6/6 (confirming the gap), `BuilderMatcherInputBoundaryTests` failed with
  `AssertionError: None != '32132'` (confirming the spy-based test closes it). Restored, reran: 45/45.

**Artifact regenerated (gitignored):** `{"page_count": 10, "table_found_pages": 4, "row_count": 14,
"review_required_rows": 8}` -- identical to §36's post-fix summary, confirming this round's fixes
changed matcher-plumbing correctness and a synthetic-edge-case invariant, not real-page row counts.
Page 58 in the fresh artifact: row 1 `supplier_sku: "32132"`, `alias_path_tested: true`,
`tier: UNRESOLVED` (no approved alias exists in the packaged local fixture); row 2 `supplier_sku: None`
(genuinely absent), `alias_path_tested: true`, `tier: UNRESOLVED`.

**Browser verification (Chrome DevTools MCP, fresh server,
`ocr_runs_staging/slice4_final_review_visual/serve.py`, gitignored):** page 5 (Berlin) re-verified,
unaffected -- 5 rows, 5 overlays. Page 58 re-verified with the fixed artifact -- identical correct
rendering to §36's pass, `Matcher: UNRESOLVED` on both rows, hover/click bidirectional highlighting
reconfirmed in both directions. Zero console errors beyond the known unrelated favicon 404. `grep` for
every adapter's product names AND `32132`/`SUPPLIER-COMMUNITY-PHARMACY` across
`web_static/*.{html,js,css}` → no match; nothing hardcoded. Pages 6 and 48 verified via the
regenerated artifact JSON directly (both `MULTILINE_BLOCK`, `canonical_supplier_code: "UNKNOWN"`,
`alias_path_tested: false` on every row, unchanged from §36) -- not re-opened in the browser this
round because this session's Chrome DevTools MCP `upload_file` tool accepts one file path per call
(each call replaces an input's file list), making a true multi-image batch upload impractical; this
limitation is disclosed rather than glossed over. Screenshot:
`output/playwright/slice4-final-candidate-page58.png`.

Safety scan pass, `py_compile`/`node --check`/`git diff --check` clean, HEAD unchanged at `9a4fc81`,
nothing staged. No production/shared/ADA DB access, no matcher-source modification, no OCR rerun, no
migration, no commit/push/deploy, no Woothi/DKSH/Charoon adapter work. Full packet: this section plus
`CANDIDATE_REPORT_COMMUNITY_PHARMACY_ADAPTER.md` (OLD/NEW matrix and manifest carried forward from
§36, both findings now closed). Stopping here -- FINAL REMEDIATED CANDIDATE, awaiting Codex's
independent re-adjudication.
## 38. Senior Developer / acting Tech Lead (Sonnet) — Slice 5 master cache, Track B matcher remediation, Thai regression, and first CI (2026-08-21)

**Status: SEALED on the Draft PR branch, NOT independently reviewed.** Branch
`slice5/master-cache-matcher-safety-2026-08-21`, PR #3 left Draft on purpose. Base `f28bb7e`.
Commits added this session: `4b5e185` (Codex-authored/pushed), `92ba315`, `d7a5ded`, `49d7422`
(Sonnet), plus `b7fbd72` (Codex, CI hardening). No commit was ever amended, reverted, rebased, or
force-pushed; `main` never moved.

**Authority chain, stated plainly.** This session began with no seal/push rights and produced a
candidate report only. The owner then appointed it **Active/acting Tech Lead** (Codex unavailable)
and later granted standing authority to remediate, test, seal as a *follow-up* commit, and push to
the feature branch / Draft PR after self-adversarial review — explicitly withholding merge, deploy,
production write, destructive migration, and any new matcher auto-confirm behaviour, and explicitly
forbidding amend/force-push. Everything below is **self-review. It is not independent review and must
not be recorded as one.** Codex's adjudication belongs in §39.

**Provenance of the two Slice-5 files.** `src/ocr_inbound/master_cache.py` and
`tests/test_master_cache.py` arrived as untracked files with **no git history of any kind** — absent
from all 9 reachable commits, no stash, single worktree. They are attributed to no one (not Codex,
not GLM, not Sonnet), and every claim about them was re-derived from the files themselves rather than
from any prior report.

**Slice 5 — six defects reproduced before editing, then remediated.** A1: the internally-created
pg8000 connection was never closed on any path (the only `close` calls were `os.close`/sqlite), while
`_build_candidate`'s docstring falsely asserted "the production connection is already closed by the
time this runs". Ownership is now explicit — an injected session stays caller-owned and is never
closed; a session opened by `default_connect()` is closed on success and on every failure including
guard failures, and close failures are swallowed *without their message* because driver teardown text
routinely echoes the DSN. A2: `_build_candidate()` created the `.next` file via `mkstemp` but the
caller bound `candidate` from the **return value**, so a mid-build failure could never reach caller
cleanup; a forced failure left `ada_cache.slice5.pz3rwu8w.next` behind. The function now owns and
unlinks its own candidate on `BaseException` (KeyboardInterrupt included). A3: `pg8000` existed only
in `.venv` and was declared nowhere — added as `pg8000>=1.31,<2.0` to `requirements.txt` and as a
`master-refresh` extra in `pyproject.toml`, and `requirements-staging.lock.txt` was corrected because
it *asserted* the companion was standard-library-only, which pg8000 falsifies (the task spec's file
list named only `requirements.txt`; declaring it there alone would have left two other files lying).
A4: `urlparse` leaves userinfo **percent-encoded**, so a password containing `@ / # ? :` — all of
which must be escaped to keep the URL parseable — authenticated with the wrong string and no
diagnosable error; `parse_database_url()` now unquotes every userinfo field and the database path.
A5: the cache wrote `active=1` under the comment "active is not a claim, it is absence of retirement",
which **invents a retirement state the source has no concept of** — verified against the live schema
that `ada.branch_stock_snapshots` has **no `is_active` column** (37 columns, none named that).
`CACHE_ACTIVE_MEANING` now defines it once as "present in the current branch-stock snapshot and
eligible for staging review matching" and that exact string appears in the code, the cache manifest,
the status output and the runbook. A6: the runbook had nothing about the refresh; it now documents
operator setup without literal secrets, both commands, the count band, dependency install,
no-fallback failure behaviour, a startup-never-refreshes proof, and stale-lock recovery. **Plus one
found while writing A6:** the refresh lock was an *empty file*, making the stale-lock diagnosis A6
was supposed to document impossible. It now records `pid=` + UTC start, the error quotes the holder,
and nothing auto-deletes a lock (PID reuse makes liveness undecidable from the file alone).

**Production access used, and its negative proof.** Read-only against `sc_drug_db` with every
statement recorded: `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`, `ROLLBACK`,
`BEGIN READ ONLY`, `SHOW transaction_read_only` (verified `on`), `SELECT current_database()`, one
`SELECT` from `ada.branch_stock_snapshots`, `ROLLBACK`. All in the declared allowlist, zero mutating
statements, owned connection closed. Verified **6,671 rows / 6,671 distinct `product_code`**, and
CODIPHEN `IC-001962` and `IC-002993 "BEDSIDE TABLE ABS 1 S"` exactly as specified. The credential
used was the admin-api `DATABASE_URL`, which is almost certainly read-write — read-only-ness was
enforced by the transaction guards, not by the role; a dedicated SELECT-only role is what the runbook
tells operators to use and remains the right production practice. Note also that
`GATE6_READONLY_DATABASE_URL` in this environment is **stale** (fails SCRAM channel binding on every
SSL mode and on plaintext); an initial hypothesis that this indicated an `ssl_context=True` driver
defect was **wrong** and is retracted here — the working credential connects fine with
`ssl_context=True`, and no SSL change was made.

**Track B — the matcher false positive, reproduced exactly.** Against the real 6,671-row cache via
pure `_predict()`: `supplier_sku=None`, `CODIPHENTABLET(XIOS)` → **IC-002993 "BEDSIDE TABLE ABS 1 S"
/ FUZZY_SUGGESTION / 0.5000**, with the full wrong candidate set `IC-002993 0.5000, 630020259 0.4865,
IC-003530 0.4681, IC-003524 0.4571, IC-002022 0.4528`. Mechanism: the lost space produced the single
junk token `CODIPHENTABLET`; trade-name and spelling tiers returned nothing; control fell through to
the whole-catalog character-level `SequenceMatcher` sweep where **any** product scoring ≥ 0.45 was
promoted straight to `FUZZY_SUGGESTION` with no requirement that a real product token be shared. Two
separately testable changes followed — B1 `meaningful_shared_tokens()` (a fuzzy candidate needs
meaningful shared trade-name evidence; generic dosage-form/packaging/furniture overlap such as
TABLE/TABLET can never qualify alone) and B2 `recover_fused_dosage_form()` (a closed allowlist of
TABLET/CAPSULE/SYRUP/CREAM/OINTMENT split at most once per token, never dictionary segmentation,
never touching words ending in `TABLE`). Staged proof on the real cache: pre-fix wrong IC-002993 →
guard-only **UNRESOLVED, never another product** → guard+recovery **IC-001962 / TRADE_NAME_MATCH /
0.6500 with human confirmation required**; Row 1 (0.7000) and the clean control (0.8500) unchanged;
`UNKNOWN TABLET` UNRESOLVED throughout (it was *already* UNRESOLVED pre-fix, so it is a
regression guard, not a defect reproduction — stated rather than claimed as a fix). Row 2 keeps
`supplier_sku=None` and `"32132"` never appears in its `source_text`. Thresholds were **not** lowered;
B1 adds evidence rather than relaxing the bar.

**B1 scope correction worth recording.** The first B1 implementation applied the evidence guard to
*every* fuzzy-sweep candidate, including runs where a stronger tier had already selected and the sweep
was merely decorating the reviewer's alternatives list. That broke
`test_product_review.py::test_reused_request_id_...` (its row dropped from 2 candidates to 1). Rather
than weaken an existing test, the guard was narrowed to `selected is None` — the case it is actually
about. Reviewers keep their full correction list on stronger tiers. **No existing test was modified,
skipped, or deleted anywhere in this session.**

**The Thai regression — shipped in `4b5e185`, caught by this session's own later self-review.** The
B1 guard as committed required **exact token equality**. Thai is written without word spaces, so
`normalize_product_text` returns a whole phrase as ONE agglutinated token: the invoice's
`พาราเซตามอล` and the master's `ยาพาราเซตามอล` (ya- = "medicine") are the same drug and share no
exact token. Reproduced on `4b5e185` itself (extracted with `git archive`, working tree untouched):
a correct match scoring **0.9474 became UNRESOLVED**, rejected with the guard's own reason code
`FUZZY_INSUFFICIENT_TOKEN_EVIDENCE:1` having refused exactly one candidate — the right one. A false
negative that pushes work back onto reviewers, i.e. the opposite of Bible §2. `92ba315` fixes it:
Thai additionally accepts **containment** of one agglutinated run inside another when the contained
run is ≥ `_MIN_THAI_CONTAINMENT_LEN` (4) and is not a stopword; **Latin deliberately stays on exact
equality**, because `CODIPHENTABLET` *contains* `CODIPHEN` and containment there would break the
mandated staged proof (guard-only ⇒ UNRESOLVED). The full OLD/guard-only/FINAL matrix re-runs
**bit-identical** after the fix. The same commit also fixes a second, smaller defect: SARA AM
(`ำ` U+0E33) is rewritten by the normalizer into its decomposed form, so three of the 22 composed
Thai stopword literals (`ยาน้ำ`, `น้ำเชื่อม`, `สำหรับ`) could never equal a normalized token and the
Thai half of the guard's generic-word filter was silently inert;
`_THAI_TRADE_NAME_STOPWORDS_NORMALIZED` closes that inside this guard only. **Process failure worth
recording:** the first candidate report listed Thai as a residual risk and then never tested it. The
risk was written down and left unexercised, which is how it shipped.

**The generic-token approach: BUILT, MEASURED, REJECTED — do not re-derive it.** The evidence gate is
still defeated by generic Thai tokens: on the live master `สามัญ` (house-brand prefix) occurs in
**2,804 of 6,671 products**, `เภสัช` 1,615, `กรัม` — *a unit* — 1,163, `ปกติ` 1,009; 719 of 6,462 Thai
evidence tokens reach more than five products, and 7,306 containment pairs exist. A line naming a
product that does not exist is suggested `COKE NO SUGAR 450 ML`. The codebase already had the doctrine
for exactly this (`_GENERIC_TOKEN_MAX_PRODUCTS = 5`, "too generic to serve as sole retrieval
evidence") and the gate simply did not apply it, so it was implemented as a sole-evidence rule
(generic tokens still count *alongside* a specific one, matching how `_trade_name_candidates` uses
it), went 31/31 green, and closed all three adversarial cases. It was then **removed**, because
measured on the real master it inverts: on 70 prefix-stripped Thai names, correct recoveries fell
49 → 47, one correct result became a **wrong product**, and one became UNRESOLVED. Root cause,
diagnosed on `ถุงมือยางลองเมด สีดำ ไซส์ M 10`: the *correct* product's shared tokens were **all three**
classified generic — because the Longmed glove family has more than five SKUs — while the *wrong*
product's vaguer `ถุงมือยาง` stayed "specific" because it is rarer. **Catalog frequency is not
specificity**; it penalises exactly the multi-SKU families where a token is most diagnostic.
`_GENERIC_TOKEN_MAX_PRODUCTS` remains sound where it is used today but is the **wrong instrument** as
a hard sole-evidence filter in this gate. A different mechanism is needed — a curated house-brand/unit
stopword list, or evidence weighting rather than a binary gate. Full evidence in
`REMEDIATION_PACKET_THAI_EVIDENCE_FOR_CODEX.md` §12.

**A near-miss vacuous test, disclosed.** While building the rejected approach, an end-to-end test was
written that returned UNRESOLVED **whether or not the fix was present** — nothing cleared the 0.45
floor in a 6-row fixture. It was caught, the fixture rebuilt so the reverted code genuinely proposes a
wrong product at 0.8750, and a companion test added that pins the revert-check inside the suite so it
cannot silently go vacuous again. Both were removed along with the rejected approach, but the failure
mode is recorded because it was nearly shipped.

**Corpus probes, including one that measured nothing.** Reachability: products with no usable evidence
token at all are **6 / 6,671 = 0.09%**, and all six are unspaced Thai runs with digits fused in that
`extract_trade_name_tokens` already skipped before this change. Targeted fuzzy-path probe (70 real
Thai names with the leading generic prefix stripped so exact retrieval fails, seed 20260821):
containment changed **2** outcomes, both `None →` the correct product (0.8889 and 0.9333), with
**zero** wrong-product transitions; the single row flagged "different product" has `old == new ==
IC-002485` at TRADE_NAME_MATCH and is therefore a pre-existing trade-name mismatch not attributable to
the change. **A first attempt sampled 150 *whole* product names and reported "0 changed" — that
measured nothing**, because whole names resolve via EXACT_NAME/TRADE_NAME before the fuzzy tier ever
runs; it is superseded and must not be cited as evidence. Sample power is low either way: 70 samples
produced only 2 transitions, so "zero wrong transitions" should not be trusted as strongly as the
number suggests.

**Base drift, escalated and resolved.** Mid-session `HEAD` moved from `f28bb7e` to `4b5e185` and a
branch appeared on origin. This session stopped and escalated rather than proceeding; the owner
confirmed it was Codex committing under their authorization. Recorded because the report at the time
flagged it as an anomaly.

**First CI, and what its first run proved.** The repo had **no `.github/` at all**. GLM 5.2 was given
a bounded task (workflow file only, no commit/push rights, explicitly barred from `matching.py`); its
report was verified against the real tree rather than accepted, and it had omitted
`permissions: contents: read` and a `concurrency` group, which were added. Five gates: compileall,
full unittest with `-W error::ResourceWarning`, safety_scan, zipapp build, package smoke, with
**no pip install step at all** — the suite is standard-library-only, verified by running it green on
a clean 3.11.9 interpreter with nothing installed; `requirements.txt` is the heavy Layers A–E
toolchain nothing in these gates imports, and pg8000 is the lazily-imported operator-only dependency
CI must never exercise. The zipapp is **not byte-reproducible** (two builds of identical source give
different SHA-256), so no build hash is asserted. The first run was red on both legs and both
failures were real information. **ubuntu-latest was a specification error by this session, not an
implementation error by GLM:** 21 errors, every one `MUTEX_PLATFORM_UNSUPPORTED — Windows named mutex
is required` (`ada_automation.py:272`), nothing else broken, matching Bible §9.1 "one Windows
workstation per ADA instance"; a Linux leg was requested for a product that cannot run on Linux, and
it was removed with the reason recorded in the file. **windows-latest gate 5** died with
`UnicodeEncodeError: 'charmap' codec` because the runner's stdout is cp1252 while `package_smoke`
prints UTF-8 captured from a subprocess; fixed with `PYTHONUTF8=1` at CI level, no product code
touched. **A test-count discrepancy was nearly waved through:** CI reported 241 run / 13 skipped
against 266 locally. A CI silently collecting fewer tests is a dangerous signal, so it was chased —
the ten test modules sum to exactly 266, all are tracked, none are gitignored, and the 25-test gap is
entirely Slice-4 tests reading the gitignored `ocr_runs_staging/` evidence. Expected, not lost
coverage; the expected numbers are documented in the workflow so a drop for any *other* reason reads
as a regression.

**CI gaps found after declaring it done — the owner pushed back correctly.** Two were introduced or
missed by this session and are recorded because `b7fbd72` (Codex) has since hardened both: (1) fixing
duplicate runs by setting `push: branches:[main]` + `pull_request:` **removed CI from every branch
with no open PR**, a coverage hole traded for tidiness without saying so; (2) gate 3's secret scan
only covered `src/`, `scripts/`, `resources/` — a planted `password = "..."` was caught in `src/` and
**passed clean in `tests/`**, leaving `tests/` (12 files), `docs/` (16) and every root file including
`fusion_review_server.py`, `ocr_feasibility.py`, `ocr_environment.py` and `run_staging.ps1`
unscanned. Still open at the time of writing: CI validates the **merge commit**, not the branch
commits (`HEAD is now at 43475ba Merge 49d7422 into f28bb7e`), equivalent only while `main` has not
moved; **no branch protection** (`/branches/main/protection` → 404), so a green tick is advisory and
nothing blocks merging red — owner action, not this session's to take; 25 Slice-4 tests never run in
CI; and no lint/type/actionlint. **The most important limitation: this CI cannot catch the class of
bug this entire session was about.** Every gate runs against fixtures; the Thai regression, the
CODIPHEN false positive and the generic-token hole all required the real 6,671-row master, which CI
has no access to and should not have. Green CI says almost nothing about matcher correctness and may
give more false confidence than no CI.

**Matcher findings left OPEN for Codex (all in `matching.py`).** (a) The generic-token hole above is
**mostly pre-existing in `4b5e185`** — `สามัญ ของที่ไม่มีอยู่จริง` → IC-003109 EAR PICKER 0.4783 and
`ผงไม่มีจริง 5 กรัม` → 630030194 MYDA B CREAM 0.5263 behave identically before and after `92ba315` —
but `92ba315` **worsens one of three** adversarial cases, `สามัญ ZZZQQ ไม่มีสินค้านี้` moving from
UNRESOLVED to IC-000027 `COKE NO SUGAR 450 ML` 0.5091. This was accepted as a documented residual
risk because real OCR text dominates adversarial text (+2 correct / 0 wrong there) and because the
obvious fix inverts — **this is the single judgement call Codex should most consider overturning.**
(b) Three Thai stopwords remain dead in `extract_trade_name_tokens` itself (same SARA AM mismatch);
measured blast radius on the real master is **0 products**, so it is a correctness tidy-up with almost
no behavioural value. (c) `matching.py:896` passes *normalized* text to `extract_attributes` while
candidate attributes come from *raw* master names, so Thai SYRUP contradictions are missed — deeper
than it looks, because `_THAI_DOSAGE_FORM_RE = [ก-๙]+` grabs maximal runs and `ยาเม็ด` /
`ยาน้ำแก้ไอ` never match the map at all; only an isolated `ยาน้ำ` does. A Thai syrup line can
therefore be matched to a tablet product without the contradiction guard blocking it. Fixing it
changes a guard that *blocks* matches, so it needs corpus measurement first. **Unifying observation:**
(a), (b) and (c) share one root cause — Thai is unspaced, so exact-token lookups against Thai word
lists barely ever fire. They are better resolved as one "Thai tokenization strategy" decision than as
three patches.

**Verification.** Full suite **266/266** locally under `-W error::ResourceWarning` (241 run / 13
skipped on a clean CI checkout, explained above), focused `test_master_cache` 34/34, focused
`test_matcher_false_positive_remediation` 24/24, **7/7 revert-checks NON-VACUOUS** with zero
ImportError/AttributeError (a revert that only produces an ImportError was never counted), safety_scan
pass, `compileall`, `git diff --check`, zipapp build and package smoke all pass, and the whole suite
also passes on a clean interpreter with no third-party package present. Dependency resolvability was
proven from a real index (`pip download "pg8000>=1.31,<2.0" --no-deps`), not from the existing venv,
and the fresh-machine path was simulated by blocking the import so the refresh fails loudly with
`MASTER_REFRESH_DRIVER_MISSING` while import/review/Ready/packaged build keep working; the zipapp
bundles no third-party package. Zero predictions, aliases or decisions were persisted by any probe
(`_predict()` only, never `predict_and_persist()`), and startup never auto-refreshes — neither
`ocr_inbound.master_cache` nor `pg8000` appears in `sys.modules` after importing the app or after
`Application.bootstrap`.

**Not done, explicitly.** No merge, no deploy, no production write, no destructive migration, no
schema/migration change, no Render or environment-variable change, no repo-settings or
branch-protection change, no alias created or approved, no auto-confirm behaviour opened, no amend,
no force-push, no history rewrite. PR #3 left Draft; `main` untouched at `f28bb7e`. Pre-existing
untracked user files (`.playwright-cli/`, `environments/`, `output/`,
`docs/HANDOFF_SLICE2_TO_NEXT_SESSION_TH.md`) preserved byte-untouched, and a pre-existing orphan
`ocr_runs_staging/realinv_20260820T040631Z/ada_cache.yux6jx3o.next` was left in place. Supporting
packets: `CANDIDATE_REPORT_SLICE5_CACHE_AND_MATCHER_REMEDIATION.md` (§15 self-review pass, §16
base-drift record), `REMEDIATION_PACKET_THAI_EVIDENCE_FOR_CODEX.md` (§12 the rejected dead end) and
`HANDOFF_TO_CODEX_TECH_LEAD_2026-08-21.md`. Stopping here — **awaiting Codex independent
adjudication in §39.**
