"""Upload rejection happens before any work is started.

A batch of uploads is validated as a whole. Validating file by file would mean a
rejected third file leaves the first two already queued: the client receives an
error while extraction is under way, which is the worst of both answers.
"""

import pytest

from app.providers.mock import MockProvider

VALID_PDF = b"%PDF-1.4 minimal"


@pytest.fixture
def client(client_with_provider):
    return client_with_provider(MockProvider(records=[{"reference": "R-1"}]))


def _upload(client, batch_id, files):
    return client.post(f"/api/batches/{batch_id}/uploads/pdf", files=files)


class TestAllOrNothing:
    def test_one_bad_file_queues_nothing(self, client, batch):
        oversized = b"%PDF" + b"x" * (11 * 1024 * 1024)
        response = _upload(
            client,
            batch["id"],
            [
                ("files", ("ok1.pdf", VALID_PDF, "application/pdf")),
                ("files", ("ok2.pdf", VALID_PDF, "application/pdf")),
                ("files", ("huge.pdf", oversized, "application/pdf")),
            ],
        )

        assert response.status_code == 413
        assert client.get(f"/api/batches/{batch['id']}/jobs").json() == [], (
            "the two valid files must not have been queued"
        )

    def test_a_valid_batch_queues_everything(self, client, batch):
        response = _upload(
            client,
            batch["id"],
            [("files", (f"ok{i}.pdf", VALID_PDF, "application/pdf")) for i in range(3)],
        )

        assert response.status_code == 202
        assert len(client.get(f"/api/batches/{batch['id']}/jobs").json()) == 3


class TestRealTypeIsChecked:
    """The declared Content-Type is client-supplied and therefore not evidence."""

    def test_a_mislabelled_file_is_refused(self, client, batch):
        response = _upload(
            client,
            batch["id"],
            [("files", ("evil.pdf", b"not a pdf at all", "application/pdf"))],
        )

        assert response.status_code == 422
        assert response.json()["code"] == "NOT_A_PDF"

    def test_a_mislabelled_file_creates_no_job(self, client, batch):
        _upload(client, batch["id"], [("files", ("evil.pdf", b"nope", "application/pdf"))])
        assert client.get(f"/api/batches/{batch['id']}/jobs").json() == []

    def test_the_rejection_names_the_offending_file(self, client, batch):
        response = _upload(
            client,
            batch["id"],
            [
                ("files", ("good.pdf", VALID_PDF, "application/pdf")),
                ("files", ("bad.pdf", b"nope", "application/pdf")),
            ],
        )
        assert response.json()["details"]["filename"] == "bad.pdf"
