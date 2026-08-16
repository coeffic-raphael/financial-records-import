"""CSV ingestion through the API."""

from tests.conftest import make_csv, upload_csv
from tests.factories import make_raw


class TestSampleFile:
    def test_import_matches_the_oracle(self, client, batch, sample_csv):
        """The supplied CSV must land in the database as 18 VALID / 12 NEEDS_REVIEW.

        The domain suite already proves this in memory; this proves it survives
        normalization, persistence and serialization.
        """
        response = upload_csv(client, batch["id"], sample_csv, "transactions_import.csv")
        assert response.status_code == 201

        body = response.json()
        assert body["imported"] == 30
        assert body["by_status"] == {"VALID": 18, "NEEDS_REVIEW": 12}

    def test_original_filename_is_preserved(self, client, batch, sample_csv):
        """Explicit assignment requirement."""
        upload_csv(client, batch["id"], sample_csv, "transactions_import.csv")
        records = client.get(f"/api/batches/{batch['id']}/records").json()["items"]
        assert {r["source_document_name"] for r in records} == {"transactions_import.csv"}
        assert {r["source_type"] for r in records} == {"CSV"}

    def test_amounts_are_serialized_as_strings(self, client, batch, sample_csv):
        """A JSON number would be parsed back into a float, losing precision."""
        upload_csv(client, batch["id"], sample_csv)
        records = client.get(f"/api/batches/{batch['id']}/records").json()["items"]
        first = next(r for r in records if r["reference"] == "TX-2026-0001")
        assert first["net_amount"] == "1463.09"
        assert isinstance(first["net_amount"], str)


class TestMalformedFiles:
    def test_missing_required_columns_is_rejected_as_a_whole(self, client, batch):
        """The only global-rejection case: the file itself is unusable."""
        content = make_csv([{"reference": "A"}], columns=["reference", "description"])
        response = upload_csv(client, batch["id"], content)

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "INVALID_CSV_STRUCTURE"
        assert "currency" in body["details"]["missing_columns"]

    def test_rejected_file_inserts_nothing(self, client, batch):
        content = make_csv([{"reference": "A"}], columns=["reference", "description"])
        upload_csv(client, batch["id"], content)
        assert client.get(f"/api/batches/{batch['id']}/records").json()["items"] == []

    def test_header_only_file_imports_zero_rows(self, client, batch):
        response = upload_csv(client, batch["id"], make_csv([]))
        assert response.status_code == 201
        assert response.json()["imported"] == 0

    def test_non_utf8_content_is_rejected(self, client, batch):
        response = upload_csv(client, batch["id"], b"\xff\xfe\x00invalid")
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_ENCODING"


class TestInvalidRows:
    def test_bad_rows_are_imported_not_rejected(self, client, batch):
        """The assignment requires importing every row rather than failing the file."""
        content = make_csv([make_raw(), make_raw(reference="B", currency="JPY")])
        response = upload_csv(client, batch["id"], content)

        assert response.json()["by_status"] == {"VALID": 1, "NEEDS_REVIEW": 1}

    def test_duplicate_reference_flags_the_second_occurrence_only(self, client, batch):
        """Order matters: the first row keeps its reference, the second is the offender."""
        content = make_csv([make_raw(), make_raw(description="Same reference again")])
        upload_csv(client, batch["id"], content)

        records = client.get(f"/api/batches/{batch['id']}/records").json()["items"]
        assert records[0]["status"] == "VALID"
        assert records[1]["status"] == "NEEDS_REVIEW"
        assert [e["code"] for e in records[1]["validation_errors"]] == ["DUPLICATE_REFERENCE"]

    def test_field_level_errors_are_exposed(self, client, batch):
        content = make_csv([make_raw(currency="JPY")])
        upload_csv(client, batch["id"], content)

        record = client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]
        errors = client.get(f"/api/records/{record['id']}/validation-errors").json()
        assert errors == [
            {
                "field": "currency",
                "code": "UNSUPPORTED_CURRENCY",
                "message": errors[0]["message"],
            }
        ]


class TestFiltering:
    """`total` is asserted alongside `items`: it is the number the reviewer
    reads to size the work, so a filter that narrowed the page but not the
    count would be worse than one that did nothing."""

    def test_filter_by_status(self, client, batch, sample_csv):
        upload_csv(client, batch["id"], sample_csv)
        url = f"/api/batches/{batch['id']}/records"
        valid = client.get(url, params={"status": "VALID"}).json()
        review = client.get(url, params={"status": "NEEDS_REVIEW"}).json()
        assert (len(valid["items"]), valid["total"]) == (18, 18)
        assert (len(review["items"]), review["total"]) == (12, 12)

    def test_filter_by_source_type(self, client, batch, sample_csv):
        upload_csv(client, batch["id"], sample_csv)
        url = f"/api/batches/{batch['id']}/records"
        csv_page = client.get(url, params={"source_type": "CSV"}).json()
        pdf_page = client.get(url, params={"source_type": "PDF"}).json()
        assert (len(csv_page["items"]), csv_page["total"]) == (30, 30)
        assert (pdf_page["items"], pdf_page["total"]) == ([], 0)
