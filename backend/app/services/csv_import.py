"""CSV ingestion.

The assignment requires importing every row rather than rejecting the whole
file, so a bad row becomes a NEEDS_REVIEW record -- never an aborted import.
There is exactly one global-rejection case: a header missing required columns,
because then the file itself is unusable rather than some of its rows.
"""

import csv
import io
from decimal import Decimal

from fastapi import status
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.domain.normalization import normalize_record
from app.domain.validation import derive_status, validate_record
from app.models import FinancialRecord, ImportBatch
from app.schemas import ImportResult

# A missing optional column (fee_amount, invoice_number...) is harmless: the
# domain defaults it. Only columns required by the data dictionary make the
# file structurally unusable.
REQUIRED_COLUMNS = frozenset(
    {
        "reference",
        "transaction_date",
        "description",
        "gross_amount",
        "net_amount",
        "currency",
        "counterparty_name",
        "country",
        "category",
    }
)


def import_csv(
    session: Session,
    batch: ImportBatch,
    filename: str,
    content: bytes,
    confidence_threshold: Decimal,
) -> ImportResult:
    try:
        # utf-8-sig transparently strips the BOM spreadsheet exports often add.
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "INVALID_ENCODING",
            "The file is not valid UTF-8 text.",
        ) from exc

    reader = csv.DictReader(io.StringIO(text))
    header = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS - header
    if missing:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "INVALID_CSV_STRUCTURE",
            "The CSV is missing required columns.",
            {"missing_columns": sorted(missing)},
        )

    # References accumulate as rows are inserted, inside the same transaction.
    # Uniqueness is scoped to the batch, and evaluated in arrival order: the
    # SECOND occurrence of a reference is the offending one, not the first.
    seen = frozenset()
    by_status: dict[str, int] = {}
    imported = 0

    for raw in reader:
        normalized, form_errors = normalize_record(
            raw, source_type="CSV", source_document_name=filename
        )
        errors = validate_record(
            normalized,
            form_errors,
            existing_references=seen,
            confidence_threshold=confidence_threshold,
        )
        record_status = derive_status(errors).value

        record = FinancialRecord(
            batch_id=batch.id,
            source_type="CSV",
            source_document_name=filename,
            status=record_status,
            validation_errors=[error.as_dict() for error in errors],
            raw_payload=dict(raw),
        )
        for name in (
            "reference",
            "transaction_date",
            "value_date",
            "description",
            "gross_amount",
            "fee_amount",
            "tax_amount",
            "net_amount",
            "currency",
            "counterparty_name",
            "counterparty_account",
            "country",
            "category",
            "invoice_number",
            "payment_method",
        ):
            setattr(record, name, getattr(normalized, name))

        session.add(record)
        if normalized.reference:
            seen = seen | {normalized.reference}
        by_status[record_status] = by_status.get(record_status, 0) + 1
        imported += 1

    session.commit()
    return ImportResult(document_name=filename, imported=imported, by_status=by_status)
