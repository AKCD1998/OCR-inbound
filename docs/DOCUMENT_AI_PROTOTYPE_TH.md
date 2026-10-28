# ต้นแบบรับเอกสารและตรวจครั้งสุดท้าย

พัฒนาบน ScProductDev; ฝึกและอ่านเอกสารหนักบน 000 HQ เท่านั้น ต้นแบบนี้แยกจากระบบเดิมและไม่มีการเปิดใช้โมเดลทดลองใน production

## เริ่มบนเครื่องพัฒนา หรือ Codex Cloud

ใช้ Python 3.11 และ standard library สำหรับหน้ารีวิว/การทดสอบ ไม่ต้องติดตั้ง Paddle, Torch หรือดาวน์โหลดโมเดลเพื่อดูต้นแบบ

```powershell
$env:PYTHONPATH='src'
python -m ocr_inbound.document_ai serve --store <PRIVATE_DIRECTORY> --reviewer <REVIEWER_NAME> --demo
python -W error::ResourceWarning -m unittest discover -s tests -p 'test_document_ai_*.py'
```

Linux/Cloud ใช้ `PYTHONPATH=src python ...` แทนการตั้งตัวแปร PowerShell เปิด localhost:8877 ผ่าน preview ของสภาพแวดล้อมนั้น โหมด demo สร้าง PDF/PNG จำลองเอง แสดงชัดว่าไม่ได้อ่านด้วย OCR และไม่เอาคำตอบจำลองไปใส่เอกสารอื่น

## เส้นทางเอกสารจริง

1. อัปโหลด PDF/PNG/JPEG เก็บต้นฉบับแบบผูก SHA256 และกันเอกสารซ้ำ
2. ตัวส่งงานเผยแพร่ request และคิวเฉพาะเอกสารไป HQ งานคงอยู่เมื่อปิดเบราว์เซอร์หรือเครื่องพัฒนา ใช้ shared lock/ตัวควบคุม CPU/RAM เดิม งานหนักทีละงาน
3. HQ เรนเดอร์ทีละหน้าและอ่าน Tesseract TSV เก็บตำแหน่ง/ข้อความจริง ใช้ parser ผู้ขายแบบ snapshot แยกตาราง/แถว หากช่องขาดให้อ่านอัตโนมัติอีกโหมดได้ครั้งเดียว เติมเฉพาะช่องขาดที่มีเจ้าของแถวตรงกันเพียงหนึ่งราย และเก็บค่าขัดกันไว้ให้คนตรวจ
4. ตัวจับคู่ทะเบียนเสนอ SKU พร้อมทางเลือก ความแรง/รูปแบบ/ขนาดยังเป็นเงื่อนไขแยกจากคำอ่าน ไม่ถือรหัสผู้ขายเป็นรหัสบริษัท รุ่นฝึกใหม่ยัง HOLD; เส้นทางนี้ใช้ตัวจับคู่ก่อนฝึก
5. หน้าเดียวแสดงภาพพร้อมกรอบ คำอ่านดิบ ค่าจัดรูป ทะเบียน และค่าที่ผู้ตรวจยืนยัน แก้ค่า/พัก/เพิ่มแถวที่ตกหล่นได้ การแก้ไม่ทับข้อความจาก OCR
6. ส่งออก JSON ได้เมื่อทุกรายการยืนยันแล้ว มีสินค้าอย่างน้อยหนึ่งรายการ และผู้ตรวจยืนยันว่าเทียบต้นฉบับครบทุกหน้า ใช้ revision/source binding กันส่งออกคำยืนยันเก่า มีประวัติพร้อม hash chain

JSON เป็น `document-ai-erp-handoff.v1` / `reviewed_supplier_document`: ข้อเท็จจริงของเอกสารที่ผู้ตรวจรับรอง พร้อมต้นทางและคำแก้ ไม่ใช่เหตุการณ์รับสินค้าจริงโดยอัตโนมัติ `posting_authorized=false` และไม่มีการเขียน ERP/Ada/StockDay วันที่ใบ/รับเข้า/โอนเป็นคนละช่อง เอกสาร non-product อย่างเดียวใช้ส่งออกสินค้าผ่านสัญญานี้ไม่ได้

### ตั้ง HQ แบบส่วนตัว

`scripts/document_ai_deploy_hq.py` เผยแพร่โค้ดที่ตรวจ hash แล้วไปโฟลเดอร์ใหม่ และสร้าง private profile จาก serial template ที่ root ตรวจแล้ว ไม่เริ่ม worker ไม่เปลี่ยน runtime เดิม จากนั้น:

```powershell
python -m ocr_inbound.document_ai serve --store <PRIVATE_DIRECTORY> --reviewer <REVIEWER_NAME> --port 8878 --hq-config <PRIVATE_HQ_PROFILE_JSON>
```

อย่าส่ง profile, catalogue, source, SQLite, ข้อมูลฝึก, ผล OCR หรือ checkpoint ขึ้น GitHub คิวอ่านจริงรับไม่เกิน 20 หน้า/ไฟล์และ 20 ล้านพิกเซล/หน้า ติดขอบเขตให้หยุดพร้อมหลักฐาน ไม่ตัดหน้าที่เหลือเงียบ ๆ

## ผลฝึกและเครื่องมือทดลอง

ดู `DOCUMENT_AI_PRODUCT_LEARNING_RESULT_20261028.md` สำหรับผลฝึกตัวจับคู่รอบแรก, `DOCUMENT_AI_VERIFICATION_20261028.md` สำหรับผลตรวจโค้ด/เส้นทาง PDF จริงบน HQ และ `../experiments/document_ai/TRIAL_RESULTS.md` สำหรับ PP-DocLayout, Docling/TableFormer และ Qwen ทุกผลเป็นงานกับข้อมูลพัฒนาแล้ว ไม่ใช่ความแม่นยำบนใบใหม่ ข้อมูลใหม่ต้องสอบรุ่นที่ตรึงไว้ก่อนฝึกต่อ

ตัวจับคู่เป็น ML เฉพาะงานเรียนจากคำตอบธุรกิจที่เก็บไว้ ไม่ใช่การสอน OCR ให้อ่านตัวอักษร ชุดนี้ยังไม่มี glyph labels ที่ยืนยันครบ การใช้ LLM silver ไม่ทำให้ข้อมูลกลายเป็น human gold

การพบตาราง/ได้กรอบไม่เท่ากับคะแนนปลายทางเพิ่ม ต้องเทียบกับ baseline เดิมและ scorer เดิมบน 484 ภาพ (เฉลยสินค้า 585 ช่องมีเฉพาะบางหน้า) ไม่รวมผล test ตัวจับคู่เข้ากับคะแนน OCR 323/585 หรือ fresh-reading 324/585

## ทำงานต่อบน Cloud

- เริ่มจากเอกสารนี้และผลทดลองที่ commit ไว้ อย่าพยายามใช้ private workstation paths เป็นข้อมูลสาธารณะ Cloud รัน unit tests/demo ได้ทันที ส่วน HQ profile ต้องตั้งในสภาพแวดล้อมส่วนตัว
- แก้คอขวด brand/model/variant/pack และเกณฑ์ abstain ก่อนฝึกตัวจับคู่อีกรอบ รุ่นแรกมี wrong proposals เพิ่ม จึงไม่เลือกใช้
- เครื่องมือ layout อยู่คนละคิวกับการฝึก ต้องผ่าน canary และตรวจทรัพยากรก่อนเชื่อม parser; วัดผลครบด้วย raw OCR เดิมเมื่อเปลี่ยน geometry เท่านั้น
- หน้ารีวิวนี้ยังไม่มีบริษัทหลายผู้ใช้/SSO/สิทธิ์ผู้อนุมัติ/adapter ERP จริง จึงเป็น prototype บน loopback ข้อมูลที่คนยืนยันเก็บตรวจย้อนหลังได้ แต่ยังไม่ใช่ระบบหลักของบริษัท
- โค้ดใหม่อยู่ใน `src/ocr_inbound/document_ai`, `experiments/document_ai`, scripts/test ที่ขึ้นต้น `document_ai` โดยคงงานเก่าและ production แยกไว้
