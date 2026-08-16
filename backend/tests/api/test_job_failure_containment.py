"""No failure may leave a job stuck in PROCESSING.

A background task has nobody to catch what it raises. Guarding only the provider
call left persistence unguarded: a database error there would end the task with
the job still claiming to be running, and nothing would ever correct it.
"""

import pytest

from app.providers.mock import MockProvider


@pytest.fixture
def failing_persistence(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("database exploded during persistence")

    monkeypatch.setattr("app.services.pdf_extraction.persist_records", _boom)


def _upload(client, batch_id):
    return client.post(
        f"/api/batches/{batch_id}/uploads/pdf",
        files=[("files", ("x.pdf", b"%PDF-1.4", "application/pdf"))],
    )


def test_a_persistence_failure_marks_the_job_failed(
    client_with_provider, batch, failing_persistence
):
    client = client_with_provider(MockProvider(records=[{"reference": "R-1"}]))
    _upload(client, batch["id"])

    job = client.get(f"/api/batches/{batch['id']}/jobs").json()[0]
    assert job["status"] == "FAILED", "a job must never be left claiming to be running"
    assert "Unexpected error" in job["error"]


def test_a_persistence_failure_leaves_no_half_written_records(
    client_with_provider, batch, failing_persistence
):
    client = client_with_provider(MockProvider(records=[{"reference": "R-1"}]))
    _upload(client, batch["id"])

    assert client.get(f"/api/batches/{batch['id']}/records").json()["items"] == []


def test_the_api_survives_a_persistence_failure(
    client_with_provider, batch, failing_persistence
):
    client = client_with_provider(MockProvider(records=[{"reference": "R-1"}]))
    _upload(client, batch["id"])

    assert client.get("/api/health").json() == {"status": "ok"}


def test_no_job_is_ever_left_in_processing(client_with_provider, batch, failing_persistence):
    """The invariant, stated directly: PROCESSING is a transient state only."""
    client = client_with_provider(MockProvider(records=[{"reference": "R-1"}]))
    _upload(client, batch["id"])

    statuses = {j["status"] for j in client.get(f"/api/batches/{batch['id']}/jobs").json()}
    assert "PROCESSING" not in statuses
    assert "PENDING" not in statuses
