"""PDF extraction: jobs, background execution, bounded concurrency.

Upload does not wait for the model. An extraction job is persisted as PENDING,
the endpoint answers 202, and the work happens afterwards. Three hazards shape
this file, and each is handled explicitly rather than discovered later.
"""

import logging
import threading
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.domain.enums import JobStatus, SourceType
from app.models import ExtractionJob, ImportBatch, SourceDocument
from app.providers.base import ExtractionProvider, ProviderError
from app.services.ingestion import persist_records
from app.services.records import lock_batch

logger = logging.getLogger(__name__)

_semaphore: threading.Semaphore | None = None
_semaphore_lock = threading.Lock()


def get_semaphore(limit: int) -> threading.Semaphore:
    """Bound how many extractions run at once.

    Not a memory guard: the thread pool would absorb dozens. It exists because
    provider quotas are counted in requests per minute, so several users
    uploading together would collect 429s. The slowest component sets the pace.
    """
    global _semaphore
    with _semaphore_lock:
        if _semaphore is None:
            _semaphore = threading.Semaphore(limit)
    return _semaphore


def reset_semaphore(limit: int | None = None) -> None:
    """Rebuild the limiter. Used by tests, and by nothing else."""
    global _semaphore
    with _semaphore_lock:
        _semaphore = threading.Semaphore(limit) if limit else None


def create_jobs(
    session: Session, batch: ImportBatch, documents: Sequence[SourceDocument]
) -> list[ExtractionJob]:
    """Persist one PENDING job per file, in a SINGLE transaction.

    Committing per job would let a failure on the second leave the first
    persisted as PENDING while the request fails -- a job nothing will ever
    pick up, because tasks are only queued once the whole request succeeds.
    """
    jobs = [
        ExtractionJob(
            batch_id=batch.id,
            document_name=document.filename,
            source_document_id=document.id,
            status=JobStatus.PENDING.value,
        )
        for document in documents
    ]
    session.add_all(jobs)
    session.commit()
    for job in jobs:
        session.refresh(job)
    return jobs


def run_extraction(
    job_id: str,
    content_path: Path,
    filename: str,
    provider: ExtractionProvider,
    session_factory: sessionmaker | None = None,
    settings: Settings | None = None,
) -> None:
    """Execute one extraction. Runs in a background thread, never in a request.

    This function is SYNCHRONOUS on purpose: declared async, it would block the
    event loop for the whole provider call and freeze every other request.

    It must never raise. The caller is a background task with nobody to catch
    it, so every failure becomes a FAILED job carrying a readable message.
    """
    settings = settings or get_settings()
    session_factory = session_factory or SessionLocal
    content_path = Path(content_path)

    # The semaphore is held for the whole job, and the session is its OWN: the
    # one injected into the request was closed when the response was sent, and
    # reusing it raises DetachedInstanceError.
    try:
        _run(job_id, content_path, filename, provider, session_factory, settings)
    finally:
        # The spooled upload belongs to this task; nothing else will clean it up.
        content_path.unlink(missing_ok=True)


def _run(
    job_id: str,
    content_path: Path,
    filename: str,
    provider: ExtractionProvider,
    session_factory: sessionmaker,
    settings: Settings,
) -> None:
    with get_semaphore(settings.max_concurrent_extractions), session_factory() as session:
        job = session.get(ExtractionJob, job_id)
        if job is None:
            logger.warning("Extraction job %s vanished before it could run", job_id)
            return

        job.status = JobStatus.PROCESSING.value
        session.commit()

        # EVERYTHING below is guarded, not just the provider call. Persistence
        # can fail too -- a database error, a batch deleted mid-flight -- and an
        # exception escaping here would leave the job stuck in PROCESSING
        # forever, because a background task has nobody to catch it.
        try:
            # Read here rather than in the request: the semaphore is held at
            # this point, so the number of documents resident in memory is
            # bounded by the concurrency limit rather than by how many uploads
            # happen to be in flight.
            result = provider.extract(content_path.read_bytes(), filename)

            batch = session.get(ImportBatch, job.batch_id)
            if batch is None:
                _fail(session, job, "The batch no longer exists.")
                return

            # Taken here, after the model call, so two extractions run in
            # parallel and only their short persistence phase serialises.
            lock_batch(session, job.batch_id)

            # Even a partial extraction is kept: usable records are persisted,
            # incomplete ones become NEEDS_REVIEW rather than being discarded.
            by_status = persist_records(
                session,
                batch,
                result.records,
                source_type=SourceType.PDF.value,
                document_name=filename,
                confidence_threshold=settings.extraction_confidence_threshold,
                field_confidences=result.field_confidence,
                document_id=job.source_document_id,
            )

            job.status = JobStatus.SUCCEEDED.value
            job.record_count = sum(by_status.values())
            if result.usage is not None:
                job.provider = result.usage.provider
                job.model = result.usage.model
                job.input_tokens = result.usage.input_tokens
                job.output_tokens = result.usage.output_tokens
                job.duration_ms = result.usage.duration_ms

            # ONE commit for the records and the job outcome together. Two
            # commits would allow a window where the records exist but the job
            # still says PROCESSING, with nothing to reconcile them.
            session.commit()
        except ProviderError as error:
            _fail(session, job, str(error))
            return
        except Exception as error:  # noqa: BLE001 -- a background task has no caller
            logger.exception("Unexpected extraction failure on job %s", job_id)
            _fail(session, job, f"Unexpected error: {type(error).__name__}")
            return

        logger.info(
            "Extraction job %s succeeded: records=%s statuses=%s",
            job_id,
            job.record_count,
            by_status,
        )


def _fail(session: Session, job: ExtractionJob, message: str) -> None:
    """Record the failure. The message never contains document content.

    The session is rolled back first: a failure part-way through persistence
    could otherwise leave uncommitted records attached, and committing the job
    status would flush them alongside it.
    """
    session.rollback()
    job = session.get(ExtractionJob, job.id)
    if job is None:
        return
    job.status = JobStatus.FAILED.value
    job.error = message[:1000]
    session.commit()
    logger.warning("Extraction job %s failed: %s", job.id, message)
