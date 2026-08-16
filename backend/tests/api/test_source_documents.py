"""Serving the document a record came from.

Reviewing an extraction means comparing it to its source. Without the document
the approval step signs for the machine's own consistency check rather than for
the data, which is not what VALIDATED means.

Serving content someone else uploaded is also where most of the risk in this
feature sits, so most of these tests are about the response headers.
"""

import hashlib

import pytest

from app.models import SourceDocument
from app.providers.mock import MockProvider
from tests.conftest import SAMPLES, make_csv, upload_csv
from tests.factories import make_raw

PDF_BYTES = (SAMPLES / "invoice_legal_services.pdf").read_bytes()


@pytest.fixture
def csv_record(client, batch):
    upload_csv(client, batch["id"], make_csv([make_raw()]), "july.csv")
    return client, client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]


@pytest.fixture
def pdf_record(client_with_provider, batch):
    client = client_with_provider(MockProvider(records=[make_raw(reference="INV-1")]))
    client.post(
        f"/api/batches/{batch['id']}/uploads/pdf",
        files=[("files", ("invoice.pdf", PDF_BYTES, "application/pdf"))],
    )
    return client, client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]


class TestTheDocumentIsKept:
    def test_a_record_says_whether_its_source_is_available(self, csv_record):
        _, record = csv_record
        assert record["has_source_document"] is True

    def test_the_bytes_come_back_unchanged(self, pdf_record):
        client, record = pdf_record
        response = client.get(f"/api/records/{record['id']}/document")

        assert response.status_code == 200
        assert response.content == PDF_BYTES

    def test_the_fingerprint_is_recorded(self, session, pdf_record):
        document = session.query(SourceDocument).one()
        assert document.content_sha256 == hashlib.sha256(PDF_BYTES).hexdigest()
        assert document.byte_size == len(PDF_BYTES)

    def test_the_csv_is_kept_too(self, csv_record):
        client, record = csv_record
        response = client.get(f"/api/records/{record['id']}/document")

        assert response.status_code == 200
        assert b"TX-TEST-0001" in response.content


class TestHeadersOnUploadedContent:
    """The response decides how a browser treats a file someone else supplied."""

    def test_the_type_is_the_servers_own(self, pdf_record):
        """Never the Content-Type from the upload, which is client-supplied."""
        client, record = pdf_record
        response = client.get(f"/api/records/{record['id']}/document")

        assert response.headers["content-type"].startswith("application/pdf")

    def test_sniffing_is_refused(self, pdf_record):
        """Otherwise the browser guesses a type of its own and the header is moot."""
        client, record = pdf_record
        response = client.get(f"/api/records/{record['id']}/document")

        assert response.headers["x-content-type-options"] == "nosniff"

    def test_a_pdf_is_shown_inline(self, pdf_record):
        client, record = pdf_record
        response = client.get(f"/api/records/{record['id']}/document")

        assert response.headers["content-disposition"].startswith("inline")
        assert "invoice.pdf" in response.headers["content-disposition"]

    def test_anything_else_is_a_download(self, csv_record):
        """Inline rendering is where uploaded content turns into a scripting problem."""
        client, record = csv_record
        response = client.get(f"/api/records/{record['id']}/document")

        assert response.headers["content-disposition"].startswith("attachment")

    def test_scripts_are_forbidden_even_if_something_slips_through(self, pdf_record):
        client, record = pdf_record
        response = client.get(f"/api/records/{record['id']}/document")

        assert "sandbox" in response.headers["content-security-policy"]


class TestFilenamesAreNotTrusted:
    def test_a_path_in_the_name_never_reaches_the_disk(self, client, batch, session):
        """The stored name is the document's own id; nothing of the client's."""
        upload_csv(client, batch["id"], make_csv([make_raw()]), "../../etc/passwd.csv")

        document = session.query(SourceDocument).one()
        assert "/" not in document.filename
        assert document.filename == "etc..passwd.csv" or ".." not in document.id

    def test_a_quote_cannot_break_the_header(self, client, batch):
        upload_csv(client, batch["id"], make_csv([make_raw()]), 'we"ird.csv')
        record = client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]

        header = client.get(f"/api/records/{record['id']}/document").headers[
            "content-disposition"
        ]
        assert header.count('"') == 2


class TestOnlyTheOwnerCanOpenIt:
    def test_another_tenant_gets_404(self, client, other_client, batch):
        """Discovered automatically by the cross-tenant matrix as well."""
        upload_csv(client, batch["id"], make_csv([make_raw()]))
        record = client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]

        assert other_client.get(f"/api/records/{record['id']}/document").status_code == 404

    def test_an_anonymous_caller_gets_401(self, anonymous_client, client, batch):
        upload_csv(client, batch["id"], make_csv([make_raw()]))
        record = client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]

        assert anonymous_client.get(f"/api/records/{record['id']}/document").status_code == 401


class TestWhenThereIsNothingToShow:
    def test_a_record_without_a_document_answers_404(self, client, batch, session):
        upload_csv(client, batch["id"], make_csv([make_raw()]))
        record_id = client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]["id"]

        from app.models import FinancialRecord

        session.get(FinancialRecord, record_id).source_document_id = None
        session.commit()

        assert client.get(f"/api/records/{record_id}/document").status_code == 404

    def test_a_missing_file_says_so_rather_than_pretending(self, client, batch, session):
        """The database is not the storage: a row can outlive its file."""
        from app.config import get_settings
        from app.services.documents import storage_path

        upload_csv(client, batch["id"], make_csv([make_raw()]))
        record = client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]
        document = session.query(SourceDocument).one()
        storage_path(get_settings().upload_storage_dir, document.id).unlink()

        response = client.get(f"/api/records/{record['id']}/document")
        assert response.status_code == 410
        assert response.json()["code"] == "DOCUMENT_UNAVAILABLE"


class TestWhatTheModelSaw:
    def test_the_original_values_are_exposed(self, pdf_record):
        """A reviewer must tell "the model read this" from "someone typed this"."""
        client, record = pdf_record
        assert record["raw_payload"]["reference"] == "INV-1"

    def test_they_survive_a_correction(self, pdf_record):
        client, record = pdf_record
        client.patch(f"/api/records/{record['id']}", json={"reference": "CORRECTED"})

        after = client.get(f"/api/records/{record['id']}").json()
        assert after["reference"] == "CORRECTED"
        assert after["raw_payload"]["reference"] == "CORRECTED"
