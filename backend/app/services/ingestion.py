"""Turning raw rows into persisted records.

Shared by CSV import and PDF extraction. Having one function rather than two is
what guarantees a PDF record is normalized, validated and scored exactly like an
imported one -- and it is why no PDF-specific validation exists anywhere.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.domain.normalization import normalize_record
from app.domain.validation import derive_status, validate_record
from app.models import FinancialRecord, ImportBatch
from app.providers.schema import record_confidence
from app.schemas import BUSINESS_FIELDS
from app.services.records import next_import_sequence, references_before


def persist_records(
    session: Session,
    batch: ImportBatch,
    rows: Sequence[dict[str, Any]],
    *,
    source_type: str,
    document_name: str,
    confidence_threshold: Decimal,
    field_confidences: Sequence[dict[str, float]] | None = None,
) -> dict[str, int]:
    """Normalize, validate and add rows to the session. Returns count per status.

    Nothing is rejected here: a row that fails validation becomes a
    NEEDS_REVIEW record, which is the whole premise of the application.

    DOES NOT COMMIT. The transaction boundary belongs to the calling service,
    which is what lets PDF extraction write the records and the job outcome in a
    SINGLE transaction. Committing here would make them two, and a crash in
    between would leave persisted records under a job still claiming to be
    running.
    """
    sequence = next_import_sequence(session, batch.id)
    # Seeded from the batch, not from zero, so a reference already imported by
    # an earlier upload is visible to this one.
    seen = references_before(session, batch.id, sequence)
    by_status: dict[str, int] = {}

    for index, row in enumerate(rows):
        payload = dict(row)
        confidence = None
        if field_confidences is not None and index < len(field_confidences):
            confidence = field_confidences[index]
            # Written into raw_payload rather than only onto the column:
            # revalidation replays from raw_payload, so a confidence kept
            # elsewhere would vanish the first time a user corrected a field.
            payload["extraction_confidence"] = str(record_confidence(confidence))

        normalized, form_errors = normalize_record(
            payload, source_type=source_type, source_document_name=document_name
        )
        errors = validate_record(
            normalized,
            form_errors,
            existing_references=seen,
            confidence_threshold=confidence_threshold,
        )
        status = derive_status(errors).value

        record = FinancialRecord(
            batch_id=batch.id,
            import_sequence=sequence,
            source_type=source_type,
            source_document_name=document_name,
            status=status,
            validation_errors=[error.as_dict() for error in errors],
            raw_payload=payload,
            extraction_confidence=normalized.extraction_confidence,
            field_confidence=confidence,
        )
        for name in BUSINESS_FIELDS:
            setattr(record, name, getattr(normalized, name))

        session.add(record)
        if normalized.reference:
            seen = seen | {normalized.reference}
        sequence += 1
        by_status[status] = by_status.get(status, 0) + 1

    session.flush()
    return by_status
