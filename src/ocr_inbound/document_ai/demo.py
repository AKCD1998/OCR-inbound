"""Deterministic, clearly synthetic review fixtures; no OCR or model calls.

The callback accepts only the exact bytes generated here. It must never attach
the fixture answers or coordinates to an unrelated uploaded document.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
from pathlib import Path
import struct
import zlib

WIDTH, HEIGHT = 900, 1100
DEMO_MARKER = "document-ai-synthetic-demo.v1\n"
_FONT = {
    ' ': ['00000'] * 7,
    'A':['01110','10001','10001','11111','10001','10001','10001'],
    'B':['11110','10001','10001','11110','10001','10001','11110'],
    'C':['01111','10000','10000','10000','10000','10000','01111'],
    'D':['11110','10001','10001','10001','10001','10001','11110'],
    'E':['11111','10000','10000','11110','10000','10000','11111'],
    'F':['11111','10000','10000','11110','10000','10000','10000'],
    'G':['01111','10000','10000','10111','10001','10001','01111'],
    'H':['10001','10001','10001','11111','10001','10001','10001'],
    'I':['11111','00100','00100','00100','00100','00100','11111'],
    'J':['00111','00010','00010','00010','10010','10010','01100'],
    'K':['10001','10010','10100','11000','10100','10010','10001'],
    'L':['10000','10000','10000','10000','10000','10000','11111'],
    'M':['10001','11011','10101','10101','10001','10001','10001'],
    'N':['10001','11001','10101','10011','10001','10001','10001'],
    'O':['01110','10001','10001','10001','10001','10001','01110'],
    'P':['11110','10001','10001','11110','10000','10000','10000'],
    'Q':['01110','10001','10001','10001','10101','10010','01101'],
    'R':['11110','10001','10001','11110','10100','10010','10001'],
    'S':['01111','10000','10000','01110','00001','00001','11110'],
    'T':['11111','00100','00100','00100','00100','00100','00100'],
    'U':['10001','10001','10001','10001','10001','10001','01110'],
    'V':['10001','10001','10001','10001','10001','01010','00100'],
    'W':['10001','10001','10001','10101','10101','10101','01010'],
    'X':['10001','10001','01010','00100','01010','10001','10001'],
    'Y':['10001','10001','01010','00100','00100','00100','00100'],
    'Z':['11111','00001','00010','00100','01000','10000','11111'],
    '0':['01110','10001','10011','10101','11001','10001','01110'],
    '1':['00100','01100','00100','00100','00100','00100','01110'],
    '2':['01110','10001','00001','00010','00100','01000','11111'],
    '3':['11110','00001','00001','01110','00001','00001','11110'],
    '4':['00010','00110','01010','10010','11111','00010','00010'],
    '5':['11111','10000','10000','11110','00001','00001','11110'],
    '6':['01110','10000','10000','11110','10001','10001','01110'],
    '7':['11111','00001','00010','00100','01000','01000','01000'],
    '8':['01110','10001','10001','01110','10001','10001','01110'],
    '9':['01110','10001','10001','01111','00001','00001','01110'],
    '-':['00000','00000','00000','11111','00000','00000','00000'],
    ':':['00000','00100','00100','00000','00100','00100','00000'],
    '/':['00001','00010','00010','00100','01000','01000','10000'],
    '.':['00000','00000','00000','00000','00000','00110','00110'],
}
_COLUMNS = [35, 170, 465, 535, 610, 730, 865]
_KEYS = ['product_code','description','quantity','unit','lot','exp_date']
_VALUES = [
    ['DEMO-001','DEMO VITAMIN 100MG','12','BOX','D2601','2028-10-28'],
    ['DEMO-002','DOCUMENT SAMPLE','8','BTL','D2602','2029-01-31'],
]


@lru_cache(maxsize=1)
def _pixels() -> bytes:
    pixels = bytearray(b'\xff\xff\xff' * WIDTH * HEIGHT)

    def rectangle(x, y, width, height, colour=(35, 48, 69)):
        line = bytes(colour) * width
        for row in range(y, y + height):
            offset = (row * WIDTH + x) * 3
            pixels[offset:offset + width * 3] = line

    def text(x, y, value, scale=2):
        for char in value:
            for yy, line in enumerate(_FONT[char]):
                for xx, on in enumerate(line):
                    if on == '1':
                        rectangle(x + xx * scale, y + yy * scale, scale, scale)
            x += 6 * scale

    rectangle(25,25,850,78,(237,245,255))
    text(40,42,'SYNTHETIC DEMO',4)
    text(40,82,'NOT A REAL INVOICE - NO OCR MODEL WAS USED',2)
    text(35,130,'SUPPLIER: DEMO COMPANY',2)
    text(35,166,'INVOICE: DEMO-0001',2)
    text(465,166,'DATE: 2026-10-28',2)
    rectangle(35,220,830,45,(229,234,242))
    for x, label in zip(_COLUMNS[:-1],['CODE','DESCRIPTION','QTY','UNIT','LOT','EXP']):
        text(x+8,235,label,2)
    for row_number, values in enumerate(_VALUES):
        y=265 + row_number*65
        for x, value in zip(_COLUMNS[:-1],values):text(x+8,y+23,value,2)
    for y in [220,265,330,395]:rectangle(35,y,831,1,(125,140,160))
    for x in _COLUMNS:rectangle(x,220,1,176,(125,140,160))
    text(35,450,'THIS FIXTURE TESTS THE FINAL REVIEW SCREEN ONLY.',2)
    text(35,486,'ROW 2 NEEDS HUMAN PRODUCT CODE CONFIRMATION.',2)
    text(35,522,'NO STOCK RECEIPT OR ERP POSTING IS AUTHORIZED.',2)
    return bytes(pixels)


def _chunk(kind: bytes, content: bytes) -> bytes:
    return struct.pack('>I',len(content))+kind+content+struct.pack('>I',zlib.crc32(kind+content)&0xffffffff)


@lru_cache(maxsize=1)
def sample_png() -> bytes:
    rgb=_pixels()
    scanlines=b''.join(b'\x00'+rgb[y*WIDTH*3:(y+1)*WIDTH*3] for y in range(HEIGHT))
    return (b'\x89PNG\r\n\x1a\n'+_chunk(b'IHDR',struct.pack('>IIBBBBB',WIDTH,HEIGHT,8,2,0,0,0))
            +_chunk(b'IDAT',zlib.compress(scanlines))+_chunk(b'IEND',b''))


@lru_cache(maxsize=1)
def sample_pdf() -> bytes:
    """A valid one-page PDF showing the identical generated RGB page."""
    image=zlib.compress(_pixels())
    contents=f'q {WIDTH} 0 0 {HEIGHT} 0 0 cm /Im0 Do Q\n'.encode('ascii')
    objects=[
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {WIDTH} {HEIGHT}] /Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>'.encode('ascii'),
        b'<< /Length '+str(len(contents)).encode()+b' >>\nstream\n'+contents+b'endstream',
        (f'<< /Type /XObject /Subtype /Image /Width {WIDTH} /Height {HEIGHT} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(image)} >>\nstream\n'.encode('ascii')+image+b'\nendstream'),
    ]
    data=bytearray(b'%PDF-1.4\n% synthetic-document-ai-demo\n');offsets=[0]
    for number, obj in enumerate(objects,1):
        offsets.append(len(data));data.extend(f'{number} 0 obj\n'.encode()+obj+b'\nendobj\n')
    startxref=len(data)
    data.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF\n'.encode())
    return bytes(data)


def prepare_demo_store(root: Path) -> None:
    """Require an isolated empty or previously marked synthetic store."""
    root=Path(root);marker=root/'.synthetic-demo-store'
    if root.exists() and any(root.iterdir()):
        if not marker.is_file() or marker.read_text(encoding='utf-8')!=DEMO_MARKER:
            raise ValueError('Demo requires a separate empty store; do not mix synthetic and real evidence')
    root.mkdir(parents=True,exist_ok=True)
    marker.write_text(DEMO_MARKER,encoding='utf-8')


def demo_processor(document: dict) -> dict:
    source_path=Path(document['source_path']);content=source_path.read_bytes()
    known={hashlib.sha256(sample_png()).hexdigest(),hashlib.sha256(sample_pdf()).hexdigest()}
    sha=hashlib.sha256(content).hexdigest()
    if sha not in known or sha!=document.get('source_sha256'):
        raise ValueError('โหมดสาธิตรับเฉพาะไฟล์ DEMO ที่สร้างไว้ ไม่ได้อ่านเอกสารจริง; ต้องเชื่อมตัวประมวลผล HQ ก่อน')
    image=sample_png();path=source_path.parent/'synthetic-demo-page.png';path.write_bytes(image)
    rows=[]
    for row_number, values in enumerate(_VALUES):
        y=265+row_number*65;fields={}
        for index,(key,value) in enumerate(zip(_KEYS,values)):
            fields[key]={'raw':value,'normalized':value,'catalogue':value if key=='product_code' else None,
                         'bbox':[_COLUMNS[index]+5,y+12,_COLUMNS[index+1]-5,y+48],
                         'bbox_frame':'original_image','reason':'ตัวอย่างจำลองจากข้อความที่โปรแกรมสร้างเอง ไม่ใช่ผล OCR'}
        if row_number==1:
            fields['product_code']['normalized']=None
            fields['product_code']['reason']='ข้อมูลสาธิต: เว้นข้อเสนอรหัสไว้ให้ทดลองยืนยันในขั้นสุดท้าย ค่าดิบและทะเบียนยังแยกกัน'
            fields['product_code']['alternatives']=[{'value':values[0],'reason':'รหัสในทะเบียนจำลองที่ตรงข้อความบนภาพจำลอง'}]
        fields['invoice_date']={'raw':'2026-10-28','normalized':'2026-10-28','catalogue':None,
                                'bbox':[535,156,855,192],'bbox_frame':'original_image',
                                'reason':'วันที่เอกสารจำลอง ไม่ใช่วันที่รับของจริง'}
        rows.append({'id':f'demo-row-{row_number+1}','page_id':'demo-page-1','line_kind':'purchase',
                     'issues':['synthetic_demo_confirmation'] if row_number==1 else [],'fields':fields})
    return {'contract':'document-ai-proposals.v1','document_id':document['id'],'source_sha256':sha,
            'artifacts_root':str(path.parent),'pages':[{'id':'demo-page-1','number':1,'width':WIDTH,'height':HEIGHT,
                     'image_path':str(path),'sha256':hashlib.sha256(image).hexdigest()}],
            'rows':rows,'processing':{'mode':'synthetic_demo','recognition_performed':False,'model_calls':0,
                                      'page_origin':'same generated RGB as exact-hash source fixture'}}


def seed_demo(store, reviewer: str) -> list[dict]:
    inputs=store.root/'demo-inputs';inputs.mkdir(exist_ok=True)
    documents=[]
    for name,content,mime in [('DEMO_SYNTHETIC_INVOICE.png',sample_png(),'image/png'),
                              ('DEMO_SYNTHETIC_INVOICE.pdf',sample_pdf(),'application/pdf')]:
        (inputs/name).write_bytes(content)
        documents.append(store.ingest_source(name,content,mime,reviewer))
    return documents
