"""Record router.

`status` appears nowhere as a writable field. It changes only through
server-side recomputation or the explicit `validate` action -- otherwise a
client could declare itself VALIDATED without ever passing validation.
"""

from fastapi import APIRouter, Depends, Response

from app.api.deps import SessionDep, TenantDep, current_tenant
from app.config import get_settings
from app.models import FinancialRecord
from app.schemas import RecordOut, RecordPatch, ValidationErrorOut
from app.services.documents import read_for_record
from app.services.records import (
    apply_correction,
    approve_record,
    get_record,
    revalidate_record,
)

router = APIRouter(
    prefix="/records",
    tags=["records"],
    dependencies=[Depends(current_tenant)],
)


@router.get("/{record_id}", response_model=RecordOut)
def read_record(record_id: str, session: SessionDep, tenant: TenantDep) -> FinancialRecord:
    return get_record(session, record_id, tenant.id)


@router.get("/{record_id}/validation-errors", response_model=list[ValidationErrorOut])
def read_validation_errors(
    record_id: str, session: SessionDep, tenant: TenantDep
) -> list[dict]:
    return get_record(session, record_id, tenant.id).validation_errors


@router.get("/{record_id}/document")
def read_source_document(
    record_id: str, session: SessionDep, tenant: TenantDep
) -> Response:
    """Serve the document a record was extracted from.

    Reviewing an extraction means comparing it to its source. Without this the
    approval step signs for the machine's own consistency check rather than for
    the data, which is not what VALIDATED is supposed to mean.

    Three headers matter here, because this is content someone else uploaded:
      - Content-Type comes from a closed list held by the server, never from the
        upload, so a file cannot decide how the browser treats it;
      - nosniff stops the browser from guessing a different one anyway;
      - only PDFs are shown inline. Anything else is a download, since inline
        rendering is where uploaded content turns into a scripting problem.
    """
    record = get_record(session, record_id, tenant.id)
    document, content = read_for_record(session, record, get_settings().upload_storage_dir)

    inline = document.media_type == "application/pdf"
    quoted = document.filename.replace('"', "")
    return Response(
        content=content,
        media_type=document.media_type,
        headers={
            "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{quoted}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; object-src 'none'; sandbox",
        },
    )


@router.patch("/{record_id}", response_model=RecordOut)
def correct_record(
    record_id: str, payload: RecordPatch, session: SessionDep, tenant: TenantDep
) -> FinancialRecord:
    """A correction ALWAYS revalidates; the status is recomputed, never supplied."""
    record = get_record(session, record_id, tenant.id)
    changes = payload.model_dump(exclude_unset=True)
    return apply_correction(
        session, record, changes, get_settings().extraction_confidence_threshold
    )


@router.post("/{record_id}/revalidate", response_model=RecordOut)
def rerun_validation(
    record_id: str, session: SessionDep, tenant: TenantDep
) -> FinancialRecord:
    record = get_record(session, record_id, tenant.id)
    return revalidate_record(session, record, get_settings().extraction_confidence_threshold)


@router.post("/{record_id}/validate", response_model=RecordOut)
def validate(record_id: str, session: SessionDep, tenant: TenantDep) -> FinancialRecord:
    return approve_record(session, get_record(session, record_id, tenant.id))
