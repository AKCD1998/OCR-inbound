"""Shared, dependency-free text normalization.

Extracted out of `matching.py` in Slice 2 (see
docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 22) so `ada_read.py` can also use
the exact same normalization when building the bilingual product cache,
without creating a circular import (`matching.py` already imports from
`ada_read.py`). `matching.py` re-exports `normalize_product_text` from here
so every existing import site (including all of Slice 0/1's tests) keeps
working unchanged.
"""
from __future__ import annotations

import re
import unicodedata

# Keeps digits, Latin letters, and Thai script characters; everything else
# (punctuation, symbols, other scripts) collapses to a single space. Thai
# script has no inter-word spacing convention the way Latin text does, but
# real product-master names in this catalog ARE space-separated (they were
# typed by humans following the printed packaging), so word-level tokenizing
# on whitespace works the same for Thai runs as it does for Latin runs here.
_KEEP_CHARS_RE = re.compile(r"[^0-9A-Zก-๙]+")


def normalize_product_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").upper()
    normalized = _KEEP_CHARS_RE.sub(" ", normalized)
    return " ".join(normalized.split())


_THAI_CHAR_RE = re.compile(r"[ก-๙]")
_LATIN_CHAR_RE = re.compile(r"[A-Za-z]")


def detect_script(text: str) -> str:
    """Classifies a piece of text as `"THAI"`, `"LATIN"`, `"MIXED"`, or
    `"NEITHER"` (digits/symbols only) based on which scripts appear in it.
    Used to auto-split a legacy single-language `name` fixture into the
    bilingual `name_thai`/`name_eng` slots, and to tag individual retrieval
    tokens by language so bilingual trade-name retrieval can search the
    right side(s) of the catalog."""
    has_thai = bool(_THAI_CHAR_RE.search(text or ""))
    has_latin = bool(_LATIN_CHAR_RE.search(text or ""))
    if has_thai and has_latin:
        return "MIXED"
    if has_thai:
        return "THAI"
    if has_latin:
        return "LATIN"
    return "NEITHER"
