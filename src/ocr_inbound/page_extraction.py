"""Layer F Slice 4 -- automatic page/row extraction from full-page OCR
evidence (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 33 for full design
rationale and Phase A characterization).

Turns a PaddleOCR JSON export for one invoice page (a flat list of
`{text, score, poly}` tokens, no structure) into a versioned, provenance-
carrying extraction: header/footer separated from the product table, the
table split into rows, and each row's fields (description, lot, mfg/exp
date, quantity, unit, unit price, total amount) matched to columns by
X-position against the table's own header row -- never by hand-copying
values out of the page image.

Evidence shape actually available for these 10 pages, confirmed by reading
the real files before writing any of this (Phase A):

  - PaddleOCR (`ocr/paddle_th/page-NNN.json`): the ONLY engine with real
    bounding-box evidence. Each item is `{"text": str, "score": float,
    "poly": [[x,y],[x,y],[x,y],[x,y]]}` in the SAME pixel coordinate space
    as `pages/page-NNN.png` (verified directly: page-005 image is
    2457x3483px, and its poly x/y values fall within that range). Treated
    here as the PRIMARY source for both text and geometry.
  - Tesseract (`ocr/tesseract/page-NNN_psmN.txt`): plain whole-page text,
    NO coordinates, NO per-token structure (confirmed: these are `.txt`
    files, not `.tsv`/`.hocr`). Used ONLY as a coarse corroboration signal
    (does a candidate row's description text appear anywhere in the
    Tesseract dump?) -- its bounding box is always reported as
    `unavailable`, per the explicit "never invent a position" requirement.
  - EasyOCR (`ocr/easyocr/`): directory exists but is EMPTY for all 10
    pages -- there is no EasyOCR evidence at all for this run. Not used;
    never fabricated.
"""
from __future__ import annotations

import json
import re
import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .text_normalize import detect_script, normalize_product_text


PAGE_EXTRACTION_CONTRACT_VERSION = "page-extract-v1"
PAGE_EXTRACTION_BUNDLE_VERSION = "page-extraction-bundle.v1"

# Bilingual keyword sets used to locate the table header row and classify
# the document -- these are read FROM the OCR text (never typed as the
# expected product data), so a page whose header wording differs simply
# fails to find a table (quarantined), it never silently invents columns.
_COLUMN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "description": ("DESCRIPTION", "รายการ"),
    "lot": ("LOT", "เลขที่ผลิต"),
    "mfg_date": ("MFG", "MFG.DATE", "วันที่ผลิต"),
    "exp_date": ("EXP", "EXP.DATE", "วันที่หมดอายุ"),
    "quantity": ("QUANTITY", "QTY", "จำนวน"),
    "unit": ("UOM", "UNIT", "หน่วยนับ"),
    "unit_price": ("UNIT PRICE", "ราคาต่อหน่วย", "ราคาด่อหน่วย"),
    "total_amount": ("TOTAL AMOUNT", "จำนวนเงินสุทธิ", "จำนวนเงิน"),
}
_TOTALS_KEYWORDS = ("SUB TOTAL", "SUBTOTAL", "รวม", "TOTAL AMOUNT", "GRAND TOTAL", "ยอดรวม", "NET AMOUNT")
_CREDIT_NOTE_KEYWORDS = ("CREDIT NOTE", "ใบลดหนี้", "DEBIT NOTE", "ใบเพิ่มหนี้")
_TAX_INVOICE_KEYWORDS = ("TAX INVOICE", "ใบกำกับภาษี")

_NUMERIC_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$")

# --- Supplier-adapter: multi-line block layout ------------------------------
# Phase A found a SECOND real table shape across 3 of the 10 pages (Unison
# page-006, Medline page-048, Community Pharmacy page-058): no column-header
# row exists anywhere on the page (the generic tabular strategy above
# correctly, honestly reports `table_found: False` for these), but each
# product instead prints as its own multi-line block containing a literal
# `LOT.`/`Lot`/`LO.` marker and a literal `MFG.`/`Mfg` ... `EXP.`/`Exp`
# marker -- printed on their own line in Unison/Medline, or fused into one
# line together in Community Pharmacy. These markers are read directly off
# the real evidence via regex (never a hand-typed product list), so this
# adapter is still automatic extraction, not a hardcoded fixture -- see
# `_multiline_block_rows` below for the exact structural rule and why it is
# a genuine, not overfit, generalization (2 independently-confirmed real
# suppliers share the block shape; a 3rd confirms the LOT+MFG+EXP-fused
# variant).
_DATE_FINDALL_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
_LOT_MARKER_RE = re.compile(r"L[O0]T?\.?\s*([A-Za-z0-9\-\/]{2,})", re.IGNORECASE)
# Exactly 10 digits, not part of a longer digit run -- Phase A confirmed
# every real internal product code on Unison/Medline is exactly 10 digits
# (1000000513, 2000000316, 1000000581, 1000000020, 1000000110...), while
# other digit runs nearby on the SAME pages are a different, confusable
# length: a 13-digit Thai tax ID (0755563000307 / 0105532083648) and a
# 12-digit invoice number (103000006626) both appear close to real product
# blocks. An earlier `\d{6,}` version of this pattern matched the tax ID on
# Community Pharmacy page-058 and picked its Thai label
# ("เลขประจำตัวผู้เสียภาษีอากร") as a fabricated "description" -- caught by
# re-running this adapter against real page-058 evidence before considering
# it done, not by a synthetic test.
_DIGIT_CODE_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")
_MAX_BLOCK_LOOKBACK_ROWS = 6


def _bbox(poly: list[list[float]]) -> dict:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return {"x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys)}


def _bbox_center_y(bbox: dict) -> float:
    return (bbox["y0"] + bbox["y1"]) / 2.0


def _bbox_overlap_x(a: dict, b: dict) -> float:
    """Horizontal overlap in px between two bboxes (0 if none)."""
    return max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))


@dataclass
class Token:
    text: str
    score: float
    poly: list[list[float]]
    bbox: dict = field(init=False)

    def __post_init__(self) -> None:
        self.bbox = _bbox(self.poly)


def load_paddle_tokens(path: Path) -> list[Token]:
    """Loads one page's PaddleOCR export exactly as written -- no text
    correction, no coordinate transformation beyond computing a convenience
    bbox from the existing polygon."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Token(text=item["text"], score=float(item["score"]), poly=item["poly"]) for item in raw]


def load_tesseract_text(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _field_provenance(token: Token | None, *, page_number: int, engine: str = "PADDLE_TH", normalized_value=None) -> dict | None:
    if token is None:
        return None
    return {
        "engine": engine,
        "raw_text": token.text,
        "normalized_value": normalized_value,
        "page_number": page_number,
        "polygon": token.poly,
        "bbox": token.bbox,
        "confidence": token.score,
    }


def _normalize_numeric(text: str) -> float | None:
    cleaned = text.replace(",", "").strip()
    if not _NUMERIC_RE.match(text.strip()):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_date_components(text: str) -> dict | None:
    """Splits a DD/MM/YY(YY) string into its literal day/month/year
    components WITHOUT resolving Buddhist-Era vs Christian-Era -- Phase A
    found both conventions on the SAME page (the header `Date` field prints
    a 4-digit Buddhist year like 2568, while Lot Mfg/Exp dates print a
    2-digit year like 24/28 that is almost certainly Christian Era given
    the invoice date, but nothing on the page states this explicitly).
    Guessing the era is exactly the kind of unsupported inference the
    contract forbids -- the raw string is kept as the authoritative value;
    only the day/month/year split is offered, tagged `era: "UNSPECIFIED"`,
    for a human or a later explicit rule to resolve."""
    match = _DATE_RE.match(text.strip())
    if not match:
        return None
    day, month, year = match.groups()
    return {"day": int(day), "month": int(month), "year_raw": year, "era": "UNSPECIFIED"}


def classify_document_type(tokens: list[Token]) -> str:
    upper_texts = [t.text.upper() for t in tokens]
    joined = " ".join(upper_texts)
    if any(keyword.upper() in joined for keyword in _CREDIT_NOTE_KEYWORDS):
        return "CREDIT_NOTE"
    if any(keyword.upper() in joined for keyword in _TAX_INVOICE_KEYWORDS):
        return "TAX_INVOICE"
    return "UNKNOWN"


_MIN_HEADER_DISTINCT_COLUMNS = 5
_HEADER_BAND_Y_TOLERANCE = 80.0


def _best_keyword_match(token_upper: str, keyword_map: dict[str, tuple[str, ...]]) -> str | None:
    """A column keyword can be a substring of another column's keyword
    (e.g. "จำนวน" (quantity) is a literal substring of "จำนวนเงินสุทธิ"
    (total_amount) -- confirmed in the real page-005 header text), so the
    MOST SPECIFIC (longest) matching keyword wins rather than whichever
    column happens to be checked first. `keyword_map` is a parameter (not
    always the module-level `_COLUMN_KEYWORDS`) so a supplier-specific
    adapter can supply its own column-concept vocabulary -- read from that
    supplier's own real header text -- without touching the generic
    tabular strategy's keyword set at all."""
    best_column, best_length = None, 0
    for column, keywords in keyword_map.items():
        for keyword in keywords:
            if keyword.upper() in token_upper and len(keyword) > best_length:
                best_column, best_length = column, len(keyword)
    return best_column


def _best_column_match(token_upper: str) -> str | None:
    return _best_keyword_match(token_upper, _COLUMN_KEYWORDS)


def _find_header_band(
    tokens: list[Token],
    keyword_map: dict[str, tuple[str, ...]],
    *,
    min_distinct: int,
    band_tolerance: float,
) -> tuple[dict[str, dict], float | None]:
    """Locates a table header row (a page commonly prints the header twice:
    once in Thai, once in English, one line below the other, or -- Phase A's
    real Community Pharmacy page-058 evidence -- once, in a single 5-column
    Thai row) and returns, per recognized column concept, the UNION of every
    header token's bbox that matched that concept's keywords -- this union is
    what later determines which X-range belongs to that column. Also returns
    the header's own maximum Y (the product rows start below it).

    Column keywords are short, common words that also legitimately occur
    OUTSIDE the header -- Phase A confirmed real page-005 footer text
    containing "จำนวนเงินรวม" (a totals recap line), a second stray
    "TOTAL AMOUNT" label near the totals block, "รายการ" inside a signature
    disclaimer sentence, and "(จำนวน.." inside payment terms -- all far
    below the real header. Matching every keyword hit page-wide (as an
    earlier version of this function did) let those footer tokens
    masquerade as "the header", inflating header_max_y from ~1340 to ~3018
    and pulling scattered footer/signature text into the product-row
    region. The real header is instead identified structurally: it is the
    Y-band on the page carrying the most DISTINCT column concepts close
    together, and it must clear `min_distinct` or this returns nothing
    honestly rather than guessing from a weaker, scattered signal."""
    hits: list[tuple[Token, str]] = []
    for token in tokens:
        column = _best_keyword_match(token.text.upper(), keyword_map)
        if column is not None:
            hits.append((token, column))
    if not hits:
        return {}, None

    ordered = sorted(hits, key=lambda pair: _bbox_center_y(pair[0].bbox))
    bands: list[list[tuple[Token, str]]] = []
    for pair in ordered:
        center_y = _bbox_center_y(pair[0].bbox)
        if bands and abs(_bbox_center_y(bands[-1][0][0].bbox) - center_y) <= band_tolerance:
            bands[-1].append(pair)
        else:
            bands.append([pair])

    header_band = max(bands, key=lambda band: len({column for _, column in band}))
    if len({column for _, column in header_band}) < min_distinct:
        return {}, None

    column_bboxes: dict[str, dict] = {}
    header_max_y = None
    for token, column in header_band:
        existing = column_bboxes.get(column)
        if existing is None:
            column_bboxes[column] = dict(token.bbox)
        else:
            existing["x0"] = min(existing["x0"], token.bbox["x0"])
            existing["x1"] = max(existing["x1"], token.bbox["x1"])
            existing["y1"] = max(existing["y1"], token.bbox["y1"])
        header_max_y = token.bbox["y1"] if header_max_y is None else max(header_max_y, token.bbox["y1"])
    return column_bboxes, header_max_y


def _find_column_bands(tokens: list[Token]) -> tuple[dict[str, dict], float | None]:
    return _find_header_band(tokens, _COLUMN_KEYWORDS, min_distinct=_MIN_HEADER_DISTINCT_COLUMNS, band_tolerance=_HEADER_BAND_Y_TOLERANCE)


def _find_totals_boundary(tokens: list[Token], below_y: float) -> float | None:
    """Y of the topmost totals-region ROW strictly below the table header
    -- the product-row region ends here. Returns None if no totals marker
    is found (page has no recognizable totals block).

    Uses the whole row-cluster the matching token belongs to, not just
    that one token's own y0: Community Pharmacy page-058's real totals
    line ("รวมแป็นเงืน" / "8,400.00") has its LABEL token sitting a few
    pixels BELOW its own numeric value in the same printed row (OCR
    baseline noise, not a layout difference), so bounding the region by
    only the label token's y0 let that numeric value sneak into the
    product-row region as a spurious extra row. Real product rows on
    every page examined in Phase A are always >>25px away from the real
    totals line, so widening the boundary to the row's own minimum y0
    only tightens the cut, it never risks swallowing a real product row
    -- PROVIDED the clustering that produces those rows never mixes in a
    token from ABOVE `below_y` in the first place. An earlier version of
    this function clustered the FULL, unfiltered token list (including
    header/body tokens with y0 <= below_y) and then took the matching
    row's own minimum y0 -- a synthetic probe (an ordinary token at y=90
    chained into the same row as a TOTAL token at y=110, with
    below_y=100) proved this could return 90, i.e. <= below_y, violating
    this function's own contract that the boundary is always strictly
    below the header. Clustering is now restricted to tokens that are
    ALREADY eligible (`y0 > below_y`) before the row-grouping step, so no
    ineligible token can ever pull a matching row's minimum y0 down to or
    below the header boundary."""
    eligible = [token for token in tokens if token.bbox["y0"] > below_y]
    matching_rows = [
        row
        for row in _cluster_rows(eligible)
        if any(any(keyword.upper() in token.text.upper() for keyword in _TOTALS_KEYWORDS) for token in row)
    ]
    if not matching_rows:
        return None
    return min(min(token.bbox["y0"] for token in row) for row in matching_rows)


def _cluster_rows(tokens: list[Token], *, y_tolerance: float = 25.0) -> list[list[Token]]:
    """Groups tokens into rows purely by vertical proximity. PaddleOCR in
    this evidence set already emits one token per printed text RUN (a full
    product name like "ISOTRATE 10 MG. (W) 50X10'S" is a single token, not
    word-by-word), so a simple greedy Y-band clustering on token centers is
    sufficient and does not need word-level geometry reasoning.

    Compares each token to the LAST token added to the current row (a
    chain: does this token sit close to the nearest token already in the
    row), not to the row's first token. Phase A found a real product row
    (Berlin page-005's UTMOS row) whose own tokens span a wider Y range
    than a single tolerance window measured from the first token -- e.g.
    description at y~1656 vs total_amount at y~1683, a 27px gap that
    exceeds a naive 25px tolerance from the first token alone, yet every
    adjacent pair within that row is well within tolerance (description
    1656 -> lot 1662 -> ... -> total_amount 1683, largest single gap 8px).
    Chaining tolerates that gradual within-row drift while still splitting
    cleanly between real rows, whose gaps (Phase A: >=30px between any two
    Berlin page-005 product rows) are larger than any single within-row
    gap observed."""
    ordered = sorted(tokens, key=lambda t: _bbox_center_y(t.bbox))
    rows: list[list[Token]] = []
    for token in ordered:
        center_y = _bbox_center_y(token.bbox)
        if rows and abs(_bbox_center_y(rows[-1][-1].bbox) - center_y) <= y_tolerance:
            rows[-1].append(token)
        else:
            rows.append([token])
    return rows


def _assign_to_column(token: Token, column_bboxes: dict[str, dict]) -> str | None:
    best_column, best_overlap = None, 0.0
    for column, bbox in column_bboxes.items():
        overlap = _bbox_overlap_x(token.bbox, bbox)
        if overlap > best_overlap:
            best_column, best_overlap = column, overlap
    return best_column


def _row_text(row: list[Token]) -> str:
    return " ".join(t.text for t in row)


def _extract_lot_from_row(row: list[Token]) -> tuple[str | None, Token | None]:
    for token in row:
        match = _LOT_MARKER_RE.search(token.text)
        if match:
            return match.group(1), token
    return None, None


def _extract_dates_token(row: list[Token]) -> Token | None:
    for token in row:
        if len(_DATE_FINDALL_RE.findall(token.text)) >= 2:
            return token
    return None


def _find_code_row(rows: list[list[Token]], start_index: int, used_row_indices: set[int]) -> int | None:
    """Walks upward (toward earlier rows on the page) from `start_index`
    looking for the nearest not-yet-claimed row containing a >=6-digit
    internal-code token -- both real block-layout pages (Unison, Medline)
    print this on the row that ALSO carries the product description, pack
    size and unit, so finding the code row is how the description is
    located without assuming any fixed number of rows between the code
    row and the Lot/Mfg/Exp row (Phase A found a generic-ingredient-name
    row sitting between them, so a fixed offset would be wrong)."""
    for index in range(start_index - 1, max(-1, start_index - 1 - _MAX_BLOCK_LOOKBACK_ROWS), -1):
        if index in used_row_indices:
            continue
        if any(_DIGIT_CODE_RE.search(token.text) for token in rows[index]):
            return index
    return None


def _multiline_block_rows(tokens: list[Token], *, page_number: int, tesseract_text: str) -> tuple[list[dict], list[str]]:
    """Fallback extraction strategy for the multi-line-block layout Phase A
    found on real Unison (page-006), Medline (page-048), and Community
    Pharmacy (page-058) pages -- see the module-level comment above
    `_DATE_FINDALL_RE` for why this is a genuine structural adapter and not
    a per-supplier hardcoded list. Only called by `extract_page` when the
    tabular-header strategy already reported no table found.

    Deliberately does NOT attempt to recover quantity/unit/unit_price/
    total_amount for this layout: unlike the Berlin tabular layout, no
    column header exists anywhere on these pages to say which numeric
    token means what, and Phase A found genuinely ambiguous evidence (two
    "1,000.00"-looking tokens on Unison's own product line with no label
    distinguishing quantity from total). Guessing that mapping is exactly
    what requirement #7 forbids -- these four fields are reported as
    unavailable with an explicit reason, honestly, rather than guessed."""
    warnings: list[str] = []
    rows = sorted(_cluster_rows(tokens), key=lambda row: min(_bbox_center_y(t.bbox) for t in row))

    date_row_indices = [i for i, row in enumerate(rows) if _extract_dates_token(row) is not None]
    if not date_row_indices:
        return [], warnings

    used_row_indices: set[int] = set()
    blocks: list[dict] = []
    for date_index in date_row_indices:
        date_row = rows[date_index]
        dates_token = _extract_dates_token(date_row)
        dates = _DATE_FINDALL_RE.findall(dates_token.text)
        mfg_raw, exp_raw = dates[0], dates[1]

        lot_value, lot_token = _extract_lot_from_row(date_row)
        lot_row_index = date_index
        if lot_value is None:
            # Not fused onto the same line (Unison/Medline shape) -- check
            # the immediately preceding rows for a standalone Lot line.
            for back in range(1, _MAX_BLOCK_LOOKBACK_ROWS + 1):
                candidate_index = date_index - back
                if candidate_index < 0 or candidate_index in used_row_indices:
                    continue
                lot_value, lot_token = _extract_lot_from_row(rows[candidate_index])
                if lot_value is not None:
                    lot_row_index = candidate_index
                    break

        search_start = min(date_index, lot_row_index)
        code_row_index = _find_code_row(rows, search_start, used_row_indices)

        quarantine_reasons: list[str] = []
        fields: dict[str, dict | None] = {
            "supplier_sku": None, "quantity": None, "unit": None, "unit_price": None, "total_amount": None,
        }
        for column in ("quantity", "unit", "unit_price", "total_amount"):
            quarantine_reasons.append(f"FIELD_UNAVAILABLE:multiline_block_layout_no_column_header:{column}")

        if code_row_index is not None:
            used_row_indices.add(code_row_index)
            lettered_tokens = [t for t in rows[code_row_index] if re.search(r"[A-Za-z฀-๿]", t.text)]
            if lettered_tokens:
                description_token = max(lettered_tokens, key=lambda t: len(t.text))
                fields["description"] = _field_provenance(description_token, page_number=page_number, normalized_value=normalize_product_text(description_token.text))
            else:
                fields["description"] = None
                quarantine_reasons.append("MISSING_FIELD:description")
        else:
            fields["description"] = None
            quarantine_reasons.append("MISSING_FIELD:description")

        if lot_token is not None:
            fields["lot"] = _field_provenance(lot_token, page_number=page_number, normalized_value=lot_value)
        else:
            fields["lot"] = None
            quarantine_reasons.append("MISSING_FIELD:lot")

        mfg_normalized = _normalize_date_components(mfg_raw)
        exp_normalized = _normalize_date_components(exp_raw)
        fields["mfg_date"] = {"engine": "PADDLE_TH", "raw_text": mfg_raw, "normalized_value": mfg_normalized, "page_number": page_number, "polygon": dates_token.poly, "bbox": dates_token.bbox, "confidence": dates_token.score}
        fields["exp_date"] = {"engine": "PADDLE_TH", "raw_text": exp_raw, "normalized_value": exp_normalized, "page_number": page_number, "polygon": dates_token.poly, "bbox": dates_token.bbox, "confidence": dates_token.score}
        if mfg_normalized is None:
            quarantine_reasons.append(f"UNPARSEABLE_DATE:mfg_date={mfg_raw!r}")
        if exp_normalized is None:
            quarantine_reasons.append(f"UNPARSEABLE_DATE:exp_date={exp_raw!r}")

        tesseract_corroborated = bool(fields.get("description")) and fields["description"]["raw_text"].strip() and fields["description"]["raw_text"].strip() in tesseract_text

        blocks.append({
            "sort_key": _bbox_center_y(dates_token.bbox),
            "fields": fields,
            "corroboration": {"tesseract_text_match": tesseract_corroborated, "tesseract_engine": "TESSERACT", "tesseract_bbox": "unavailable"},
            "quarantine_reasons": quarantine_reasons,
            "lot_key": (lot_value, mfg_raw, exp_raw),
        })

    # Phase A found a real near-duplicate block on Unison page-006: the
    # exact same description/lot/mfg/exp repeated at a second, separate Y
    # position with its quantity/price/total simply missing -- structurally
    # two distinct row-clusters, so never silently merged or dropped, but
    # identical (lot, mfg, exp) across more than one block on the same page
    # is real evidence something is wrong (either a genuine OCR duplicate
    # detection, or two legitimately separate purchase lines that happen to
    # share a batch -- this extractor cannot tell which, so both are kept
    # and flagged for a human to resolve, never silently deduplicated).
    key_counts: dict[tuple, int] = {}
    for block in blocks:
        if all(part is not None for part in block["lot_key"]):
            key_counts[block["lot_key"]] = key_counts.get(block["lot_key"], 0) + 1
    for block in blocks:
        if key_counts.get(block["lot_key"], 0) > 1:
            block["quarantine_reasons"].append("DUPLICATE_LOT_MFG_EXP_ACROSS_BLOCKS")

    blocks.sort(key=lambda b: b["sort_key"])
    product_rows = []
    for index, block in enumerate(blocks, start=1):
        product_rows.append({
            "row_index": index,
            "fields": block["fields"],
            "corroboration": block["corroboration"],
            "quarantine_reasons": block["quarantine_reasons"],
            "review_required": bool(block["quarantine_reasons"]),
        })
    return product_rows, warnings


# --- Supplier-adapter: Community Pharmacy code-table layout -----------------
# Real page-058 evidence (บริษัท ชุมชนเภสัชกรรม จำกัด (มหาชน) / Community
# Pharmacy) turned out to be a THIRD distinct real layout, not a variant of
# the generic multi-line-block adapter above: it DOES have a genuine single-
# language (Thai-only, not bilingual) 5-column table header --
# "รหัสสินค้า" (supplier's own product code) | "รายละเอิยด"/"รายละเอียด"
# (description) | "จำนวน" (quantity, printed fused with its unit, e.g.
# "240.00 box") | "ราคารวมภาษี" (unit price incl. tax) | "จำนวนเงิน" (line
# total) -- confirmed by reading the real token dump, not assumed. Because
# this table header uses different Thai wording than Berlin's and has no
# English duplicate line, it correctly does NOT satisfy the generic tabular
# strategy's `_MIN_HEADER_DISTINCT_COLUMNS` gate against `_COLUMN_KEYWORDS`
# (only "จำนวน" and "จำนวนเงิน" happen to overlap that vocabulary), so this
# adapter uses its OWN keyword map via the same `_find_header_band` engine.
#
# Layout shape, per real evidence: each product prints as TWO consecutive
# row-clusters -- a "data row" (code, description, quantity+unit, unit
# price, total) immediately followed by a "Lot row" (Lot/Mfg/Exp fused onto
# one line, matching the same `_LOT_MARKER_RE`/`_DATE_FINDALL_RE` primitives
# the generic multi-line-block adapter already uses). This is a SIMPLER,
# more reliable pairing rule than that adapter's "walk upward looking for a
# code row" search (which exists there specifically to skip past an extra
# generic-ingredient-name row Unison/Medline print between the code row and
# the Lot row) -- Community Pharmacy's own evidence has no such row in
# between, so pairing "this row, then the very next row" is what the real
# geometry actually shows, not an assumption.
#
# Selection gate: BOTH the supplier's own name text (a real string read from
# the page, never the filename or page number) AND this specific column
# header must independently be found before this adapter activates -- a
# page that merely mentions "ชุมชนเภสัชกรรม" without this table shape (or
# vice versa) does not trigger it.
# A stable, deterministic supplier_code for the matcher's exact-alias
# lookup contract -- tied to the confirmed real identity-marker match
# below, NEVER to a filename or page number (a page's own text is the
# only thing that ever sets this). extract_page() reports this same
# constant only on the branch where `_detect_community_pharmacy_table`
# actually matched both the identity marker AND the table header; every
# other branch reports the literal string "UNKNOWN" so a caller (the
# artifact builder) can never mistake "no identity contract exists yet
# for this page" for "an alias lookup was attempted and found nothing".
_COMMUNITY_PHARMACY_CANONICAL_SUPPLIER_CODE = "SUPPLIER-COMMUNITY-PHARMACY"
_COMMUNITY_PHARMACY_IDENTITY_MARKERS = ("ชุมชนเภสัชกรรม",)
_COMMUNITY_PHARMACY_COLUMN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "supplier_sku": ("รหัสสินค้า",),
    "description": ("รายละเอียด", "รายละเอิยด"),
    "quantity": ("จำนวน",),
    "unit_price": ("ราคารวมภาษี",),
    "total_amount": ("จำนวนเงิน",),
}
_COMMUNITY_PHARMACY_MIN_DISTINCT_COLUMNS = 3
_COMMUNITY_PHARMACY_HEADER_BAND_TOLERANCE = 40.0
_QTY_UNIT_SPLIT_RE = re.compile(r"^([\d,]+\.?\d*)\s+(\S.*)$")


def _is_lot_dates_row(row: list[Token]) -> bool:
    """A row is a fused Lot/Mfg/Exp marker row (this supplier's own real
    shape, e.g. "LO. 25B031 Mfg, 07/02/25 Exp, 06/02/28") when it carries
    BOTH a Lot marker and at least 2 dates -- reusing the exact same
    structural primitives (`_LOT_MARKER_RE`, `_DATE_FINDALL_RE`) the
    generic multi-line-block adapter already uses, never a new ad hoc
    pattern."""
    lot_value, _ = _extract_lot_from_row(row)
    return lot_value is not None and _extract_dates_token(row) is not None


def _detect_community_pharmacy_table(tokens: list[Token]) -> tuple[dict[str, dict], float | None]:
    joined_upper = " ".join(t.text for t in tokens)
    if not any(marker in joined_upper for marker in _COMMUNITY_PHARMACY_IDENTITY_MARKERS):
        return {}, None
    return _find_header_band(
        tokens,
        _COMMUNITY_PHARMACY_COLUMN_KEYWORDS,
        min_distinct=_COMMUNITY_PHARMACY_MIN_DISTINCT_COLUMNS,
        band_tolerance=_COMMUNITY_PHARMACY_HEADER_BAND_TOLERANCE,
    )


def _community_pharmacy_code_table_rows(tokens: list[Token], *, page_number: int, tesseract_text: str) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    column_bboxes, header_max_y = _detect_community_pharmacy_table(tokens)
    if not column_bboxes or header_max_y is None:
        return [], warnings

    totals_y = _find_totals_boundary(tokens, header_max_y)
    if totals_y is None:
        warnings.append("NO_TOTALS_MARKER_FOUND_TABLE_REGION_UNBOUNDED_BELOW")
        totals_y = max(t.bbox["y1"] for t in tokens) + 1

    region_tokens = [t for t in tokens if header_max_y < t.bbox["y0"] < totals_y]
    rows = sorted(_cluster_rows(region_tokens), key=lambda row: min(_bbox_center_y(t.bbox) for t in row))

    blocks: list[dict] = []
    index = 0
    while index < len(rows):
        row = rows[index]
        if _is_lot_dates_row(row):
            # An orphan Lot row with no preceding data row (should not
            # happen on well-formed evidence, but never silently absorbed
            # into the wrong product either).
            warnings.append("ORPHAN_LOT_ROW:" + _row_text(row))
            index += 1
            continue

        data_row = row
        lot_row = None
        if index + 1 < len(rows) and _is_lot_dates_row(rows[index + 1]):
            lot_row = rows[index + 1]
            index += 2
        else:
            index += 1

        fields_by_column: dict[str, list[Token]] = {}
        unassigned: list[Token] = []
        for token in data_row:
            column = _assign_to_column(token, column_bboxes)
            if column is None:
                unassigned.append(token)
                continue
            fields_by_column.setdefault(column, []).append(token)

        quarantine_reasons: list[str] = []
        fields: dict[str, dict | None] = {}

        supplier_sku_tokens = fields_by_column.get("supplier_sku", [])
        if supplier_sku_tokens:
            token = supplier_sku_tokens[0]
            # Kept as a distinct field from `description` and NEVER folded
            # into it -- this is the wholesaler's own opaque product code
            # (confirmed 5 digits on real evidence, "32132"), not the
            # shop's internal product code. The matcher's existing
            # `supplier_sku` contract (matching.py) already treats this
            # field as exact-alias-lookup-only evidence, never as
            # free-text scanned for an internal code -- this adapter only
            # has to route the value into the right field, never invent
            # matcher logic.
            fields["supplier_sku"] = _field_provenance(token, page_number=page_number, normalized_value=token.text.strip())
            if len(supplier_sku_tokens) > 1:
                quarantine_reasons.append("MULTIPLE_TOKENS_IN_COLUMN:supplier_sku")
        else:
            fields["supplier_sku"] = None

        description_tokens = fields_by_column.get("description", [])
        if description_tokens:
            if len(description_tokens) > 1:
                description_tokens = sorted(description_tokens, key=lambda t: t.bbox["x0"])
                quarantine_reasons.append("MULTI_TOKEN_DESCRIPTION_JOINED")
                joined_text = " ".join(t.text for t in description_tokens)
                representative = description_tokens[0]
                fields["description"] = {
                    "engine": "PADDLE_TH", "raw_text": joined_text,
                    "normalized_value": normalize_product_text(joined_text),
                    "page_number": page_number,
                    "polygon": representative.poly, "bbox": representative.bbox,
                    "confidence": min(t.score for t in description_tokens),
                }
            else:
                token = description_tokens[0]
                fields["description"] = _field_provenance(token, page_number=page_number, normalized_value=normalize_product_text(token.text))
        else:
            fields["description"] = None
            quarantine_reasons.append("MISSING_FIELD:description")

        quantity_tokens = fields_by_column.get("quantity", [])
        if quantity_tokens:
            if len(quantity_tokens) > 1:
                quarantine_reasons.append("MULTIPLE_TOKENS_IN_COLUMN:quantity")
                quantity_tokens = sorted(quantity_tokens, key=lambda t: t.bbox["x0"])
            token = quantity_tokens[0]
            # This supplier prints quantity and unit fused onto one token
            # ("240.00 box") -- split on the real text via a generic
            # number-then-word pattern rather than guessing a fixed unit
            # vocabulary; if the token does not match that shape, the
            # whole text is kept as the quantity's raw evidence and unit
            # stays unavailable rather than guessed.
            split = _QTY_UNIT_SPLIT_RE.match(token.text.strip())
            quantity_text = split.group(1) if split else token.text
            unit_text = split.group(2) if split else None
            quantity_normalized = _normalize_numeric(quantity_text)
            if quantity_normalized is None:
                quarantine_reasons.append(f"UNPARSEABLE_NUMBER:quantity={token.text!r}")
            fields["quantity"] = {
                "engine": "PADDLE_TH", "raw_text": quantity_text, "normalized_value": quantity_normalized,
                "page_number": page_number, "polygon": token.poly, "bbox": token.bbox, "confidence": token.score,
            }
            if unit_text:
                fields["unit"] = {
                    "engine": "PADDLE_TH", "raw_text": unit_text, "normalized_value": unit_text.strip().lower(),
                    "page_number": page_number, "polygon": token.poly, "bbox": token.bbox, "confidence": token.score,
                }
            else:
                fields["unit"] = None
        else:
            fields["quantity"] = None
            fields["unit"] = None

        for column in ("unit_price", "total_amount"):
            column_tokens = fields_by_column.get(column, [])
            if not column_tokens:
                fields[column] = None
                continue
            if len(column_tokens) > 1:
                quarantine_reasons.append(f"MULTIPLE_TOKENS_IN_COLUMN:{column}")
                column_tokens = sorted(column_tokens, key=lambda t: t.bbox["x0"])
            token = column_tokens[0]
            normalized_value = _normalize_numeric(token.text)
            if normalized_value is None:
                quarantine_reasons.append(f"UNPARSEABLE_NUMBER:{column}={token.text!r}")
            fields[column] = _field_provenance(token, page_number=page_number, normalized_value=normalized_value)

        if lot_row is not None:
            lot_value, lot_token = _extract_lot_from_row(lot_row)
            dates_token = _extract_dates_token(lot_row)
            fields["lot"] = _field_provenance(lot_token, page_number=page_number, normalized_value=lot_value)
            dates = _DATE_FINDALL_RE.findall(dates_token.text)
            mfg_raw, exp_raw = dates[0], dates[1]
            mfg_normalized = _normalize_date_components(mfg_raw)
            exp_normalized = _normalize_date_components(exp_raw)
            fields["mfg_date"] = {"engine": "PADDLE_TH", "raw_text": mfg_raw, "normalized_value": mfg_normalized, "page_number": page_number, "polygon": dates_token.poly, "bbox": dates_token.bbox, "confidence": dates_token.score}
            fields["exp_date"] = {"engine": "PADDLE_TH", "raw_text": exp_raw, "normalized_value": exp_normalized, "page_number": page_number, "polygon": dates_token.poly, "bbox": dates_token.bbox, "confidence": dates_token.score}
            if mfg_normalized is None:
                quarantine_reasons.append(f"UNPARSEABLE_DATE:mfg_date={mfg_raw!r}")
            if exp_normalized is None:
                quarantine_reasons.append(f"UNPARSEABLE_DATE:exp_date={exp_raw!r}")
        else:
            fields["lot"] = None
            fields["mfg_date"] = None
            fields["exp_date"] = None
            quarantine_reasons.append("MISSING_FIELD:lot")

        # Same-Lot/Mfg/Exp across two purchase rows is NOT, on its own,
        # evidence of an OCR duplicate on this supplier's real layout --
        # unlike the generic multi-line-block adapter's Unison evidence
        # (where a duplicate block was missing its OWN quantity/price/
        # total, i.e. genuinely looked like a re-detected copy of the same
        # row), Community Pharmacy's own real page-058 evidence shows two
        # rows with the SAME Lot but DIFFERENT quantities (240.00 vs
        # 96.00) and distinct row geometry -- consistent with two real
        # purchase/allocation lines against one received batch, not a
        # rendering artifact. This adapter therefore does NOT run the
        # generic adapter's duplicate-lot quarantine rule at all; each row
        # stands on its own evidence.
        if unassigned:
            quarantine_reasons.append("UNASSIGNED_TOKENS_IN_ROW:" + ";".join(t.text for t in unassigned))

        tesseract_corroborated = bool(fields.get("description")) and fields["description"]["raw_text"].strip() and fields["description"]["raw_text"].strip() in tesseract_text

        blocks.append({
            "fields": fields,
            "corroboration": {"tesseract_text_match": tesseract_corroborated, "tesseract_engine": "TESSERACT", "tesseract_bbox": "unavailable"},
            "quarantine_reasons": quarantine_reasons,
        })

    product_rows = []
    for row_index, block in enumerate(blocks, start=1):
        product_rows.append({
            "row_index": row_index,
            "fields": block["fields"],
            "corroboration": block["corroboration"],
            "quarantine_reasons": block["quarantine_reasons"],
            "review_required": bool(block["quarantine_reasons"]),
        })
    return product_rows, warnings


def extract_page(
    *,
    page_number: int,
    paddle_json_path: Path,
    tesseract_text_path: Path | None,
    image_size: tuple[int, int] | None = None,
    min_token_score: float = 0.30,
) -> dict:
    """Produces one versioned `PageExtraction` dict. Never writes anything;
    the caller decides whether/where to persist the result."""
    all_tokens = load_paddle_tokens(paddle_json_path)
    # A token this weak is very likely stray OCR noise (Phase A found one:
    # a lone lowercase "o" at score 0.096 sitting inside the MONOLIN row on
    # page-005) -- excluded from row assignment entirely rather than risk
    # it being read as a real field value, but kept in `warnings` so the
    # exclusion itself has provenance.
    tokens = [t for t in all_tokens if t.score >= min_token_score]
    low_score_dropped = [t for t in all_tokens if t.score < min_token_score]
    tesseract_text = load_tesseract_text(tesseract_text_path)

    document_type = classify_document_type(tokens)

    warnings: list[str] = []
    for dropped in low_score_dropped:
        warnings.append(f"LOW_CONFIDENCE_TOKEN_EXCLUDED:{dropped.text!r}@score={dropped.score:.3f}")

    # Try the most narrowly-gated, supplier-identity-specific adapter
    # first (real supplier name text AND its own real column header must
    # both be found -- see `_detect_community_pharmacy_table` -- so this
    # can never misfire on an unrelated page just because page order
    # changed; it is never selected by filename or page number). Falling
    # through to the generic strategies below is the fail-safe path when
    # this adapter's gate does not match.
    cp_rows, cp_warnings = _community_pharmacy_code_table_rows(tokens, page_number=page_number, tesseract_text=tesseract_text)
    if cp_rows:
        return {
            "contract_version": PAGE_EXTRACTION_CONTRACT_VERSION,
            "page_number": page_number,
            "image_size": {"width": image_size[0], "height": image_size[1]} if image_size else None,
            "document_type": document_type,
            "table_found": True,
            "extraction_strategy": "COMMUNITY_PHARMACY_CODE_TABLE",
            "canonical_supplier_code": _COMMUNITY_PHARMACY_CANONICAL_SUPPLIER_CODE,
            "column_bands": {},
            "table_header_max_y": None,
            "totals_boundary_y": None,
            "product_rows": cp_rows,
            "warnings": warnings + cp_warnings,
        }

    column_bboxes, header_max_y = _find_column_bands(tokens)

    if not column_bboxes or header_max_y is None or "description" not in column_bboxes:
        # The tabular-header strategy found nothing. Before honestly giving
        # up, try the multi-line-block fallback strategy (Unison/Medline/
        # Community Pharmacy real evidence) -- a generic interface, tried in
        # a fixed order, with the LAST resort being an honest "no table
        # found" rather than a guess (requirement: "supplier-specific
        # adapters ... must share a generic interface with a fail-safe
        # fallback").
        block_rows, block_warnings = _multiline_block_rows(tokens, page_number=page_number, tesseract_text=tesseract_text)
        if block_rows:
            return {
                "contract_version": PAGE_EXTRACTION_CONTRACT_VERSION,
                "page_number": page_number,
                "image_size": {"width": image_size[0], "height": image_size[1]} if image_size else None,
                "document_type": document_type,
                "table_found": True,
                "extraction_strategy": "MULTILINE_BLOCK",
                # No supplier-identity contract exists yet for the
                # multi-line-block layout's suppliers (Unison/Medline) --
                # "UNKNOWN" is the honest report, never a guess and never
                # derived from filename/page number. A caller must not
                # treat this as "alias lookup was tried and found nothing".
                "canonical_supplier_code": "UNKNOWN",
                "column_bands": {},
                "table_header_max_y": None,
                "totals_boundary_y": None,
                "product_rows": block_rows,
                "warnings": warnings + block_warnings,
            }
        return {
            "contract_version": PAGE_EXTRACTION_CONTRACT_VERSION,
            "page_number": page_number,
            "image_size": {"width": image_size[0], "height": image_size[1]} if image_size else None,
            "document_type": document_type,
            "table_found": False,
            "extraction_strategy": "NONE",
            "canonical_supplier_code": "UNKNOWN",
            "product_rows": [],
            "totals": {},
            "warnings": warnings + block_warnings + ["NO_TABLE_HEADER_FOUND"],
        }

    totals_y = _find_totals_boundary(tokens, header_max_y)
    if totals_y is None:
        warnings.append("NO_TOTALS_MARKER_FOUND_TABLE_REGION_UNBOUNDED_BELOW")
        totals_y = max(t.bbox["y1"] for t in tokens) + 1

    region_tokens = [t for t in tokens if header_max_y < t.bbox["y0"] < totals_y]
    row_clusters = _cluster_rows(region_tokens)
    row_clusters.sort(key=lambda row: min(_bbox_center_y(t.bbox) for t in row))

    product_rows = []
    row_index = 0
    for row_tokens in row_clusters:
        fields_by_column: dict[str, list[Token]] = {}
        unassigned: list[Token] = []
        for token in row_tokens:
            column = _assign_to_column(token, column_bboxes)
            if column is None:
                unassigned.append(token)
                continue
            fields_by_column.setdefault(column, []).append(token)

        if not fields_by_column.get("description"):
            # No token in this Y-band landed in the description column at
            # all -- this is not a product row with a missing name, it is
            # non-product text that happens to fall between the header and
            # the totals boundary (Phase A found a real example: a
            # standalone "VAT INCLUDED" / "บาท" note line printed just
            # below the Berlin page-005 header, before the first real
            # product row). A genuine product row always has SOME text in
            # its description column, even if other fields are missing --
            # so rather than emit an empty, all-None row that would falsely
            # count as "found 7 rows" when only 5 are real products, this
            # band is dropped with its own provenance kept in `warnings`.
            stray_texts = [t.text for t in row_tokens]
            warnings.append("NON_PRODUCT_ROW_EXCLUDED:no_description_token:" + ";".join(stray_texts))
            continue

        row_index += 1
        index = row_index
        quarantine_reasons: list[str] = []
        fields: dict[str, dict | None] = {"supplier_sku": None}

        description_tokens = fields_by_column.get("description", [])
        if len(description_tokens) > 1:
            # Multiple description-column tokens in one row band: a real,
            # legitimate case is a wrapped/multi-line product description.
            # Join them in row (then reading) order rather than guessing
            # which one is "the" name, and flag it for review either way --
            # concatenation is a display convenience, not a claim that the
            # join is semantically correct.
            description_tokens = sorted(description_tokens, key=lambda t: t.bbox["x0"])
            quarantine_reasons.append("MULTI_TOKEN_DESCRIPTION_JOINED")
            joined_text = " ".join(t.text for t in description_tokens)
            representative = description_tokens[0]
            fields["description"] = {
                "engine": "PADDLE_TH", "raw_text": joined_text,
                "normalized_value": normalize_product_text(joined_text),
                "page_number": page_number,
                "polygon": representative.poly, "bbox": representative.bbox,
                "confidence": min(t.score for t in description_tokens),
            }
        elif description_tokens:
            token = description_tokens[0]
            fields["description"] = _field_provenance(token, page_number=page_number, normalized_value=normalize_product_text(token.text))
        else:
            fields["description"] = None
            quarantine_reasons.append("MISSING_FIELD:description")

        for column in ("lot", "mfg_date", "exp_date", "quantity", "unit", "unit_price", "total_amount"):
            column_tokens = fields_by_column.get(column, [])
            if not column_tokens:
                fields[column] = None
                continue
            if len(column_tokens) > 1:
                quarantine_reasons.append(f"MULTIPLE_TOKENS_IN_COLUMN:{column}")
                column_tokens = sorted(column_tokens, key=lambda t: t.bbox["x0"])
            token = column_tokens[0]
            normalized_value = None
            if column in ("mfg_date", "exp_date"):
                normalized_value = _normalize_date_components(token.text)
                if normalized_value is None:
                    quarantine_reasons.append(f"UNPARSEABLE_DATE:{column}={token.text!r}")
            elif column in ("quantity", "unit_price", "total_amount"):
                normalized_value = _normalize_numeric(token.text)
                if normalized_value is None:
                    quarantine_reasons.append(f"UNPARSEABLE_NUMBER:{column}={token.text!r}")
            fields[column] = _field_provenance(token, page_number=page_number, normalized_value=normalized_value)

        # Arithmetic sanity: quantity * unit_price should be close to
        # total_amount when all three are present and numeric -- silence on
        # either side is never a conflict (per the same principle Layer F's
        # attribute guard already uses), but a real mismatch is evidence
        # this row's field alignment may be wrong and must not be trusted
        # blindly.
        qty = fields["quantity"]["normalized_value"] if fields.get("quantity") else None
        price = fields["unit_price"]["normalized_value"] if fields.get("unit_price") else None
        total = fields["total_amount"]["normalized_value"] if fields.get("total_amount") else None
        if qty is not None and price is not None and total is not None:
            expected = round(qty * price, 2)
            if abs(expected - total) > max(0.05, total * 0.01):
                quarantine_reasons.append(f"QUANTITY_PRICE_TOTAL_MISMATCH:{qty}*{price}={expected}!={total}")

        tesseract_corroborated = bool(fields.get("description")) and fields["description"]["raw_text"].strip() and fields["description"]["raw_text"].strip() in tesseract_text

        if unassigned:
            quarantine_reasons.append("UNASSIGNED_TOKENS_IN_ROW:" + ";".join(t.text for t in unassigned))

        product_rows.append({
            "row_index": index,
            "fields": fields,
            "corroboration": {"tesseract_text_match": tesseract_corroborated, "tesseract_engine": "TESSERACT", "tesseract_bbox": "unavailable"},
            "quarantine_reasons": quarantine_reasons,
            "review_required": bool(quarantine_reasons),
        })

    return {
        "contract_version": PAGE_EXTRACTION_CONTRACT_VERSION,
        "page_number": page_number,
        "image_size": {"width": image_size[0], "height": image_size[1]} if image_size else None,
        "document_type": document_type,
        "table_found": True,
        "extraction_strategy": "TABULAR_HEADER",
        # No supplier-identity contract exists yet for the tabular-header
        # layout's suppliers (Berlin/Woothi/DKSH/Charoon) -- honest
        # "UNKNOWN", never a guess and never derived from filename/page
        # number.
        "canonical_supplier_code": "UNKNOWN",
        "column_bands": column_bboxes,
        "table_header_max_y": header_max_y,
        "totals_boundary_y": totals_y,
        "product_rows": product_rows,
        "warnings": warnings,
    }


def build_page_extraction_bundle(
    *,
    source_name: str,
    source_sha256: str,
    pages: list[dict],
    image_refs: dict[int, str] | None = None,
    matcher_results: dict[tuple[int, int], dict] | None = None,
) -> dict:
    """Build the deterministic, UI-facing Slice-4 artifact.

    This function only projects extraction evidence.  It neither invokes the
    OCR engines nor writes to SQLite.  Matcher results, when supplied by a
    caller that used the matcher's pure ``_predict`` boundary, are copied as
    evidence and never persisted here.
    """
    image_refs = image_refs or {}
    matcher_results = matcher_results or {}
    ordered_pages = []
    for page in sorted(pages, key=lambda value: int(value["page_number"])):
        projected = dict(page)
        page_number = int(page["page_number"])
        projected["image_ref"] = image_refs.get(page_number)
        projected_rows = []
        for row in page.get("product_rows", []):
            projected_row = dict(row)
            projected_row["matcher_result"] = matcher_results.get(
                (page_number, int(row["row_index"])),
                {"tier": "NOT_EVALUATED", "proposed_product_code": None, "candidate_set": [], "alias_path_tested": False},
            )
            projected_rows.append(projected_row)
        projected["product_rows"] = projected_rows
        ordered_pages.append(projected)

    summary = {
        "page_count": len(ordered_pages),
        "table_found_pages": sum(bool(page.get("table_found")) for page in ordered_pages),
        "row_count": sum(len(page.get("product_rows", [])) for page in ordered_pages),
        "review_required_rows": sum(
            bool(row.get("review_required"))
            for page in ordered_pages
            for row in page.get("product_rows", [])
        ),
    }
    payload = {
        "contract_version": PAGE_EXTRACTION_BUNDLE_VERSION,
        "source": {"name": source_name, "sha256": source_sha256},
        "summary": summary,
        "pages": ordered_pages,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["artifact_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


def write_page_extraction_bundle(path: Path, payload: dict) -> Path:
    """Atomically write a validated bundle without leaving a partial file."""
    if payload.get("contract_version") != PAGE_EXTRACTION_BUNDLE_VERSION:
        raise ValueError("Unsupported page-extraction bundle contract")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return path
