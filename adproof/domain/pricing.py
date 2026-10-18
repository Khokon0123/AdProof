"""Deterministic price and discount arithmetic (Decimal, never floats)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Engineering tolerance for an explicitly rounded integer percentage. Not a legal safe harbor.
PERCENT_TOLERANCE = Decimal("0.5")

_MONEY = re.compile(r"(?P<cur>US\$|\$|USD\s?|€|EUR\s?|£|GBP\s?)\s?(?P<amt>\d{1,6}(?:[.,]\d{2})?)", re.I)
_PCT = re.compile(r"(?P<pct>\d{1,3}(?:\.\d+)?)\s?%\s?(?:off|discount|savings?)", re.I)


def money(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a money amount: {value!r}") from exc


def currency_code(symbol: str) -> str:
    s = symbol.strip().upper()
    if s in ("$", "US$", "USD"):
        return "USD"
    if s in ("€", "EUR"):
        return "EUR"
    if s in ("£", "GBP"):
        return "GBP"
    return s


def find_prices(text: str) -> list[tuple[Decimal, str, str]]:
    """Return (amount, currency, matched_text) for each price in text."""
    return [(money(m["amt"]), currency_code(m["cur"]), m.group(0)) for m in _MONEY.finditer(text)]


def find_percent_offs(text: str) -> list[tuple[Decimal, str]]:
    return [(Decimal(m["pct"]), m.group(0)) for m in _PCT.finditer(text)]


def discount_percent(reference: Decimal, current: Decimal) -> Decimal:
    if reference <= 0:
        raise ValueError("reference price must be positive")
    return ((reference - current) / reference * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class DiscountCheck:
    claimed: Decimal
    actual: Decimal
    supported: bool
    derivation: str


def check_discount(claimed_pct: Decimal, reference: Decimal, current: Decimal) -> DiscountCheck:
    actual = discount_percent(reference, current)
    supported = abs(actual - claimed_pct) <= PERCENT_TOLERANCE
    derivation = (f"({reference} - {current}) / {reference} x 100 = {actual}%; "
                  f"claimed {claimed_pct}% (tolerance ±{PERCENT_TOLERANCE} points)")
    return DiscountCheck(claimed_pct, actual, supported, derivation)
