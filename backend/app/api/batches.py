"""Batch router.

Secure by construction: the tenant dependency is declared ON THE ROUTER, so it
applies to everything inside it. Adding an endpoint here cannot accidentally
skip tenant scoping -- that would require moving it to the public router
deliberately.
"""

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import (
    SessionDep,
    SessionFactoryDep,
    TenantDep,
    current_tenant,
    get_extraction_provider,
)
from app.api.errors import APIError, not_found
from app.config import get_settings
from app.models import ExtractionJob, FinancialRecord, ImportBatch
from app.providers.base import ExtractionProvider
from app.schemas import (
    BatchCreate,
    BatchOut,
    BatchSummary,
    ExtractionAccepted,
    ExtractionJobOut,
    ImportResult,
    Page,
    RecordOut,
)
from app.services.csv_import import import_csv
from app.services.documents import collect_stored_files, refuse_duplicate, store
from app.services.pdf_extraction import create_jobs, run_extraction
from app.services.records import lock_batch_for_import
from app.services.summary import build_summary

router = APIRouter(
    prefix="/batches",
    tags=["batches"],
    dependencies=[Depends(current_tenant)],
)


def _safe_filename(raw: str | None, fallback: str) -> str:
    """Keep the base name only.

    A client-supplied filename is data, never a path: it is stored and displayed
    but never used to build a filesystem location. Control characters are
    stripped so the value cannot disturb a log line or a terminal.
    """
    name = (raw or fallback).replace("\\", "/").split("/")[-1]
    name = "".join(character for character in name if character.isprintable())
    return name.strip() or fallback


PDF_MAGIC = b"%PDF"
UPLOAD_CHUNK_BYTES = 64 * 1024


async def _spool_upload(
    upload: UploadFile, max_bytes: int, fallback: str, kind: str
) -> tuple[str, Path]:
    """Stream an upload to disk, refusing it as soon as it is too large.

    Reading the whole body and then measuring it makes the size limit a
    FUNCTIONAL limit, not a memory one: an 11 MB file is fully resident before
    being rejected, and several uploads in one request multiply that. Reading in
    chunks and stopping at the threshold means an oversized upload never
    occupies more than one chunk.

    The content goes to a temporary file because the background task needs it
    after the response has been sent, by which point the request's own upload
    object is closed. The task deletes it when it is done.
    """
    filename = _safe_filename(upload.filename, fallback)
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")  # noqa: SIM115
    path = Path(handle.name)
    total = 0
    head = b""

    try:
        while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
            total += len(chunk)
            if total > max_bytes:
                raise APIError(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    "FILE_TOO_LARGE",
                    "The uploaded file exceeds the maximum allowed size.",
                    {"filename": filename, "max_bytes": max_bytes},
                )
            if len(head) < len(PDF_MAGIC):
                head += chunk[: len(PDF_MAGIC) - len(head)]
            handle.write(chunk)

        # The declared Content-Type is client-supplied and therefore not
        # evidence. Checking the real signature costs four bytes and stops a
        # mislabelled file from reaching a paid API only to fail there.
        if kind == "pdf" and not head.startswith(PDF_MAGIC):
            raise APIError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "NOT_A_PDF",
                "The uploaded file is not a PDF document.",
                {"filename": filename},
            )
    except BaseException:
        handle.close()
        path.unlink(missing_ok=True)
        raise

    handle.close()
    return filename, path


def _get_batch(session, batch_id: str, tenant_id: str) -> ImportBatch:
    batch = session.scalar(
        select(ImportBatch).where(ImportBatch.id == batch_id, ImportBatch.tenant_id == tenant_id)
    )
    if batch is None:
        raise not_found("Batch")
    return batch


@router.post("", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
def create_batch(payload: BatchCreate, session: SessionDep, tenant: TenantDep) -> ImportBatch:
    batch = ImportBatch(name=payload.name, tenant_id=tenant.id)
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


@router.get("", response_model=list[BatchOut])
def list_batches(session: SessionDep, tenant: TenantDep) -> list[ImportBatch]:
    return list(
        session.scalars(
            select(ImportBatch)
            .where(ImportBatch.tenant_id == tenant.id)
            .order_by(ImportBatch.created_at.desc())
        )
    )


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_batch(batch_id: str, session: SessionDep, tenant: TenantDep) -> None:
    """Delete a batch and everything it holds.

    The obvious recovery from uploading the wrong file, and the only one: there
    is no other way to undo an import.

    Deliberately NOT refused on a batch holding approved records. That guard
    would be defensible -- approving is a human act and deleting erases it --
    but nothing un-approves a record, so it would create batches that can never
    be removed. The interface states what is about to be destroyed instead,
    which puts the fact where the decision is made.
    """
    batch = _get_batch(session, batch_id, tenant.id)
    settings = get_settings()

    # Read the paths first: the rows are about to cascade away with the batch.
    paths = collect_stored_files(session, batch.id, settings.upload_storage_dir)

    session.delete(batch)
    session.commit()

    # After the commit, never before. A failure here leaves files with no rows,
    # which is untidy; the reverse leaves rows pointing at files that are gone,
    # which is the broken "open the source document" button.
    for path in paths:
        path.unlink(missing_ok=True)


@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: str, session: SessionDep, tenant: TenantDep) -> ImportBatch:
    return _get_batch(session, batch_id, tenant.id)


@router.post(
    "/{batch_id}/uploads/csv",
    response_model=ImportResult,
    status_code=status.HTTP_201_CREATED,
)
async def upload_csv(
    batch_id: str,
    file: Annotated[UploadFile, File()],
    session: SessionDep,
    tenant: TenantDep,
    force: bool = Query(
        default=False,
        description="Import a document already present in this batch. The client "
        "asks the person first; the server never decides this on its own.",
    ),
) -> ImportResult:
    batch = _get_batch(session, batch_id, tenant.id)
    settings = get_settings()

    # Spooled like a PDF, so the size limit bounds memory here too, and stored
    # for the same reason: a reviewer checking an imported row should be able to
    # open the file it came from.
    filename, spooled = await _spool_upload(file, settings.max_upload_bytes, "upload.csv", "csv")
    try:
        # Before the lock and before any write: refusing after storing the
        # document would leave the very row this check exists to prevent.
        if not force:
            refuse_duplicate(session, batch, spooled)
        # Before store(), not inside persist_records(). store() inserts a
        # source_document row whose foreign key makes PostgreSQL take a
        # FOR KEY SHARE lock on this batch; two imports would then each hold one
        # and deadlock trying to promote it to FOR UPDATE.
        lock_batch_for_import(session, batch.id)
        document = store(
            session,
            batch,
            filename=filename,
            kind="csv",
            spooled=spooled,
            root=settings.upload_storage_dir,
        )
        return import_csv(
            session,
            batch,
            filename,
            spooled.read_bytes(),
            settings.extraction_confidence_threshold,
            document_id=document.id,
        )
    finally:
        spooled.unlink(missing_ok=True)


@router.post(
    "/{batch_id}/uploads/pdf",
    response_model=ExtractionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_pdfs(
    batch_id: str,
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File()],
    session: SessionDep,
    tenant: TenantDep,
    provider: Annotated[ExtractionProvider, Depends(get_extraction_provider)],
    session_factory: SessionFactoryDep,
    force: bool = Query(
        default=False,
        description="Import a document already present in this batch. The client "
        "asks the person first; the server never decides this on its own.",
    ),
) -> ExtractionAccepted:
    """Accept one or more PDFs and answer immediately.

    202, not 201: nothing has been extracted yet. An invoice takes seconds and a
    statement longer, so holding the request open would leave the interface
    frozen and risk a proxy timeout. The client follows progress through the
    returned jobs.
    """
    batch = _get_batch(session, batch_id, tenant.id)
    settings = get_settings()

    # EVERY file is validated before ANY job is created. Validating as we go
    # would mean a rejected third file leaves the first two already queued: the
    # client receives an error while work is under way, which is the worst of
    # both answers. Any file already spooled is removed if a later one fails.
    spooled: list[tuple[str, Path]] = []
    try:
        for upload in files:
            spooled.append(
                await _spool_upload(upload, settings.max_upload_bytes, "document.pdf", "pdf")
            )
    except BaseException:
        for _, path in spooled:
            path.unlink(missing_ok=True)
        raise

    # Checked once every file is on disk and before any is stored, for the same
    # reason the spooling is grouped: a duplicate in the third file must not
    # leave the first two imported.
    if not force:
        try:
            for _, path in spooled:
                refuse_duplicate(session, batch, path)
        except BaseException:
            for _, path in spooled:
                path.unlink(missing_ok=True)
            raise

    documents = [
        store(
            session,
            batch,
            filename=filename,
            kind="pdf",
            spooled=path,
            root=settings.upload_storage_dir,
        )
        for filename, path in spooled
    ]

    # One transaction for every job, so a failure part-way cannot leave a job
    # persisted as PENDING with no task ever queued for it.
    jobs = create_jobs(session, batch, documents)

    for job, (filename, path) in zip(jobs, spooled, strict=True):
        # Queued rather than awaited; the task opens its own session, reads the
        # spooled file and deletes it.
        background_tasks.add_task(run_extraction, job.id, path, filename, provider, session_factory)

    return ExtractionAccepted(jobs=[ExtractionJobOut.model_validate(job) for job in jobs])


@router.get("/{batch_id}/jobs", response_model=list[ExtractionJobOut])
def list_jobs(batch_id: str, session: SessionDep, tenant: TenantDep) -> list[ExtractionJob]:
    """Extraction state for this batch. Polled by the frontend until settled."""
    batch = _get_batch(session, batch_id, tenant.id)
    return list(
        session.scalars(
            select(ExtractionJob)
            .where(ExtractionJob.batch_id == batch.id)
            .order_by(ExtractionJob.created_at)
        )
    )


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@router.get("/{batch_id}/records", response_model=Page[RecordOut])
def list_records(
    batch_id: str,
    session: SessionDep,
    tenant: TenantDep,
    record_status: str | None = Query(default=None, alias="status"),
    source_type: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> Page[RecordOut]:
    """Return one page of a batch's records.

    The page is bounded by the server, not by the caller's good manners: a
    batch holds as many records as the uploaded file had rows, so an unbounded
    list would let a single import decide how much memory a response takes.

    Ordering is `import_sequence`, the position the row had in its import. It
    is the order a reviewer expects -- the order of the file they uploaded --
    and it is total within a batch, so a record cannot appear on two pages or
    on none because two timestamps happened to tie.
    """
    batch = _get_batch(session, batch_id, tenant.id)

    filtered = select(FinancialRecord).where(FinancialRecord.batch_id == batch.id)
    if record_status:
        filtered = filtered.where(FinancialRecord.status == record_status)
    if source_type:
        filtered = filtered.where(FinancialRecord.source_type == source_type)

    # Counted over the filtered set, before the slice: this is what tells a
    # reviewer how much work is left, not how much fits on one page.
    total = session.scalar(select(func.count()).select_from(filtered.subquery())) or 0
    records = session.scalars(
        filtered.order_by(FinancialRecord.import_sequence).limit(limit).offset(offset)
    )
    # Converted here rather than left to the response model: parametrizing a
    # generic is the one place a stray ORM object would reach Pydantic itself.
    return Page[RecordOut](
        items=[RecordOut.model_validate(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{batch_id}/summary", response_model=BatchSummary)
def get_summary(batch_id: str, session: SessionDep, tenant: TenantDep) -> BatchSummary:
    return build_summary(session, _get_batch(session, batch_id, tenant.id))
