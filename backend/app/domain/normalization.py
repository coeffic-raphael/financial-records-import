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
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.errors import ErrorCode, FieldError
from app.domain.record import NormalizedRecord

_DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")
_THOUSANDS_GROUP_RE = re.compile(r"^\d{3}$")

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


def normalize_amount(value: Any) -> tuple[Decimal | None, bool]:
    """Return (amount, readable).

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
        return None, True
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if not text:
        return None, True

    has_dot, has_comma = "." in text, "," in text

    if has_dot and has_comma:
        decimal_sep = "." if text.rfind(".") > text.rfind(",") else ","
        text = text.replace("," if decimal_sep == "." else ".", "")
        text = text.replace(decimal_sep, ".")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        if text.count(sep) > 1 or _THOUSANDS_GROUP_RE.match(text.rsplit(sep, 1)[1]):
            text = text.replace(sep, "")
        else:
            text = text.replace(sep, ".")

    if not _DECIMAL_RE.match(text):
        return None, False
    try:
        return Decimal(text), True
    except InvalidOperation:
        return None, False


def normalize_date(value: Any) -> tuple[date | None, bool]:
    """Return (date, readable). ISO first, then DD/MM/YYYY.

    Day precedes month: this is not an arbitrary convention. The supplied bank
    statement contains 18/07/2026, 22/07/2026 and 27/07/2026 -- a first
    component greater than 12 rules out the US reading. The sample data settles
    the ambiguity by itself.
    """
    if value is None:
        return None, True
    text = str(value).strip()
    if not text:
        return None, True
    try:
        return date.fromisoformat(text), True
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%d/%m/%Y").date(), True
    except ValueError:
        return None, False


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
        amount, readable = normalize_amount(raw.get(name))
        values[name] = amount
        if not readable:
            errors.append(
                FieldError(
                    field=name,
                    code=ErrorCode.NOT_NUMERIC,
                    message=f"Not a numeric value: {raw.get(name)!r}",
                )
            )

    for name in DATE_FIELDS:
        parsed, readable = normalize_date(raw.get(name))
        values[name] = parsed
        if not readable:
            errors.append(
                FieldError(
                    field=name,
                    code=ErrorCode.INVALID_DATE,
                    message=f"Unreadable date: {raw.get(name)!r}",
                )
            )

    confidence, confidence_readable = normalize_amount(raw.get("extraction_confidence"))
    if not confidence_readable:
        errors.append(
            FieldError(
                field="extraction_confidence",
                code=ErrorCode.NOT_NUMERIC,
                message=f"Confidence is not numeric: {raw.get('extraction_confidence')!r}",
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
