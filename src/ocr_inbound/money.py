from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .errors import DomainError


THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
DECIMAL_PATTERN = re.compile(r"^-?\d+(?:\.\d+)?$")


def normalize_thai_digits(value: str) -> str:
    return value.translate(THAI_DIGITS)


def parse_decimal(value: str) -> Decimal:
    normalized = normalize_thai_digits(str(value)).replace(",", "").strip()
    if not DECIMAL_PATTERN.fullmatch(normalized):
        raise DomainError("DECIMAL_FORMAT_INVALID", f"Invalid decimal value: {value}")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise DomainError("DECIMAL_FORMAT_INVALID", f"Invalid decimal value: {value}") from exc


def decimal_to_canonical(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def line_total_minor(quantity: str, unit_price_minor: int, discount_minor: int = 0) -> int:
    total = (parse_decimal(quantity) * Decimal(unit_price_minor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(total) - int(discount_minor)


def parse_thai_date(value: str) -> date:
    normalized = normalize_thai_digits(value.strip()).replace("-", "/")
    parts = normalized.split("/")
    if len(parts) != 3:
        raise DomainError("DATE_FORMAT_INVALID", f"Invalid date: {value}")
    day, month, year = (int(part) for part in parts)
    if year >= 2400:
        year -= 543
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise DomainError("DATE_FORMAT_INVALID", f"Invalid date: {value}") from exc
