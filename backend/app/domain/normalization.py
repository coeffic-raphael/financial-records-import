"""Normalization: cleans up FORM, never judges SUBSTANCE.

Split of responsibility with validation:
  - an unreadable amount or date is a *form* problem and produces a FieldError
    here (NOT_NUMERIC / INVALID_DATE);
  - a zero amount, an inconsistent net or an unsupported currency is a
    *substance* problem and belongs to validation.py.

Intended consequence: "1,200.00" becomes valid after normalization, whereas a
wrong net_amount stays an error.

No unreadable value is ever silently overwritten: it remains available in
raw_payload.
"""

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.domain.errors import ErrorCode, FieldError
from app.domain.record import NormalizedRecord

_DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")
_THOUSANDS_GROUP_RE = re.compile(r"^\d{3}$")

# Largest value the amount columns can hold: NUMERIC(18, 2) leaves 16 integer
# digits. Beyond it PostgreSQL refuses the INSERT, which would fail the whole
# import -- so an out-of-range amount is caught here and reported as a field
# error, exactly like an unreadable one.
MAX_AMOUNT = Decimal("9999999999999999.99")

# Amount columns hold two decimals. Anything finer cannot be stored as written,
# so it is REPORTED rather than quietly rounded: silently turning 0.0001 into
# 0.00 would let a record be validated on a value the database never receives.
AMOUNT_SCALE = 2

# A group of three digits is only a thousands separator if what precedes it can
# actually be a leading group: one to three digits with no leading zero. Without
# this, "0.001" was read as 1.
_THOUSANDS_LEFT_RE = re.compile(r"^-?[1-9]\d{0,2}$")

AMOUNT_FIELDS = ("gross_amount", "fee_amount", "tax_amount", "net_amount")
DATE_FIELDS = ("transaction_date", "value_date")
TEXT_FIELDS = (
    "reference",
    "description",
    "counterparty_name",
    "counterparty_account",
    "invoice_number",
)
ENUM_FIELDS = ("currency", "category", "payment_method")


def normalize_text(value: Any) -> str | None:
    """Trim, and turn the empty string into None.

    This makes "missing field" and "empty field" validate identically.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_enum(value: Any) -> str | None:
    """Uppercase; spaces and hyphens become underscores.

    Does NOT check membership: that is a business rule, so it belongs to
    validation.
    """
    text = normalize_text(value)
    if text is None:
        return None
    return re.sub(r"[\s-]+", "_", text.upper())


def normalize_country(value: Any) -> str | None:
    text = normalize_text(value)
    return text.upper() if text else None


def normalize_amount(value: Any) -> tuple[Decimal | None, ErrorCode | None]:
    """Return (amount, problem) where problem is None when the value is usable.

    Returning the reason rather than a boolean lets the caller distinguish
    "this is not a number" from "this number cannot be stored", which are
    different messages for the user.

    Separator rules, applied in order:
      1. strip spaces (including non-breaking ones);
      2. if BOTH '.' and ',' are present -> the RIGHTMOST is the decimal
         separator, the other one is dropped;
      3. if only one kind is present:
         a. several occurrences                  -> thousands separator,
         b. one occurrence followed by exactly   -> thousands separator,
            three digits
         c. otherwise                            -> decimal separator;
      4. the result must match -?\\d+(\\.\\d+)? or the value is unreadable.

    Accepted residual ambiguity: "1.200" yields 1200 even though the author may
    have meant 1.2. No information available can settle it (documented
    limitation). A stated simple rule beats a clever heuristic that cannot be
    defended.
    """
    if value is None:
        return None, None
    text = str(value).strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        return None, None

    has_dot, has_comma = "." in text, "," in text

    if has_dot and has_comma:
        decimal_sep = "." if text.rfind(".") > text.rfind(",") else ","
        text = text.replace("," if decimal_sep == "." else ".", "")
        text = text.replace(decimal_sep, ".")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        left, right = text.rsplit(sep, 1)
        looks_like_thousands = text.count(sep) > 1 or bool(
            _THOUSANDS_GROUP_RE.match(right) and _THOUSANDS_LEFT_RE.match(left)
        )
        text = text.replace(sep, "") if looks_like_thousands else text.replace(sep, ".")

    if not _DECIMAL_RE.match(text):
        return None, ErrorCode.NOT_NUMERIC
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None, ErrorCode.NOT_NUMERIC
    if -amount.as_tuple().exponent > AMOUNT_SCALE:
        return None, ErrorCode.AMOUNT_SCALE_EXCEEDED
    if abs(amount) > MAX_AMOUNT:
        return None, ErrorCode.AMOUNT_OUT_OF_RANGE
    return amount, None


def normalize_confidence(value: Any) -> tuple[Decimal | None, ErrorCode | None]:
    """Return (confidence, problem).

    A confidence is not an amount, and the difference matters. Rounding money
    loses money; rounding an estimate of certainty from 0.9512 to 0.95 loses
    nothing anyone can act on. So this one is QUANTIZED on purpose, while
    amounts are reported and left alone.

    The [0, 1] range is checked by the validation layer, not here: an
    out-of-range confidence is a business problem, and the raw value must
    survive to be shown.
    """
    parsed, problem = normalize_amount(value)
    if problem is ErrorCode.AMOUNT_SCALE_EXCEEDED:
        text = str(value).strip()
        try:
            return Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), None
        except InvalidOperation:
            return None, ErrorCode.NOT_NUMERIC
    return parsed, problem


def normalize_date(value: Any) -> tuple[date | None, ErrorCode | None]:
    """Return (date, problem). ISO first, then DD/MM/YYYY.

    Day precedes month: this is not an arbitrary convention. The supplied bank
    statement contains 18/07/2026, 22/07/2026 and 27/07/2026 -- a first
    component greater than 12 rules out the US reading. The sample data settles
    the ambiguity by itself.
    """
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    try:
        return date.fromisoformat(text), None
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%d/%m/%Y").date(), None
    except ValueError:
        return None, ErrorCode.INVALID_DATE


def normalize_record(
    raw: Mapping[str, Any],
    *,
    source_type: str | None = None,
    source_document_name: str | None = None,
) -> tuple[NormalizedRecord, list[FieldError]]:
    """Return the normalized record and FORM errors only."""
    errors: list[FieldError] = []
    values: dict[str, Any] = {}

    for name in TEXT_FIELDS:
        values[name] = normalize_text(raw.get(name))

    for name in ENUM_FIELDS:
        values[name] = normalize_enum(raw.get(name))

    values["country"] = normalize_country(raw.get("country"))

    for name in AMOUNT_FIELDS:
        amount, problem = normalize_amount(raw.get(name))
        values[name] = amount
        if problem is ErrorCode.AMOUNT_OUT_OF_RANGE:
            errors.append(
                FieldError(
                    field=name,
                    code=problem,
                    message=f"Amount exceeds the storable range: {raw.get(name)!r}",
                )
            )
        elif problem is not None:
            errors.append(
                FieldError(
                    field=name,
                    code=problem,
                    message=f"Not a numeric value: {raw.get(name)!r}",
                )
            )

    for name in DATE_FIELDS:
        parsed, problem = normalize_date(raw.get(name))
        values[name] = parsed
        if problem is not None:
            errors.append(
                FieldError(
                    field=name,
                    code=problem,
                    message=f"Unreadable date: {raw.get(name)!r}",
                )
            )

    confidence, confidence_problem = normalize_confidence(raw.get("extraction_confidence"))
    if confidence_problem is not None:
        errors.append(
            FieldError(
                field="extraction_confidence",
                code=confidence_problem,
                message=f"Confidence is not usable: {raw.get('extraction_confidence')!r}",
            )
        )

    record = NormalizedRecord(
        **values,
        source_type=source_type,
        source_document_name=source_document_name,
        extraction_confidence=confidence,
        raw_payload=dict(raw),
    )
    return record, errors
