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
