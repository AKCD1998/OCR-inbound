from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher

from .ada_read import AdaReferenceCache
from .db import Repository, canonical_json
from .text_normalize import detect_script, normalize_product_text  # noqa: F401 (re-exported for existing import sites)


# Real internal codes come in two shapes: `IC-` followed by four to six
# digits (older fixtures use four, e.g. IC-0006; the live product master
# uses six, e.g. IC-000648), and a bare `630` prefix followed by four to six
# more digits (older fixtures use four for a seven-digit total, e.g.
# 6300001; the live master uses six for a nine-digit total, e.g. 630010124).
# \b on both ends means a match can never start or end in the middle of an
# unbroken digit run, so a code accidentally embedded inside a longer
# barcode or document number is never mistaken for a real internal code --
# see tests/test_matching.py::InternalCodeRegexTests for the explicit
# partial-match-prevention cases this depends on.
INTERNAL_CODE = re.compile(r"\b(?:IC-\d{4,6}|630\d{4,6})\b", re.IGNORECASE)

# Generic dosage-form / unit / connector words that must never be treated as
# a trade-name retrieval token on their own -- matching on "TABLET" or "BOX"
# alone is how a bare word would spuriously retrieve half the catalog.
_TRADE_NAME_STOPWORDS = frozenset(
    {
        "TAB", "TABS", "TABLET", "TABLETS", "CAP", "CAPS", "CAPSULE", "CAPSULES",
        "SYRUP", "SPRAY", "INJ", "INJECTION", "CREAM", "GEL", "SOLUTION", "SOL",
        "DROP", "DROPS", "OINTMENT", "SUSP", "SUSPENSION", "POWDER", "LOTION",
        "PATCH", "SACHET",
        "BOX", "BOTTLE", "PACK", "PIECE", "PIECES", "SET", "UNIT", "UNITS",
        "WITH", "AND", "THE", "FOR", "PER",
        # NOTE: "PLUS" was removed from this list -- it is a legitimate,
        # load-bearing part of many real trade names ("ALPHA PLUS", brand
        # "X PLUS"/"X FORTE"/"X EXTRA" naming patterns), not a generic
        # connector word. Filtering it out let a shorter competitor name
        # ("ALPHA 10 MG") win over the actual exact match ("ALPHA PLUS 10
        # MG") purely because the retrieval token pool lost its most
        # specific word. See tests/test_matching.py::ExactNameBeforeTradeNameTests.
    }
)
_MIN_TRADE_NAME_TOKEN_LEN = 4

# Thai script carries more information per character than Latin script (no
# vowel-only or two-letter function words the way English has "OF"/"TO"),
# so a Thai retrieval token can safely be shorter than the Latin minimum
# above while still being specific enough to serve as retrieval evidence.
_MIN_THAI_TRADE_NAME_TOKEN_LEN = 3

# Thai equivalents of the generic dosage-form/unit/connector words above --
# same purpose: "เม็ด" (tablet) or "ยา" (drug/medicine, appears in nearly
# every Thai product name) alone must never be treated as trade-name
# retrieval evidence, exactly like "TABLET" or "MEDICINE" would not be.
_THAI_TRADE_NAME_STOPWORDS = frozenset(
    {
        "ยา", "เม็ด", "แคปซูล", "ครีม", "เจล", "น้ำเชื่อม", "ยาน้ำ", "หยด",
        "สเปรย์", "ฉีด", "ขี้ผึ้ง", "ผง", "โลชั่น", "แผง", "ขวด", "กล่อง",
        "ชิ้น", "และ", "หรือ", "กับ", "สำหรับ", "ของ",
    }
)

# A token that appears in more than this many DISTINCT master products is
# treated as too generic to serve as sole retrieval evidence (a manufacturer/
# brand-line prefix like "MEDLINE" spans dozens of unrelated items, and a
# supplier's own name is a WHO, never a WHAT). Only usable in combination
# with a more specific token in the same line.
_GENERIC_TOKEN_MAX_PRODUCTS = 5

_STRENGTH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(MG|MCG|G|ML|IU|MEQ)\b")
_PACK_DIM_RE = re.compile(r"(\d+)\s*X\s*(\d+)")

# Canonical dosage-form categories. Variant spellings collapse to one key so
# "TAB" and "TABLET" are recognized as the same form; the guard below treats
# two DIFFERENT categories appearing on both sides as a hard contradiction
# (a tablet can never be the same SKU as a syrup, cream, or drops).
_DOSAGE_FORM_MAP = {
    "TABLET": "TABLET", "TAB": "TABLET", "TABS": "TABLET", "TABLETS": "TABLET",
    "CAPSULE": "CAPSULE", "CAP": "CAPSULE", "CAPS": "CAPSULE", "CAPSULES": "CAPSULE",
    "SYRUP": "SYRUP",
    "CREAM": "CREAM",
    "GEL": "GEL",
    "SOLUTION": "SOLUTION", "SOL": "SOLUTION",
    "DROP": "DROP", "DROPS": "DROP",
    "SPRAY": "SPRAY",
    "INJECTION": "INJECTION", "INJ": "INJECTION",
    "OINTMENT": "OINTMENT",
    "SUSPENSION": "SUSPENSION", "SUSP": "SUSPENSION",
    "POWDER": "POWDER",
    "LOTION": "LOTION",
    "PATCH": "PATCH",
    "SACHET": "SACHET",
}
_DOSAGE_FORM_RE = re.compile(r"[A-Z]+")

# Thai equivalents of the same canonical dosage-form categories (Slice 2) --
# the contradiction guard must work the same way regardless of which
# language the OCR text or the master name happens to be in; a Thai "เม็ด"
# (tablet) contradicting an English "SYRUP" is exactly as real a
# contradiction as "TABLET" vs "SYRUP" would be.
_THAI_DOSAGE_FORM_MAP = {
    "เม็ด": "TABLET",
    "แคปซูล": "CAPSULE",
    "น้ำเชื่อม": "SYRUP", "ยาน้ำ": "SYRUP",
    "ครีม": "CREAM",
    "เจล": "GEL",
    "สารละลาย": "SOLUTION",
    "หยด": "DROP",
    "สเปรย์": "SPRAY",
    "ฉีด": "INJECTION", "ยาฉีด": "INJECTION",
    "ขี้ผึ้ง": "OINTMENT",
    "ยาแขวนตะกอน": "SUSPENSION",
    "ผง": "POWDER",
    "โลชั่น": "LOTION",
    "แผ่นแปะ": "PATCH",
    "ซอง": "SACHET",
}
_THAI_DOSAGE_FORM_RE = re.compile(r"[ก-๙]+")


def normalize_supplier_sku(value: str | None) -> str | None:
    """Normalizes a supplier SKU the same way product text is normalized, so
    it can be compared for EXACT equality against an alias key. This is a
    thin, separately-named wrapper around `normalize_product_text` (not a
    different algorithm) so every call site that touches a supplier SKU
    reads as domain-explicit about what it's handling -- a supplier SKU is
    an OPAQUE, supplier-specific identifier, never an internal product code
    and never a barcode, even when it happens to look like one (real
    supplier catalogs sometimes assign SKUs that coincidentally resemble an
    `IC-XXXXXX` or `630XXXXXX` shape, or a barcode-length digit run). Slice 1
    of the field-contract rework (see docs/DEV_LAPTOP_SETUP_LEDGER_TH.md
    section 16) exists specifically to stop those coincidental shapes from
    being silently promoted to EXACT_CODE/EXACT_BARCODE."""
    return normalize_product_text(value) if value else None


def normalized_phrase_in_text(phrase: str, text: str) -> bool:
    """Match a normalized alias as a complete whitespace-delimited phrase.

    Both values must already use ``normalize_product_text``. This deliberately
    rejects character-substring matches such as ``PARA`` inside ``XPARAX``;
    for Thai it applies the same explicit phrase-boundary contract and does
    not guess word boundaries inside an unspaced Thai run.
    """
    if not phrase or not text:
        return False
    return re.search(rf"(?:^| ){re.escape(phrase)}(?: |$)", text) is not None


def extract_trade_name_tokens(normalized_text: str) -> list[str]:
    """Words specific enough to serve as a safe trade-name retrieval key:
    long enough (four characters for Latin words, three for Thai words --
    see `_MIN_THAI_TRADE_NAME_TOKEN_LEN`), no digit (strength/pack numbers
    are handled separately as attributes, not as name tokens), and not a
    generic dosage-form/unit/connector word IN ITS OWN SCRIPT (Thai and
    Latin stopword lists are both checked; a mixed Thai+English line
    naturally produces a mix of Thai and Latin tokens since
    `normalize_product_text` never merges the two scripts together). Sorted
    longest first so more specific tokens are tried before shorter, more
    ambiguous ones. Supplier/manufacturer-name exclusion happens later, in
    ProductMatcher._trade_name_candidates, where the invoicing document's
    own supplier is known -- this function has no document context."""
    tokens: list[str] = []
    for word in normalized_text.split():
        if any(ch.isdigit() for ch in word):
            continue
        script = detect_script(word)
        if script == "THAI":
            if len(word) < _MIN_THAI_TRADE_NAME_TOKEN_LEN or word in _THAI_TRADE_NAME_STOPWORDS:
                continue
        else:
            # LATIN or MIXED (a token can't actually be MIXED post-normalize
            # since Thai/Latin runs are whitespace-separated by
            # normalize_product_text, but treat conservatively as Latin-rule
            # if it ever happens) -- use the original English-tuned rule.
            if len(word) < _MIN_TRADE_NAME_TOKEN_LEN or word in _TRADE_NAME_STOPWORDS:
                continue
        tokens.append(word)
    seen: set[str] = set()
    ordered: list[str] = []
    for word in sorted(tokens, key=len, reverse=True):
        if word not in seen:
            seen.add(word)
            ordered.append(word)
    return ordered


# --- B2: fused dosage-form suffix recovery -----------------------------------
# A real Community Pharmacy invoice line lost the space between the trade name
# and the dosage form: `CODIPHENTABLET(XIOS)`. Tokenizing that yields the single
# junk token "CODIPHENTABLET", which matches no product, so retrieval fell all
# the way through to the character-level fuzzy sweep and proposed an unrelated
# product. Splitting a KNOWN dosage-form suffix back off restores the real trade
# name token ("CODIPHEN") without inventing anything.
#
# This is deliberately NOT dictionary segmentation. It is a closed allowlist of
# dosage forms, applied at most once per token, and it only fires when the
# remaining prefix is itself long enough to be a legitimate trade-name token.
# Note what is absent: "TABLE". Splitting generic furniture/packaging words is
# exactly the failure this whole change exists to prevent, so "BEDSIDETABLE" and
# "VEGETABLE" are left alone -- only "TABLET" (the dosage form) is recoverable.
_FUSED_DOSAGE_FORM_SUFFIXES = ("TABLET", "CAPSULE", "OINTMENT", "SYRUP", "CREAM")


def recover_fused_dosage_form(normalized_text: str) -> str:
    """Splits a fused known dosage-form suffix off each token.

    `CODIPHENTABLET` -> `CODIPHEN TABLET`; `BEDSIDETABLE`, `VEGETABLE`,
    `ICECREAM`, and a bare `TABLET` are all returned unchanged.

    This is MATCHING NORMALIZATION ONLY. It never rewrites OCR evidence: the
    caller keeps the original `source_text`/`normalized_text` for audit and uses
    the recovered string purely as a retrieval key.
    """
    if not normalized_text:
        return normalized_text
    recovered: list[str] = []
    for word in normalized_text.split():
        recovered.append(_split_fused_suffix(word))
    return " ".join(recovered)


def _split_fused_suffix(word: str) -> str:
    if any(character.isdigit() for character in word) or detect_script(word) == "THAI":
        return word
    for suffix in _FUSED_DOSAGE_FORM_SUFFIXES:
        if not word.endswith(suffix) or word == suffix:
            continue
        prefix = word[: -len(suffix)]
        # The prefix must stand on its own as trade-name evidence. Without this,
        # a short accidental ending would manufacture a bogus token, and the
        # whole point of the split is to RECOVER a real one.
        if len(prefix) < _MIN_TRADE_NAME_TOKEN_LEN or prefix in _TRADE_NAME_STOPWORDS:
            return word
        # At most one split per token -- no recursive segmentation.
        return f"{prefix} {suffix}"
    return word


# --- B1: fuzzy-sweep evidence guard ------------------------------------------
# Tokens that describe a dosage form, a package, or a piece of furniture are
# shared by hundreds of unrelated products. Character-level SequenceMatcher
# similarity that rests ONLY on words like these is not product evidence, it is
# coincidence -- the real defect this guards was `CODIPHENTABLET(XIOS)` scoring
# 0.5000 against "BEDSIDE TABLE ABS 1 S". "TABLE" is listed here rather than in
# `_TRADE_NAME_STOPWORDS` on purpose: real furniture products legitimately carry
# it in their master names, so it must stay usable for ordinary retrieval and be
# rejected only as SOLE fuzzy evidence. NOTE: this hand-picked set does NOT
# close the generic-token hole -- "สามัญ" alone reaches 2,804 of 6,671 master
# products. Applying the existing _GENERIC_TOKEN_MAX_PRODUCTS doctrine here was
# built, measured and REJECTED (catalog frequency is not specificity: a
# multi-SKU brand family makes its most diagnostic token look generic, which
# blocked a correct product and admitted a wrong one). Do not re-derive it --
# see docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 38, open finding (a).
_FUZZY_GENERIC_EVIDENCE_TOKENS = frozenset(
    {"TABLE", "TABLES", "STAND", "CASE", "BAG", "TUBE", "STRIP", "BLISTER", "CARTON", "REFILL", "SIZE", "TYPE", "MODEL"}
)


# Thai is written WITHOUT word spaces, so `normalize_product_text` cannot split
# a Thai run into words the way it does for Latin -- a whole Thai phrase arrives
# as ONE agglutinated token. Requiring exact token equality there is therefore
# not "strict", it is simply wrong: the master name "ยาพาราเซตามอล" (ya- =
# "medicine" prefix) and the invoice's "พาราเซตามอล" are the same drug and share
# no exact token. Latin tokens are already whitespace-separated words, so they
# stay on exact equality -- which is what keeps a fused "CODIPHENTABLET" from
# matching "CODIPHEN" by containment before the B2 split has run. See
# docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 38: this guard as first committed
# demanded exact equality and turned a correct 0.9474 Thai match into
# UNRESOLVED.
_MIN_THAI_CONTAINMENT_LEN = 4

# `normalize_product_text` rewrites Thai SARA AM (U+0E33 "ำ") into its decomposed
# NIKHAHIT+SARA AA form, so a stopword written the composed way can never equal a
# token that has been through the normalizer ("ยาน้ำ" -> "ยาน้ํา"). The guard
# below compares NORMALIZED tokens, so it must compare them against NORMALIZED
# stopwords or the Thai half of its generic-word filter silently does nothing.
# Scope note: this local set fixes the comparison INSIDE this guard only. The
# same composed/decomposed mismatch also affects `_THAI_TRADE_NAME_STOPWORDS` as
# used by `extract_trade_name_tokens`, and `_THAI_DOSAGE_FORM_MAP` as used by
# `extract_attributes` -- both pre-date this change and are reported as separate
# findings rather than altered here, because fixing them shifts existing
# retrieval and contradiction behaviour well beyond this remediation. Both are
# logged as open findings (b) and (c) in docs/DEV_LAPTOP_SETUP_LEDGER_TH.md
# section 38.
_THAI_TRADE_NAME_STOPWORDS_NORMALIZED = frozenset(
    normalize_product_text(word) for word in _THAI_TRADE_NAME_STOPWORDS
) | _THAI_TRADE_NAME_STOPWORDS


def meaningful_shared_tokens(source_normalized: str, candidate_normalized: str) -> set[str]:
    """Trade-name tokens present on BOTH sides, excluding generic dosage-form,
    packaging, and furniture words. A non-empty result is the minimum evidence
    the fuzzy tier needs before it may propose a product at all.

    Latin: exact token equality. Thai: exact equality OR containment of one
    agglutinated run inside the other (see `_MIN_THAI_CONTAINMENT_LEN`), because
    Thai has no word boundaries to tokenize on.
    """
    source = set(extract_trade_name_tokens(source_normalized)) - _FUZZY_GENERIC_EVIDENCE_TOKENS
    candidate = set(extract_trade_name_tokens(candidate_normalized)) - _FUZZY_GENERIC_EVIDENCE_TOKENS
    shared = source & candidate
    for source_token in source - shared:
        if detect_script(source_token) != "THAI":
            continue
        for candidate_token in candidate - shared:
            if detect_script(candidate_token) != "THAI":
                continue
            shorter, longer = sorted((source_token, candidate_token), key=len)
            if (
                len(shorter) >= _MIN_THAI_CONTAINMENT_LEN
                and shorter in longer
                and shorter not in _THAI_TRADE_NAME_STOPWORDS_NORMALIZED
            ):
                shared.add(shorter)
    return shared


def within_edit_distance_one(a: str, b: str) -> bool:
    """True when `a` can become `b` via at most one single-character
    insertion, deletion, or substitution. Used for the "คุณหมายถึง...หรือไม่"
    ("did you mean...?") spelling-suggestion tier -- a cheap, dependency-free
    check (no full Levenshtein DP table needed) that catches the single most
    common real OCR failure mode: one character read wrong, dropped, or
    doubled (e.g. "MINIDIAP" vs "MINIDIAB", one substitution)."""
    if a == b:
        return False  # not a correction, it's the same token
    len_a, len_b = len(a), len(b)
    if abs(len_a - len_b) > 1:
        return False
    if len_a == len_b:
        differences = sum(1 for x, y in zip(a, b) if x != y)
        return differences == 1
    # One is exactly one character longer -- check if deleting that one
    # character from the longer string yields the shorter string.
    shorter, longer = (a, b) if len_a < len_b else (b, a)
    i = j = 0
    skipped = False
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
        elif not skipped:
            skipped = True
            j += 1
        else:
            return False
    return True


def extract_attributes(text: str) -> dict:
    """Strength (value+unit), pack-dimension (AxB), and dosage-form tokens
    found in a piece of text, used only as a contradiction guard -- never
    as a positive-match requirement, since either side (OCR text or a
    master product's name) may simply omit an attribute. Dosage-form
    detection is bilingual (Slice 2): both English and Thai dosage words
    are recognized and mapped to the SAME canonical category set, so a
    Thai-language OCR line and an English-language master name still
    correctly contradict (or agree) with each other."""
    upper = (text or "").upper()
    strengths = {(float(value), unit) for value, unit in _STRENGTH_RE.findall(upper)}
    packs = {(int(a), int(b)) for a, b in _PACK_DIM_RE.findall(upper)}
    dosage_forms = {_DOSAGE_FORM_MAP[word] for word in _DOSAGE_FORM_RE.findall(upper) if word in _DOSAGE_FORM_MAP}
    dosage_forms |= {_THAI_DOSAGE_FORM_MAP[word] for word in _THAI_DOSAGE_FORM_RE.findall(upper) if word in _THAI_DOSAGE_FORM_MAP}
    return {"strengths": strengths, "packs": packs, "dosage_forms": dosage_forms}


def decode_line_evidence(raw: object) -> dict:
    """Decodes `document_lines.evidence_json` at exactly ONE boundary,
    regardless of which path it arrived through:

    - In-process callers (tests, and any future in-memory pipeline stage)
      may hand `_predict` an already-decoded dict directly.
    - The real production path goes through `Repository.list_lines()`,
      which returns raw SQLite rows as-is -- `evidence_json` there is the
      `TEXT` column exactly as written by `canonical_json(...)` at import
      time (see `Repository.import_ocr_projection`), i.e. a JSON STRING,
      never a dict.

    Every evidence reader (barcode/internal-code candidates) must go
    through this function so both paths behave identically. Before this
    existed, `_barcode_candidates` checked `isinstance(evidence, dict)`
    directly -- true in every offline test (which builds `line` dicts by
    hand) but false for every real persisted line, so EXACT_BARCODE could
    never actually fire in production despite passing 4/4 tests. See
    docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 17 (Codex finding 2)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def attributes_conflict(a: dict, b: dict) -> bool:
    """True only when both sides state a value for the same attribute and
    the stated values disagree. Silence on either side is never treated as
    a contradiction -- most real master names omit pack size entirely, and
    penalizing that would make the guard reject good matches as often as
    bad ones."""
    if a["strengths"] and b["strengths"]:
        shared_units = {unit for _, unit in a["strengths"]} & {unit for _, unit in b["strengths"]}
        if shared_units:
            a_values = {value for value, unit in a["strengths"] if unit in shared_units}
            b_values = {value for value, unit in b["strengths"] if unit in shared_units}
            if not (a_values & b_values):
                return True
    if a["packs"] and b["packs"] and not (a["packs"] & b["packs"]):
        return True
    if a["dosage_forms"] and b["dosage_forms"] and not (a["dosage_forms"] & b["dosage_forms"]):
        return True
    return False


class ProductMatcher:
    # layer-f-v2: inserted a trade-name token-retrieval tier
    # (TRADE_NAME_MATCH, never auto-confirmable) between ACTIVE_ALIAS and
    # EXACT_NAME, with ingredient/strength/pack-size/dosage-form
    # contradiction guards, generic-token and supplier-name exclusion, and
    # a tie-detection rule that refuses to auto-pick among equally-ranked
    # candidates; widened INTERNAL_CODE to recognize real six/nine-digit
    # codes; and gave trade-name candidates a normalized numeric [0,1]
    # confidence instead of a placeholder string. Later within v2: moved
    # EXACT_NAME ahead of TRADE_NAME_MATCH, dropped product-name length from
    # the trade-name tie key, and un-stopworded "PLUS" (see
    # tests/test_matching.py::ExactNameBeforeTradeNameTests).
    #
    # Bumped to layer-f-v3 (Slice 1 -- field-contract separation, see
    # docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 16): internal-code scanning
    # no longer reads supplier_sku (only description_final/raw_ocr_text);
    # supplier_sku is no longer passed to find_by_barcode -- EXACT_BARCODE
    # now requires explicit evidence_json["barcode_candidates"] evidence,
    # supports multiple candidate barcodes resolving to the same product,
    # and quarantines the line (UNRESOLVED, no downstream tier may
    # override) when candidates resolve to different products; ACTIVE_ALIAS
    # gained an exact (supplier_code, normalized_supplier_sku) lookup path
    # ahead of the pre-existing free-text substring path.
    #
    # Slice 1 remediation round 1 (still layer-f-v3 at the time -- see
    # docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 17, Codex's second
    # adjudication of this slice): (1) evidence_json is now decoded through
    # one shared boundary (`decode_line_evidence`) that accepts both an
    # already-decoded dict (offline tests) and the raw JSON TEXT a real DB
    # round trip actually returns -- EXACT_BARCODE could never fire in
    # production before this; (2) EXACT_CODE's free-text fallback now
    # rejects any digit run identical to this line's own supplier_sku (OCR
    # text routinely echoes the printed SKU inline, which must not shadow a
    # correct supplier alias), and gained an explicit-provenance path via
    # evidence_json["internal_code_candidates"].
    #
    # Slice 1 remediation round 2 (still layer-f-v3 at the time -- see
    # docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 18, Codex's third
    # adjudication): EXACT_CODE now auto-confirms ONLY from
    # explicit-provenance evidence; a free-text digit-run hit with no
    # provenance is downgraded to the new, never-auto-confirmable
    # INTERNAL_CODE_TEXT_MATCH tier (inserted after EXACT_NAME, before
    # TRADE_NAME_MATCH); explicit internal-code evidence that resolves to
    # more than one distinct product now quarantines (UNRESOLVED), mirroring
    # the existing barcode-conflict rule, instead of silently picking the
    # first array entry.
    #
    # Bumped to layer-f-v4 (Slice 1 remediation round 3 -- see
    # docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 19, Codex's fourth
    # adjudication of this slice): the matching rules themselves did not
    # change in this round, but the AUDIT CONTRACT did -- `input_hash` now
    # includes the normalized identifier evidence (supplier_sku,
    # barcode_candidates, internal_code_candidates) that rounds 1-2 added as
    # real matching inputs, so two predictions that differ only in that
    # evidence (e.g. "no evidence -> UNRESOLVED" vs "explicit code evidence
    # -> EXACT_CODE") are no longer indistinguishable after the fact by
    # input_hash alone.
    #
    # Bumped to layer-f-v5 (Slice 1 remediation round 4 -- see
    # docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 20, Codex's fifth
    # adjudication): same shape of gap, one more field. `unit_final` feeds
    # `proposed_unit_code` directly but was never in the hash -- "BOX" vs
    # "EACH" changed the output with no corresponding change recorded on the
    # input side. Added the normalized `unit_final` value. Also split the
    # previously-blended `text` field (which merged description_final,
    # raw_ocr_text, AND supplier_sku into one opaque normalized string) into
    # independently-hashed `description_final` and `raw_ocr_text` fields,
    # since the matcher gives those two genuinely different roles (see the
    # comment above `input_payload` in `_predict` for specifics) and a
    # single merged string could hide which one actually changed. Bumping
    # RULESET_VERSION again marks that the input_hash formula in effect for
    # every Slice-1-remediated prediction differs from what `layer-f-v4`
    # denoted for anything predicted before this round.
    #
    # Bumped to layer-f-v6 for Slice 2 (see ledger sections 22-25): product
    # names are searched as independent Thai/English fields; Thai/mixed
    # token and dosage-form handling, approved global spelling aliases,
    # review-only spelling suggestions, and the fuzzy attribute guard all
    # materially change the matching rules compared with sealed Slice 1.
    RULESET_VERSION = "layer-f-v6"

    def __init__(self, repository: Repository, cache: AdaReferenceCache) -> None:
        self.repository = repository
        self.cache = cache

    def predict_and_persist(self, document: dict, line: dict, ocr_versions: dict) -> dict:
        prediction = self._predict(document, line, ocr_versions)
        persisted = self.repository.persist_prediction_before_display(document["id"], line["id"], prediction)
        # The DTO is assembled only after the insert transaction committed and was read back.
        return {"prediction_id": persisted["id"], "tier": persisted["tier"], "method": persisted["method"], "product_code": persisted["proposed_product_code"], "unit_code": persisted["proposed_unit_code"], "candidates": prediction["candidate_set"], "provenance": prediction["provenance"]}

    def _supplier_name_tokens(self, document: dict) -> set[str]:
        """Words identifying WHO sold the item (the invoicing supplier's own
        code and/or master-registered name), never usable alone as evidence
        of WHAT the item is."""
        tokens: set[str] = set()
        supplier_code = document.get("supplier_code") or ""
        tokens.update(normalize_product_text(supplier_code).split())
        try:
            supplier_row = self.cache.get_supplier(supplier_code)
        except Exception:
            supplier_row = None
        if supplier_row and supplier_row.get("name"):
            tokens.update(normalize_product_text(supplier_row["name"]).split())
        return {t for t in tokens if t}

    def _barcode_candidates(self, line: dict) -> list[str]:
        """Explicit barcode evidence for this line, if any. Deliberately
        reads ONLY `evidence_json["barcode_candidates"]` (already-existing,
        schema-unchanged JSON evidence column, decoded through
        `decode_line_evidence` so this works identically whether `line`
        came from an in-process caller or a real DB round trip) -- never
        `supplier_sku` and never free OCR text. A barcode is meaningful
        evidence only when an upstream stage specifically tagged it as a
        barcode (a decoded barcode symbol, or an invoice field explicitly
        labeled barcode/EAN/UPC); a bare digit run that merely LOOKS like a
        barcode is not barcode evidence and must never be promoted here."""
        evidence = decode_line_evidence(line.get("evidence_json"))
        raw = evidence.get("barcode_candidates") or []
        if not isinstance(raw, (list, tuple)):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    def _internal_code_candidates(self, line: dict) -> list[str]:
        """Explicit internal-code evidence for this line, if any -- read
        from `evidence_json["internal_code_candidates"]` (same
        evidence-provenance pattern and decode boundary as barcode
        evidence). When an upstream stage has tagged specific text as the
        shop's own internal code, that is trusted directly and the free-OCR
        -text regex fallback in `_predict` is skipped entirely for this
        line."""
        evidence = decode_line_evidence(line.get("evidence_json"))
        raw = evidence.get("internal_code_candidates") or []
        if not isinstance(raw, (list, tuple)):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    def _trade_name_candidates(
        self,
        document: dict,
        source_attrs: dict,
        normalized: str,
        description_normalized: str,
        override_tokens: list[str] | None = None,
    ) -> tuple[list[tuple[dict, str]], bool]:
        """Returns (ranked [(product, score_string), ...] up to 5, is_tied).
        is_tied is True when the top two survivors are equally well
        supported after every guard -- callers must not auto-pick a "first"
        candidate in that case.

        `override_tokens`, when given, is used verbatim INSTEAD of
        extracting tokens from `normalized`/`description_normalized` --
        this is how the SPELLING_SUGGESTION tier (see
        `_spelling_suggestion_candidates`) reuses every guard in this
        method (generic-token exclusion, attribute-contradiction blocking,
        tie detection) against a spelling-corrected token list, instead of
        duplicating this logic against a second, less-tested code path."""
        if override_tokens is not None:
            tokens = override_tokens
        else:
            tokens = extract_trade_name_tokens(normalized) or extract_trade_name_tokens(description_normalized)
            supplier_tokens = self._supplier_name_tokens(document)
            tokens = [t for t in tokens if t not in supplier_tokens]
        if not tokens:
            return [], False

        products = self.cache.list_products()
        # Bilingual retrieval haystack (Slice 2): built from name_thai AND
        # name_eng independently, never a COALESCE-collapsed single name --
        # a product with only an English or only a Thai name still works
        # (the missing field is simply None/omitted from the join), and a
        # product with BOTH is searchable by either language's tokens in
        # the same pass.
        haystacks = {
            product["product_code"]: normalize_product_text(
                " ".join(filter(None, [product.get("name_thai"), product.get("name_eng"), product.get("ingredient") or ""]))
            )
            for product in products
        }

        def word_hit(token: str, haystack: str) -> bool:
            return re.search(rf"\b{re.escape(token)}\b", haystack) is not None

        token_product_counts = {
            token: sum(1 for haystack in haystacks.values() if word_hit(token, haystack)) for token in tokens
        }
        specific_tokens = [t for t in tokens if token_product_counts[t] <= _GENERIC_TOKEN_MAX_PRODUCTS]

        matched: list[tuple[dict, list[str]]] = []
        for require_all, token_pool in ((True, tokens), (False, specific_tokens)):
            if not token_pool:
                continue
            matched = []
            for product in products:
                haystack = haystacks[product["product_code"]]
                hits = [token for token in token_pool if word_hit(token, haystack)]
                if not hits:
                    continue
                if require_all and len(hits) < len(token_pool):
                    continue
                matched.append((product, hits))
            if matched:
                break
        if not matched:
            return [], False

        survivors: list[tuple[dict, list[str], dict]] = []
        for product, hits in matched:
            candidate_text = " ".join(
                filter(None, [product.get("name_thai"), product.get("name_eng"), product.get("strength") or "", product.get("size") or ""])
            )
            candidate_attrs = extract_attributes(candidate_text)
            if attributes_conflict(source_attrs, candidate_attrs):
                continue
            survivors.append((product, hits, candidate_attrs))
        if not survivors:
            return [], False

        def agreement_count(candidate_attrs: dict) -> int:
            return (
                len(source_attrs["strengths"] & candidate_attrs["strengths"])
                + len(source_attrs["packs"] & candidate_attrs["packs"])
                + len(source_attrs["dosage_forms"] & candidate_attrs["dosage_forms"])
            )

        def tie_key(entry: tuple[dict, list[str], dict]) -> tuple:
            # Deliberately just (hit count, attribute agreement) -- these
            # are the only two things that are actual EVIDENCE about which
            # candidate is more likely correct. Name length is NOT evidence
            # (a shorter catalog name is not more or less likely to be the
            # right product) and must never decide a match: including it
            # here previously let two equally-supported candidates escape
            # tie-detection just because one product's name happened to be
            # shorter, silently picking the wrong one as often as the right
            # one. See tests/test_matching.py::ExactNameBeforeTradeNameTests
            # ::test_trade_name_tie_is_not_broken_by_shorter_product_name.
            product, hits, candidate_attrs = entry
            return (-len(hits), -agreement_count(candidate_attrs))

        # product_code is a purely cosmetic, deterministic sort tiebreaker
        # for DISPLAY ordering only -- it must never be read back to decide
        # is_tied (that check uses tie_key alone, which excludes it).
        survivors.sort(key=lambda entry: tie_key(entry) + (entry[0]["product_code"],))
        is_tied = len(survivors) >= 2 and tie_key(survivors[0]) == tie_key(survivors[1])

        ranked: list[tuple[dict, str]] = []
        for product, hits, candidate_attrs in survivors[:5]:
            coverage = len(hits) / len(tokens) if tokens else 0.0
            score = 0.5 + 0.3 * coverage + 0.05 * min(agreement_count(candidate_attrs), 2)
            ranked.append((product, f"{min(score, 0.90):.4f}"))
        return ranked, is_tied

    def _spelling_suggestion_candidates(
        self, document: dict, source_attrs: dict, normalized: str, description_normalized: str
    ) -> tuple[list[tuple[dict, str]], bool, dict[str, str]]:
        """"คุณหมายถึง...หรือไม่" -- Slice 2's spelling/typo suggestion tier.
        Only meaningful when ordinary trade-name retrieval found NOTHING at
        all for this line (checked by the caller before invoking this): for
        each OCR token that has zero hits anywhere in the catalog, looks for
        a catalog vocabulary token within one single-character edit (see
        `within_edit_distance_one`) that is NOT itself an over-generic token
        (same `_GENERIC_TOKEN_MAX_PRODUCTS` threshold as ordinary retrieval),
        then reruns trade-name retrieval with the corrected token substituted
        in -- reusing every existing guard (attribute-contradiction
        blocking, tie detection, generic-token exclusion) via
        `_trade_name_candidates(override_tokens=...)` rather than
        duplicating that logic. Returns (ranked candidates, is_tied,
        {original_token: corrected_token} for every correction actually
        applied) -- the corrections dict is empty when no plausible
        correction was found for anything, which the caller uses to decide
        whether to report `SPELLING_SUGGESTION` at all."""
        tokens = extract_trade_name_tokens(normalized) or extract_trade_name_tokens(description_normalized)
        supplier_tokens = self._supplier_name_tokens(document)
        tokens = [t for t in tokens if t not in supplier_tokens]
        if not tokens:
            return [], False, {}

        products = self.cache.list_products()
        haystacks = {
            product["product_code"]: normalize_product_text(
                " ".join(filter(None, [product.get("name_thai"), product.get("name_eng"), product.get("ingredient") or ""]))
            )
            for product in products
        }
        vocabulary_counts: dict[str, int] = {}
        for haystack in haystacks.values():
            for word in set(extract_trade_name_tokens(haystack)):
                vocabulary_counts[word] = vocabulary_counts.get(word, 0) + 1

        corrections: dict[str, str] = {}
        for token in tokens:
            if token in vocabulary_counts:
                continue  # a real hit exists; ordinary retrieval already tried this token
            best_match: str | None = None
            for candidate_word, count in vocabulary_counts.items():
                if count > _GENERIC_TOKEN_MAX_PRODUCTS:
                    continue
                if not within_edit_distance_one(token, candidate_word):
                    continue
                if best_match is None or (count, len(candidate_word)) < (vocabulary_counts[best_match], len(best_match)):
                    # Prefer the LEAST generic (lowest product count) match,
                    # and among equally-specific matches the longer/more
                    # descriptive one -- the same "specific evidence wins"
                    # principle ordinary retrieval already follows.
                    best_match = candidate_word
            if best_match:
                corrections[token] = best_match
        if not corrections:
            return [], False, {}

        corrected_tokens = [corrections.get(t, t) for t in tokens]
        ranked, is_tied = self._trade_name_candidates(
            document, source_attrs, normalized, description_normalized, override_tokens=corrected_tokens
        )
        return ranked, is_tied, corrections

    def _predict(self, document: dict, line: dict, ocr_versions: dict) -> dict:
        # --- Field contract (Slice 1) ---------------------------------------
        # Three inputs carry fundamentally different meaning and must never
        # be conflated, even when one happens to look like another:
        #   - description_final / raw_ocr_text: free OCR text on the invoice
        #     line. This is the ONLY source scanned for an explicit internal
        #     product code (IC-XXXXXX / 630XXXXXX).
        #   - supplier_sku: an OPAQUE, supplier-specific identifier. It is
        #     the wholesaler's own code, not the shop's internal code, and
        #     it is never treated as a barcode. Its only role in matching is
        #     as the exact key half of a (supplier_code, normalized SKU)
        #     alias lookup -- never free-text scanning.
        #   - evidence_json["barcode_candidates"]: explicit barcode evidence
        #     (e.g. a decoded barcode symbol, or an invoice field an
        #     upstream stage specifically labeled as a barcode/EAN/UPC).
        #     Barcodes can legitimately change over time and a product can
        #     have more than one on file -- see the EXPLICIT BARCODE
        #     evidence block below for how that is handled safely.
        # `source_text` (used only for the audit-facing `source_text` output
        # field, never for code/barcode matching) keeps including
        # supplier_sku so a human reviewer can still see it was present.
        source_text = " ".join(filter(None, [line.get("supplier_sku"), line.get("description_final"), line.get("raw_ocr_text")]))
        code_scan_text = " ".join(filter(None, [line.get("description_final"), line.get("raw_ocr_text")]))
        normalized = normalize_product_text(source_text)
        description_normalized = normalize_product_text(line.get("description_final") or "")
        # B2: retrieval-only views of the same text, with a fused known
        # dosage-form suffix split back off (`CODIPHENTABLET` ->
        # `CODIPHEN TABLET`). `normalized`/`description_normalized` above are
        # the AUDIT values and stay exactly as the OCR produced them -- they are
        # what gets hashed into `input_hash` and reported as `normalized_text`.
        # Nothing below rewrites the stored evidence.
        normalized_retrieval = recover_fused_dosage_form(normalized)
        description_retrieval = recover_fused_dosage_form(description_normalized)
        supplier_sku_normalized = normalize_supplier_sku(line.get("supplier_sku"))
        candidates: list[dict] = []
        selected: dict | None = None
        quarantined = False
        tier, method, reasons = "UNRESOLVED", "unresolved_human", ["NO_MASTER_CANDIDATE_RESOLVED"]

        # EXPLICIT INTERNAL CODE. `EXACT_CODE` auto-confirms ONLY from
        # explicit-provenance evidence now -- docs/DEV_LAPTOP_SETUP_LEDGER_TH.md
        # section 18 (Codex's second Slice-1 re-adjudication) proved the
        # earlier supplier_sku-equality exclusion was not enough on its own:
        # it only protects a line where `supplier_sku` was actually parsed.
        # A line where the wholesaler code appears in free OCR text but the
        # parser failed to populate the structured `supplier_sku` field
        # would still sail through the fallback regex scan and auto-confirm
        # the wrong product -- an entirely plausible OCR failure mode, not a
        # contrived edge case. The fix is structural, not another exclusion
        # rule: a bare digit run found by scanning free text is no longer
        # trusted enough to auto-confirm AT ALL, regardless of whether it
        # happens to collide with `supplier_sku`.
        #
        # Two provenance paths now exist, and they are handled completely
        # differently:
        #   (a) evidence_json["internal_code_candidates"] -- an upstream
        #       stage explicitly tagged this text as the shop's own
        #       internal code. This alone is trusted enough to auto-confirm.
        #       If more than one candidate resolves to DIFFERENT real
        #       products, that is an active contradiction -- quarantine the
        #       line exactly like conflicting barcode evidence does, rather
        #       than silently picking the first array entry (Codex's second
        #       probe: `[IC-000001, IC-000002]` used to auto-confirm
        #       IC-000001 with no conflict signal at all).
        #   (b) no explicit evidence: `code_scan_text` is still scanned with
        #       the INTERNAL_CODE regex for backward compatibility (Layer F
        #       v1's documented tier-1 behavior, and the existing
        #       characterization tests), but any hit is now DOWNGRADED to a
        #       review-only candidate under the new `INTERNAL_CODE_TEXT_MATCH`
        #       tier (see below, after EXACT_NAME) -- never auto-confirmed,
        #       always `human_confirmation_required`. A hit identical to
        #       this line's own (normalized) supplier_sku, when one is
        #       present, is still excluded outright from even that
        #       downgraded candidate list -- there is no reason to dangle an
        #       almost-certainly-coincidental echoed SKU in front of a human
        #       as though it were a real signal.
        explicit_codes = self._internal_code_candidates(line)
        internal_code_text_candidates: list[dict] = []
        if explicit_codes:
            matched_internal_code_products: dict[str, dict] = {}
            for code in explicit_codes:
                product = self.cache.get_product(code.upper())
                if product:
                    matched_internal_code_products[product["product_code"]] = product
            if len(matched_internal_code_products) == 1:
                selected = next(iter(matched_internal_code_products.values()))
                tier, method, reasons = "EXACT_CODE", "exact_internal_code", ["MASTER_CODE_EXACT"]
            elif len(matched_internal_code_products) > 1:
                quarantined = True
                tier, method, reasons = "UNRESOLVED", "unresolved_human", ["INTERNAL_CODE_CONFLICT_MULTIPLE_PRODUCTS"]
                candidates = [
                    {"product_code": product["product_code"], "name": product["name"], "score": "0.0000", "purchase_count": 0}
                    for product in sorted(matched_internal_code_products.values(), key=lambda p: p["product_code"])
                ]
        else:
            seen_internal_code_products: dict[str, dict] = {}
            for code in INTERNAL_CODE.findall(code_scan_text):
                if supplier_sku_normalized and normalize_product_text(code) == supplier_sku_normalized:
                    continue
                product = self.cache.get_product(code.upper())
                if product:
                    seen_internal_code_products[product["product_code"]] = product
            internal_code_text_candidates = list(seen_internal_code_products.values())

        # EXPLICIT BARCODE evidence -- only from evidence the upstream stage
        # specifically tagged as a barcode, never derived from supplier_sku.
        # A product may have more than one barcode on file (old + new): if
        # every candidate that resolves to a product resolves to the SAME
        # product, that is confirming, auto-confirmable evidence. If they
        # resolve to DIFFERENT products, that is an active contradiction --
        # quarantine the line for a human rather than silently picking one
        # side. An unrecognized (brand-new, not-yet-in-master) barcode alone
        # is not treated as a rejection; it simply does not select anything
        # here, and the line falls through to the remaining gates instead of
        # being guessed.
        barcode_candidates = self._barcode_candidates(line)
        if selected is None and not quarantined and barcode_candidates:
            matched_products: dict[str, dict] = {}
            for candidate_barcode in barcode_candidates:
                product = self.cache.find_by_barcode(candidate_barcode)
                if product:
                    matched_products[product["product_code"]] = product
            if len(matched_products) == 1:
                selected = next(iter(matched_products.values()))
                tier, method, reasons = "EXACT_BARCODE", "exact_barcode_evidence", ["MASTER_BARCODE_EXACT"]
            elif len(matched_products) > 1:
                # Conflicting barcode evidence points at more than one real
                # product -- never auto-pick a side. Quarantine the line and
                # surface every conflicting product so a human resolves it;
                # no weaker downstream tier (alias/name/trade-name/fuzzy) is
                # allowed to paper over this contradiction.
                quarantined = True
                tier, method, reasons = "UNRESOLVED", "unresolved_human", ["BARCODE_CONFLICT_MULTIPLE_PRODUCTS"]
                candidates = [
                    {"product_code": product["product_code"], "name": product["name"], "score": "0.0000", "purchase_count": 0}
                    for product in sorted(matched_products.values(), key=lambda p: p["product_code"])
                ]

        # A named, human-approved supplier alias outranks an unapproved
        # trade-name token guess -- a curated mapping a reviewer already
        # confirmed must never be shadowed by a fresh heuristic retrieval.
        # Two independent lookup paths feed this tier:
        #   (a) EXACT (supplier_code, normalized_supplier_sku) key match --
        #       the SKU is opaque, so this must be an exact-equality lookup,
        #       never a substring scan. The same SKU from two different
        #       suppliers may legitimately point at two different products,
        #       since aliases are always scoped by supplier_code.
        #   (b) the pre-existing free-text substring match against the OCR
        #       description/raw text (unchanged from Layer F v3), for
        #       aliases recorded from description text rather than a SKU.
        aliases = self.repository.list_aliases(document["supplier_code"])
        if selected is None and not quarantined:
            sku_matches = (
                [a for a in aliases if a["status"] == "ACTIVE" and a["normalized_supplier_text"] == supplier_sku_normalized]
                if supplier_sku_normalized
                else []
            )
            if len(sku_matches) == 1:
                candidate = self.cache.get_product(sku_matches[0]["ada_product_code"])
                if candidate:
                    selected, tier, method, reasons = candidate, "ACTIVE_ALIAS", "supplier_sku_active_alias", ["SUPPLIER_SKU_ALIAS_EXACT"]
            if selected is None:
                text_scan = normalize_product_text(code_scan_text)
                active = [alias for alias in aliases if alias["status"] == "ACTIVE" and alias["normalized_supplier_text"] in text_scan]
                if len(active) == 1:
                    candidate = self.cache.get_product(active[0]["ada_product_code"])
                    if candidate:
                        selected, tier, method, reasons = candidate, "ACTIVE_ALIAS", "supplier_active_alias", ["NAMED_APPROVED_ALIAS"]

        # A full, exact, deterministic match on the entire normalized
        # description is stronger evidence than any partial token-based
        # retrieval -- it must be checked BEFORE trade-name retrieval, not
        # after. Trade-name matching is inherently lossy (it drops
        # dosage-form/unit words and, previously, wrongly dropped
        # legitimate brand-name words too); a product whose name matches
        # the OCR text word-for-word must always win over one that only
        # partially matches, and must never be shadowed by a heuristic that
        # never even sees the full string.
        if selected is None and not quarantined:
            exact_names = self.cache.find_by_normalized_name(description_normalized)
            if len(exact_names) == 1:
                selected, tier, method, reasons = exact_names[0], "EXACT_NAME", "exact_normalized_name", ["MASTER_NAME_EXACT"]

        # A globally-approved spelling/name alias is stronger than every
        # unapproved heuristic tier, but remains below explicit identifiers,
        # supplier-scoped ACTIVE_ALIAS, and deterministic EXACT_NAME. Match
        # only a complete normalized phrase; an approved alias never grants
        # permission to match arbitrary character substrings. Attribute
        # contradictions quarantine the alias proposal for human review and
        # prevent every weaker tier from erasing that conflict.
        source_attrs = extract_attributes(normalized)
        if selected is None and not quarantined:
            text_scan = normalize_product_text(code_scan_text)
            active_name_aliases = [a for a in self.repository.list_name_aliases() if a["status"] == "ACTIVE"]
            name_alias_matches = [
                alias
                for alias in active_name_aliases
                if normalized_phrase_in_text(normalize_product_text(alias["normalized_text"]), text_scan)
            ]
            resolved_alias_products: dict[str, dict] = {}
            conflicting_alias_products: dict[str, dict] = {}
            for alias in name_alias_matches:
                candidate = self.cache.get_product(alias["ada_product_code"])
                if not candidate:
                    continue
                candidate_text = " ".join(
                    filter(None, [candidate.get("name_thai"), candidate.get("name_eng"), candidate.get("strength") or "", candidate.get("size") or ""])
                )
                if attributes_conflict(source_attrs, extract_attributes(candidate_text)):
                    conflicting_alias_products[candidate["product_code"]] = candidate
                else:
                    resolved_alias_products[candidate["product_code"]] = candidate
            if conflicting_alias_products:
                quarantined = True
                tier, method, reasons = "UNRESOLVED", "unresolved_human", ["SPELLING_ALIAS_ATTRIBUTE_CONFLICT"]
                candidates = [
                    {"product_code": product["product_code"], "name": product["name"], "score": "0.0000", "purchase_count": 0}
                    for product in sorted(conflicting_alias_products.values(), key=lambda item: item["product_code"])
                ]
            elif len(resolved_alias_products) == 1:
                selected = next(iter(resolved_alias_products.values()))
                tier, method, reasons = "SPELLING_ALIAS", "approved_spelling_alias", ["NAMED_APPROVED_SPELLING_ALIAS"]
            elif len(resolved_alias_products) > 1:
                quarantined = True
                tier, method, reasons = "UNRESOLVED", "unresolved_human", ["SPELLING_ALIAS_CONFLICT_MULTIPLE_PRODUCTS"]
                candidates = [
                    {"product_code": product["product_code"], "name": product["name"], "score": "0.0000", "purchase_count": 0}
                    for product in sorted(resolved_alias_products.values(), key=lambda item: item["product_code"])
                ]

        # INTERNAL_CODE_TEXT_MATCH -- a digit run found by scanning free OCR
        # text that happens to equal a real product code, with NO explicit
        # provenance backing it. Structurally identical in spirit to
        # TRADE_NAME_MATCH: it is allowed to propose a product, but it can
        # NEVER auto-confirm (deliberately excluded from
        # AUTO_CONFIRMABLE_TIERS below) -- a human must always confirm this
        # one specifically because "the digits happen to match" is not the
        # same guarantee as "an upstream stage said this IS the internal
        # code". See docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 18.
        if selected is None and not quarantined and internal_code_text_candidates:
            selected = internal_code_text_candidates[0]
            unique = len(internal_code_text_candidates) == 1
            tier, method, reasons = (
                "INTERNAL_CODE_TEXT_MATCH",
                "internal_code_text_match",
                ["INTERNAL_CODE_TEXT_UNIQUE_NO_PROVENANCE_HUMAN_REQUIRED"] if unique else ["INTERNAL_CODE_TEXT_MULTIPLE_CANDIDATES_HUMAN_REQUIRED"],
            )

        # Bilingual trade-name retrieval (Slice 2 -- Thai, English, and
        # mixed-script OCR text all flow through the SAME call here;
        # `extract_trade_name_tokens`/haystack construction are bilingual as
        # of this slice, see docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 22).
        trade_name_candidates: list[tuple[dict, str]] = []
        if selected is None and not quarantined:
            trade_name_candidates, trade_name_tie = self._trade_name_candidates(
                document, source_attrs, normalized_retrieval, description_retrieval
            )
            if trade_name_candidates and not trade_name_tie:
                selected = trade_name_candidates[0][0]
                unique = len(trade_name_candidates) == 1
                tier, method, reasons = (
                    "TRADE_NAME_MATCH",
                    "trade_name_token_match",
                    ["TRADE_NAME_TOKEN_UNIQUE_AFTER_ATTRIBUTE_GUARD"] if unique else ["TRADE_NAME_TOKEN_MULTIPLE_CANDIDATES_HUMAN_REQUIRED"],
                )
            elif trade_name_candidates and trade_name_tie:
                # Two or more candidates are equally well supported -- there
                # is no principled basis to prefer one over the other, so no
                # product is proposed. The tied candidates are still shown
                # (see candidate_set population below) for a human to choose.
                tier, method, reasons = "UNRESOLVED", "unresolved_human", ["TRADE_NAME_TOKEN_AMBIGUOUS_TIE_NO_AUTO_PICK"]

        # SPELLING_SUGGESTION ("คุณหมายถึง...หรือไม่", Slice 2) -- only
        # attempted when ordinary trade-name retrieval found NOTHING AT ALL
        # (an empty result, not a tie -- a tie already has its own, separate
        # no-auto-pick handling above). Never auto-confirmable: a
        # spelling-corrected guess is fundamentally less certain than a
        # literal token match, so it must always be reviewed by a human,
        # regardless of how confident the correction looks.
        spelling_suggestion_candidates: list[tuple[dict, str]] = []
        spelling_corrections: dict[str, str] = {}
        if selected is None and not quarantined and not trade_name_candidates:
            spelling_suggestion_candidates, spelling_tie, spelling_corrections = self._spelling_suggestion_candidates(
                document, source_attrs, normalized_retrieval, description_retrieval
            )
            if spelling_suggestion_candidates and not spelling_tie:
                selected = spelling_suggestion_candidates[0][0]
                unique = len(spelling_suggestion_candidates) == 1
                correction_note = ";".join(f"{original}->{fix}" for original, fix in sorted(spelling_corrections.items()))
                tier, method, reasons = (
                    "SPELLING_SUGGESTION",
                    "did_you_mean_spelling_suggestion",
                    [
                        f"DID_YOU_MEAN:{correction_note}",
                        "SPELLING_SUGGESTION_UNIQUE_HUMAN_REQUIRED" if unique else "SPELLING_SUGGESTION_MULTIPLE_CANDIDATES_HUMAN_REQUIRED",
                    ],
                )
            elif spelling_suggestion_candidates and spelling_tie:
                tier, method, reasons = "UNRESOLVED", "unresolved_human", ["SPELLING_SUGGESTION_AMBIGUOUS_TIE_NO_AUTO_PICK"]

        history_codes = {row["product_code"]: row for row in self.cache.purchase_history(document["supplier_code"])}

        if quarantined:
            pass  # candidates already populated with the conflicting products above; no weaker tier may override this.
        elif internal_code_text_candidates:
            # No-provenance digit-run hits, never auto-confirmable -- see the
            # INTERNAL_CODE_TEXT_MATCH tier above. A flat score is used
            # (rather than a coverage-style formula like trade-name's)
            # because "the code equals this exact catalog value" isn't a
            # graded signal the way partial word overlap is; it either
            # matches a real product code or it doesn't.
            candidates = [
                {
                    "product_code": product["product_code"],
                    "name": product["name"],
                    "score": "0.6000" if len(internal_code_text_candidates) == 1 else "0.5000",
                    "purchase_count": history_codes.get(product["product_code"], {}).get("purchase_count", 0),
                }
                for product in internal_code_text_candidates[:5]
            ]
        elif trade_name_candidates:
            # The guard-filtered trade-name pool (confident pick or tied) is
            # far more relevant to a human reviewer than whole-catalog fuzzy
            # noise -- surface it directly instead of running the generic
            # fuzzy sweep below.
            candidates = [
                {
                    "product_code": product["product_code"],
                    "name": product["name"],
                    "score": score,
                    "purchase_count": history_codes.get(product["product_code"], {}).get("purchase_count", 0),
                }
                for product, score in trade_name_candidates
            ]
        elif spelling_suggestion_candidates:
            # "did you mean" candidates -- reusing trade-name-style scores
            # but these are ALWAYS review-required, never auto-confirmed
            # (see SPELLING_SUGGESTION above); surfacing them beats falling
            # through to the whole-catalog SequenceMatcher sweep, which
            # tends to score poorly against a short, distinctive-but-
            # misspelled token buried inside a long full product name.
            candidates = [
                {
                    "product_code": product["product_code"],
                    "name": product["name"],
                    "score": score,
                    "purchase_count": history_codes.get(product["product_code"], {}).get("purchase_count", 0),
                }
                for product, score in spelling_suggestion_candidates
            ]
        else:
            fuzzy_rejected_for_evidence = 0
            products = self.cache.list_products()
            for product in products:
                # Bilingual fuzzy fallback (Slice 2): score against BOTH
                # normalized_name_thai and normalized_name_eng independently
                # and take whichever language is the closer match -- never
                # the COALESCE-collapsed legacy `normalized_name` alone,
                # which would silently prefer whichever language a reviewer
                # happened to enter first.
                score_eng = SequenceMatcher(None, description_normalized, product.get("normalized_name_eng") or "").ratio()
                score_thai = SequenceMatcher(None, description_normalized, product.get("normalized_name_thai") or "").ratio()
                score = max(score_eng, score_thai)
                if product["product_code"] in history_codes:
                    score = min(1.0, score + 0.05)
                if score < 0.45:
                    continue
                # Slice 2: the whole-catalog fuzzy fallback previously never
                # ran the strength/pack/dosage-form contradiction guard at
                # all (only _trade_name_candidates did) -- a real 6,665-
                # product Phase E rerun caught this proposing a 3x3 INCH
                # wound dressing for a line that explicitly said "10x20cm"
                # (see docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 22 Phase E
                # evidence). A candidate whose stated attributes actively
                # contradict the source line's stated attributes must never
                # be offered, in ANY tier -- this was already true for
                # trade-name retrieval and is now true here too.
                candidate_text = " ".join(
                    filter(None, [product.get("name_thai"), product.get("name_eng"), product.get("strength") or "", product.get("size") or ""])
                )
                if attributes_conflict(source_attrs, extract_attributes(candidate_text)):
                    continue
                # B1: character-level similarity ALONE may not propose a
                # product. SequenceMatcher happily scores 0.5000 between
                # "CODIPHENTABLET XIOS" and "BEDSIDE TABLE ABS 1 S" purely on
                # shared letters, and that suggestion is not merely unhelpful --
                # a plausible-looking wrong product in front of a reviewer is
                # how poisoned confirmations enter the alias table (Bible
                # section 3: precision over recall). Require at least one
                # meaningful trade-name token shared with the candidate;
                # generic dosage-form/packaging/furniture overlap such as
                # TABLE/TABLET can never qualify on its own. Note the
                # threshold is untouched: this ADDS evidence, it does not relax
                # the bar to let anything through.
                # Scope: this guard governs whether the fuzzy tier may PROPOSE a
                # product, which is only in play when no stronger tier already
                # selected one. When a stronger tier (EXACT_NAME, EXACT_CODE,
                # ...) has already decided, this loop is merely decorating the
                # reviewer's alternatives list, and silently shortening that
                # list would take correction options away from a human without
                # improving precision anywhere.
                if selected is None:
                    shared = meaningful_shared_tokens(
                        description_retrieval or normalized_retrieval,
                        normalize_product_text(" ".join(filter(None, [product.get("name_thai"), product.get("name_eng")]))),
                    )
                    if not shared:
                        fuzzy_rejected_for_evidence += 1
                        continue
                candidates.append({"product_code": product["product_code"], "name": product["name"], "score": f"{score:.4f}", "purchase_count": history_codes.get(product["product_code"], {}).get("purchase_count", 0)})
            candidates.sort(key=lambda item: (-float(item["score"]), item["product_code"]))
            candidates = candidates[:5]

            if selected is None and candidates:
                top = self.cache.get_product(candidates[0]["product_code"])
                selected, tier, method, reasons = top, "FUZZY_SUGGESTION", "fuzzy_human_suggestion", ["HUMAN_CONFIRM_REQUIRED"]
            elif selected is None and fuzzy_rejected_for_evidence:
                # Something DID clear the similarity threshold but nothing
                # cleared the evidence bar. Say so explicitly, so an auditor can
                # tell "no product looked similar" apart from "similar-looking
                # products were deliberately refused".
                tier, method, reasons = (
                    "UNRESOLVED",
                    "unresolved_human",
                    [f"FUZZY_INSUFFICIENT_TOKEN_EVIDENCE:{fuzzy_rejected_for_evidence}"],
                )

        if selected and not self.cache.get_product(selected["product_code"]):
            selected = None
            tier, method, reasons = "UNRESOLVED", "unresolved_human", ["OUT_OF_MASTER_BLOCKED"]
        if selected:
            # candidate_set must never silently disagree with
            # proposed_product_code -- the selected product is always
            # guaranteed to be candidates[0], regardless of which pool
            # (trade-name or generic fuzzy) populated the list above. On a
            # small fixture the two would coincidentally line up; against
            # the real ~6,700-product master they routinely do not without
            # this guarantee.
            selected_score = "1.0000" if tier in {"EXACT_CODE", "EXACT_BARCODE", "ACTIVE_ALIAS", "SPELLING_ALIAS", "EXACT_NAME"} else None
            selected_entry = next((c for c in candidates if c["product_code"] == selected["product_code"]), None)
            if selected_entry is None:
                selected_entry = {
                    "product_code": selected["product_code"],
                    "name": selected["name"],
                    "score": selected_score if selected_score is not None else "0.5000",
                    "purchase_count": history_codes.get(selected["product_code"], {}).get("purchase_count", 0),
                }
                candidates = [selected_entry] + candidates
            elif candidates[0]["product_code"] != selected["product_code"]:
                candidates = [selected_entry] + [c for c in candidates if c["product_code"] != selected["product_code"]]
            candidates = candidates[:5]
        unit_code = None
        raw_unit = (line.get("unit_final") or "").strip().upper()
        if selected:
            full = self.cache.get_product(selected["product_code"])
            valid_units = [item["unit_code"] for item in full.get("units", [])]
            unit_code = raw_unit if raw_unit in valid_units else (valid_units[0] if len(valid_units) == 1 else None)

        # input_hash must change whenever any input that could change the
        # outcome changes.
        #
        # docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 19 (Codex's third Slice-1
        # re-adjudication) proved this was not true for identifier evidence:
        # "no evidence -> UNRESOLVED" and "explicit internal-code evidence ->
        # EXACT_CODE" produced the IDENTICAL hash, because barcode_candidates/
        # internal_code_candidates/supplier_sku were never included below.
        #
        # docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 20 (Codex's fourth
        # re-adjudication) proved a second, structurally identical gap:
        # `unit_final` feeds `proposed_unit_code` directly (see immediately
        # above) but was never part of the hash either -- changing
        # "BOX" -> "EACH" changed the OUTPUT but not the recorded input, so
        # audit could never tell the two predictions apart. Fixed by adding
        # the exact normalized value (`.strip().upper()`, matching what
        # `unit_code` resolution actually compares) below.
        #
        # Also per section 20: the single blended `text` field (normalized
        # source_text, mixing description_final + raw_ocr_text +
        # supplier_sku together) collapsed two fields the matcher gives
        # genuinely DIFFERENT roles (description_final drives EXACT_NAME/
        # description-similarity scoring; raw_ocr_text is scanned only for
        # INTERNAL_CODE-shaped substrings) into one opaque string -- a
        # change to either field could be invisible or indistinguishable in
        # the hash depending on what else was in the joined string. They are
        # now hashed as two separate, independently normalized fields.
        #
        # Every set-valued field below is sorted so the hash is stable
        # regardless of array/evidence order -- the same evidence content
        # must always hash the same, order is not meaningful here.
        input_payload = {
            "supplier": document["supplier_code"],
            "line_id": line["id"],
            "description_final": description_normalized,
            "raw_ocr_text": normalize_product_text(line.get("raw_ocr_text") or ""),
            "supplier_sku": supplier_sku_normalized,
            "unit_final": raw_unit,
            "barcode_evidence": sorted(set(barcode_candidates)),
            "internal_code_evidence": sorted({normalize_product_text(code) for code in explicit_codes}),
            "ruleset": self.RULESET_VERSION,
        }
        return {
            "tier": tier, "method": method, "source_text": source_text, "normalized_text": normalized,
            "input_hash": hashlib.sha256(canonical_json(input_payload).encode("utf-8")).hexdigest(),
            "proposed_product_code": selected["product_code"] if selected else None, "proposed_unit_code": unit_code,
            "confidence": candidates[0]["score"] if candidates else None, "candidate_set": candidates, "reason_codes": reasons,
            "provenance": {"tier": tier, "method": method, "master_only": True, "human_confirmation_required": tier not in {"EXACT_CODE", "EXACT_BARCODE", "ACTIVE_ALIAS", "SPELLING_ALIAS"}},
            "evidence": {"line_evidence": line.get("evidence_json"), "supplier_code": document["supplier_code"]},
            "ocr_engine_versions": ocr_versions, "ruleset_version": self.RULESET_VERSION,
        }
