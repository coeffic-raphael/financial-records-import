"""Records and the job outcome are written in one transaction.

Persisting the records and then recording the job outcome in a second commit
leaves a window where the records exist under a job that still claims to be
running. Nothing reconciles that afterwards, so the window must not exist.
"""

import pytest

from app.models import FinancialRecord
from app.providers.mock import MockProvider
from tests.conftest import make_csv, upload_csv
from tests.factories import make_raw

RECORDS = [{"reference": f"R-{index}", "gross_amount": "10.00"} for index in range(3)]


@pytest.fixture
def crash_after_records_are_written(monkeypatch):
    """Let persistence do its work, then fail before the outcome is recorded."""
    from app.services import pdf_extraction

    real = pdf_extraction.persist_records

    def _wrapper(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("crash after records were written")

    monkeypatch.setattr(pdf_extraction, "persist_records", _wrapper)


def _upload(client, batch_id):
    return client.post(
        f"/api/batches/{batch_id}/uploads/pdf",
        files=[("files", ("x.pdf", b"%PDF-1.4", "application/pdf"))],
    )


class TestExtractionIsAtomic:
    def test_records_do_not_survive_a_later_failure(
        self, client_with_provider, batch, crash_after_records_are_written
    ):
        """The regression: persist_records used to commit on its own.

        Its rows would then outlive the failure that followed, leaving records
        attached to a job that never reported success.
        """
        client = client_with_provider(MockProvider(records=RECORDS))
        _upload(client, batch["id"])

        assert client.get(f"/api/batches/{batch['id']}/records").json()["items"] == []

    def test_the_job_reports_the_failure(
        self, client_with_provider, batch, crash_after_records_are_written
    ):
        client = client_with_provider(MockProvider(records=RECORDS))
        _upload(client, batch["id"])

        job = client.get(f"/api/batches/{batch['id']}/jobs").json()[0]
        assert job["status"] == "FAILED"
        assert job["record_count"] is None

    def test_a_successful_run_writes_both(self, client_with_provider, batch):
        client = client_with_provider(MockProvider(records=RECORDS))
        _upload(client, batch["id"])

        job = client.get(f"/api/batches/{batch['id']}/jobs").json()[0]
        records = client.get(f"/api/batches/{batch['id']}/records").json()["items"]

        assert job["status"] == "SUCCEEDED"
        assert job["record_count"] == len(records) == 3


class TestCsvImportIsAtomic:
    def test_a_failure_mid_import_leaves_nothing(self, client, batch, session, monkeypatch):
        from app.services import csv_import

        real = csv_import.persist_records

        def _wrapper(*args, **kwargs):
            real(*args, **kwargs)
            raise RuntimeError("crash before commit")

        monkeypatch.setattr(csv_import, "persist_records", _wrapper)

        # TestClient re-raises server exceptions rather than returning 500; what
        # matters here is what the database keeps, not the status code.
        with pytest.raises(RuntimeError, match="crash before commit"):
            upload_csv(client, batch["id"], make_csv([make_raw(), make_raw(reference="B")]))

        session.expire_all()
        assert session.query(FinancialRecord).count() == 0, (
            "rows added before the failure must not outlive it"
        )
