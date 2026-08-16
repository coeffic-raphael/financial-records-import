"""Record lifecycle: revalidation, correction, approval.

The single most important function here is `revalidate`. Import and correction
share it, so the two paths cannot drift apart -- which is what makes the
assignment's "a corrected record must be revalidated" structural rather than a
separate treatment.
"""

from decimal import Decimal

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import APIError, not_found
from app.domain.enums import RecordStatus
from app.domain.normalization import normalize_record
from app.domain.validation import derive_status, validate_record
from app.models import FinancialRecord, ImportBatch
from app.schemas import BUSINESS_FIELDS


def existing_references(
    session: Session, batch_id: str, exclude_record_id: str | None = None
) -> frozenset[str]:
    """References already used in this batch.

    `exclude_record_id` is not an optimisation, it is a correctness
    requirement: without it, revalidating any record would find its own
    reference and flag it DUPLICATE_REFERENCE against itself -- making
    correction impossible.
    """
    query = select(FinancialRecord.reference).where(
        FinancialRecord.batch_id == batch_id,
        FinancialRecord.reference.is_not(None),
    )
    if exclude_record_id is not None:
        query = query.where(FinancialRecord.id != exclude_record_id)
    return frozenset(r for r in session.scalars(query) if r)


def revalidate(
    record: FinancialRecord,
    references: frozenset[str],
    confidence_threshold: Decimal,
) -> FinancialRecord:
    """Replay the full pipeline from `raw_payload` and refresh the record.

    raw_payload is the source of truth: normalization applies to a correction
    exactly as it applies to an import, so a user may type "1 200,00" and have
    it accepted.
    """
    normalized, form_errors = normalize_record(
        record.raw_payload,
        source_type=record.source_type,
        source_document_name=record.source_document_name,
    )
    errors = validate_record(
        normalized,
        form_errors,
        existing_references=references,
        confidence_threshold=confidence_threshold,
    )

    for name in BUSINESS_FIELDS:
        setattr(record, name, getattr(normalized, name))
    if normalized.extraction_confidence is not None:
        record.extraction_confidence = normalized.extraction_confidence

    record.validation_errors = [error.as_dict() for error in errors]
    record.status = derive_status(errors).value
    return record


def get_record(session: Session, record_id: str, tenant_id: str) -> FinancialRecord:
    """Fetch a record scoped to the tenant. 404 when it belongs to someone else."""
    record = session.scalar(
        select(FinancialRecord)
        .join(ImportBatch, FinancialRecord.batch_id == ImportBatch.id)
        .where(FinancialRecord.id == record_id, ImportBatch.tenant_id == tenant_id)
    )
    if record is None:
        raise not_found("Record")
    return record


def revalidate_record(
    session: Session, record: FinancialRecord, confidence_threshold: Decimal
) -> FinancialRecord:
    references = existing_references(session, record.batch_id, exclude_record_id=record.id)
    revalidate(record, references, confidence_threshold)
    session.commit()
    session.refresh(record)
    return record


def apply_correction(
    session: Session,
    record: FinancialRecord,
    changes: dict[str, str | None],
    confidence_threshold: Decimal,
) -> FinancialRecord:
    """Merge the correction into raw_payload, then revalidate.

    A corrected record can never stay VALIDATED: the status is always
    recomputed from the validation result.
    """
    payload = dict(record.raw_payload)
    payload.update({key: value for key, value in changes.items()})
    record.raw_payload = payload
    return revalidate_record(session, record, confidence_threshold)


def approve_record(session: Session, record: FinancialRecord) -> FinancialRecord:
    """Move a record to VALIDATED. Only reachable from VALID.

    VALIDATED is never derived by the engine -- it requires this explicit action,
    which is why `status` is not a writable field on the correction payload.
    """
    if record.status != RecordStatus.VALID.value:
        raise APIError(
            status.HTTP_409_CONFLICT,
            "RECORD_NOT_VALID",
            "Only a VALID record can be validated.",
            {"status": record.status},
        )
    record.status = RecordStatus.VALIDATED.value
    session.commit()
    session.refresh(record)
    return record
