# OCR Inbound Review App — Design Brief

สถานะ: แนวคิดเริ่มต้นสำหรับส่งต่อให้ Sol Ex High ออกแบบ UX/UI และ technical workflow

วันที่: 21 กรกฎาคม 2026

## 1. เป้าหมายของผลิตภัณฑ์

สร้าง Windows Desktop Review App สำหรับรับใบกำกับ/ใบส่งสินค้าจาก supplier แล้วทำงานตามลำดับดังนี้:

1. รับไฟล์ PDF หรือภาพเอกสาร
2. OCR และ extract ข้อมูลหัวเอกสารกับรายการสินค้า
3. จับคู่ supplier และสินค้าใน ADA POS
4. ให้พนักงานตรวจ ยืนยัน หรือแก้ไขข้อมูลอย่างรวดเร็ว
5. ส่งข้อมูลที่ยืนยันแล้วไปกรอกในหน้าจอ `ซื้อ > ใบรับของ/ใบซื้อสินค้า` ของ ADA POS Back
6. อ่านผลกลับมาตรวจสอบก่อนบันทึก และเก็บ audit trail หลังบันทึก

North Star Metric คือ **ลดเวลาที่คนใช้ต่อ invoice โดยไม่ลดความถูกต้อง** ไม่ใช่พยายามให้ระบบอัตโนมัติทุกกรณี

## 2. ขอบเขตเริ่มต้น

เริ่มจากเอกสารของ supplier ที่ OCR อ่านง่ายที่สุด 3 ราย:

1. บริษัท วุฒิ อินเตอร์ดรักส์ 2010 จำกัด
2. บริษัท เจริญเภสัช จำกัด (Charoon Bhesaj)
3. บริษัท เบอร์ลินฟาร์มาซูติคอลอินดัสตรี้ จำกัด

MVP รองรับทีละหนึ่ง invoice และให้คนยืนยันก่อนส่งเข้า ADA POS ทุกครั้ง ยังไม่มี auto-approval

## 3. ผู้ใช้งานหลัก

- พนักงานรับสินค้า/คีย์เอกสาร
- เภสัชกรหรือผู้ตรวจสอบรายการที่ไม่แน่ใจ
- ผู้ดูแลระบบที่แก้ supplier template, product mapping และ automation failure

ผู้ใช้หลักไม่ควรต้องเข้าใจ OCR confidence, database schema หรือรายละเอียดของ automation

## 4. Workflow หลัก

```text
Inbox
  -> OCR Processing
  -> Review Header
  -> Review Line Items
  -> Resolve Exceptions
  -> Ready for ADA
  -> ADA Preflight
  -> Enter into ADA POS
  -> Reconcile Totals
  -> Human Confirm Save
  -> Completed / Failed
```

สถานะเอกสารที่แนะนำ:

- `NEW`
- `PROCESSING`
- `NEEDS_REVIEW`
- `READY_FOR_ADA`
- `SENDING_TO_ADA`
- `ADA_REVIEW_REQUIRED`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

ต้องป้องกันการส่ง invoice เดิมซ้ำโดยใช้ supplier + invoice number + date + grand total และเก็บ ADA document number หลังสำเร็จ

## 5. Information Architecture

Navigation หลักควรมีเพียง:

- Inbox
- Review Queue
- Completed
- Exceptions
- Supplier Templates
- Product Mappings
- Settings / System Health

หน้าแรกควรตอบได้ทันทีว่า วันนี้มีเอกสารกี่ใบ รอตรวจอะไร ส่งเข้า ADA สำเร็จกี่ใบ และมีปัญหากี่ใบ

## 6. หน้าจอหลัก

### 6.1 Inbox

หน้าที่:

- ลากไฟล์ PDF/ภาพเข้ามา หรือเลือกไฟล์จากเครื่อง
- แสดง supplier ที่ระบบคาดว่าเป็นเจ้าของเอกสาร
- แสดงจำนวนหน้า เวลาอัปโหลด และสถานะ OCR
- ตรวจไฟล์ซ้ำก่อนเริ่มประมวลผล
- เปิดเอกสารเข้าสู่ Review Workspace

รายการควรเรียงตามสิ่งที่ต้องทำก่อน ไม่ใช่ตามเวลาที่อัปโหลดอย่างเดียว

### 6.2 Review Queue

แต่ละแถวแสดง:

- Supplier
- Invoice number
- Invoice date
- จำนวนรายการสินค้า
- Grand total
- จำนวน field/row ที่ยังมีปัญหา
- เวลาที่รอ
- สถานะ

Quick filters:

- ต้องตรวจทั้งหมด
- Header ผิดปกติ
- สินค้าจับคู่ไม่ได้
- จำนวน/ราคาไม่แน่ใจ
- พร้อมส่ง ADA
- Automation ล้มเหลว

### 6.3 Review Workspace

ใช้ layout 3 ส่วน:

```text
+----------------------+---------------------------+------------------+
| Document Viewer      | Extracted Data            | Evidence/Status  |
| PDF/Image            | Header + Product Rows     | OCR candidates   |
| zoom/highlight       | editable review table     | ADA match        |
+----------------------+---------------------------+------------------+
```

#### Document Viewer

- Zoom, rotate และเปลี่ยนหน้า
- เมื่อเลือก field หรือ row ให้ highlight ตำแหน่งต้นฉบับ
- แสดงภาพต้นฉบับ ไม่ใช้ภาพที่แก้ข้อความแล้ว
- เปิดดู OCR candidates เมื่อจำเป็น แต่ไม่รบกวนผู้ใช้ทั่วไป

#### Header Review

Fields ขั้นต่ำ:

- Supplier
- Invoice/document number
- Invoice date
- Purchase order/reference number ถ้ามี
- Payment type: เงินสด/เงินเชื่อ
- Credit days และ due date
- Currency
- Subtotal
- Discount
- VAT rate และ VAT amount
- Grand total

ใช้ visual status ต่อ field:

- เขียว: ผ่าน rule และ confidence สูง
- เหลือง: ต้องตรวจ
- แดง: ขัดแย้งหรือข้อมูลไม่ครบ
- เทา: ไม่มีในเอกสาร/ไม่เกี่ยวข้อง

สีต้องไม่เป็นสัญญาณเพียงอย่างเดียว ต้องมี icon และข้อความสถานะด้วย

#### Line Item Review Table

Columns ขั้นต่ำ:

- ลำดับ
- Supplier SKU
- ข้อความชื่อสินค้าจากเอกสาร
- ADA product code
- ADA product name
- Unit
- Quantity
- Free quantity
- Unit price
- Discount
- Line total
- Lot number (ถ้ามี)
- Expiry date (ถ้ามี)
- Match status

Interaction สำคัญ:

- Keyboard-first: Tab, Enter, ลูกศร, shortcut สำหรับ confirm row
- ยืนยันหลายแถวพร้อมกันได้เฉพาะแถวที่ผ่าน validation
- ค้นหา product master ด้วย code, barcode,ชื่อสินค้า,ingredient และ alias
- แสดง top candidates พร้อมเหตุผลที่ match
- ห้ามระบบเลือกสินค้าที่ไม่มีใน product master
- หากไม่แน่ใจต้องเลือก `ต้องตรวจ` ได้ ไม่บังคับเดา
- แก้หนึ่ง mapping แล้วเสนอใช้กับข้อความแบบเดียวกันใน invoice นี้ได้
- การสร้าง supplier alias ใหม่ต้องบันทึกเป็น candidate ก่อน ไม่เปิดใช้ถาวรทันที

### 6.4 Exception Resolver

จัดกลุ่มข้อผิดพลาดแทนการแสดง error กระจัดกระจาย:

- Supplier ไม่ชัดเจน
- Invoice ซ้ำ
- Product ไม่พบ
- Product match หลายตัว
- Unit ไม่ตรง
- Quantity/price ผิดรูปแบบ
- Line total ไม่สัมพันธ์กับ quantity x price
- ยอดรวม invoice ไม่ตรงกับผลรวมรายการ
- ADA popup หรือ validation error

ทุก correction ต้องเก็บ error category และสิ่งที่ผู้ใช้แก้ เพื่อใช้ปรับระบบในอนาคต

### 6.5 Human Correction และ Learning Dataset

พนักงานต้องสามารถแก้ข้อมูลที่ OCR หรือ product matching อ่านผิดได้ทั้งระดับ field และระดับรายการสินค้า โดยไม่ต้องกลับไปแก้ไฟล์ต้นฉบับ ตัวอย่างข้อมูลที่แก้ได้:

- Supplier
- เลขที่และวันที่ invoice
- รหัส/ชื่อสินค้า
- ADA product mapping
- หน่วย จำนวน ของแถม ราคา ส่วนลด และยอดรวม
- Lot number และ expiry date
- VAT และข้อมูลหัวเอกสารอื่น

ทุกครั้งที่พนักงานกด `ยืนยัน` หรือ `แก้ไข` ระบบต้องเก็บตัวอย่างสำหรับการเรียนรู้ โดยเก็บอย่างน้อย:

- ภาพหรือพิกัดบริเวณต้นฉบับที่ใช้ตัดสิน
- ข้อความดิบจาก OCR ของแต่ละ engine
- ค่าที่ระบบเสนอครั้งแรก
- confidence และเหตุผลที่ระบบเลือกค่านั้น
- ค่าใหม่ที่พนักงานแก้และยืนยัน
- Supplier, document type และ field/column ที่เกี่ยวข้อง
- ADA product code ที่ยืนยันแล้ว
- ประเภทข้อผิดพลาด (`error_category`)
- ผู้ตรวจ วันเวลา และเวลาที่ใช้ตัดสิน
- OCR/model/prompt/rule version ที่สร้างคำตอบเดิม

ตัวอย่างหนึ่งรายการควรมีรูปแบบแนวคิดดังนี้:

```json
{
  "supplier": "WOOTHI",
  "field": "quantity",
  "source_text": "96",
  "predicted_value": "36",
  "corrected_value": "96",
  "action": "correct",
  "error_category": "QUANTITY_EXTRACTION_ERROR",
  "ada_product_code": "630XXXX",
  "model_version": "ocr-fusion-v1",
  "review_duration_seconds": 8.4
}
```

#### Learning Loop

```text
OCR prediction
  -> พนักงานเห็นภาพและค่าที่ระบบเสนอ
  -> Confirm หรือ Correct
  -> เก็บ prediction + final value + evidence
  -> ตรวจคุณภาพและแยก train/validation/holdout
  -> สร้าง supplier alias/rule หรือฝึก model รุ่นใหม่
  -> ประเมินกับ frozen holdout
  -> คนอนุมัติ model ก่อนใช้งานจริง
  -> เก็บผลการ review รอบถัดไปต่อเนื่อง
```

ระบบสามารถเก่งขึ้นได้สองระดับ:

1. **เรียนรู้แบบไม่ต้องรอ ML:** หากชื่อสินค้าจาก supplier เดิมถูกพนักงานยืนยันว่าตรงกับ ADA product เดิมหลายครั้ง ระบบสร้าง supplier-specific alias candidate และเสนอ mapping นั้นได้แม่นขึ้นในครั้งถัดไป
2. **เรียนรู้ด้วย ML:** correction ที่ผ่านการตรวจคุณภาพจะกลายเป็น labeled dataset สำหรับฝึก OCR candidate selection, field extraction, unit normalization, supplier identification และ product matching

ข้อกำหนดสำคัญเพื่อไม่ให้ระบบเรียนผิด:

- การแก้หนึ่งครั้งยังไม่ควรกลายเป็นกฎถาวรหรือ training truth โดยอัตโนมัติ
- Alias ต้องยืนยันซ้ำตามเกณฑ์ และ alias ที่ชี้ไปหลายสินค้าต้อง quarantine
- เก็บทั้ง `confirm` และ `correct` เพื่อหลีกเลี่ยง dataset ที่มีแต่ตัวอย่างผิด
- แยก dataset ตาม supplier และ document layout
- กัน frozen holdout ไว้ตั้งแต่ต้นและห้ามนำไป train
- Version dataset, OCR engine, rules และ model ทุกครั้ง
- Model ใหม่ต้องทำงาน shadow mode และผ่าน accuracy gate ก่อนแทนรุ่นเดิม
- การ deploy model หรือเพิ่ม automation ต้องมีผู้รับผิดชอบอนุมัติ
- Human correction คือ ground truth หลังยืนยัน แต่ต้องสามารถแก้/ถอน label ได้หากพบว่าพนักงานเลือกผิด

Review App ควรมีหน้า `Learning/Data Quality` สำหรับผู้ดูแลระบบในระยะถัดไป เพื่อดูจำนวน labeled examples, conflict, class balance, supplier coverage, error categories และ dataset/model version โดยไม่จำเป็นต้องอยู่ในหน้าจอของพนักงานทั่วไป

### 6.6 ADA Preflight

ก่อนส่งต้องแสดง checklist:

- ADA POS กำลังเปิดและตอบสนอง
- อยู่บริษัท/สาขาที่ถูกต้อง
- หน้าจอ `ใบรับของ/ใบซื้อสินค้า` พร้อมใช้งาน
- Supplier map กับ ADA แล้ว
- ทุก product row มี ADA product code และ unit ที่ใช้ได้
- Header total กับ line totals reconcile แล้ว
- ไม่พบ invoice ซ้ำ

ปุ่มหลักใช้คำว่า `เตรียมส่งเข้า ADA` ก่อน และแยกจาก `เริ่มกรอก ADA` เพื่อป้องกันการกดพลาด

### 6.7 ADA Automation Monitor

แสดงความคืบหน้าแบบ row-by-row:

- กำลังกรอก field/row ใด
- สำเร็จแล้วกี่รายการ
- ค่าใดที่ ADA POS ตอบกลับ
- popup หรือ validation ใดเกิดขึ้น
- ปุ่ม Pause และ Stop safely

เมื่อพบสิ่งผิดปกติ automation ต้องหยุด ไม่กดข้ามและไม่เดา

หลังกรอกครบ:

1. อ่าน supplier, invoice number, จำนวนแถว และยอดรวมกลับจาก ADA
2. เทียบกับข้อมูลใน Review App
3. แสดง diff ถ้ามี
4. ให้คนกด `ยืนยันบันทึกใน ADA` ใน MVP

### 6.8 Completion Receipt

แสดงและเก็บ:

- ADA document number
- วันที่/เวลาบันทึก
- ผู้ตรวจและผู้ยืนยัน
- จำนวนรายการและ grand total
- Screenshot ก่อน/หลังบันทึก
- ผล reconciliation
- Automation log

## 7. Product Matching UX

ลำดับการจับคู่ที่แนะนำ:

1. Exact ADA product code/barcode
2. Supplier-specific confirmed alias
3. Exact normalized name
4. Purchase history ของ supplier
5. Fuzzy candidate list
6. Human selection

แสดง provenance ของคำแนะนำ เช่น `ตรงกับรหัส`, `เคยซื้อจาก supplier นี้ 14 ครั้ง` หรือ `ชื่อคล้าย 92%` แทนการแสดง confidence ตัวเลขอย่างเดียว

เมื่อ candidate หลายตัวใกล้กัน ให้แสดงข้อมูลช่วยตัดสิน:

- ขนาด/ความแรง
- หน่วยขาย
- ผู้ผลิต
- barcode
- ราคาซื้อล่าสุด
- วันที่ซื้อครั้งล่าสุด

## 8. ADA POS Integration Strategy

ผลจากการตรวจโปรแกรมจริง:

- ADA POS Back version `4.6006.0030`
- เป็น Visual Basic 6 และหน้าหลักเป็น `ThunderRT6MDIForm`
- เมนูและ header controls ควบคุมผ่าน Win32 ได้
- หน้ารับของมีประมาณ 116 controls
- ตารางสินค้าเป็น custom ATL grid (`ATL:034CF9A0`)
- ฐานข้อมูลเป็น SQL Server Express ชื่อ `AdaAcc`
- สามารถอ่าน product/supplier/history จากฐานข้อมูลแบบ read-only ได้

แนวทางที่แนะนำ:

- อ่าน product master, supplier และประวัติจาก SQL แบบ read-only
- กรอกเอกสารผ่าน ADA POS UI เพื่อให้ business rules ภายในโปรแกรมทำงานครบ
- ห้ามเขียนตาราง ADA โดยตรงใน MVP
- ใช้ control handle/class/control ID สำหรับ header
- ใช้ keyboard-driven deterministic workflow สำหรับ custom product grid
- ใช้ภาพ/pixel matching เป็น fallback เท่านั้น
- ตรวจ popup ทุกขั้นและใช้ timeout ที่ชัดเจน
- ทุก action ต้อง idempotent หรือสามารถตรวจได้ว่าเคยทำแล้ว

## 9. Data Model ขั้นต่ำ

### Document

- id
- source_file_path / file hash
- supplier_id และ supplier confidence
- invoice number/date
- totals และ VAT
- OCR run/version
- workflow status
- duplicate key
- created/updated timestamps

### Document Line

- document_id และ sequence
- raw OCR text
- supplier SKU
- extracted description/unit/quantity/price/discount/total
- lot/expiry
- matched ADA product code
- match method/confidence/status
- reviewer correction

### Review Decision

- document/line/field reference
- original value
- proposed value
- final value
- action: confirm/correct/reject
- error category
- reviewer
- duration seconds
- timestamp

### ADA Automation Run

- document_id
- target company/branch
- started/finished timestamps
- state และ current step
- row-level results
- popup/error details
- preflight snapshot
- reconciliation result
- ADA document number
- screenshots/log paths

## 10. Safety และ Reliability Requirements

- ห้ามส่งเอกสารที่ยังมี unresolved red fields
- ห้ามบันทึก ADA หากยอดรวมหรือจำนวนแถวไม่ตรง
- ห้ามทำงานพร้อมกันสอง automation run บน ADA instance เดียว
- ตรวจ company/branch ทุกครั้งก่อนกรอก
- ตรวจ duplicate ทั้งใน Review App และ ADA
- Automation ต้อง resume หรือ restart ได้โดยไม่สร้างเอกสารซ้ำ
- Pause เมื่อผู้ใช้แตะ keyboard/mouse ระหว่าง run หรือมีหน้าต่างอื่นแทรก
- เก็บค่าเดิม/ค่าใหม่และหลักฐานทุก correction
- ห้ามเก็บ password หรือ connection string เป็น plaintext ใน log
- แยก staging/test mode ออกจาก production อย่างชัดเจน

## 11. UX Principles

- Answer first: ผู้ใช้ต้องเห็นทันทีว่า “ต้องแก้อะไร”
- Evidence adjacent: ภาพต้นฉบับอยู่ใกล้ field ที่กำลังตรวจ
- Keyboard-first สำหรับผู้ใช้ที่ทำงานหลาย invoice ต่อวัน
- Progressive disclosure: ซ่อนรายละเอียด OCR/automation จนกว่าจะต้องใช้
- No silent guessing: uncertainty ต้องมองเห็นและส่งต่อให้คนตัดสิน
- Safe by default: การเพิ่ม automation ต้องมี human approval
- Preserve context: เมื่อเกิด error ผู้ใช้กลับมาทำต่อจากจุดเดิมได้
- Thai-first UI และใช้คำที่ตรงกับคำใน ADA POS

## 12. MVP Acceptance Criteria

- รองรับ Top 3 suppliers
- Extract header และ product rows เข้า Review Workspace
- ผู้ใช้แก้และยืนยันด้วย keyboard ได้
- Match กับ ADA supplier/product master แบบ read-only
- ส่งเอกสารเข้า ADA POS โดยมี human confirmation ก่อน save
- ห้ามเกิด duplicate document
- Reconcile row count และ grand total 100% ก่อน save
- Automation success rateอย่างน้อย 95% บนเอกสารทดสอบ 30 ใบ
- เก็บ duration per invoice และ per review decision
- เก็บ audit log และ failure evidence ครบ

Metrics หลัก:

- Human minutes per invoice
- First-pass confirmation rate
- จำนวน field/row ที่ต้องแก้
- Product match rate แยกตาม tier
- ADA automation success rate
- Reconciliation failure rate
- Duplicate prevention rate

## 13. สิ่งที่ยังต้องพิสูจน์

- พฤติกรรมการกรอก custom ATL product grid ด้วย keyboard
- Product lookup popup และการเลือกหน่วย
- Popup เมื่อรหัสไม่พบ ราคาผิด หรือสินค้าซ้ำ
- การอ่าน row count และค่ารายแถวกลับจาก ADA
- ความหมายของปุ่มบันทึกกับอนุมัติใน workflow จริง
- การ rollback/cancel เอกสารที่กรอกค้าง
- Schema และ API contract ของ `ADACallAPI.dll`

## 14. สิ่งที่อยู่นอก MVP

- Auto-approval โดยไม่ผ่านคน
- เขียนข้อมูลเข้าฐาน ADA โดยตรง
- รองรับ supplier ทุกบริษัท
- AI เลือกสินค้านอก product master
- Mobile app
- Multi-user automation บน ADA instance เดียวกัน
- Dashboard เชิงบริหารแบบเต็มรูปแบบ

## 15. Prompt สำหรับส่งให้ Sol Ex High

```text
ช่วยออกแบบ Windows Desktop OCR Invoice Review App จาก design brief นี้ โดยเน้น workflow สำหรับพนักงานรับสินค้าในร้านขายยาไทย

เป้าหมายหลักคือให้ผู้ใช้ตรวจข้อมูล invoice และรายการสินค้าให้เร็วที่สุด แล้วส่งข้อมูลเข้า ADA POS Back อย่างปลอดภัย ห้ามออกแบบให้ระบบ auto-save โดยไม่มี human confirmation ใน MVP

กรุณาส่งมอบ:
1. Information architecture และ end-to-end user flow
2. Wireframe ของ Inbox, Review Queue, Review Workspace, Exception Resolver, ADA Preflight, Automation Monitor และ Completion Receipt
3. Interaction specification โดยเฉพาะ keyboard workflow ของตารางสินค้า
4. Component/state inventory รวม loading, empty, warning, conflict, failure และ recovery states
5. วิธีแสดง OCR evidence, product match provenance และ validation โดยไม่ทำให้หน้าจอรก
6. Safety UX สำหรับ duplicate prevention, total reconciliation, pause/stop และ human confirm before save
7. Human correction UX และโครงสร้าง learning dataset ที่เก็บ prediction, correction, evidence, error category และ model version ครบถ้วน
8. Data-quality workflow สำหรับ alias confirmation, label conflict, dataset versioning, frozen holdout และ model approval
9. Visual direction ที่เหมาะกับงาน back-office แบบ high-density แต่ยังอ่านง่าย รองรับภาษาไทย
10. MVP scope, acceptance criteria และรายการคำถามที่ต้องทดสอบกับผู้ใช้จริง

ข้อจำกัดทางเทคนิค:
- ADA POS เป็น VB6
- Header controls จับผ่าน Win32 ได้
- ตารางสินค้าเป็น custom ATL grid และน่าจะต้องควบคุมด้วย keyboard workflow
- อ่าน supplier/product/history จาก SQL Server AdaAcc ได้แบบ read-only
- ห้ามเขียนฐาน ADA โดยตรงใน MVP
- ต้องเก็บ audit trail และตรวจยอดก่อนบันทึกทุกครั้ง

อย่าทำเป็น dashboard ทั่วไป ให้เน้น review speed, exception handling, evidence และ safe handoff เข้า ADA POS
```
