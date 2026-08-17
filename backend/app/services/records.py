"""Record lifecycle: revalidation, correction, approval.

The single most important function here is `revalidate`. Import and correction
share it, so the two paths cannot drift apart -- which is what makes the
assignment's "a corrected record must be revalidated" structural rather than a
separate treatment.
"""

from collections.abc import Sequence
from decimal import Decimal

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import APIError, not_found
from app.domain.enums import RecordStatus, SourceType
from app.domain.normalization import normalize_record
from app.domain.validation import derive_status, validate_record
from app.models import FinancialRecord, ImportBatch
from app.providers.schema import record_confidence
from app.schemas import BUSINESS_FIELDS


def references_before(session: Session, batch_id: str, sequence: int) -> frozenset[str]:
    """References used EARLIER in this batch than the given arrival position.

    The policy is "the first occurrence wins", and it must give the same answer
    every time it is evaluated. Two properties make that true:

    - looking only at records BEFORE this one excludes the record itself, so a
      record can never be flagged a duplicate of itself;
    - looking at arrival ORDER rather than at "every other record" means the
      first of two duplicates stays VALID when revalidated. Comparing against
      all siblings would flip it to NEEDS_REVIEW with no correction having
      happened -- the same data changing verdict on re-read.

    Ordering comes from import_sequence, never from the UUID primary key, which
    carries no order at all.
    """
    query = select(FinancialRecord.reference).where(
        FinancialRecord.batch_id == batch_id,
        FinancialRecord.import_sequence < sequence,
        FinancialRecord.reference.is_not(None),
    )
    return frozenset(reference for reference in session.scalars(query) if reference)


def lock_batch(session: Session, batch_id: str) -> None:
    """Serialise everything that reads or writes one batch's references.

    Two things in an import are read-then-write, and both are wrong when two
    imports overlap:

    - `next_import_sequence` reads MAX and adds one, so both would allocate the
      same positions and neither record would see the other as earlier;
    - `references_before` cannot see rows the other transaction has not
      committed, so a reference present in both would be reported as duplicate
      in neither.

    A counter fixes only the first. Locking the batch row fixes both: the second
    import waits, then reads a database where the first has committed.

    Taken by every path that reads references or writes a status: import,
    extraction, correction, revalidation, approval and bulk correction. A path
    that skipped it would race the others while they hold it, which is the same
    defect with a longer name.

    Held until commit, because the outer service owns the transaction. Two
    different batches never contend.
    """
    session.execute(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update())


def next_import_sequence(session: Session, batch_id: str) -> int:
    """Arrival position for the next record of this batch.

    Continuing across uploads is what makes uniqueness batch-scoped rather than
    file-scoped: a reference already imported by an earlier file is visible to
    a later one.

    KNOWN LIMITATION -- not concurrency-safe. This reads MAX and adds one, so
    two imports running at the same time on the same batch can both read the
    same maximum and allocate the same position. Those rows would then never see
    each other as earlier, and a duplicate between them would go unreported.

    This is the same window as the reference race already documented: both come
    from read-then-write outside a lock. Sequential imports -- the only mode
    exercised here -- are unaffected. Production would use an atomic counter on
    import_batch, or a UNIQUE (batch_id, import_sequence) constraint with retry
    on conflict.
    """
    highest = session.scalar(
        select(func.max(FinancialRecord.import_sequence)).where(
            FinancialRecord.batch_id == batch_id
        )
    )
    return 0 if highest is None else highest + 1


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


def revalidate_in_transaction(
    session: Session, record: FinancialRecord, confidence_threshold: Decimal
) -> None:
    """Replay validation on one record. DOES NOT COMMIT."""
    references = references_before(session, record.batch_id, record.import_sequence)
    revalidate(record, references, confidence_threshold)


def revalidate_record(
    session: Session, record: FinancialRecord, confidence_threshold: Decimal
) -> FinancialRecord:
    """Locked because it reads references_before: without it, the verdict could
    be computed from a set another transaction is halfway through changing."""
    lock_batch(session, record.batch_id)
    session.refresh(record)
    revalidate_in_transaction(session, record, confidence_threshold)
    session.commit()
    session.refresh(record)
    return record


def correct_in_transaction(
    session: Session,
    record: FinancialRecord,
    changes: dict[str, str | None],
    confidence_threshold: Decimal,
) -> None:
    """Merge the correction into raw_payload and revalidate. DOES NOT COMMIT.

    Split out so several records can be corrected in ONE transaction. The
    committing version below used to be the only one, and looping over it gave
    a commit per record: a failure on the third left the first two written,
    which is not what "nothing was modified" means.

    Conventions §3.2 already said only the outermost service commits. Nothing
    enforced it here because no caller ever chained two corrections.

    A corrected record can never stay VALIDATED: the status is always
    recomputed from the validation result.
    """
    payload = dict(record.raw_payload)
    payload.update({key: value for key, value in changes.items()})
    record.raw_payload = payload
    _account_for_human_review(record, changes)
    revalidate_in_transaction(session, record, confidence_threshold)


def apply_correction(
    session: Session,
    record: FinancialRecord,
    changes: dict[str, str | None],
    confidence_threshold: Decimal,
) -> FinancialRecord:
    """One record, one transaction: what the single-record route needs.

    Locked like every other path: a correction can change `reference`, which is
    exactly what `references_before` reads elsewhere.
    """
    lock_batch(session, record.batch_id)
    session.refresh(record)
    correct_in_transaction(session, record, changes, confidence_threshold)
    session.commit()
    session.refresh(record)
    return record


def apply_corrections(
    session: Session,
    records: Sequence[FinancialRecord],
    changes: dict[str, str | None],
    confidence_threshold: Decimal,
) -> dict[str, int]:
    """The same correction applied to several records, in ONE transaction.

    Loops over the very function the single-record route uses. A bulk variant
    that recomputed its own way would drift from the import path, and nothing
    would say so on the day it did.
    """
    if records:
        # One lock for the whole request: the route scopes it to a single batch,
        # so there is no ordering problem and no deadlock to avoid.
        lock_batch(session, records[0].batch_id)
        for record in records:
            session.refresh(record)

    for record in records:
        correct_in_transaction(session, record, changes, confidence_threshold)
    session.commit()

    by_status: dict[str, int] = {}
    for record in records:
        session.refresh(record)
        by_status[record.status] = by_status.get(record.status, 0) + 1
    return by_status


def _account_for_human_review(record: FinancialRecord, changes: dict[str, str | None]) -> None:
    """A value a person typed is no longer something the model was unsure about.

    Extraction confidence describes THE EXTRACTION, not the data as it stands.
    Leaving it untouched after a correction made the workflow a dead end: the
    eight statement lines the model could not complete kept LOW_CONFIDENCE
    forever, so filling in every missing field still left them NEEDS_REVIEW and
    they could never be approved.

    Each corrected field therefore becomes certain, and the aggregate is
    recomputed from what remains model-sourced. A field the model was unsure
    about and nobody touched still blocks approval, which is the point.
    """
    if record.source_type != SourceType.PDF.value or not changes:
        return

    scores = dict(record.field_confidence or {})
    if not scores:
        return

    for field in changes:
        if field in scores:
            scores[field] = 1.0

    record.field_confidence = scores
    aggregate = f"{record_confidence(scores):.2f}"
    record.raw_payload = {**record.raw_payload, "extraction_confidence": aggregate}


def approve_record(session: Session, record: FinancialRecord) -> FinancialRecord:
    """Move a record to VALIDATED. Only reachable from VALID.

    VALIDATED is never derived by the engine -- it requires this explicit action,
    which is why `status` is not a writable field on the correction payload.

    The lock comes BEFORE the check, and the record is refreshed under it. The
    status was read into memory when the route loaded the record; a correction
    committing in between makes that value stale, and the check would then pass
    on a record the correction has just invalidated. Because SQLAlchemy only
    writes the dirty column, the result was a record marked VALIDATED still
    carrying its validation errors -- the one thing the assignment forbids.
    """
    lock_batch(session, record.batch_id)
    session.refresh(record)

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
