"""The nine steps of the assignment's "Main workflow", walked in order.

Every other test file covers one unit or one edge case. This one exists to
answer a different question: can a user actually get from an empty account to
an approved record? A suite can be entirely green while the path between its
parts is broken, so the steps are asserted here as a sequence rather than
independently.

The step numbers match the assignment, and are meant to stay matched.
"""

import csv
import io

from app.providers.mock import MockProvider
from tests.factories import VALID_RAW


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def test_csv_workflow_from_import_to_approval(client):
    # 1. Create an import batch.
    response = client.post("/api/batches", json={"name": "Q3 review"})
    assert response.status_code == 201, response.text
    batch_id = response.json()["id"]

    # 2. Upload a CSV file. One clean row, one a reviewer will have to fix.
    clean = dict(VALID_RAW, reference="OK-1")
    broken = dict(VALID_RAW, reference="BAD-1", net_amount="999.00", country="FRA")
    response = client.post(
        f"/api/batches/{batch_id}/uploads/csv",
        files={"file": ("import.csv", _csv_bytes([clean, broken]), "text/csv")},
    )
    assert response.status_code == 201, response.text

    # 3. Extract and normalize into the common data model.
    records = client.get(f"/api/batches/{batch_id}/records").json()["items"]
    assert len(records) == 2

    # 4. View valid records and records requiring review, separately.
    url = f"/api/batches/{batch_id}/records"
    valid = client.get(url, params={"status": "VALID"}).json()["items"]
    needs_review = client.get(url, params={"status": "NEEDS_REVIEW"}).json()["items"]
    assert [record["reference"] for record in valid] == ["OK-1"]
    assert [record["reference"] for record in needs_review] == ["BAD-1"]

    record_id = needs_review[0]["id"]

    # 5. See field-level validation errors: which field, not just how many.
    errors = client.get(f"/api/records/{record_id}/validation-errors").json()
    assert sorted({error["field"] for error in errors}) == ["country", "net_amount"]

    # 6. Correct imported values, and 7. re-run validation after the correction.
    # The correction alone re-runs the pipeline: a user never has to remember to
    # ask for it, which is what keeps a corrected record from staying stale.
    response = client.patch(
        f"/api/records/{record_id}",
        json={"country": "FR", "net_amount": clean["net_amount"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "VALID"
    assert response.json()["validation_errors"] == []

    # 7 again, explicitly: re-running validation is also available on its own and
    # is idempotent -- it must not undo the correction it just confirmed.
    response = client.post(f"/api/records/{record_id}/revalidate")
    assert response.status_code == 200
    assert response.json()["status"] == "VALID"

    # 8. Validate an individual record.
    response = client.post(f"/api/records/{record_id}/validate")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "VALIDATED"

    # 9. View a batch summary.
    summary = client.get(f"/api/batches/{batch_id}/summary").json()
    assert summary["total_records"] == 2
    assert summary["by_status"] == {"VALID": 1, "VALIDATED": 1}
    assert summary["by_source_type"] == {"CSV": 2}


def test_step_two_accepts_several_pdf_documents(client):
    """Step 2 reads "one or more PDF documents" -- the plural is the point."""
    batch_id = client.post("/api/batches", json={"name": "PDF"}).json()["id"]
    uploads = [
        ("files", (f"invoice-{index}.pdf", b"%PDF-1.7\n" + b"x" * 64, "application/pdf"))
        for index in range(3)
    ]
    response = client.post(f"/api/batches/{batch_id}/uploads/pdf", files=uploads)
    assert response.status_code == 202, response.text

    jobs = client.get(f"/api/batches/{batch_id}/jobs").json()
    assert len(jobs) == 3
    assert {job["status"] for job in jobs} == {"SUCCEEDED"}


def test_pdf_extraction_feeds_the_same_pipeline(client_with_provider):
    """Steps 2-3 on the PDF branch reach the same model as the CSV branch.

    The assignment asks for one common data model, so the interesting assertion
    is not that extraction ran -- it is that what comes out of it is indexed,
    filterable and reviewable exactly like an imported row.
    """
    extracted = dict(VALID_RAW, reference="PDF-1")
    # One unsure field: enough to send the record to review on confidence alone,
    # with every other field extracted cleanly.
    confidence = {field: 0.4 if field == "gross_amount" else 1.0 for field in extracted}
    client = client_with_provider(MockProvider(records=[extracted], field_confidence=[confidence]))

    batch_id = client.post("/api/batches", json={"name": "PDF real"}).json()["id"]
    response = client.post(
        f"/api/batches/{batch_id}/uploads/pdf",
        files=[("files", ("statement.pdf", b"%PDF-1.7\n" + b"x" * 64, "application/pdf"))],
    )
    assert response.status_code == 202, response.text

    records = client.get(f"/api/batches/{batch_id}/records").json()["items"]
    assert len(records) == 1
    record = records[0]

    assert record["source_type"] == "PDF"
    assert record["source_document_name"] == "statement.pdf"
    # Low confidence alone forces review, per the data dictionary.
    assert record["status"] == "NEEDS_REVIEW"
    assert record["extraction_confidence"] == "0.40"
    assert record["field_confidence"]["gross_amount"] == 0.4
    # The document is kept, so the reviewer can check the value against it.
    assert record["has_source_document"] is True
