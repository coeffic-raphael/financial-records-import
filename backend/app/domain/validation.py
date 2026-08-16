"""Validation engine: judges SUBSTANCE.

Every rule is a pure function `(record) -> list[FieldError]`. The engine applies
them ALL and concatenates: no rule short-circuits the others, because the user
must see every error at once instead of discovering them one at a time.

Cascading errors across *different* fields are kept. TX-2026-0027 has a negative
fee_amount, which also makes net_amount inconsistent -- both are reported.
Hiding the second one would require a dependency graph between rules, for no
gain: the user fixes the fee and revalidates.
"""

from collections.abc import Sequence
from decimal import Decimal

from app.domain.countries import ISO_3166_1_ALPHA_2
from app.domain.enums import Category, Currency, PaymentMethod, RecordStatus, SourceType
from app.domain.errors import ErrorCode, FieldError
from app.domain.record import NormalizedRecord

REQUIRED_FIELDS = (
    "reference",
    "transaction_date",
    "description",
    "gross_amount",
    "net_amount",
    "currency",
    "counterparty_name",
    "country",
    "category",
)

NET_AMOUNT_TOLERANCE = Decimal("0.01")

# Storage is generous (TEXT), so an over-long value can no longer break an
# INSERT. These bounds are about data quality, not about column capacity: a
# 4000-character counterparty name is a broken import, not a supplier.
MAX_FIELD_LENGTHS = {
    "reference": 100,
    "description": 2000,
    "counterparty_name": 300,
    "counterparty_account": 100,
    "country": 100,
    "category": 100,
    "currency": 100,
    "invoice_number": 100,
    "payment_method": 100,
}
DEFAULT_CONFIDENCE_THRESHOLD = Decimal("0.70")


def _err(field: str, code: ErrorCode, message: str) -> FieldError:
    return FieldError(field=field, code=code, message=message)


def check_required_fields(
    record: NormalizedRecord, fields_with_form_errors: frozenset[str] = frozenset()
) -> list[FieldError]:
    """Report missing required fields.

    A field that is PRESENT but unreadable already produced a form error
    (NOT_NUMERIC / INVALID_DATE); we do not report it a second time as missing.
    Without this suppression TX-2026-0016 would raise two errors instead of one
    and the CSV oracle would fail.
    """
    errors = []
    for name in REQUIRED_FIELDS:
        if name in fields_with_form_errors:
            continue
        if getattr(record, name) is None:
            errors.append(
                _err(name, ErrorCode.REQUIRED_FIELD_MISSING, f"Field {name} is required.")
            )
    return errors


def check_gross_amount_non_zero(record: NormalizedRecord) -> list[FieldError]:
    if record.gross_amount is not None and record.gross_amount == 0:
        return [_err("gross_amount", ErrorCode.ZERO_AMOUNT, "gross_amount must not be zero.")]
    return []


def check_non_negative_amounts(record: NormalizedRecord) -> list[FieldError]:
    errors = []
    for name in ("fee_amount", "tax_amount"):
        value = getattr(record, name)
        if value is not None and value < 0:
            errors.append(_err(name, ErrorCode.NEGATIVE_AMOUNT, f"{name} must not be negative."))
    return errors


AMOUNT_OPERANDS = ("gross_amount", "fee_amount", "tax_amount", "net_amount")


def check_net_amount(
    record: NormalizedRecord, fields_with_form_errors: frozenset[str] = frozenset()
) -> list[FieldError]:
    """net_amount == gross_amount + tax_amount - fee_amount, tolerance 0.01.

    Two distinct reasons to skip the check, which must not be confused:

    - an operand is MISSING -> gross or net absent means the formula has no
      subject; fee and tax absent legitimately default to 0 per the data
      dictionary, so the check still runs.
    - an operand is UNREADABLE -> the formula cannot be evaluated at all. Note
      that an unreadable fee normalizes to None, which would otherwise be read
      as "absent, so zero" and produce a NET_AMOUNT_MISMATCH that is simply
      false: we do not know what the fee was.
    """
    if any(name in fields_with_form_errors for name in AMOUNT_OPERANDS):
        return []
    if record.gross_amount is None or record.net_amount is None:
        return []
    fee = record.fee_amount if record.fee_amount is not None else Decimal(0)
    tax = record.tax_amount if record.tax_amount is not None else Decimal(0)
    expected = record.gross_amount + tax - fee
    if abs(expected - record.net_amount) > NET_AMOUNT_TOLERANCE:
        return [
            _err(
                "net_amount",
                ErrorCode.NET_AMOUNT_MISMATCH,
                f"net_amount expected {expected}, got {record.net_amount}.",
            )
        ]
    return []


def check_currency(record: NormalizedRecord) -> list[FieldError]:
    if record.currency is not None and record.currency not in set(Currency):
        return [
            _err(
                "currency",
                ErrorCode.UNSUPPORTED_CURRENCY,
                f"Unsupported currency: {record.currency}. Expected EUR, USD, GBP or CHF.",
            )
        ]
    return []


def check_category(record: NormalizedRecord) -> list[FieldError]:
    if record.category is not None and record.category not in set(Category):
        return [
            _err(
                "category",
                ErrorCode.UNSUPPORTED_CATEGORY,
                f"Unsupported category: {record.category}.",
            )
        ]
    return []


def check_payment_method(record: NormalizedRecord) -> list[FieldError]:
    """payment_method is OPTIONAL: an empty value is not an error (TX-2026-0029)."""
    if record.payment_method is not None and record.payment_method not in set(PaymentMethod):
        return [
            _err(
                "payment_method",
                ErrorCode.UNSUPPORTED_PAYMENT_METHOD,
                f"Unsupported payment method: {record.payment_method}.",
            )
        ]
    return []


def check_field_lengths(record: NormalizedRecord) -> list[FieldError]:
    """Flag values that are too long to be plausible.

    The value is still stored: raw_payload keeps the original and the column is
    TEXT, so nothing is lost and nothing crashes. Overall input size is bounded
    upstream by the upload limit.
    """
    errors = []
    for name, limit in MAX_FIELD_LENGTHS.items():
        value = getattr(record, name)
        if value is not None and len(value) > limit:
            errors.append(
                _err(
                    name,
                    ErrorCode.VALUE_TOO_LONG,
                    f"{name} is {len(value)} characters long, maximum is {limit}.",
                )
            )
    return errors


def check_country(record: NormalizedRecord) -> list[FieldError]:
    if record.country is not None and record.country not in ISO_3166_1_ALPHA_2:
        return [
            _err(
                "country",
                ErrorCode.INVALID_COUNTRY_CODE,
                f"Unknown ISO 3166-1 alpha-2 country code: {record.country}.",
            )
        ]
    return []


def check_confidence_range(record: NormalizedRecord) -> list[FieldError]:
    """A confidence outside [0, 1] is meaningless.

    NUMERIC(3, 2) would not have enforced this -- it accepts up to 9.99 -- and
    relying on the column would have made 10.00 a failed INSERT rather than a
    reportable error. So the range is a business rule and storage stays
    generous, like every other externally supplied value.
    """
    if record.source_type != SourceType.PDF.value:
        return []
    confidence = record.extraction_confidence
    if confidence is not None and not (Decimal(0) <= confidence <= Decimal(1)):
        return [
            _err(
                "extraction_confidence",
                ErrorCode.CONFIDENCE_OUT_OF_RANGE,
                f"Confidence must be between 0 and 1, got {confidence}.",
            )
        ]
    return []


def check_confidence(
    record: NormalizedRecord, threshold: Decimal = DEFAULT_CONFIDENCE_THRESHOLD
) -> list[FieldError]:
    """PDF only: low confidence forces NEEDS_REVIEW even without field errors.

    The source check is not cosmetic. `extraction_confidence` is a PDF-only
    field per the data dictionary; without this guard a CSV carrying a stray
    `extraction_confidence` column would be flagged LOW_CONFIDENCE, which is
    meaningless for a source that involves no extraction.
    """
    if record.source_type != SourceType.PDF.value:
        return []
    if record.extraction_confidence is not None and record.extraction_confidence < threshold:
        return [
            _err(
                "extraction_confidence",
                ErrorCode.LOW_CONFIDENCE,
                f"Extraction confidence {record.extraction_confidence} below "
                f"threshold {threshold}.",
            )
        ]
    return []


def check_reference_uniqueness(
    reference: str | None, existing_references: frozenset[str] = frozenset()
) -> list[FieldError]:
    """Uniqueness of `reference` WITHIN a batch.

    Takes a set of references, never a database session: the domain stays
    testable without a database. The service layer supplies the set from the
    current transaction.

    Note: there is deliberately NO UNIQUE constraint in the schema -- it would
    make the import of the CSV's duplicated row fail, whereas the assignment
    requires importing every row.
    """
    if reference is not None and reference in existing_references:
        return [
            _err(
                "reference",
                ErrorCode.DUPLICATE_REFERENCE,
                f"Reference {reference} already exists in this import.",
            )
        ]
    return []


def validate_record(
    record: NormalizedRecord,
    form_errors: Sequence[FieldError] = (),
    *,
    existing_references: frozenset[str] = frozenset(),
    confidence_threshold: Decimal = DEFAULT_CONFIDENCE_THRESHOLD,
) -> list[FieldError]:
    """Apply every rule and return both form and substance errors."""
    fields_with_form_errors = frozenset(error.field for error in form_errors)

    errors: list[FieldError] = list(form_errors)
    errors += check_required_fields(record, fields_with_form_errors)
    errors += check_reference_uniqueness(record.reference, existing_references)
    errors += check_gross_amount_non_zero(record)
    errors += check_non_negative_amounts(record)
    errors += check_net_amount(record, fields_with_form_errors)
    errors += check_currency(record)
    errors += check_country(record)
    errors += check_category(record)
    errors += check_payment_method(record)
    errors += check_field_lengths(record)
    errors += check_confidence_range(record)
    errors += check_confidence(record, confidence_threshold)
    return errors


def derive_status(errors: Sequence[FieldError]) -> RecordStatus:
    """VALIDATED is never derived here: it requires an explicit user action."""
    return RecordStatus.NEEDS_REVIEW if errors else RecordStatus.VALID
