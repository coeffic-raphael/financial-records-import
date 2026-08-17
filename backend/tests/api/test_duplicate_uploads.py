"""Uploading the same document into the same batch twice.

Left alone this is quietly expensive. The supplied CSV imported twice leaves 60
records, 42 of them needing review -- every row of the second import flagged as
a duplicate reference -- and the only way back is deleting the whole batch.

So the server refuses and says what it found. It does not decide: `force` lets
the caller go ahead once a person has been asked.
"""

import pytest

from tests.conftest import make_csv, upload_csv
from tests.factories import make_raw

PDF = b"%PDF-1.7\n" + b"x" * 64


def _upload_pdf(client, batch_id, name="invoice.pdf", content=PDF, force=False):
    return client.post(
        f"/api/batches/{batch_id}/uploads/pdf",
        files=[("files", (name, content, "application/pdf"))],
        params={"force": "true"} if force else None,
    )


class TestTheSecondUploadIsRefused:
    def test_an_identical_csv_is_refused(self, client, batch, sample_csv):
        assert upload_csv(client, batch["id"], sample_csv).status_code == 201

        response = upload_csv(client, batch["id"], sample_csv)

        assert response.status_code == 409
        assert response.json()["code"] == "DUPLICATE_DOCUMENT"

    def test_it_says_which_document_and_when(self, client, batch, sample_csv):
        upload_csv(client, batch["id"], sample_csv, "january.csv")

        details = upload_csv(client, batch["id"], sample_csv, "again.csv").json()["details"]

        assert details["document_name"] == "january.csv"
        assert details["uploaded_at"]

    def test_nothing_is_imported_by_the_refused_attempt(self, client, batch, sample_csv):
        """The whole point: a refusal must not leave the rows it prevents."""
        upload_csv(client, batch["id"], sample_csv)
        upload_csv(client, batch["id"], sample_csv)

        assert client.get(f"/api/batches/{batch['id']}/records").json()["total"] == 30

    def test_a_renamed_file_is_still_the_same_file(self, client, batch, sample_csv):
        """Matched on content, not on name -- renaming is not a new import."""
        upload_csv(client, batch["id"], sample_csv, "january.csv")

        assert upload_csv(client, batch["id"], sample_csv, "february.csv").status_code == 409

    def test_an_identical_pdf_is_refused(self, client, batch):
        assert _upload_pdf(client, batch["id"]).status_code == 202

        assert _upload_pdf(client, batch["id"], name="copy.pdf").status_code == 409

    def test_a_duplicate_among_several_pdfs_stops_all_of_them(self, client, batch):
        """Same rule as the size check: a bad third file must not leave the
        first two already queued."""
        _upload_pdf(client, batch["id"], name="first.pdf")

        response = client.post(
            f"/api/batches/{batch['id']}/uploads/pdf",
            files=[
                ("files", ("new.pdf", b"%PDF-1.7\nnew content", "application/pdf")),
                ("files", ("again.pdf", PDF, "application/pdf")),
            ],
        )

        assert response.status_code == 409
        assert len(client.get(f"/api/batches/{batch['id']}/jobs").json()) == 1


class TestWhatIsNotADuplicate:
    def test_a_different_file_goes_through(self, client, batch, sample_csv):
        upload_csv(client, batch["id"], sample_csv)

        other = make_csv([make_raw(reference="OTHER-1")])
        assert upload_csv(client, batch["id"], other, "other.csv").status_code == 201

    def test_the_same_file_in_another_batch_is_a_second_import(self, client, batch, sample_csv):
        """Scoped to the batch on purpose: the same statement legitimately
        belongs to two different imports."""
        upload_csv(client, batch["id"], sample_csv)
        other = client.post("/api/batches", json={"name": "another"}).json()

        assert upload_csv(client, other["id"], sample_csv).status_code == 201


class TestTheCallerCanInsist:
    def test_force_imports_it_anyway(self, client, batch, sample_csv):
        """The server refuses; it does not forbid. The interface asks a person
        first, and this is what carries their answer."""
        upload_csv(client, batch["id"], sample_csv)

        response = client.post(
            f"/api/batches/{batch['id']}/uploads/csv",
            files={"file": ("again.csv", sample_csv, "text/csv")},
            params={"force": "true"},
        )

        assert response.status_code == 201
        assert client.get(f"/api/batches/{batch['id']}/records").json()["total"] == 60

    def test_force_works_for_pdfs_too(self, client, batch):
        _upload_pdf(client, batch["id"])

        assert _upload_pdf(client, batch["id"], name="copy.pdf", force=True).status_code == 202


@pytest.mark.parametrize("endpoint", ["csv", "pdf"])
def test_the_refusal_is_scoped_to_the_tenant(other_client, batch, sample_csv, endpoint):
    """A foreign batch is not found, so its documents cannot be probed for."""
    if endpoint == "csv":
        response = upload_csv(other_client, batch["id"], sample_csv)
    else:
        response = _upload_pdf(other_client, batch["id"])
    assert response.status_code == 404
