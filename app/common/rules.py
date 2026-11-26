"""Deterministic checks and fixes. Pure functions: no AWS, no model."""

import hashlib
import re
from datetime import date, timedelta
from difflib import SequenceMatcher

TOLERANCE = 0.02  # rounding slack in the document's currency
MAX_TAX_RATE = 0.27  # the highest standard VAT rate in common use
FUZZY_THRESHOLD = 0.85
REQUIRED = ("vendor", "invoice_number", "date", "currency", "total")
_SUFFIXES = {"co", "company", "inc", "ltd", "llc", "llp", "gmbh", "limited"}
LABELS = {
    "vendor": "vendor name",
    "invoice_number": "document number",
    "date": "date",
    "currency": "currency",
    "total": "total",
}


def issue(code: str, field: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "field": field, "message": message, "severity": severity}


def errors(issues: list[dict]) -> list[dict]:
    return [item for item in issues if item["severity"] == "error"]


def _number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _differs(a: float, b: float) -> bool:
    return abs(a - b) > TOLERANCE + 1e-9


def line_total(fields: dict) -> float | None:
    """Sum of the line amounts, or None if there are no lines or one lacks an amount."""
    lines = fields.get("line_items") or []
    amounts = [line.get("amount") for line in lines]
    if not amounts or not all(_number(a) for a in amounts):
        return None
    return round(sum(amounts), 2)


def bad_lines(fields: dict) -> list[int]:
    """1-based numbers of lines where quantity x unit price is not the amount."""
    bad = []
    for number, line in enumerate(fields.get("line_items") or [], start=1):
        quantity, price, amount = (line.get(k) for k in ("quantity", "unit_price", "amount"))
        if all(_number(v) for v in (quantity, price, amount)):
            if _differs(quantity * price, amount):
                bad.append(number)
    return bad


def check_fields(fields: dict, today: date | None = None) -> list[dict]:
    """Required fields, date, arithmetic and tax rate."""
    found = []
    for name in REQUIRED:
        if fields.get(name) in (None, ""):
            found.append(issue("missing_field", name, f"The {LABELS[name]} is missing."))

    if fields.get("date"):
        try:
            issued = date.fromisoformat(fields["date"])
        except (TypeError, ValueError):
            found.append(issue("bad_date", "date", "The date is not a valid calendar date."))
        else:
            if issued > (today or date.today()) + timedelta(days=1):
                found.append(issue("bad_date", "date", f"The date {issued} is in the future."))

    for number in bad_lines(fields):
        found.append(
            issue(
                "line_math",
                "line_items",
                f"Line {number}: quantity times unit price does not equal the line amount.",
            )
        )

    subtotal, tax, total = (fields.get(k) for k in ("subtotal", "tax", "total"))
    lines = line_total(fields)
    if lines is not None and _number(subtotal) and _differs(lines, subtotal):
        found.append(
            issue(
                "line_sum",
                "subtotal",
                f"The line items add up to {lines:.2f}, but the subtotal is {subtotal:.2f}.",
            )
        )
    base = subtotal if _number(subtotal) else lines
    if base is not None and _number(total):
        expected = round(base + (tax if _number(tax) else 0), 2)
        if _differs(expected, total):
            found.append(
                issue(
                    "total_mismatch",
                    "total",
                    f"Subtotal plus tax is {expected:.2f}, but the total is {total:.2f}.",
                )
            )
    if _number(subtotal) and _number(tax) and subtotal != 0:
        rate = tax / subtotal
        if rate < -0.001 or rate > MAX_TAX_RATE + 0.001:
            found.append(issue("tax_rate", "tax", f"The tax rate of {rate:.0%} is not plausible."))
    return found


# --- Vendors and duplicates ------------------------------------------------------------------


def normalize_vendor(name: str | None) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().replace("&", " and ")).split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


def find_vendor(name: str | None, vendors: list[dict]) -> dict | None:
    key = normalize_vendor(name)
    return next((v for v in vendors if v["vendor_key"] == key), None)


def fuzzy_vendor(name: str | None, vendors: list[dict]) -> tuple[dict, float] | None:
    """The closest known vendor, if it is close enough to be a misspelling."""
    key = normalize_vendor(name)
    if not key or not vendors:
        return None
    scored = [(SequenceMatcher(None, key, v["vendor_key"]).ratio(), v) for v in vendors]
    score, best = max(scored, key=lambda pair: pair[0])
    return (best, round(score, 3)) if score >= FUZZY_THRESHOLD else None


def duplicate_key(session_id: str, fields: dict) -> str | None:
    """Same vendor + document number + total, within one visitor's session."""
    vendor = normalize_vendor(fields.get("vendor"))
    number = re.sub(r"\s", "", str(fields.get("invoice_number") or "")).upper()
    total = fields.get("total")
    if not (vendor and number and _number(total)):
        return None
    raw = f"{session_id}|{vendor}|{number}|{total:.2f}"
    return hashlib.sha256(raw.encode()).hexdigest()


# --- Fixes and explanations ------------------------------------------------------------------


def recompute_totals(fields: dict) -> dict:
    """Corrections the arithmetic itself proves, as {field: new value}.

    Only when every line is internally consistent, and either the lines or the printed total
    agree about which figure is wrong. Never guesses without line items.
    """
    lines = line_total(fields)
    if lines is None or bad_lines(fields):
        return {}
    subtotal, tax, total = (fields.get(k) for k in ("subtotal", "tax", "total"))
    tax_value = tax if _number(tax) else 0
    if lines != 0 and not -0.001 <= tax_value / lines <= MAX_TAX_RATE + 0.001:
        return {}
    changes = {}
    if _number(subtotal) and _differs(lines, subtotal):
        changes["subtotal"] = lines
    expected = round(lines + tax_value, 2)
    if _number(total) and _differs(expected, total):
        changes["total"] = expected
    return changes


MONETARY_FIELDS = ("currency", "subtotal", "tax", "total")
LINE_NUMBERS = ("quantity", "unit_price", "amount")


def is_monetary_change(name: str, old, new) -> bool:
    """Would replacing `old` with `new` change any money on the document?

    Filling an empty amount counts. In line items only the numbers count, not the wording.
    """
    if name == "line_items":

        def numbers(lines):
            return [tuple(line.get(key) for key in LINE_NUMBERS) for line in lines or []]

        return numbers(old) != numbers(new)
    return name in MONETARY_FIELDS and old != new


def show(value) -> str:
    if isinstance(value, list):
        return f"{len(value)} line items"
    return "empty" if value in (None, "") else str(value)


def explain(issues: list[dict], tried: list[str], suggestions: dict | None = None) -> str:
    """Plain-English summary for the human reviewer."""
    problems = " ".join(item["message"] for item in errors(issues))
    attempts = " ".join(tried) if tried else "No automatic fix applies to this kind of problem."
    text = (
        f"This document needs a person to check it. {problems} What was already tried: {attempts}"
    )
    if suggestions:
        text += (
            " Amounts are never changed without you: the suggested correction is pre-filled, "
            "so Approve accepts it."
        )
    return text
