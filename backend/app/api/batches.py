"""Batch router.

Secure by construction: the tenant dependency is declared ON THE ROUTER, so it
applies to everything inside it. Adding an endpoint here cannot accidentally
skip tenant scoping -- that would require moving it to the public router
deliberately.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy import select

from app.api.deps import SessionDep, TenantDep, current_tenant
from app.api.errors import APIError, not_found
from app.config import get_settings
from app.models import FinancialRecord, ImportBatch
from app.schemas import BatchCreate, BatchOut, BatchSummary, ImportResult, RecordOut
from app.services.csv_import import import_csv
from app.services.summary import build_summary

router = APIRouter(
    prefix="/batches",
    tags=["batches"],
    dependencies=[Depends(current_tenant)],
)


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
) -> ImportResult:
    batch = _get_batch(session, batch_id, tenant.id)
    settings = get_settings()

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise APIError(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "FILE_TOO_LARGE",
            "The uploaded file exceeds the maximum allowed size.",
            {"max_bytes": settings.max_upload_bytes},
        )

    # The client-supplied filename is never trusted as a path: only its base
    # name is kept, and it is stored as data, never used to build a filesystem
    # location.
    filename = (file.filename or "upload.csv").replace("\\", "/").split("/")[-1]

    return import_csv(
        session, batch, filename, content, settings.extraction_confidence_threshold
    )


@router.get("/{batch_id}/records", response_model=list[RecordOut])
def list_records(
    batch_id: str,
    session: SessionDep,
    tenant: TenantDep,
    record_status: str | None = Query(default=None, alias="status"),
    source_type: str | None = Query(default=None),
) -> list[FinancialRecord]:
    batch = _get_batch(session, batch_id, tenant.id)
    query = select(FinancialRecord).where(FinancialRecord.batch_id == batch.id)
    if record_status:
        query = query.where(FinancialRecord.status == record_status)
    if source_type:
        query = query.where(FinancialRecord.source_type == source_type)
    return list(session.scalars(query.order_by(FinancialRecord.created_at)))


@router.get("/{batch_id}/summary", response_model=BatchSummary)
def get_summary(batch_id: str, session: SessionDep, tenant: TenantDep) -> BatchSummary:
    return build_summary(session, _get_batch(session, batch_id, tenant.id))
