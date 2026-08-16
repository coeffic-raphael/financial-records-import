"""The status machine, and what a caller is allowed to move it with.

The assignment fixes three statuses and one ordering rule: a corrected record
is revalidated before it can become VALIDATED. That rule is only worth
anything if the server owns it, so this file asserts it from the outside --
over HTTP, the way a client that ignored the interface would.

The frontend disables its Validate button on a record with issues. That is an
affordance, not a control: everything here bypasses it.
"""

import pytest

from app.models import FinancialRecord
from app.schemas import BUSINESS_FIELDS, RecordPatch
from tests.conftest import make_csv, upload_csv
from tests.factories import make_raw

SYSTEM_COLUMNS = sorted(set(FinancialRecord.__table__.c.keys()) - set(BUSINESS_FIELDS))


@pytest.fixture
def record(client, batch):
    """Build one record in whichever status a test asks for."""

    def _make(status: str, reference: str = "R-1"):
        row = make_raw(reference=reference)
        if status == "NEEDS_REVIEW":
            row = make_raw(reference=reference, country="FRA")
        upload_csv(client, batch["id"], make_csv([row]), f"{reference}.csv")
        items = client.get(f"/api/batches/{batch['id']}/records").json()["items"]
        made = next(item for item in items if item["reference"] == reference)
        if status == "VALIDATED":
            made = client.post(f"/api/records/{made['id']}/validate").json()
        assert made["status"] == status
        return made

    return _make


class TestWhatMayMoveARecord:
    def test_only_business_fields_can_be_sent(self):
        """The allowlist is the schema itself, not a check inside a handler."""
        assert set(RecordPatch.model_fields) == set(BUSINESS_FIELDS)

    @pytest.mark.parametrize("column", SYSTEM_COLUMNS)
    def test_no_system_column_can_be_written(self, client, record, column):
        """Derived from the model, so a column added later is refused by default.

        This is the generic form of "status is not writable". `status` and
        `validation_errors` are the obvious ones, but `extraction_confidence`
        matters just as much: a client that could raise it would be declaring
        the model certain of a value it never read.
        """
        made = record("NEEDS_REVIEW")
        response = client.patch(f"/api/records/{made['id']}", json={column: "anything"})
        assert response.status_code == 422, f"{column} was accepted"

    def test_a_refused_field_changes_nothing(self, client, record):
        """422 rather than a silent partial write."""
        made = record("NEEDS_REVIEW")
        client.patch(
            f"/api/records/{made['id']}",
            json={"status": "VALIDATED", "description": "smuggled in"},
        )
        after = client.get(f"/api/records/{made['id']}").json()
        assert after["status"] == "NEEDS_REVIEW"
        assert after["description"] == made["description"]


class TestApprovalIsReachableFromOneStatusOnly:
    @pytest.mark.parametrize("status", ["NEEDS_REVIEW", "VALIDATED"])
    def test_validate_is_refused(self, client, record, status):
        made = record(status)
        response = client.post(f"/api/records/{made['id']}/validate")
        assert response.status_code == 409
        assert response.json()["code"] == "RECORD_NOT_VALID"

    def test_validate_is_accepted_from_valid(self, client, record):
        made = record("VALID")
        assert client.post(f"/api/records/{made['id']}/validate").json()["status"] == "VALIDATED"


class TestACorrectionAlwaysPrecedesApproval:
    """The assignment's ordering rule, in the two directions it can be broken."""

    def test_a_correction_drops_an_approval_even_when_it_fixes_nothing(self, client, record):
        """The subtle direction.

        Editing a description on an approved record does not make the record
        wrong -- but it does mean nobody has approved *this* version. Staying
        VALIDATED would let an edit ride on an earlier approval.
        """
        made = record("VALIDATED")
        after = client.patch(f"/api/records/{made['id']}", json={"description": "reworded"}).json()
        assert after["status"] == "VALID"

    def test_a_correction_that_breaks_the_record_sends_it_back_to_review(self, client, record):
        made = record("VALIDATED")
        after = client.patch(f"/api/records/{made['id']}", json={"country": "ZZZ"}).json()
        assert after["status"] == "NEEDS_REVIEW"
        assert {e["code"] for e in after["validation_errors"]} == {"INVALID_COUNTRY_CODE"}

    def test_approval_must_be_asked_for_again_after_a_correction(self, client, record):
        """End to end: approve, edit, and the approval is gone until re-asked."""
        made = record("VALIDATED")
        client.patch(f"/api/records/{made['id']}", json={"description": "reworded"})
        assert client.get(f"/api/records/{made['id']}").json()["status"] == "VALID"

        again = client.post(f"/api/records/{made['id']}/validate")
        assert again.json()["status"] == "VALIDATED"


class TestTheServerDecidesRegardlessOfTheCaller:
    def test_revalidation_recomputes_from_what_was_imported(self, client, record):
        """Status is derived, never asserted.

        `raw_payload` is the source of truth, so revalidating cannot drift from
        what the import decided -- the same code answers both.
        """
        made = record("NEEDS_REVIEW")
        assert client.post(f"/api/records/{made['id']}/revalidate").json()["status"] == (
            "NEEDS_REVIEW"
        )

    def test_a_corrected_value_is_normalized_server_side(self, client, record):
        """The client sends raw text; the server decides what it means.

        No frontend formatting is trusted, which is what lets a reviewer type
        an amount the way their locale writes it.
        """
        made = record("NEEDS_REVIEW")
        after = client.patch(
            f"/api/records/{made['id']}", json={"country": "fr ", "gross_amount": "1 200,00"}
        ).json()
        assert after["country"] == "FR"
        assert after["gross_amount"] == "1200.00"
