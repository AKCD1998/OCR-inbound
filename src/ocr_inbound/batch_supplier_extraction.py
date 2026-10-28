"""Offline, evidence-preserving extraction for heterogeneous inbound scans.

This adapter does not approve product identities, receipt links, or KY9 rows.
The table's printed headers establish columns; product anchors establish bounded
blocks. Missing fields and text-only fallback remain explicitly reviewable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from difflib import SequenceMatcher
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path


CONTRACT_VERSION = "batch-supplier-extraction.v1"
_KEYS = {
    "row_index": ("NO", "ITEM", "ลำดับ", "ลำคับ"),
    "description": ("DESCRIPTION", "DESERIPTION", "DECRIPTION", "DESCRIPTON", "DESAIPTION", "DESCROTON", "DESCRCON", "DESARIPTION", "PEXCRATION", "DESCROTION", "DESCRPTION", "PRODUCT", "รายการสินค้า", "รายการซิน", "รายละเอียด", "รายละเอียค", "รายละเอี่ยอ", "รายละอัยค", "รายการ", "ราบการ", "ราอการสินต้ำ", "ราอการันด้า", "ชื่อสินค้า", "ช่อสินค้า", "ซื่อสินก้า", "ชื่อสินก้า", "ซื่อสินค้า"),
    "supplier_code": ("MATERIALNO", "MATENALNO", "MATERALNO", "MATERALNA", "MACRALO", "ITEMCODE", "PRODUCTCODE", "SKU", "CODE", "รหัสสินค้า", "รหัสสินก้า", "รหัส"),
    "quantity": ("QUANTITY", "QOMTITY", "QUANTTY", "QUANTIRY", "QUANHN", "QTY", "จำนวน", "เต็ม"),
    "unit": ("UOM", "PACKING", "UNIT", "หน่วยนับ", "หน่วยขาย", "หน่าย", "หน่วย"),
    "lot": ("BATCHNO", "BATCHTO", "LOTNO", "LOT", "เลขที่ผลิต", "เลขทีเล็ด", "เลขที่ผลิด"),
    "mfg_date": ("MFGDATE", "MFG", "วันที่ผลิต", "วันที่ผลิด"),
    "exp_date": ("EXPDATE", "EXP", "วันที่หมดอายุ"),
    "unit_price": ("UNITPRICE", "UNITPTRICE", "PRICE", "ราคาต่อหน่วย", "ราคาค่อหน่วย", "ราคาด่อหน่วย", "รากาต่อหน่วย", "ราคาขายไม่", "ราคา/หน่วย", "รากา/หน่วย", "ราคารวมภาษี"),
    "amount": ("TOTALAMOUNT", "NETAMOUNT", "AMOUNT", "AMEUNT", "JOTALAMOUNT", "TOTAL", "จำนวนเงินสุทธิ", "จำนวนเงิน", "จำนวนงิน", "จำนวนเวิน", "จำนวนเงิฐ", "ราการวมกาษ์", "รวม"),
}
_DATE_PATTERN = r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})"
_DATE_RE = re.compile(_DATE_PATTERN)
_LOT_RE = re.compile(r"\bL[O0]T(?=\b|E[\s.#:]|\d|[A-Z0-9]+/E[XKRYN]P)(?:E(?=[\s.#:]))?(?:\s+N[O0]\b\.?)?[.#:]?\s*[:#.]?\s*(.+?)(?=\s*[/;,]?\s*E[XKRYN]P\b|\s*MF(?:[GD])?\b|\s*QTY\b|$)", re.I)
_EXP_RE = re.compile(r"\bE[XKRYN]P\.?(?:\s*DATE\.?)?\s*[-:,.]?\s*(" + _DATE_PATTERN + r")", re.I)
_MFG_RE = re.compile(r"\bMF(?:[GD])?\.?(?:\s*DATE\.?)?\s*[-:.]?\s*(" + _DATE_PATTERN + r")", re.I)
_NUMBER_RE = re.compile(r"^[+-]?\d[\d,]*(?:\.\d+)?$")
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9./_$-]{1,29}$")
_THAI_MONTHS = {"มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6, "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12}


def _compact(value):
    return re.sub(r"[\s\W_]+", "", value.upper(), flags=re.UNICODE)


@dataclass(frozen=True)
class EvidenceToken:
    token_id: str
    text: str
    confidence: float | None
    box: tuple[float, float, float, float] | None
    engine: str = "PADDLE_TH"

    @property
    def cx(self):
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self):
        return (self.box[1] + self.box[3]) / 2


def _tokens(rows):
    result, rejected = [], []
    for index, row in enumerate(rows or []):
        text = str(row.get("text", "")).strip()
        poly = row.get("box") or row.get("poly")
        score = row.get("confidence", row.get("score"))
        if not text:
            continue
        if not poly or len(poly) < 4:
            rejected.append({"index": index, "text": text, "reason": "missing_geometry"})
            continue
        try:
            xs, ys = [float(p[0]) for p in poly], [float(p[1]) for p in poly]
            box = (min(xs), min(ys), max(xs), max(ys))
            if box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError("empty box")
            engine=str(row.get("engine") or "PADDLE_TH")
            token_id=str(row.get("token_id") or f"{'paddle' if engine=='PADDLE_TH' else engine.lower()}:{index}")
            result.append(EvidenceToken(token_id, text, float(score) if score is not None else None, box, engine))
        except (TypeError, ValueError, IndexError):
            rejected.append({"index": index, "text": text, "reason": "invalid_geometry"})
    return result, rejected


def _field(tokens, value=None, *, raw=None, flags=()):
    if not tokens:
        return None
    ordered = sorted(tokens, key=lambda t: (t.cy if t.box else 0, t.cx if t.box else 0))
    text = raw if raw is not None else " ".join(t.text for t in ordered)
    boxes = [t.box for t in ordered if t.box]
    bbox = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None
    scores = [t.confidence for t in ordered if t.confidence is not None]
    provenance_flags=list(flags)
    if any(t.engine.startswith("ASSISTANT_VISUAL") for t in ordered):
        provenance_flags.append("assistant_visual_annotation_requires_human_review")
    return {"raw_value": text, "normalized_value": text if value is None else value,
            "bbox": bbox, "confidence": min(scores) if scores else None,
            "engine": ordered[0].engine if len({t.engine for t in ordered})==1 else "MIXED_OCR",
            "engines": sorted({t.engine for t in ordered}), "token_ids": [t.token_id for t in ordered],
            "review_flags": list(dict.fromkeys(provenance_flags)),
            "source_spans": [{"token_id": t.token_id, "raw_text": t.text, "bbox": list(t.box) if t.box else None, "confidence": t.confidence,"engine":t.engine} for t in ordered]}


def _number(text):
    value = text.strip()
    if not _NUMBER_RE.fullmatch(value):
        return None
    return value.replace(",", "")


def _date_field(token, raw):
    field = _field([token], raw, raw=raw)
    parts = re.split(r"[-/.]", raw)
    if len(parts) == 3:
        if len(parts[0]) == 4:
            year, month, day = map(int, parts)
            convention = "year_month_day"
        else:
            day, month, year = map(int, parts)
            convention = "day_month_year"
        if year < 100:
            field["normalized_value"] = None
            field["review_flags"].append("two_digit_year_unresolved")
        else:
            calendar = "buddhist" if year > 2400 else "gregorian"
            if calendar == "buddhist":
                year -= 543
            try:
                field["normalized_value"] = date(year, month, day).isoformat()
            except ValueError:
                field["normalized_value"] = None
                field["review_flags"].append("invalid_calendar_date")
            field["date_calendar"] = calendar
        field["date_order"] = convention
    return field


def _lines(tokens, tolerance=None):
    if not tokens:
        return []
    tolerance = tolerance or max(8, statistics.median(t.box[3] - t.box[1] for t in tokens) * .55)
    lines = []
    for token in sorted(tokens, key=lambda t: (t.cy, t.cx)):
        if lines and abs(token.cy - statistics.median(t.cy for t in lines[-1])) <= tolerance:
            lines[-1].append(token)
        else:
            lines.append([token])
    return [sorted(line, key=lambda t: t.cx) for line in lines]


@lru_cache(maxsize=16384)
def _header_key(text):
    compact = _compact(text)
    if "DESCRIPTION" in compact:
        return "description"
    if any(_compact(word) in compact for word in _KEYS["description"] if len(word)>=4 and re.search(r"[ก-๙]",word)):
        return "description"
    if compact in {_compact("หน่วยละ"),_compact("หน่ายละ"),_compact("ราคา"),_compact("ราคา/หน่วย"),_compact("ราคา/หน่าย")}:
        return "unit_price"
    if compact==_compact("มูลค่า"):
        return "amount"
    # An imperfect PRICE label must not become the shorter UNIT role.
    if re.match(r"^UN[I1T]{1,2}",compact) and SequenceMatcher(None,compact[:9],"UNITPRICE").ratio()>=.70:
        return "unit_price"
    # Long terms must win over UNIT, DATE, AMOUNT and other substrings.
    hits = []
    for key, words in _KEYS.items():
        for word in words:
            needle = _compact(word)
            if key=="row_index" and compact!=needle:
                continue
            if key=="quantity" and needle==_compact("จำนวน") and compact!=needle:
                continue
            if needle and (compact == needle or (len(needle) >= 4 and needle in compact)):
                hits.append((len(needle), key))
    if not hits:
        # OCR spelling variants are a header hypothesis only. The caller
        # still requires a multi-column, spatially spread printed header.
        # Fuzzy role selection is exposed as a review flag, never a text edit.
        if 5<=len(compact)<=24 and re.fullmatch(r"[A-Z]+",compact):
            canonical={"description":"DESCRIPTION","supplier_code":"MATERIALNO","quantity":"QUANTITY","unit_price":"UNITPRICE","amount":"TOTALAMOUNT","lot":"BATCHNO"}
            scored=[(SequenceMatcher(None,compact,label).ratio(),key) for key,label in canonical.items()]
            score,key=max(scored)
            if score>=.68:
                return key
        return None
    return max(hits)[1]


def _header(tokens, height):
    candidates = []
    median_height = statistics.median(t.box[3] - t.box[1] for t in tokens) if tokens else 30
    for seed in tokens:
        if seed.cy > height * .7:
            continue
        band = [t for t in tokens if abs(t.cy - seed.cy) <= median_height * 1.0]
        fields = {}
        for t in band:
            key = _header_key(t.text)
            if key:
                fields.setdefault(key, []).append(t)
        # These observed short OCR variants are unsafe global aliases.
        # Require all three actual Woothi-style printed header roles in
        # the same spatial band before considering their missing roles.
        compact_band={_compact(t.text) for t in band}
        if "SKU" in compact_band and compact_band & {"PRODUCT","PROOUCT"} and "TOTAL" in compact_band:
            for t in band:
                role={"OY":"quantity","ON":"quantity","UNT":"unit","UAT":"unit","PROOUCT":"description",
                      "PPICE":"unit_price","PRRCE":"unit_price"}.get(_compact(t.text))
                if role:
                    fields.setdefault(role,[]).append(t)
        if {"description","supplier_code","quantity","unit_price","amount"}<=fields.keys():
            for t in band:
                if _compact(t.text)=="UON":
                    fields.setdefault("unit",[]).append(t)
        if "description" not in fields or len(fields) < 3 or not ({"quantity", "supplier_code", "lot"} & fields.keys()):
            continue
        # A table header must span columns and not merely be a sentence.
        if max(t.cx for v in fields.values() for t in v) - min(t.cx for v in fields.values() for t in v) < height * .15:
            continue
        score = len(fields) + ("quantity" in fields) + ("unit_price" in fields) + ("amount" in fields)
        candidates.append((score, seed.cy, fields))
    if not candidates:
        return None
    _, _, fields = max(candidates, key=lambda c: (c[0], c[1]))
    anchors = {}
    for key, group in fields.items():
        # Prefer English labels when both languages are present; duplicate
        # price columns are kept separate until the exclusion label resolves it.
        preferred = [t for t in group if re.search(r"[A-Za-z]", t.text)] or group
        if key == "unit_price" and len(preferred) > 1:
            exclusion = [t for t in preferred if re.search(r"EX[CL]|ไม่รวม", t.text, re.I)]
            chosen = max(exclusion or preferred, key=lambda t: t.cx)
        elif key == "amount":
            chosen = max(group, key=lambda t: t.cx)
        elif key == "row_index":
            no_label=[t for t in preferred if re.fullmatch(r"N[O0]\.?",t.text.strip(),re.I)]
            chosen=min(no_label or preferred,key=lambda t:t.cx)
        else:
            chosen = max(preferred, key=lambda t: len(_compact(t.text)))
        anchors[key] = chosen
    ordered = sorted(anchors, key=lambda key: anchors[key].cx)
    bounds = {}
    for i, key in enumerate(ordered):
        left = (anchors[ordered[i-1]].cx + anchors[key].cx) / 2 if i else -1
        right = (anchors[key].cx + anchors[ordered[i+1]].cx) / 2 if i + 1 < len(ordered) else float("inf")
        bounds[key] = [left, right]
    # Descriptions are left aligned under a centered header. A preceding
    # code header constrains their left edge better than the center midpoint.
    if "supplier_code" in anchors and ordered.index("description")>0 and ordered[ordered.index("description")-1]=="supplier_code":
        edge = anchors["supplier_code"].box[2] + median_height * .3
        bounds["supplier_code"][1] = edge
        bounds["description"][0] = edge
    elif "supplier_code" not in anchors and "unit" not in anchors and ordered.index("description")>0 and ordered[ordered.index("description")-1]=="quantity":
        edge=anchors["quantity"].box[2]+median_height*.3
        bounds["quantity"][1]=edge
        bounds["description"][0]=edge
    selected = [t for group in fields.values() for t in group]
    approximate=[]
    for key,token in anchors.items():
        raw=_compact(token.text)
        if not any(_compact(word)==raw or (len(_compact(word))>=4 and _compact(word) in raw) for word in _KEYS[key]):
            approximate.append(key)
    return {"anchors": anchors, "bounds": bounds, "bottom": max(t.box[3] for t in selected), "tokens": selected, "median_height": median_height,"approximate_header_roles":approximate}


def _supplier(tokens, height):
    top = [t for t in tokens if t.cy < height * .20]
    joined = " ".join(t.text for t in top)
    identities = (("dksh", r"\bDKSH\b"), ("diethelm_keller_logistics", r"Diethelm\s+Keller"),
                  ("zuellig", r"ZUELLIG|ซิลลิ[กคดส]|ชิอลิก"), ("woothi", r"WOOTHI|วุฒิ\s*อินเตอร์"),
                  ("berlin", r"BERLIN|เบอร์ลิน"), ("anb", r"A\.N\.B\.|เอ\.เอ็นบี"),
                  ("bangkok_drug", r"BANGKOK\s*DRUG|บางกอก\s*ดรัก"), ("t_man", r"T\.MAN|ที\.แมน"),
                  ("thepprathanporn", r"เทพประทานพร"), ("macrophar", r"MacroPhar|แมคโครฟาร์"),
                  ("bl_hua", r"B\.L\.HUA|BLHUA"), ("pks_medical", r"P\.K\.S\.\s*MEDICAL"),
                  ("kmp", r"เค\.เอ็ม\.พี|K\.?M\.?P"), ("community_pharmacy",r"ชุมชนเภสัชกรรม"), ("tnp",r"ที[่]?\.?\s*เอ็น\s*พี\s*เฮลท์|T\.?N\.?P\.?\s*HEALTH"), ("longmed",r"ลองเมด|LONGMED"), ("yuwell",r"YUWE[L1]|ยูเวล"), ("dch_auriga",r"DCH\s*AURIGA|ดีซีเอช\s*ออริกา"), ("greater_mybacin",r"GREATER\s+MYBACIN"))
    for key, pattern in identities:
        hit = next((t for t in top if re.search(pattern, t.text, re.I)), None)
        if hit:
            return {"key": key, "evidence": _field([hit]), "identity_status": "ocr_candidate"}
    company = next((t for t in top if "บริษัท" in t.text and "เอสซี" not in t.text), None)
    return {"key": "unrecognized", "evidence": _field([company]) if company else None, "identity_status": "unrecognized"}


def _label_value(tokens, pattern, value_pattern, *, max_y):
    found = []
    for label in tokens:
        if label.cy > max_y:
            continue
        match = re.search(pattern, label.text, re.I)
        if not match:
            continue
        rest = label.text[match.end():].strip(" :#./")
        inline = re.search(value_pattern, rest, re.I)
        if inline:
            found.append((label, inline.group(0), "inline_label"))
            continue
        row_height = max(15, label.box[3] - label.box[1])
        options = []
        for value in tokens:
            if value is label or value.cy > max_y:
                continue
            vmatch = re.fullmatch(value_pattern, value.text.strip(), re.I)
            if not vmatch:
                continue
            same_line = abs(value.cy - label.cy) < row_height * .8 and value.box[0] >= label.box[2] - row_height * .3
            below = 0 < value.cy - label.cy < row_height * 2.6 and abs(value.cx - label.cx) < max(label.box[2]-label.box[0], value.box[2]-value.box[0]) * 2.2
            if same_line or below:
                distance = abs(value.cy-label.cy) * 3 + abs(value.cx-label.cx)
                options.append((distance, value))
        if options:
            _, value = min(options, key=lambda pair: pair[0])
            found.append((value, value.text.strip(), "label_neighbor"))
    # Identical repeated labels count as corroboration, not conflicts.
    unique = {}
    for token, value, relation in found:
        unique.setdefault(value, []).append((token, relation))
    return [{"value": value, "evidence": _field([pair[0] for pair in evidence], value), "relation": evidence[0][1]} for value, evidence in unique.items()]


def _document(tokens, supplier, header, height):
    max_y = header["bottom"] if header else height * .44
    invoice_pattern = r"(?:BILL\s*NO\.?|TAX\s*INVOICE/INVOICE\s*NO\.?|INV\.?(?:\s*NO\.?|[#*])|เลขที่เอกสาร|(?:เลขที่|เอชที่|เละที่)\s*/\s*I[nm][vns][.#*]?(?:\s*No\.?)?)"
    inv = _label_value(tokens, invoice_pattern, r"[A-Za-z0-9][A-Za-z0-9/-]{5,25}", max_y=max_y)
    # Thai-only 'เลขที่' is admissible only for documents with a nearby title;
    # an unqualified bare number is never collected as an invoice by fallback.
    if not inv:
        inv = _label_value(tokens, r"^เลขที่$", r"[A-Za-z0-9][A-Za-z0-9/-]{5,25}", max_y=max_y * .8)
    date_tokens = [t for t in tokens if not re.search(r"DUE\s*DATE|Effective\s*Date|ครบกำหนด",t.text,re.I)]
    dates = _label_value(date_tokens, r"(?:วันที่เอกสาร|วันที่ออกเอกสาร|/\s*Date|^DATE$|^วันที่$)", _DATE_PATTERN, max_y=max_y)
    metadata_crosschecks=[]
    if supplier["key"]=="zuellig" and len(inv)==1:
        # A payment stub is an independent repeated printing on the SAME
        # scan, and is accepted only after its explicit invoice reference
        # agrees with the header. A disagreement is retained, never repaired.
        repeats=_label_value(tokens,r"เลขที่บิล",r"[A-Za-z0-9][A-Za-z0-9/-]{5,25}",max_y=height)
        if any(item["value"]==inv[0]["value"] for item in repeats):
            stub_dates=_label_value(tokens,r"ลงวันที่",_DATE_PATTERN,max_y=height)
            dates.extend(stub_dates)
            metadata_crosschecks.append({"type":"payment_stub_repeated_invoice","invoice_references":repeats,"date_candidates":stub_dates,"basis":"explicit_matching_invoice_reference_on_same_source_image"})
    date_values = []
    for candidate in dates:
        token_id = candidate["evidence"]["token_ids"][0]
        token = next(t for t in tokens if t.token_id == token_id)
        date_values.append(_date_field(token, candidate["value"]))
    # Written Thai month dates are explicit, four-digit Buddhist years.
    for token in tokens:
        if token.cy > max_y:
            continue
        match = re.fullmatch(r"\s*(\d{1,2})\s+(" + "|".join(_THAI_MONTHS) + r")\s+(\d{4})\s*", token.text)
        if match:
            day, month, year = int(match[1]), _THAI_MONTHS[match[2]], int(match[3])
            try:
                norm = date(year-543 if year>2400 else year, month, day).isoformat()
            except ValueError:
                norm = None
            field = _field([token], norm)
            if norm is None:
                field["normalized_value"] = None
                field["review_flags"].append("invalid_calendar_date")
            date_values.append(field)
    printed = []
    for token in tokens:
        if token.cy > height * .25:
            continue
        match = re.search(r"(?:PAGE|PIGE|หน้าที่|หน้า)\s*[:/]?\s*(\d+)\s*/\s*(\d+)", token.text, re.I)
        if match:
            printed.append(_field([token], {"page": int(match[1]), "pages": int(match[2])}))
    if not printed:
        neighboring=_label_value(tokens,r"(?:\bPAGE\b|\bPIGE\b|หน้าที่|หน้า)\s*[:/]?\s*$",r"\d+\s*/\s*\d+",max_y=height*.25)
        for item in neighboring:
            first,last=map(int,item["value"].split("/"))
            field=item["evidence"]
            field["normalized_value"]={"page":first,"pages":last}
            printed.append(field)
    kinds = " ".join(t.text for t in tokens if t.cy < max_y)
    credit_variant=any(SequenceMatcher(None,re.sub(r"[^A-Z]","",t.text.upper()),"COPYCREDITNOTE").ratio()>=.75 for t in tokens if t.cy<max_y and re.search(r"NOTE|NOSE",t.text,re.I))
    credit_marker=bool(re.search(r"CREDIT\s*NOTE|ลดหนี้|ลอหนี้|อดหนี้|ลลหนี้",kinds,re.I))
    tax_dates=sum(len(_DATE_RE.findall(t.text)) for t in tokens)
    tax_ids=sum(bool(re.fullmatch(r"\d{13}",re.sub(r"[\s-]","",t.text))) for t in tokens)
    tax_period_header=any(t.cy<height*.12 and "ภาษ" in t.text and "/" in t.text for t in tokens)
    tax_structure=tax_dates>=10 and tax_ids>=6 and tax_period_header and not any(_LOT_RE.search(t.text) for t in tokens)
    tax_title_variant=any(t.cy<height*.2 and "รายงานภา" in t.text for t in tokens)
    # Barcodes and many expiry dates also occur on normal long invoices.
    # Those structural counts alone must never suppress merchandise rows.
    kind = "purchase_vat_report" if re.search(r"รายงานภาษีซื้อ|PURCHASE\s*(?:VAT|TAX)\s*REPORT", kinds, re.I) else "tax_register_report" if tax_title_variant else "credit_note" if credit_marker or credit_variant else "invoice_or_delivery" if re.search(r"INVOICE|ใบกำกับภาษี|ใบส่งของ", kinds, re.I) else "unclassified"
    flags = []
    if credit_variant and not re.search(r"CREDIT\s*NOTE|ใบลดหนี้",kinds,re.I):
        flags.append("document_type_ocr_variant_requires_review")
    if kind=="tax_register_report":
        flags.append("tax_register_type_requires_source_review")
    if len(inv) != 1:
        flags.append("invoice_number_missing" if not inv else "invoice_number_conflict")
    normalized_dates = {f["normalized_value"] for f in date_values if f["normalized_value"]}
    if len(normalized_dates) > 1:
        flags.append("invoice_date_conflict")
    if not date_values:
        flags.append("invoice_date_missing")
    elif not normalized_dates:
        flags.append("invoice_date_unresolved")
    return {"supplier": supplier, "document_type": kind,
            "invoice_number": inv[0]["evidence"] if len(inv) == 1 else None,
            "invoice_number_candidates": inv, "invoice_date": date_values[0] if len(date_values)==1 or len(normalized_dates)==1 else None,
            "invoice_date_candidates": date_values, "printed_page": printed[0] if len(printed)==1 else None,
            "metadata_crosschecks":metadata_crosschecks,"tax_register_structure":{"date_occurrences":tax_dates,"thirteen_digit_identifier_tokens":tax_ids,"period_header_detected":tax_period_header,"report_title_variant":tax_title_variant},"review_flags": flags}


def _column(token, header):
    # Tokens spanning the printed code and description are not sliced into
    # invented bounding boxes. They are split textually with a shared bbox.
    for key, (left, right) in header["bounds"].items():
        if left <= token.cx < right:
            return key
    return None


def _plain_description(text):
    return (bool(re.search(r"[A-Za-zก-๙]", text)) and not (_LOT_RE.search(text) or _EXP_RE.search(text) or _MFG_RE.search(text)) and not re.search(r"(?:CAT\.?\s*[NH][O0]|E[XKR]P\s*[.,:]|\bMF[GD]\b|\bQTY\s*[:.]|^รวม|TOTAL|หมายเหตุ|VAT|สั่งซื้อ|จำนวนรายการ|SUB\s*TOTAL|E\.\s*&\s*O\.E|ผิด\s*ตก|LESS CASH|FORM NO|PAGE NO|EFF[A-Z]*\s*D[AU]TE|INTERNAL USE|https?://|dksh\.\s*com|ชำระ|ธนาคาร|บัญชี|CHEQUE|PAYMENT|^FM[-_/]|บาท(?:ถ้วน|ล้วน)|ไม่รับ.*(?:เปล|คืน|ทืน))", text, re.I)
            and not _DATE_RE.fullmatch(text.strip()))


def _split_code_description(text):
    # Numeric/hyphen supplier codes observed in the Thepprathanporn layout
    # can be glued directly to Thai product text, without an OCR space.
    match=re.fullmatch(r"(\d[\d-]{3,19}\d)\s*[-:;()]?\s*([A-Za-zก-๙].+)",text)
    if not match:
        match=re.fullmatch(r"(\d[\d-]{5,19}\d)\s+(.+)",text)
    return (match[1],match[2]) if match and _plain_description(match[2]) else None


def _split_quantity_unit_description(text):
    match=re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s+(PCS|BOX|PACK|PAC|SET|TUB|TUBE|BTL|BT|EA)[.\s-]+(.+)",text,re.I)
    return (match[1],match[2],match[3]) if match and _plain_description(match[3]) else None


def _leading_quantity_inline_lot(text):
    match=re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s+(.{8,}?)\s*[(]?\s*LOT\s*[:#].+",text,re.I)
    return (match[1],match[2].rstrip()) if match and _plain_description(match[2]) else None


def _unreadable_merged_description(line,header):
    if not {"supplier_code","description","quantity","unit_price","amount"}<=header["anchors"].keys():
        return []
    if not all(any(_column(t,header)==key and re.fullmatch(r"\d[\d,.]{2,}",t.text) for t in line) for key in ("unit_price","amount")):
        return []
    return [t for t in line if t.box[0]<header["bounds"]["supplier_code"][1] and t.box[2]>header["bounds"]["description"][0] and re.fullmatch(r"\d[\d,./ -]*",t.text)]


def _row_fields(block, anchor_line, header, supplier):
    fields = {key: None for key in ("supplier_code", "description", "quantity", "unit", "lot", "mfg_date", "exp_date", "unit_price", "amount")}
    flags, links = [], []
    bycol = {}
    for t in anchor_line:
        bycol.setdefault(_column(t, header), []).append(t)
    descriptions = [t for t in bycol.get("description", []) if _plain_description(t.text)]
    codes = [t for t in bycol.get("supplier_code", []) if _CODE_RE.fullmatch(t.text.strip()) and len(t.text.strip())>=3]
    combined_code_header="supplier_code" in header["anchors"] and bool(re.search(r"ลำ[ดค]ับ",header["anchors"]["supplier_code"].text))
    if combined_code_header:
        for token in bycol.get("supplier_code",[]):
            match=re.fullmatch(r"\d{1,3}\s+([A-Za-z0-9][A-Za-z0-9./_$-]{2,29})",token.text)
            if match:
                fields["supplier_code"]=_field([token],match[1],raw=match[1],flags=["row_index_supplier_code_shared_detection"])
                flags.append("row_index_supplier_code_shared_detection")
                break
    # Zuellig and a few generic layouts merge item code + description in a
    # single OCR detection. Only an explicit numeric prefix is split.
    for token in anchor_line:
        if "supplier_code" not in header["anchors"] and not re.search(r"รหัส",header["anchors"]["description"].text):
            continue
        if token.box[0] < header["anchors"]["description"].cx and token.box[2] > header["bounds"]["description"][0]:
            match = _split_code_description(token.text)
            if match:
                fields["supplier_code"] = _field([token], match[0], raw=match[0], flags=["shared_detection_bbox"])
                fields["description"] = _field([token], match[1].strip(), raw=match[1].strip(), flags=["shared_detection_bbox"])
                descriptions = [t for t in descriptions if t is not token]
                flags.append("code_description_shared_detection")
                break
    if fields["supplier_code"] is None and codes:
        fields["supplier_code"] = _field(codes, "".join(t.text.strip() for t in sorted(codes, key=lambda t:t.cx)))
        if len(codes)>1:
            fields["supplier_code"]["review_flags"].append("code_fragment_join")
        if any(re.search(r"[$_]",token.text) for token in codes):
            fields["supplier_code"]["review_flags"].append("supplier_code_nonstandard_glyph_requires_review")
    if fields["description"] is None and descriptions:
        fields["description"] = _field(descriptions)
    if "quantity" in header["anchors"] and header["anchors"]["quantity"].cx<header["anchors"]["description"].cx:
        for token in anchor_line:
            fused=_split_quantity_unit_description(token.text)
            inline=_leading_quantity_inline_lot(token.text)
            if fused and token.box[0]<header["bounds"]["quantity"][1] and token.box[2]>header["bounds"]["quantity"][1]:
                fields["quantity"]=_field([token],fused[0],raw=fused[0],flags=["shared_quantity_unit_description_detection"])
                fields["unit"]=_field([token],fused[1],raw=fused[1],flags=["shared_quantity_unit_description_detection"])
                fields["description"]=_field([token],fused[2],raw=fused[2],flags=["shared_quantity_unit_description_detection"])
                flags.append("shared_quantity_unit_description_detection")
                break
            if inline and token.box[0]<header["bounds"]["quantity"][1] and token.box[2]>header["bounds"]["quantity"][1]:
                fields["quantity"]=_field([token],inline[0],raw=inline[0],flags=["shared_inline_lot_product_detection"])
                fields["description"]=_field([token],inline[1],raw=inline[1],flags=["shared_inline_lot_product_detection","unit_name_boundary_unresolved"])
                flags.extend(["shared_inline_lot_product_detection","unit_name_boundary_unresolved"])
                break
    # A description continuation is accepted only inside this product block
    # and within the description column, before the explicit lot/date line.
    continuations=[]
    anchor_y=statistics.median(t.cy for t in anchor_line)
    for line in _lines([t for t in block if t not in anchor_line]):
        if statistics.median(t.cy for t in line)>anchor_y+header["median_height"]*2.5:
            break
        if any(_LOT_RE.search(t.text) or _EXP_RE.search(t.text) for t in line):
            break
        extras = [t for t in line if _column(t, header)=="description" and _plain_description(t.text)]
        if extras and fields["description"] and not any(_number(t.text) for t in line if _column(t, header)=="quantity"):
            if descriptions:
                continuations.extend(extras)
                fields["description"] = _field(descriptions+continuations)
                flags.append("description_multiline_candidate")
    for key in ("quantity", "unit_price", "amount"):
        numeric = [t for t in bycol.get(key, []) if _number(t.text) is not None]
        # Multiple printed price/discount columns may sit inside a broad
        # generic interval. Keep only cells aligned with this actual header.
        if key in {"unit_price","amount"} and numeric:
            numeric = [t for t in numeric if t.box[3]-t.box[1] >= header["median_height"]*.65]
            anchor = header["anchors"][key]
            max_distance=max((anchor.box[2]-anchor.box[0])*1.2,header["median_height"]*2.2)
            numeric = [t for t in numeric if abs(t.cx-anchor.cx)<=max_distance]
        if key in {"unit_price","amount"} and numeric:
            anchor = header["anchors"][key]
            distances = [abs(t.cx-anchor.cx) for t in numeric]
            nearest = min(distances)
            numeric = [t for t,distance in zip(numeric,distances) if distance <= nearest + header["median_height"]*.8]
        if len(numeric)==1:
            fields[key] = _field(numeric, _number(numeric[0].text))
        elif len(numeric)>1:
            flags.append(f"{key}_multiple_candidates")
        malformed=[t for t in bycol.get(key,[]) if re.fullmatch(r"[\d.,]+",t.text) and _number(t.text) is None]
        if malformed:
            flags.append(f"{key}_malformed_numeric_ocr")
            candidates=[]
            for token in malformed:
                candidate=_field([token])
                if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+[.,]\d{2}",token.text):
                    candidate["proposed_normalized_value"]=re.sub(r"[.,]","",token.text[:-3])+"."+token.text[-2:]
                    candidate["interpretation_status"]="grouping_separator_requires_source_review"
                candidates.append(candidate)
            links.append({"type":f"{key}_unparsed_numeric_evidence","candidates":candidates})
    units = [t for t in bycol.get("unit", []) if re.search(r"[A-Za-zก-๙]", t.text) and not re.search(r"\bVAT\b",t.text,re.I)]
    if units:
        fields["unit"] = _field(units)
    elif "unit" not in header["anchors"]:
        unit_tokens=[t for t in block if _column(t,header)=="quantity" and re.fullmatch(r"BOX|PACK|PCS|BTL|TUBE|กล่อง|ขวด|แผง|หลอด|ชิ้น|โหล",t.text,re.I)]
        if len(unit_tokens)==1:
            fields["unit"]=_field(unit_tokens,flags=["unit_below_quantity_without_separate_column"])
    # Quantity+unit may be joined by OCR, e.g. '5กล่อง'. The shared source
    # polygon is retained intact and never claimed to locate a substring.
    if not fields["quantity"]:
        for token in anchor_line:
            if _column(token,header) in {"quantity","unit"}:
                match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([A-Za-zก-๙]+)(?:\s*\[(\d+)\])?", token.text)
                if match and (re.search(r"[ก-๙]",match[2]) or match[2].upper() in {"PCS","BOX","PACK","PAC","SET","TUB","TUBE","BTL","BT","EA","BOTTLE"}):
                    fields["quantity"] = _field([token], match[1], raw=match[1], flags=["shared_detection_bbox"])
                    fields["unit"] = _field([token], match[2], raw=match[2], flags=["shared_detection_bbox"])
                    flags.append("quantity_unit_shared_detection")
                    if match[3]:
                        links.append({"type":"printed_unit_bracket_annotation","evidence":_field([token],match[3],raw=match[3],flags=["shared_detection_bbox"]),"may_multiply_quantity":False,"interpretation_status":"printed_pack_annotation_requires_review"})
    explicit_qty=[(token,match) for token in block if (match:=re.search(r"\bQTY\s*[:.]\s*(\d+(?:\.\d+)?)",token.text,re.I))]
    if not fields["quantity"] and len(explicit_qty)==1:
        token,match=explicit_qty[0]
        fields["quantity"]=_field([token],match[1],raw=match[1],flags=["quantity_from_literal_qty_marker"])
        flags.append("quantity_from_literal_qty_marker")
    if "unit" not in header["anchors"] and not fields["unit"]:
        standalone_units=[token for token in anchor_line if re.fullmatch(r"BOX|PACK|PCS|BTL|TUBE|กล่อง|ขวด|แผง|หลอด|ชิ้น|โหล",token.text,re.I)]
        if len(standalone_units)==1:
            fields["unit"]=_field(standalone_units,flags=["literal_standalone_unit_without_header"])
            if fields["description"] and standalone_units[0] in descriptions:
                descriptions=[token for token in descriptions if token not in standalone_units]
                if descriptions:fields["description"]=_field(descriptions)
    lot_candidates, mfg_candidates, exp_candidates = [], [], []
    for token in block:
        lot = _LOT_RE.search(token.text)
        tman_lot = re.search(r"(?:L/C\s*NO\.?|C\s*NO\.?)\s*[:.]?\s*([A-Za-z0-9/-]+)",token.text,re.I) if supplier=="t_man" and _MFG_RE.search(token.text) and _EXP_RE.search(token.text) else None
        if not lot and tman_lot:
            lot_candidates.append(_field([token],tman_lot[1],raw=tman_lot[1],flags=["supplier_l_c_no_lot_label"]))
        if lot:
            value = lot[1].strip(" ()/:;.,")
            if value and not re.search(r"\s", value):
                lot_candidates.append(_field([token], value, raw=value))
                prefix = re.match(r"^\s*(\d{1,4}(?:\.\d+)?)\s+L[O0]T", token.text, re.I)
                if prefix:
                    links.append({"type":"printed_lot_quantity", "quantity":_field([token], prefix[1], raw=prefix[1]), "lot_token_id":token.token_id})
                elif re.match(r"^\s*\d+\s+L[O0]T",token.text,re.I):
                    links.append({"type":"unclassified_numeric_prefix_before_lot","evidence":_field([token]),"association_verified":False})
                    flags.append("lot_line_numeric_prefix_semantics_unresolved")
            else:
                flags.append("lot_text_ambiguous")
        for regex, candidates in ((_EXP_RE, exp_candidates), (_MFG_RE,mfg_candidates)):
            match = regex.search(token.text)
            if match:
                candidates.append(_date_field(token,match[1]))
        col = _column(token,header)
        if col=="lot" and supplier in {"dksh","diethelm_keller_logistics"} and token.cx < header["anchors"]["lot"].box[0]-header["median_height"]*.8:
            continue
        if col in {"lot","mfg_date","exp_date"}:
            if col=="lot" and supplier in {"dksh","diethelm_keller_logistics"} and token not in anchor_line and re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2,4}",token.text.strip()):
                lot_candidates.append(_field([token],token.text.strip(),flags=["date_shaped_printed_batch_identifier_requires_review"]))
            elif col=="lot" and not lot and _CODE_RE.fullmatch(token.text.strip()) and not _number(token.text.strip()) is None and "." not in token.text:
                # DKSH prints reference price (@ 64.20) then batch on a
                # second line under Batch No. Decimals and '@' are not lots.
                if not (supplier=="dksh" and token in anchor_line):
                    lot_candidates.append(_field([token],token.text.strip()))
            elif col=="lot" and not lot and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/-]{2,}",token.text) and not _DATE_RE.fullmatch(token.text) and "@" not in token.text:
                lot_candidates.append(_field([token],token.text.strip()))
            elif col in {"mfg_date","exp_date"} and _DATE_RE.fullmatch(token.text.strip()):
                (mfg_candidates if col=="mfg_date" else exp_candidates).append(_date_field(token,token.text.strip()))
    for key, candidates in (("lot",lot_candidates),("mfg_date",mfg_candidates),("exp_date",exp_candidates)):
        unique = {c["raw_value"]:c for c in candidates}
        if len(unique)==1:
            fields[key] = next(iter(unique.values()))
        elif len(unique)>1:
            flags.append(f"{key}_multiple_candidates")
            links.append({"type":f"{key}_candidates", "candidates":list(unique.values())})
    # Greater's explicit QUANTITY & PACKING cell gives a count followed by
    # pack contents. Do not turn the contents (ML/TABS/etc.) into sale units
    # or multiply them into a base quantity. Lot/M./E. are printed together
    # on one bounded subline; its two-digit years remain unresolved.
    if supplier=="greater_mybacin":
        quantity_tokens=[token for token in bycol.get("quantity",[]) if re.match(r"^\s*\d+\s*[X×]",token.text,re.I)]
        if len(quantity_tokens)==1:
            token=quantity_tokens[0]
            match=re.fullmatch(r"\s*(\d+)\s*[X×]\s*(.+)",token.text,re.I)
            if match:
                fields["quantity"]=_field([token],match[1],raw=match[1],flags=["combined_quantity_and_packing_cell"])
                fields["packing"]=_field([token],match[2],raw=match[2],flags=["combined_quantity_and_packing_cell","packing_not_sale_unit"])
                links.append({"type":"printed_quantity_and_packing","quantity":fields["quantity"],"packing":fields["packing"],"may_multiply_quantity":False,"sale_unit_explicit":False})
        batch_lines=[]
        for token in block:
            match=re.search(r"\bLot[.:]\s*([A-Za-z0-9-]+)\s*\(\d+\)\s*M[.]\s*("+_DATE_PATTERN+r")\s*E[.]\s*("+_DATE_PATTERN+r")",token.text,re.I)
            if match:batch_lines.append((token,match))
        if len(batch_lines)==1:
            token,match=batch_lines[0]
            fields["lot"]=_field([token],match[1],raw=match[1],flags=["supplier_printed_lot_m_e_subline"])
            fields["mfg_date"]=_date_field(token,match[2])
            fields["exp_date"]=_date_field(token,match[3])
    if supplier in {"dksh","diethelm_keller_logistics"} and len({item["raw_value"] for item in lot_candidates})>1:
        split_lines=[]
        for line in _lines(block,header["median_height"]*.6):
            pairs=[t for t in line if re.fullmatch(r"\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?",t.text.strip())]
            ids={t.token_id for t in line}
            batches=[candidate for candidate in lot_candidates if ids.intersection(candidate["token_ids"])]
            expiries=[t for t in line if re.search(r"E[XKR]P\s*[:,.]",t.text,re.I)]
            if len(pairs)==1 and len(batches)==1:
                first,second=re.split(r"\s*/\s*",pairs[0].text.strip())
                split_lines.append({"printed_quantity_pair":_field(pairs,{"first_component":first,"second_component":second}),
                    "lot":batches[0],"expiry_text":_field(expiries) if expiries else None,
                    "quantity_semantics_verified":False,"association_verified":False})
        if len(split_lines)>1:
            links.append({"type":"multi_lot_printed_subline_candidates","lines":split_lines,
                "main_quantity_must_not_be_duplicated_per_lot":True,"interpretation_status":"explicit_source_subline_quantities_require_review"})
            flags.append("multi_lot_printed_subline_quantities_require_review")
    lot_quantities = [l for l in links if l["type"]=="printed_lot_quantity"]
    if not fields["quantity"] and len(lot_quantities)==1:
        fields["quantity"] = dict(lot_quantities[0]["quantity"])
        fields["quantity"]["review_flags"] = ["quantity_from_explicit_lot_line"]
        flags.append("main_quantity_missing_lot_quantity_candidate")
    if fields["quantity"] and len(lot_quantities)==1 and Decimal(fields["quantity"]["normalized_value"]) != Decimal(lot_quantities[0]["quantity"]["normalized_value"]):
        flags.append("main_and_lot_quantity_conflict")
    for key in ("description","quantity","unit","lot"):
        if not fields[key]:
            flags.append(f"{key}_missing")
    if "supplier_code" in header["anchors"] and not fields["supplier_code"]:
        flags.append("supplier_code_missing")
    if not fields["mfg_date"] and not fields["exp_date"]:
        flags.append("mfg_and_exp_missing")
    if fields["lot"] and len(fields["lot"]["raw_value"])<3:
        flags.append("short_lot_requires_source_review")
    if any(f and f["confidence"] is not None and f["confidence"]<.85 for f in fields.values()):
        flags.append("low_ocr_confidence")
    for key,field in fields.items():
        if field:
            flags.extend(f"{key}:{flag}" for flag in field["review_flags"] if flag not in {"shared_detection_bbox"})
    flags.append("human_review_required")
    return fields, list(dict.fromkeys(flags)), links


def _product_rows(tokens, header, supplier, height):
    if not header:
        return [], [], None
    body = [t for t in tokens if t.cy > header["bottom"] + header["median_height"]*.10]
    # End on explicit totals, never on a generic word embedded in a name.
    boundaries = [t.box[1] for t in body if t.box[1]>header["bottom"]+header["median_height"]*1.6 and re.search(r"^(?:\**\s*(?:SUB\s*TOTAL|TOTAL\s*A[MA][O0]?U?NT)|จำนวนรายการสินค้า|ยอดรวมหน้านี้|รวมมูลค่าสินค้า|มูลค่าสินค้า|รวมเงิน|รวมเป็นเงิน|รวมทั้งสิ้น|รวม$|หมายเหตุ|หมายเทต|กายเหตุ)|https?://|connect\.dksh\.com|สั่ง.{0,3}สินค้า.*ติดตาม",t.text.strip(),re.I)]
    if supplier=="greater_mybacin":
        boundaries.extend(t.box[1] for t in body if re.match(r"^ส่วนล[ดค]เงินสด\s*:",t.text.strip()))
    boundary = min(boundaries) if boundaries else height*.82
    body = [t for t in body if t.cy < boundary]
    backorder_markers=[t for t in body if re.search(r"ค[่้]างส่ง|คำงส่ง|BACK\s*ORDER|OUTSTANDING\s*(?:ITEM|ORDER)",t.text,re.I)]
    lines = _lines(body, header["median_height"]*.60)
    anchors=[]
    for line in lines:
        cols={}
        for t in line:
            cols.setdefault(_column(t,header),[]).append(t)
        desc = any(_plain_description(t.text) for t in cols.get("description",[]))
        combined = any(_split_code_description(t.text) for t in line if t.box[0] < header["anchors"]["description"].cx)
        combined_code_header="supplier_code" in header["anchors"] and bool(re.search(r"ลำ[ดค]ับ",header["anchors"]["supplier_code"].text))
        code = any((_CODE_RE.fullmatch(t.text) and len(t.text)>=3) or (combined_code_header and re.fullmatch(r"\d{1,3}\s+[A-Za-z0-9./_$-]{3,30}",t.text)) for t in cols.get("supplier_code",[]))
        nums = sum(_number(t.text) is not None for t in line if _column(t,header) in {"quantity","unit_price","amount"})
        # Ignore headers and explicit lot lines before testing row anchors.
        quantity = any(_number(t.text) is not None or re.fullmatch(r"\d+(?:\.\d+)?\s*[A-Za-zก-๙]+",t.text) for t in line if _column(t,header) in {"quantity","unit"})
        has_money_header=bool({"amount","unit_price"} & header["anchors"].keys())
        money_cell=any(re.fullmatch(r"[\d,.]+",t.text) for t in line if _column(t,header) in {"unit_price","amount"})
        fused_quantity_description=any(_split_quantity_unit_description(t.text) or _leading_quantity_inline_lot(t.text) for t in line) if "quantity" in header["anchors"] and header["anchors"]["quantity"].cx<header["anchors"]["description"].cx else False
        quantity=quantity or fused_quantity_description
        # Literal QTY with printed manufacturing/expiry labels can anchor a
        # nearby free-goods line even when main quantity OCR is malformed.
        below=[t for t in body if statistics.median(token.cy for token in line)<t.cy<statistics.median(token.cy for token in line)+header["median_height"]*4]
        explicit_qty_below=sum(bool(re.search(r"\bQTY\s*[:.]\s*\d",t.text,re.I)) for t in below)==1 and any(_MFG_RE.search(t.text) for t in below) and any(re.search(r"E[XKR]P\s*[:.,]",t.text,re.I) for t in below)
        quantity=quantity or (desc and explicit_qty_below)
        missing_code_row=quantity and money_cell
        # Retain a printed product with two separate price/amount cells even
        # when its quantity detection is absent. Quantity remains null.
        separate_money_cells=all(any(_number(t.text) is not None or re.fullmatch(r"\d[\d,.]{2,}",t.text) for t in cols.get(key,[])) for key in ("unit_price","amount"))
        missing_quantity_row=desc and "quantity" in header["anchors"] and separate_money_cells
        unreadable_merged_description=bool(_unreadable_merged_description(line,header))
        gift_markers=[t for t in line if (_column(t,header)=="supplier_code" and re.fullmatch(r"ชดเชย|ซดเรย|ทเรย|ทดแทน|แถม",t.text.strip())) or re.search(r"สินค้าทดแทน|สินค้าแถม",t.text)]
        explicit_gift_row=bool(gift_markers) and desc and quantity
        if unreadable_merged_description or explicit_gift_row or ((desc or combined or fused_quantity_description) and (code or combined or missing_code_row or missing_quantity_row or ("supplier_code" not in header["anchors"] and quantity and (money_cell or not has_money_header)))):
            anchors.append(line)
    rows=[]
    for index,line in enumerate(anchors):
        # Skewed/tall detections can overlap an adjacent line's top edge.
        # Center-based bounded blocks avoid a reversed empty interval; the
        # actual anchor detections are retained even in the ambiguous case.
        start=statistics.median(t.cy for t in line)-header["median_height"]*.60
        end=statistics.median(t.cy for t in anchors[index+1])-header["median_height"]*.60 if index+1<len(anchors) else boundary
        block=[t for t in body if t in line or (t.cy >= start and t.cy < end)]
        fields,flags,links=_row_fields(block,line,header,supplier)
        gift_markers=[t for t in line if (_column(t,header)=="supplier_code" and re.fullmatch(r"ชดเชย|ซดเรย|ทเรย|ทดแทน|แถม",t.text.strip())) or re.search(r"สินค้าทดแทน|สินค้าแถม",t.text)]
        if gift_markers:
            links.append({"type":"printed_gift_or_substitute_marker","evidence":_field(gift_markers),"interpretation_status":"supplier_marker_ocr_variant_requires_review"})
            flags.append("printed_gift_or_substitute_marker_requires_review")
        if fields["description"] is None:
            unreadable=_unreadable_merged_description(line,header)
            if not unreadable:continue
            flags.append("description_unreadable_merged_detection")
            links.append({"type":"unreadable_merged_description_evidence","detections":[_field([token]) for token in unreadable],"may_infer_product_name":False})
        boxes=[t.box for t in block]
        incomplete = any(f in flags for f in ("description_missing","quantity_missing","unit_missing","lot_missing","mfg_and_exp_missing","lot_multiple_candidates","supplier_code_missing")) or any("year_unresolved" in f or "invalid_calendar_date" in f for f in flags)
        rows.append({"row_number":len(rows)+1,"outcome":"partial" if incomplete else "candidate",
                     "fields":fields,"review_flags":flags,"relationships":links,
                     "block_bbox":[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)],
                     "evidence_token_ids":[t.token_id for t in block],"association_basis":"printed_header_columns_and_bounded_product_block", "association_verified":False})
        preceding_markers=[marker for marker in backorder_markers if marker.cy<statistics.median(t.cy for t in line)]
        rows[-1]["section"]="backorder" if preceding_markers else "goods"
        if preceding_markers:
            rows[-1]["section_marker"]=_field([max(preceding_markers,key=lambda marker:marker.cy)])
            rows[-1]["excluded_from_receipts"]=True
            rows[-1]["outcome"]="quarantine"
            rows[-1]["review_flags"].append("backorder_not_receipt_evidence")
    used={token_id for row in rows for token_id in row["evidence_token_ids"]}
    orphan=[{"token_id":t.token_id,"text":t.text,"bbox":list(t.box),"reason":"unattached_lot_or_date"} for t in body if t.token_id not in used and (_LOT_RE.search(t.text) or _EXP_RE.search(t.text) or _MFG_RE.search(t.text))]
    return rows,orphan,boundary


def _tnp_explicit_rows(tokens,header,page_number,image_size):
    """Full-code TNP shape: code + quantity/name, then LOT/QTY/MFG/EXP.

    This is gated by supplier identity at the caller, the printed multi-column
    header, a real alphanumeric seller-code detection, and explicit quantity/
    dates on its bounded lot line. Nothing is populated by a supplier default.
    """
    if not header:
        return []
    width,height=image_size
    anchors=sorted([t for t in tokens if t.cy>header["bottom"] and t.box[0]<width*.15 and re.fullmatch(r"[A-Z]\d{8}",t.text)],key=lambda t:t.cy)
    results=[]
    for index,code in enumerate(anchors):
        row_height=header["median_height"]
        main=[t for t in tokens if abs(t.cy-code.cy)<=row_height*.8]
        end=min(anchors[index+1].cy-row_height*.7,code.cy+row_height*4) if index+1<len(anchors) else code.cy+row_height*4
        block=[t for t in tokens if code.cy-row_height*.8<=t.cy<end]
        lot_lines=[t for t in block if _LOT_RE.search(t.text) and re.search(r"\bQTY[.:]?\s*\d",t.text,re.I) and _MFG_RE.search(t.text) and _EXP_RE.search(t.text)]
        if len(lot_lines)!=1:
            continue
        explicit=lot_lines[0]
        qty=re.search(r"\bQTY[.:]?\s*(\d+(?:\.\d+)?)\s*([A-Z]{1,6})\b",explicit.text,re.I)
        descriptions=[t for t in main if t is not code and t.box[0]>width*.15 and t.box[0]<width*.65 and _plain_description(t.text)]
        if not qty or not descriptions:
            continue
        description=max(descriptions,key=lambda t:len(t.text))
        raw_description=re.sub(r"^\s*\d+(?:\.\d+)?\s*","",description.text,count=1)
        fields,flags,links=_row_fields(block,main,header,"tnp")
        fields["supplier_code"]=_field([code],code.text)
        fields["description"]=_field([description],raw_description,raw=raw_description,flags=["fused_unit_description_requires_review"])
        fields["quantity"]=_field([explicit],qty[1],raw=qty[1],flags=["quantity_from_explicit_lot_line"])
        fields["unit"]=_field([explicit],qty[2].upper(),raw=qty[2],flags=["unit_from_explicit_lot_line"])
        for key,regex in (("lot",_LOT_RE),("mfg_date",_MFG_RE),("exp_date",_EXP_RE)):
            match=regex.search(explicit.text)
            if match:
                fields[key]=_field([explicit],match[1].strip(" ()/:;., "),raw=match[1].strip(" ()/:;., ")) if key=="lot" else _date_field(explicit,match[1])
        flags=[flag for flag in flags if flag not in {"quantity_missing","unit_missing","supplier_code_missing","description_missing","lot_missing","mfg_and_exp_missing","main_quantity_missing_lot_quantity_candidate","lot_text_ambiguous"}]
        flags.extend(["supplier_adapter_tnp_explicit_lot_qty_dates","fused_unit_description_requires_review"])
        if code.box[0]<=width*.02:
            flags.append("supplier_code_near_source_edge_review")
        boxes=[t.box for t in block]
        results.append({"row_number":len(results)+1,"page_number":page_number,"outcome":"partial","fields":fields,"review_flags":list(dict.fromkeys(flags)),
                        "relationships":links,"block_bbox":[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)],
                        "evidence_token_ids":[t.token_id for t in block],"association_basis":"supplier_identity_printed_header_and_explicit_code_lot_qty_date_block","association_verified":False,"section":"goods"})
    return results


def extract_batch_page(page_number, paddle_rows, image_size, tesseract_text=None, source_file=None):
    """Return review candidates with real OCR provenance, never approvals.

    ``tesseract_text`` is plain text only. It may corroborate an exact lot/code,
    but cannot acquire Paddle geometry or silently replace a field.
    """
    tokens,rejected=_tokens(paddle_rows)
    width,height=image_size
    header=_header(tokens,height)
    supplier=_supplier(tokens,height)
    document=_document(tokens,supplier,header,height)
    rows,orphans,boundary=_product_rows(tokens,header,supplier["key"],height)
    if supplier["key"]=="tnp":
        tnp_rows=_tnp_explicit_rows(tokens,header,page_number,image_size)
        if tnp_rows:
            rows=tnp_rows
            orphans=[]
    non_receipt_rows=[row for row in rows if row.get("section")=="backorder"]
    rows=[row for row in rows if row.get("section")!="backorder"]
    if document["document_type"]=="credit_note":
        for row in rows:
            row["section"]="credit_note_return"
            row["excluded_from_receipts"]=True
            row["outcome"]="quarantine"
            row["review_flags"].append("credit_note_return_not_purchase_receipt")
        non_receipt_rows.extend(rows)
        rows=[]
    if document["document_type"] in {"purchase_vat_report","tax_register_report"}:
        rows=[]
        non_receipt_rows=[]
        orphans=[]
    plain=tesseract_text or ""
    normalized_plain=_compact(plain)
    text_candidates=[]
    for line_number,line in enumerate(plain.splitlines(),1):
        if not re.search(r"\bL[O0]T|\bE[XKR]P|\bMFG",line,re.I):
            continue
        for key,regex in (("lot",_LOT_RE),("exp_date",_EXP_RE),("mfg_date",_MFG_RE)):
            match=regex.search(line)
            if match:
                text_candidates.append({"field":key,"raw_value":match[1].strip(" ()/:;.,"),"raw_line":line,"line_number":line_number,"engine":"TESSERACT_TEXT","bbox":None,"confidence":None,"association_verified":False,"review_flags":["text_only_unattached_evidence","human_review_required"]})
    for row in rows+non_receipt_rows:
        row["page_number"]=page_number
        row["tesseract_corroboration"]={key:bool(field and len(_compact(str(field["normalized_value"] or "")))>=3 and _compact(str(field["normalized_value"])) in normalized_plain) if plain else None for key,field in row["fields"].items() if key in {"supplier_code","lot"}}
        invoice_date=document["invoice_date"]["normalized_value"] if document["invoice_date"] else None
        expiry=row["fields"]["exp_date"]["normalized_value"] if row["fields"]["exp_date"] else None
        manufacture=row["fields"]["mfg_date"]["normalized_value"] if row["fields"]["mfg_date"] else None
        date_flags=[]
        if invoice_date and expiry and expiry<invoice_date:date_flags.append("expiry_precedes_invoice_source_review")
        if invoice_date and manufacture and manufacture>invoice_date:date_flags.append("manufacture_after_invoice_source_review")
        if manufacture and expiry and expiry<manufacture:date_flags.append("expiry_precedes_manufacture_source_review")
        if date_flags:
            row["review_flags"].extend(date_flags)
            if row["outcome"]!="quarantine":
                row["outcome"]="partial"
    flags=list(document["review_flags"])
    if not header:flags.append("printed_table_header_not_reconstructed")
    elif header["approximate_header_roles"]:flags.append("approximate_ocr_header_roles_require_review")
    if header and any(token.engine.startswith("ASSISTANT_VISUAL") for token in header["tokens"]):
        flags.append("assistant_visual_header_proposal_requires_review")
        for row in rows+non_receipt_rows:
            row["review_flags"].append("assistant_visual_header_proposal_requires_review")
            row["association_basis"]="assistant_visual_printed_header_proposal_and_bounded_actual_ocr_body"
            if row["outcome"]!="quarantine":row["outcome"]="partial"
    if not rows:flags.append("no_structured_product_rows")
    if rejected:flags.append("invalid_ocr_geometry")
    if orphans:flags.append("unattached_lot_date_evidence")
    if any(row.get("section")=="backorder" for row in non_receipt_rows):flags.append("backorder_section_excluded_from_product_rows")
    if any(row.get("section")=="credit_note_return" for row in non_receipt_rows):flags.append("credit_note_rows_preserved_as_excluded_returns")
    if document["document_type"]=="credit_note":flags.append("credit_note_requires_separate_treatment")
    if document["document_type"] in {"purchase_vat_report","tax_register_report"}:flags.append("crosscheck_report_not_product_evidence")
    if supplier["key"]=="unrecognized":flags.append("supplier_adapter_unrecognized")
    if plain and not tokens:flags.append("text_only_fallback_no_field_geometry")
    flags.append("human_review_required")
    outcome="quarantine" if not rows or document["document_type"]=="credit_note" else "partial" if any(r["outcome"]=="partial" for r in rows) or any(f in flags for f in ("invoice_number_missing","invoice_number_conflict","invoice_date_missing","invoice_date_unresolved","invoice_date_conflict","approximate_ocr_header_roles_require_review")) else "candidate"
    return {"contract_version":CONTRACT_VERSION,"page_number":page_number,"source_file":source_file,
            "image_size":[width,height],"outcome":outcome,"document":document,"product_rows":rows,"non_receipt_rows":non_receipt_rows,
            "table":{"found":header is not None,"header_bbox":_field(header["tokens"])["bbox"] if header else None,
                     "columns":{key:{"header":_field([token],flags=["approximate_ocr_header_role"] if key in header["approximate_header_roles"] else []),"x_interval":[None if not abs(x)<float('inf') else x for x in header["bounds"][key]]} for key,token in header["anchors"].items()} if header else {},"body_bottom":boundary},
            "orphan_evidence":orphans,"text_only_candidates":text_candidates,"rejected_tokens":rejected,"review_flags":list(dict.fromkeys(flags)),
            "tesseract_fallback":{"available":bool(plain),"mode":"exact_text_corroboration_only","geometry":None,"text_sha256":hashlib.sha256(plain.encode()).hexdigest() if plain else None},
            "human_verified":False,"production_ready":False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paddle",required=True,type=Path)
    parser.add_argument("--page",required=True,type=int)
    parser.add_argument("--width",required=True,type=int)
    parser.add_argument("--height",required=True,type=int)
    parser.add_argument("--source-file")
    parser.add_argument("--tesseract",type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args(argv)
    data=json.loads(args.paddle.read_text(encoding="utf-8"))
    result=extract_batch_page(args.page,data,(args.width,args.height),args.tesseract.read_text(encoding="utf-8") if args.tesseract else None,args.source_file)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")


if __name__=="__main__":
    main()
