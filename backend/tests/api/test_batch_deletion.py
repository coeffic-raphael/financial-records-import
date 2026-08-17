"""Deleting a batch.

The only way to undo an import. Uploading the wrong file otherwise leaves a
batch that can never be removed, which is how a workspace fills with noise.

What makes this worth testing is the reach: one row deleted takes records, jobs
and stored documents with it, across the database AND the filesystem, which do
not share a transaction.
"""

from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import ExtractionJob, FinancialRecord, ImportBatch, SourceDocument
from tests.conftest import make_csv, upload_csv
from tests.factories import make_raw


@pytest.fixture
def loaded_batch(client, batch, sample_csv):
    """A batch with records and a stored source document."""
    upload_csv(client, batch["id"], sample_csv, "transactions_import.csv")
    return batch


def _files(session, batch_id) -> list[Path]:
    root = get_settings().upload_storage_dir
    return [
        Path(root) / document_id
        for document_id in session.scalars(
            select(SourceDocument.id).where(SourceDocument.batch_id == batch_id)
        )
    ]


class TestWhatDeletionTakesWithIt:
    def test_the_batch_is_gone(self, client, loaded_batch, session):
        assert client.delete(f"/api/batches/{loaded_batch['id']}").status_code == 204
        assert session.get(ImportBatch, loaded_batch["id"]) is None

    def test_its_records_go_too(self, client, loaded_batch, session):
        client.delete(f"/api/batches/{loaded_batch['id']}")

        remaining = session.scalars(
            select(FinancialRecord).where(FinancialRecord.batch_id == loaded_batch["id"])
        ).all()
        assert remaining == []

    def test_its_source_documents_go_too(self, client, loaded_batch, session):
        client.delete(f"/api/batches/{loaded_batch['id']}")

        remaining = session.scalars(
            select(SourceDocument).where(SourceDocument.batch_id == loaded_batch["id"])
        ).all()
        assert remaining == []

    def test_the_files_on_disk_go_too(self, client, loaded_batch, session):
        """The database cascade cannot reach these, so the route must.

        Left behind they would leak permanently: nothing else ever looks at a
        file whose row is gone.
        """
        paths = _files(session, loaded_batch["id"])
        assert paths and all(path.exists() for path in paths)

        client.delete(f"/api/batches/{loaded_batch['id']}")

        assert not any(path.exists() for path in paths)

    def test_extraction_jobs_go_too(self, client, batch, session):
        client.post(
            f"/api/batches/{batch['id']}/uploads/pdf",
            files=[("files", ("a.pdf", b"%PDF-1.7\n" + b"x" * 64, "application/pdf"))],
        )
        client.delete(f"/api/batches/{batch['id']}")

        remaining = session.scalars(
            select(ExtractionJob).where(ExtractionJob.batch_id == batch["id"])
        ).all()
        assert remaining == []


class TestWhatDeletionLeavesAlone:
    def test_another_batch_is_untouched(self, client, loaded_batch, session):
        other = client.post("/api/batches", json={"name": "keep me"}).json()
        upload_csv(client, other["id"], make_csv([make_raw(reference="K-1")]), "keep.csv")

        client.delete(f"/api/batches/{loaded_batch['id']}")

        assert session.get(ImportBatch, other["id"]) is not None
        kept = session.scalars(
            select(FinancialRecord).where(FinancialRecord.batch_id == other["id"])
        ).all()
        assert len(kept) == 1
        assert all(path.exists() for path in _files(session, other["id"]))

    def test_an_approved_record_does_not_block_it(self, client, loaded_batch, session):
        """Deliberate: nothing un-approves a record, so refusing here would make
        the batch permanently undeletable. The interface warns instead."""
        record = client.get(f"/api/batches/{loaded_batch['id']}/records?status=VALID").json()[
            "items"
        ][0]
        assert client.post(f"/api/records/{record['id']}/validate").status_code == 200

        assert client.delete(f"/api/batches/{loaded_batch['id']}").status_code == 204


class TestOnlyTheOwnerCanDeleteIt:
    def test_another_tenant_gets_404(self, other_client, loaded_batch, session):
        assert other_client.delete(f"/api/batches/{loaded_batch['id']}").status_code == 404
        assert session.get(ImportBatch, loaded_batch["id"]) is not None

    def test_an_anonymous_caller_is_refused(self, anonymous_client, loaded_batch):
        assert anonymous_client.delete(f"/api/batches/{loaded_batch['id']}").status_code == 401

    def test_an_unknown_batch_is_404(self, client):
        assert client.delete("/api/batches/does-not-exist").status_code == 404
