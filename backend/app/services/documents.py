"""Storing and reading uploaded documents.

Files live outside any served directory and are named after their own
identifier, never after anything a client sent. Reaching one goes through the
tenant-scoped endpoint, which is the only door.
"""

import hashlib
from pathlib import Path

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import APIError, not_found
from app.models import FinancialRecord, ImportBatch, SourceDocument

# Set by the server, never read from the upload. A client-declared type is not
# evidence, and letting one through would decide how a browser interprets the
# file we hand back.
MEDIA_TYPES = {"pdf": "application/pdf", "csv": "text/csv"}


def storage_path(root: str, document_id: str) -> Path:
    """Where a document lives on disk.

    The name is the document's own identifier: no part of the path comes from
    the client, so no filename can escape the directory however it is crafted.
    """
    return Path(root).expanduser().resolve() / document_id


def store(
    session: Session,
    batch: ImportBatch,
    *,
    filename: str,
    kind: str,
    spooled: Path,
    root: str,
) -> SourceDocument:
    """Move a spooled upload into permanent storage and record it."""
    content = spooled.read_bytes()
    document = SourceDocument(
        batch_id=batch.id,
        filename=filename,
        media_type=MEDIA_TYPES[kind],
        byte_size=len(content),
        content_sha256=hashlib.sha256(content).hexdigest(),
    )
    session.add(document)
    session.flush()

    destination = storage_path(root, document.id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return document


def read_for_record(
    session: Session, record: FinancialRecord, root: str
) -> tuple[SourceDocument, bytes]:
    """The document a record came from, for the tenant that owns it.

    The caller has already resolved the record within its tenant, so ownership
    is settled before this is reached.
    """
    if record.source_document_id is None:
        raise not_found("Source document")

    document = session.get(SourceDocument, record.source_document_id)
    if document is None:
        raise not_found("Source document")

    path = storage_path(root, document.id)
    if not path.is_file():
        # The row survived its file: the database is not the storage, and
        # saying so is better than serving nothing with a misleading 404.
        raise APIError(
            status.HTTP_410_GONE,
            "DOCUMENT_UNAVAILABLE",
            "The stored document is no longer available.",
            {"filename": document.filename},
        )
    return document, path.read_bytes()


def sha256_of(path: Path) -> str:
    """Read a spooled upload in chunks: the point of spooling was not to hold
    the whole file in memory, and hashing it in one read would undo that."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def refuse_duplicate(session: Session, batch: ImportBatch, spooled: Path) -> None:
    """Stop a byte-identical document being imported into the same batch twice.

    Scoped to the batch, like the index behind it. The same file legitimately
    belongs in two different batches -- that is a second import, not a mistake.

    Raises rather than skipping, so the caller decides. Importing the same file
    twice is usually an accident and costs the reviewer real work: the supplied
    CSV done twice leaves 60 records, 42 of them needing review, and the only
    way back is deleting the whole batch.
    """
    existing = find_duplicate(session, batch, sha256_of(spooled))
    if existing is None:
        return
    raise APIError(
        status.HTTP_409_CONFLICT,
        "DUPLICATE_DOCUMENT",
        f"{existing.filename} was already imported into this batch.",
        {
            "document_name": existing.filename,
            "uploaded_at": existing.created_at.isoformat(),
        },
    )


def find_duplicate(
    session: Session, batch: ImportBatch, content_sha256: str
) -> SourceDocument | None:
    """A byte-identical document already in this batch, if there is one."""
    return session.scalar(
        select(SourceDocument).where(
            SourceDocument.batch_id == batch.id,
            SourceDocument.content_sha256 == content_sha256,
        )
    )


def collect_stored_files(session: Session, batch_id: str, root: str) -> list[Path]:
    """The paths of every file belonging to a batch.

    The database cascades: dropping the batch row takes its records, jobs and
    source_document rows with it. Files on disk are outside that guarantee, and
    nothing else would ever look at them again -- so they have to be collected
    here or they leak for good.

    Read the paths BEFORE the rows disappear, delete them AFTER the transaction
    commits: a failed delete then leaves files with no rows, which is untidy,
    where the reverse leaves rows pointing at nothing, which is a broken button.
    """
    paths = [
        storage_path(root, document_id)
        for document_id in session.scalars(
            select(SourceDocument.id).where(SourceDocument.batch_id == batch_id)
        )
    ]
    return paths
