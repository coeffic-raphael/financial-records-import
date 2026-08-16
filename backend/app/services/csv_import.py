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
from app.models import ImportBatch
from app.schemas import ImportResult
from app.services.ingestion import persist_records

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
    document_id: str | None = None,
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

    rows = list(reader)
    by_status = persist_records(
        session,
        batch,
        rows,
        source_type="CSV",
        document_name=filename,
        confidence_threshold=confidence_threshold,
        document_id=document_id,
    )
    # The service owns the transaction: one commit for the whole file, so a
    # failure part-way leaves nothing behind.
    session.commit()
    return ImportResult(document_name=filename, imported=len(rows), by_status=by_status)
