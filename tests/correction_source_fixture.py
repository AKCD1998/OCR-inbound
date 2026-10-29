"""Small synthetic source API for portable correction-policy unit tests.

This is a test double, not the frozen invoice parser or its unit dictionary.
It recognizes only labels and the BOX/SET units used in invented fixtures.
HQ evaluation always receives the independently pinned real helper modules.
No invoice text, private dictionaries, files, models, or production imports.
"""
from dataclasses import dataclass
import math
import re
from statistics import median
from types import SimpleNamespace


@dataclass(frozen=True)
class Token:
    id: str
    text: str
    box: tuple
    score: float | None
    engine: str
    reader: str

    @property
    def cx(self):return (self.box[0]+self.box[2])/2
    @property
    def cy(self):return (self.box[1]+self.box[3])/2
    @property
    def height(self):return self.box[3]-self.box[1]


LABELS={
    'supplier_code':('CODE','Material No.','รหัสสินค้า'),
    'description':('Description','Product Description'),
    'quantity':('QTY','Quantity'),
    'unit':('Unit','UOM'),
    'unit_price':('Price','Unit Price'),
    'amount':('Amount',),
}

def compact(text):return re.sub(r'[\s\W_]+','',text.upper())

LOOKUP={compact(label):role for role,labels in LABELS.items() for label in labels}

def role(text):return LOOKUP.get(compact(text))

def bbox(tokens):
    return [min(t.box[0] for t in tokens),min(t.box[1] for t in tokens),
            max(t.box[2] for t in tokens),max(t.box[3] for t in tokens)]

def read_tokens(rows,reader,size):
    tokens=[];rejected=[]
    for index,item in enumerate(rows):
        try:
            if not isinstance(item,dict):raise ValueError('not_token_object')
            if {'expected_raw','expected_normalized','reference_value','gold_value'}&set(item):
                raise ValueError('answer_annotation')
            engine=str(item.get('engine') or ('PADDLE_TH' if reader=='primary' else 'TESSERACT'))
            if engine.upper().startswith(('HUMAN','ASSISTANT','USER','SILVER','GOLD')):
                raise ValueError('non_machine_annotation')
            text=str(item.get('text') or '').strip();box=tuple(float(v) for v in item['box'])
            confidence=item.get('confidence',item.get('score'))
            confidence=float(confidence) if confidence is not None else None
            if (not text or len(box)!=4 or not all(math.isfinite(v) for v in box)
                    or not 0<=box[0]<box[2]<=size[0] or not 0<=box[1]<box[3]<=size[1]
                    or confidence is not None and (not math.isfinite(confidence) or not 0<=confidence<=1)):
                raise ValueError('invalid_geometry_or_confidence')
            tokens.append(Token(str(item.get('token_id') or 'synthetic:'+str(index)),text,box,confidence,engine,reader))
        except (KeyError,TypeError,ValueError,IndexError) as error:
            rejected.append({'reader':reader,'index':index,'reason':str(error)})
    by_id={}
    for token in tokens:by_id.setdefault(token.id,set()).add(token)
    ambiguous={key for key,values in by_id.items() if len(values)>1}
    return list(dict.fromkeys(t for t in tokens if t.id not in ambiguous)),rejected

def header_parts(tokens):
    parts=[(role(t.text),(t,)) for t in tokens if role(t.text)]
    short=[t for t in tokens if len(t.text)<25 and re.fullmatch(r'[A-Za-zก-๙.]+',t.text)]
    for a in short:
        for b in short:
            if a.id==b.id or a.reader!=b.reader or a.engine!=b.engine:continue
            horizontal=(0<=b.box[0]-a.box[2]<=max(a.height,b.height)*1.25
                        and abs(a.cy-b.cy)<=max(a.height,b.height)*.45)
            vertical=(0<=b.box[1]-a.box[3]<=max(a.height,b.height)*.7
                      and abs(a.cx-b.cx)<=max(a.box[2]-a.box[0],b.box[2]-b.box[0])*.5)
            if (horizontal or vertical) and role(a.text+' '+b.text):
                parts.append((role(a.text+' '+b.text),(a,b)))
    return parts

def header(tokens,size):
    """Minimal coherent-header test double for invented source fixtures."""
    parts=header_parts([t for t in tokens if t.cy<size[1]*.70])
    parts=[(r,g) for r,g in parts if not any({t.id for t in g}<{t.id for t in other} for _,other in parts)]
    candidates=[]
    for _,seed in parts:
        cy=median(t.cy for t in seed);height=max(t.height for t in seed)
        band=[(r,g) for r,g in parts if abs(median(t.cy for t in g)-cy)<=height*1.8]
        anchors={}
        for r,g in band:
            if r not in anchors or len(g)>len(anchors[r]):anchors[r]=g
        if {'description','quantity'}<=set(anchors) and len(anchors)>=3:
            words=list(dict.fromkeys(t for g in anchors.values() for t in g))
            candidates.append((len(anchors),-bbox(words)[1],{'anchors':anchors,'bbox':bbox(words)}))
    return max(candidates,key=lambda value:value[:2])[2] if candidates else None

def parse_literal_unit(text):
    """Only the unit literals of this synthetic fixture, without conversions."""
    if not isinstance(text,str) or not re.fullmatch(r'BOX(?:ES)?|SETS?',text,re.I):return None
    return {'unit_raw':text,'packing_raw':None,
            'set_unit_requires_nonadditive_guard':text.upper() in ('SET','SETS')}

core=SimpleNamespace(_read=read_tokens,_role=role,_bbox=bbox,_header_parts=header_parts,_header=header)
