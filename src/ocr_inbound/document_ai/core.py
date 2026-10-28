"""Immutable sources, proposal/review separation, and an auditable export gate.

No OCR fitting, ERP connection, or automatic human approvals exist in this module.
Processing is an injected background adapter so heavy work can stay on HQ.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import struct
import threading
import uuid

def now(): return datetime.now(timezone.utc).isoformat()
def canonical(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(data): return hashlib.sha256(data).hexdigest()
class PrototypeError(ValueError):
    def __init__(self,code,message,status=400):
        super().__init__(message);self.code=code;self.message=message;self.status=status

def source_type(content):
    if content.startswith(b'%PDF-'):return 'application/pdf','.pdf'
    if content.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png','.png'
    if content.startswith(b'\xff\xd8\xff'):return 'image/jpeg','.jpg'
    raise PrototypeError('UNSUPPORTED_SOURCE','รับเฉพาะ PDF, PNG และ JPEG ที่ตรวจชนิดไฟล์ได้',415)

def image_dimensions(content):
    if content.startswith(b'\x89PNG\r\n\x1a\n') and len(content)>=24 and content[12:16]==b'IHDR':
        w,h=struct.unpack('>II',content[16:24])
    elif content.startswith(b'\xff\xd8'):
        i=2;w=h=0
        while i+4<=len(content):
            if content[i]!=255:break
            while i<len(content) and content[i]==255:i+=1
            if i>=len(content):break
            marker=content[i];i+=1
            if marker in (0xD8,0xD9,0x01) or 0xD0<=marker<=0xD7:continue
            if i+2>len(content):break
            length=int.from_bytes(content[i:i+2],'big')
            if length<2 or i+length>len(content):break
            if marker in (0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF) and length>=7:
                h=int.from_bytes(content[i+3:i+5],'big');w=int.from_bytes(content[i+5:i+7],'big');break
            if marker==0xDA:break
            i+=length
    else:w=h=0
    if not w or not h or w*h>100_000_000:raise PrototypeError('IMAGE_DIMENSIONS','ภาพมีขนาดไม่ถูกต้องหรือเกินขอบเขต',422)
    return w,h

def safe_id(value):
    return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',value) is not None

class PrototypeStore:
    def __init__(self,root,processor=None,required_fields=('product_code','quantity','unit')):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.db_path=self.root/'review.sqlite3';self.processor=processor
        self.required_fields=tuple(required_fields);self._lock=threading.RLock()
        self._pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='document-ai-transport')
        self._futures={};self._closed=False
        with self._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,source_sha TEXT UNIQUE NOT NULL,filename TEXT NOT NULL,media_type TEXT NOT NULL,status TEXT NOT NULL,revision INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,error TEXT,result_sha TEXT);
            CREATE TABLE IF NOT EXISTS assets(document_id TEXT NOT NULL,id TEXT NOT NULL,path TEXT NOT NULL,sha TEXT NOT NULL,media_type TEXT NOT NULL,width INTEGER,height INTEGER,page_number INTEGER,page_id TEXT,PRIMARY KEY(document_id,id));
            CREATE TABLE IF NOT EXISTS rows(document_id TEXT NOT NULL,id TEXT NOT NULL,proposal TEXT NOT NULL,decision TEXT NOT NULL DEFAULT 'pending',corrections TEXT NOT NULL DEFAULT '{}',note TEXT NOT NULL DEFAULT '',reviewer TEXT,PRIMARY KEY(document_id,id));
            CREATE TABLE IF NOT EXISTS audit(sequence INTEGER PRIMARY KEY AUTOINCREMENT,document_id TEXT NOT NULL,event_type TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS exports(document_id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,sha TEXT NOT NULL,PRIMARY KEY(document_id,revision));
            ''')
            if 'page_id' not in {r[1] for r in db.execute('PRAGMA table_info(assets)')}:db.execute('ALTER TABLE assets ADD COLUMN page_id TEXT')
    @contextmanager
    def _db(self,write=False):
        with self._lock:
            db=sqlite3.connect(self.db_path,timeout=15);db.row_factory=sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA journal_mode=WAL')
            if write:db.execute('BEGIN IMMEDIATE')
            try:
                yield db;db.commit()
            except BaseException:
                db.rollback();raise
            finally:db.close()
    def _event(self,db,document_id,event_type,actor,payload):
        prev=db.execute('SELECT event_hash FROM audit ORDER BY sequence DESC LIMIT 1').fetchone()
        previous=prev[0] if prev else '0'*64
        event={'document_id':document_id,'event_type':event_type,'actor':actor,'created_at':now(),'payload':payload,'previous_hash':previous}
        sha=digest(canonical(event).encode())
        db.execute('INSERT INTO audit(document_id,event_type,actor,created_at,payload,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?)',(document_id,event_type,actor,event['created_at'],canonical(payload),previous,sha))
    def _document(self,db,document_id):
        d=db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
        if not d:raise PrototypeError('NOT_FOUND','ไม่พบเอกสารนี้',404)
        return dict(d)
    def _revision(self,d,expected):
        if type(expected) is not int or d['revision']!=expected:raise PrototypeError('REVISION_CONFLICT','ข้อมูลเปลี่ยนแล้ว กรุณาโหลดเอกสารล่าสุดก่อนบันทึก',409)
    def _bump(self,db,document_id,status='review'):
        db.execute('UPDATE documents SET revision=revision+1,status=?,updated_at=? WHERE id=?',(status,now(),document_id))
    def ingest_source(self,filename,content,media_type=None,reviewer='operator'):
        if self._closed:raise PrototypeError('CLOSED','ระบบกำลังปิด',503)
        if not content or len(content)>80*1024*1024:raise PrototypeError('SOURCE_SIZE','ขนาดเอกสารต้องอยู่ระหว่าง 1 ไบต์ถึง 80 MB',413)
        mime,suffix=source_type(content)
        if mime.startswith('image/'):image_dimensions(content)
        if media_type and media_type.split(';')[0] not in (mime,'application/octet-stream'):
            raise PrototypeError('SOURCE_TYPE_MISMATCH','ชนิดไฟล์ไม่ตรงกับเนื้อหาที่ส่งมา',415)
        filename=str(filename).replace('\\','/').split('/')[-1][:240] or 'document'+suffix
        sha=digest(content)
        with self._db(write=True) as db:
            old=db.execute('SELECT id FROM documents WHERE source_sha=?',(sha,)).fetchone()
            if old:return self.get_document(old[0])
            document_id=uuid.uuid4().hex;folder=self.root/'documents'/document_id;folder.mkdir(parents=True)
            source=folder/('source'+suffix);source.write_bytes(content)
            if digest(source.read_bytes())!=sha:raise PrototypeError('SOURCE_WRITE','ตรวจไฟล์ที่เก็บแล้วไม่ตรงต้นฉบับ',500)
            timestamp=now()
            db.execute('INSERT INTO documents(id,source_sha,filename,media_type,status,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(document_id,sha,filename,mime,'processing',1,timestamp,timestamp))
            db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?)',(document_id,'source',str(source.relative_to(self.root)),sha,mime,None,None,None,None))
            self._event(db,document_id,'source_ingested',reviewer,{'source_sha256':sha,'filename':filename,'bytes':len(content),'media_type':mime})
        self._submit(document_id)
        return self.get_document(document_id)
    def _submit(self,document_id):
        if not self.processor:return
        existing=self._futures.get(document_id)
        if existing and not existing.done():return
        def work():
            try:
                document=self.get_document(document_id);source,_=self.get_asset(document_id,'source')
                result=self.processor({**document,'source_path':str(source)})
                self.install_result(document_id,result)
            except Exception as exc:
                with self._db(write=True) as db:
                    db.execute('UPDATE documents SET status=?,error=?,updated_at=? WHERE id=?',('failed',type(exc).__name__+': '+str(exc)[:1500],now(),document_id))
                    self._event(db,document_id,'processing_failed','processor',{'error_type':type(exc).__name__,'message':str(exc)[:1500]})
        self._futures[document_id]=self._pool.submit(work)
    def resume_pending(self):
        with self._db() as db:ids=[r[0] for r in db.execute("SELECT id FROM documents WHERE status='processing'")]
        for document_id in ids:self._submit(document_id)
        return len(ids)
    def install_result(self,document_id,result):
        result=json.loads(canonical(result))
        if result.get('contract')!='document-ai-proposals.v1':raise PrototypeError('RESULT_CONTRACT','ผลประมวลผลมีรูปแบบไม่ตรงสัญญา')
        if not isinstance(result.get('pages'),list) or not isinstance(result.get('rows'),list):raise PrototypeError('RESULT_SCHEMA','ผลต้องมีรายการหน้าและแถว')
        if len(result['pages'])>500 or len(result['rows'])>20000:raise PrototypeError('RESULT_SIZE','ผลประมวลผลเกินขอบเขตต้นแบบ')
        payload_sha=digest(canonical(result).encode())
        with self._db(write=True) as db:
            d=self._document(db,document_id)
            if result.get('source_sha256')!=d['source_sha']:raise PrototypeError('SOURCE_BINDING','ผลไม่ตรง SHA256 ต้นฉบับ',409)
            if result.get('document_id') not in (None,document_id):raise PrototypeError('DOCUMENT_BINDING','ผลไม่ตรงเอกสาร',409)
            if d['result_sha']==payload_sha:return self.get_document(document_id)
            if d['result_sha']:raise PrototypeError('RESULT_IMMUTABLE','ผลเดิมถูกตรึงแล้ว ต้องสร้างรุ่นใหม่แทนการเขียนทับ',409)
            pages={};ids=set();numbers=set()
            for page in result['pages']:
                page_id=str(page['id']);width=page.get('width');height=page.get('height')
                number=page.get('number')
                if not safe_id(page_id) or page_id in pages or type(number) is not int or not 1<=number<=500 or number in numbers or type(width) is not int or type(height) is not int or min(width,height)<=0:raise PrototypeError('PAGE_SCHEMA','หน้าเอกสารหรือขนาดไม่ถูกต้อง')
                numbers.add(number)
                pages[page_id]=page
                path=Path(page['image_path']).resolve();base=Path(result.get('artifacts_root',path.parent)).resolve()
                if not path.is_relative_to(base) or path.is_symlink():raise PrototypeError('ASSET_PATH','ตำแหน่งภาพไม่อยู่ในขอบเขตผลประมวลผล')
                content=path.read_bytes();mime,suffix=source_type(content)
                if not mime.startswith('image/'):raise PrototypeError('PAGE_TYPE','หน้าที่เรนเดอร์ต้องเป็นภาพ')
                if image_dimensions(content)!=(width,height):raise PrototypeError('PAGE_DIMENSIONS','ขนาดภาพจริงไม่ตรงกับพิกัดผลอ่าน',409)
                page_sha=digest(content)
                if page.get('sha256')!=page_sha:raise PrototypeError('ASSET_SHA','SHA256 ภาพหน้าไม่ตรง')
                asset_id='page-'+str(page['number']);dest=self.root/'documents'/document_id/(asset_id+suffix)
                if dest.exists() and digest(dest.read_bytes())!=page_sha:raise PrototypeError('ASSET_IMMUTABLE','ภาพหน้ามีอยู่แล้วและไม่ตรง')
                if not dest.exists():dest.write_bytes(content)
                db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?)',(document_id,asset_id,str(dest.relative_to(self.root)),page_sha,mime,width,height,page['number'],page_id))
                page['image_asset_id']=asset_id
            for row in result['rows']:
                row_id=str(row['id'])
                if not safe_id(row_id) or row_id in ids or row.get('page_id') not in pages:raise PrototypeError('ROW_BINDING','แถวซ้ำหรือไม่ผูกหน้าเอกสาร')
                ids.add(row_id)
                if not isinstance(row.get('fields'),dict) or any(not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',k) for k in row['fields']):raise PrototypeError('FIELD_SCHEMA','ชื่อช่องข้อมูลไม่ถูกต้อง')
                page=pages[row['page_id']]
                row=json.loads(canonical(row));row['source_sha256']=d['source_sha'];row['page_number']=page['number'];row.setdefault('issues',[]);row.setdefault('line_kind','purchase')
                if row['line_kind'] not in ('purchase','free','non_product','context'):raise PrototypeError('ROW_KIND','ประเภทแถวไม่ถูกต้อง')
                for key,value in row['fields'].items():
                    if not isinstance(value,dict):raise PrototypeError('FIELD_SCHEMA','ช่องต้องแยกค่าดิบและข้อเสนอ')
                    value.setdefault('raw',None);value.setdefault('normalized',None);value.setdefault('catalogue',None);value['final']=value.get('normalized')
                    b=value.get('bbox');valid=isinstance(b,list) and len(b)==4 and all(isinstance(x,(int,float)) and math.isfinite(x) for x in b)
                    valid=valid and 0<=b[0]<b[2]<=page['width'] and 0<=b[1]<b[3]<=page['height'] and value.get('bbox_frame')=='original_image'
                    if b is not None and not valid:value['bbox']=None;value['reason']=(value.get('reason','')+' พิกัดยังไม่ยืนยัน จึงไม่แสดงกรอบ').strip()
                db.execute('INSERT INTO rows(document_id,id,proposal) VALUES(?,?,?)',(document_id,row_id,canonical(row)))
            db.execute('UPDATE documents SET status=?,revision=revision+1,updated_at=?,result_sha=?,error=NULL WHERE id=?',('review',now(),payload_sha,document_id))
            self._event(db,document_id,'proposals_prepared','processor',{'source_sha256':d['source_sha'],'result_sha256':payload_sha,'pages':len(pages),'rows':len(ids),'processing':result.get('processing',{}),'completeness_confirmed':False})
        return self.get_document(document_id)
    def _display_row(self,row):
        r=json.loads(row['proposal']);corrections=json.loads(row['corrections'])
        for key in ('original_line_kind','disposition','field_values_attested_correct'):r.pop(key,None)
        for k,v in corrections.items():
            r['fields'].setdefault(k,{'raw':None,'normalized':None,'catalogue':None,'bbox':None})
            r['fields'][k]['final']=v['value'];r['fields'][k]['final_authority']='human_attestation';r['fields'][k]['evidence_ids']=v.get('evidence_ids',[])
        if row['decision']=='excluded':
            r['original_line_kind']=r.get('line_kind','purchase')
            r['line_kind']='non_product';r['disposition']='excluded_non_product'
            r['field_values_attested_correct']=False
        return {**r,'decision':row['decision'],'note':row['note'],'reviewer':row['reviewer']}
    def list_documents(self):
        with self._db() as db:ids=[r[0] for r in db.execute('SELECT id FROM documents ORDER BY created_at DESC')]
        return [self.get_document(i) for i in ids]
    def get_document(self,document_id):
        with self._db() as db:
            d=self._document(db,document_id);rows=[self._display_row(r) for r in db.execute('SELECT * FROM rows WHERE document_id=? ORDER BY rowid',(document_id,))]
            pages=[{'id':a['page_id'] or 'p'+str(a['page_number']),'number':a['page_number'],'width':a['width'],'height':a['height'],'image_asset_id':a['id'],'source_asset_id':'source','media_type':a['media_type']} for a in db.execute("SELECT * FROM assets WHERE document_id=? AND id<>'source' ORDER BY page_number",(document_id,))]
            if not pages:pages=[{'id':'source','number':1,'source_asset_id':'source','media_type':d['media_type'],'width':None,'height':None}]
            approved=sum(r['decision'] in ('approved','corrected') for r in rows)
            goods=sum(r.get('line_kind') in ('purchase','free') for r in rows)
            excluded=sum(r['decision']=='excluded' for r in rows)
            context=sum(r.get('line_kind') not in ('purchase','free') and r['decision']!='excluded' for r in rows)
            approved_goods=sum(r.get('line_kind') in ('purchase','free') and r['decision'] in ('approved','corrected') for r in rows)
            return {'id':d['id'],'filename':d['filename'],'source_sha256':d['source_sha'],'media_type':d['media_type'],'status':d['status'],'revision':d['revision'],'created_at':d['created_at'],'error':d['error'],'pages':pages,'rows':rows,'required_fields':list(self.required_fields),'summary':{'rows':len(rows),'goods_rows':goods,'context_rows':context,'excluded':excluded,'approved_goods':approved_goods,'approved':approved,'decided':approved+excluded,'held':sum(r['decision']=='held' for r in rows),'pending':sum(r['decision']=='pending' for r in rows),'exportable':bool(approved_goods) and approved+excluded==len(rows) and d['status'] in ('review','approved')},'posting_authorized':False}
    def _validate_final(self,row):
        # An exclusion attests only that this is not a goods line. Its retained
        # machine values can be incomplete or wrong and are not approved facts.
        if row.get('decision')=='excluded':return
        for key in ('invoice_date','receive_date','receiving_date','receipt_date','mfg_date','exp_date','transfer_date'):
            value=row['fields'].get(key,{}).get('final')
            if value not in (None,''):
                try:
                    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError()
                    date.fromisoformat(value)
                except ValueError:raise PrototypeError('DATE_INVALID','วันที่ต้องเป็นวันที่จริงในรูปแบบ YYYY-MM-DD: '+key,422)
        if row.get('line_kind') in ('non_product','context'):return
        missing=[k for k in self.required_fields if row['fields'].get(k,{}).get('final') in (None,'')]
        if missing:raise PrototypeError('REQUIRED_FIELDS','ยังขาดช่องที่ต้องตรวจ: '+', '.join(missing),422)
        for key in ('product_code','unit'):
            value=row['fields'][key]['final']
            if not isinstance(value,str) or not value.strip() or value!=value.strip():raise PrototypeError('IDENTITY_UNIT_INVALID','รหัสสินค้าและหน่วยต้องเป็นข้อความที่ไม่ว่างและไม่มีช่องว่างหัวท้าย',422)
        if isinstance(row['fields']['quantity']['final'],bool):raise PrototypeError('QUANTITY_INVALID','จำนวนต้องเป็นตัวเลข',422)
        try:q=Decimal(str(row['fields']['quantity']['final']).replace(',',''))
        except (InvalidOperation,KeyError):raise PrototypeError('QUANTITY_INVALID','จำนวนต้องเป็นตัวเลข',422)
        if not q.is_finite() or q<=0:raise PrototypeError('QUANTITY_INVALID','จำนวนรับต้องมากกว่าศูนย์',422)
        # Invoice dates, payment dates, and receive dates remain independent keys.
    def review_row(self,document_id,row_id,decision,corrections=None,note='',reviewer='',expected_revision=None,exclusion_confirmed=False):
        if decision not in ('approve','correct','hold','exclude'):raise PrototypeError('DECISION','ผลตรวจไม่ถูกต้อง')
        if not str(reviewer).strip():raise PrototypeError('REVIEWER','กรุณาระบุผู้ตรวจ')
        if len(str(note))>10000:raise PrototypeError('NOTE_SIZE','ข้อความยาวเกินไป')
        corrections=corrections or {}
        if not isinstance(corrections,dict):raise PrototypeError('CORRECTIONS','ค่าที่แก้ต้องเป็นรายการช่อง')
        if decision=='exclude':
            if not isinstance(reviewer,str) or not reviewer.strip():raise PrototypeError('REVIEWER','กรุณาระบุผู้ตรวจ')
            if not isinstance(note,str) or not note.strip() or exclusion_confirmed is not True:raise PrototypeError('EXCLUSION_CONFIRMATION_REQUIRED','ระบุเหตุผลและยืนยันกับต้นฉบับว่าแถวนี้ไม่ใช่รายการสินค้า',422)
            if corrections:raise PrototypeError('EXCLUSION_CORRECTIONS','การไม่นับเป็นสินค้าไม่แก้ค่าที่ระบบอ่าน เก็บเหตุผลและต้นฉบับไว้แยกกัน',422)
        normalized={}
        for k,v in corrections.items():
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',k):raise PrototypeError('FIELD_SCHEMA','ชื่อช่องข้อมูลไม่ถูกต้อง')
            item=v if isinstance(v,dict) else {'value':v};value=item.get('value')
            if isinstance(value,(dict,list)) or value is not None and not isinstance(value,(str,int,float,bool)):raise PrototypeError('CORRECTION_VALUE','ค่าช่องต้องเป็นข้อความ ตัวเลข หรือ null')
            if isinstance(value,float) and not math.isfinite(value):raise PrototypeError('CORRECTION_VALUE','ค่าตัวเลขไม่ถูกต้อง')
            normalized[k]={'value':value,'evidence_ids':item.get('evidence_ids',[])}
        with self._db(write=True) as db:
            d=self._document(db,document_id);self._revision(d,expected_revision)
            if d['status'] not in ('review','approved'):raise PrototypeError('NOT_READY','เอกสารยังไม่พร้อมตรวจ',409)
            allowed={r[0] for r in db.execute('SELECT id FROM assets WHERE document_id=?',(document_id,))}
            for item in normalized.values():
                evidence=item['evidence_ids']
                if not isinstance(evidence,list) or any(not isinstance(e,str) or e not in allowed for e in evidence):raise PrototypeError('EVIDENCE_BINDING','หลักฐานต้องเป็นภาพหรือหน้าของเอกสารนี้เท่านั้น',422)
                if not evidence:item['evidence_ids']=['source']
            row=db.execute('SELECT * FROM rows WHERE document_id=? AND id=?',(document_id,row_id)).fetchone()
            if not row:raise PrototypeError('ROW_NOT_FOUND','ไม่พบแถวนี้',404)
            merged={**json.loads(row['corrections']),**normalized}
            newdecision={'approve':'approved','correct':'corrected','hold':'held','exclude':'excluded'}[decision]
            if normalized and decision=='approve':newdecision='corrected'
            proposed=self._display_row({**dict(row),'corrections':canonical(merged),'decision':newdecision})
            if decision not in ('hold','exclude'):self._validate_final(proposed)
            db.execute('UPDATE rows SET decision=?,corrections=?,note=?,reviewer=? WHERE document_id=? AND id=?',(newdecision,canonical(merged),str(note),reviewer,document_id,row_id))
            self._bump(db,document_id)
            self._event(db,document_id,'row_reviewed',reviewer,{'row_id':row_id,'decision':newdecision,'corrections':normalized,'note':str(note),'based_on_revision':expected_revision,'printed_OCR_modified':False,'exclusion_confirmed':decision=='exclude' and exclusion_confirmed is True,'disposition':proposed.get('disposition'),'original_line_kind':proposed.get('original_line_kind')})
        return self.get_document(document_id)
    def add_review_row(self,document_id,fields,note,reviewer,expected_revision,page_id):
        if not str(reviewer).strip() or not str(note).strip():raise PrototypeError('ATTESTATION_REQUIRED','กรุณาระบุผู้ตรวจและเหตุผลการเพิ่มรายการ')
        with self._db(write=True) as db:
            d=self._document(db,document_id);self._revision(d,expected_revision)
            doc=self.get_document(document_id);page=next((p for p in doc['pages'] if p['id']==page_id),None)
            if not page or d['status'] not in ('review','approved'):raise PrototypeError('PAGE_NOT_FOUND','ไม่พบหน้าที่พร้อมตรวจ',409)
            row_id='manual-'+uuid.uuid4().hex
            proposed={'id':row_id,'page_id':page_id,'page_number':page['number'],'source_sha256':d['source_sha'],'line_kind':'purchase','issues':['human_added_missing_row'],'fields':{}}
            for k,v in fields.items():
                if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',k) or isinstance(v,(dict,list)):raise PrototypeError('FIELD_SCHEMA','ช่องที่เพิ่มไม่ถูกต้อง')
                proposed['fields'][k]={'raw':None,'normalized':None,'catalogue':None,'final':None,'bbox':None,'reason':'ผู้ตรวจเพิ่มจากต้นฉบับ ไม่ใช่คำอ่าน OCR'}
            db.execute('INSERT INTO rows(document_id,id,proposal,corrections,note,reviewer) VALUES(?,?,?,?,?,?)',(document_id,row_id,canonical(proposed),canonical({k:{'value':v,'evidence_ids':['source']} for k,v in fields.items()}),note,reviewer))
            self._bump(db,document_id);self._event(db,document_id,'missing_row_added',reviewer,{'row_id':row_id,'page_id':page_id,'fields':fields,'note':note,'authority':'human_attestation','printed_OCR_modified':False})
        return self.get_document(document_id)
    def history(self,document_id):
        with self._db() as db:
            self._document(db,document_id)
            return [{**dict(r),'payload':json.loads(r['payload'])} for r in db.execute('SELECT * FROM audit WHERE document_id=? ORDER BY sequence',(document_id,))]
    def get_asset(self,document_id,asset_id):
        with self._db() as db:
            self._document(db,document_id);row=db.execute('SELECT * FROM assets WHERE document_id=? AND id=?',(document_id,asset_id)).fetchone()
            if not row:raise PrototypeError('ASSET_NOT_FOUND','ไม่พบไฟล์ที่เอกสารนี้อนุญาต',404)
            path=(self.root/row['path']).resolve()
            if not path.is_relative_to(self.root/'documents'/document_id) or digest(path.read_bytes())!=row['sha']:raise PrototypeError('ASSET_INTEGRITY','ไฟล์หลักฐานเปลี่ยนหรืออยู่นอกขอบเขต',409)
            return path,row['media_type']
    def export_document(self,document_id,reviewer='',completeness_confirmed=False,expected_revision=None,source_sha256=None):
        if completeness_confirmed is not True:raise PrototypeError('COMPLETENESS_REQUIRED','ต้องตรวจเทียบต้นฉบับครบทุกหน้าและยืนยันว่าไม่มีรายการตกหล่นก่อนส่งต่อ',422)
        if not str(reviewer).strip():raise PrototypeError('REVIEWER','กรุณาระบุผู้ตรวจ')
        with self._db(write=True) as db:
            d=self._document(db,document_id);self._revision(d,expected_revision)
            if source_sha256!=d['source_sha']:raise PrototypeError('SOURCE_BINDING','คำยืนยันต้องผูกกับต้นฉบับที่กำลังตรวจ',409)
            doc=self.get_document(document_id)
            if not doc['summary']['exportable']:raise PrototypeError('UNRESOLVED_ROWS','ยังมีรายการที่รอตรวจ/พักไว้ หรือยังไม่มีรายการที่ตรวจได้',409)
            for r in doc['rows']:self._validate_final(r)
            for a in db.execute('SELECT id FROM assets WHERE document_id=?',(document_id,)):self.get_asset(document_id,a['id'])
            old=db.execute('SELECT payload FROM exports WHERE document_id=? AND revision=?',(document_id,d['revision'])).fetchone()
            if old:return json.loads(old[0])
            goods_rows=[r for r in doc['rows'] if r.get('line_kind') in ('purchase','free') and r['decision'] in ('approved','corrected')]
            excluded_rows=[r for r in doc['rows'] if r['decision']=='excluded']
            context_rows=[r for r in doc['rows'] if r.get('line_kind') not in ('purchase','free') and r['decision']!='excluded']
            bundle={'contract':'document-ai-erp-handoff.v1','event_type':'reviewed_supplier_document','document_id':document_id,'document_revision':d['revision'],'source_sha256':d['source_sha'],'source_filename':d['filename'],'reviewer':reviewer,'reviewed_at':now(),'completeness_attestation':{'confirmed':True,'source_sha256':d['source_sha'],'revision':d['revision'],'reviewer':reviewer},'human_reviewed':True,'posting_authorized':False,'physical_receipt_automatically_inferred':False,'rows':doc['rows'],'audit_head':db.execute('SELECT event_hash FROM audit ORDER BY sequence DESC LIMIT 1').fetchone()[0]}
            bundle.update({'goods_rows':goods_rows,'context_rows':context_rows,'excluded_rows':excluded_rows,
                           'row_scope':{'rows':'all reviewed decisions retained for audit, including exclusions',
                                        'goods_rows':'only approved/corrected purchase/free document lines; no live posting authority',
                                        'excluded_rows':'audit only; machine field values are not attested correct'}})
            bundle['payload_sha256']=digest(canonical(bundle).encode())
            db.execute('INSERT INTO exports VALUES(?,?,?,?)',(document_id,d['revision'],canonical(bundle),bundle['payload_sha256']))
            db.execute('UPDATE documents SET status=? WHERE id=?',('approved',document_id))
            self._event(db,document_id,'reviewed_document_exported',reviewer,{'revision':d['revision'],'payload_sha256':bundle['payload_sha256'],'completeness_confirmed':True,'source_sha256':d['source_sha'],'posting_authorized':False})
            return bundle
    def verify_audit(self):
        previous='0'*64
        with self._db() as db:
            records=list(db.execute('SELECT * FROM audit ORDER BY sequence'))
            for r in records:
                event={k:r[k] for k in ('document_id','event_type','actor','created_at','previous_hash')};event['payload']=json.loads(r['payload'])
                if r['previous_hash']!=previous or digest(canonical(event).encode())!=r['event_hash']:return False
                previous=r['event_hash']
        return True
    def close(self,wait=True):
        self._closed=True;self._pool.shutdown(wait=wait,cancel_futures=False)
