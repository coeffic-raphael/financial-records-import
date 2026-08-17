"""Correcting several records of a batch in one request.

The reason it exists: the supplied bank statement produces eight records that
name no counterparty, because the document names none. Sixteen corrections, one
screen at a time, for a value the reviewer knows once.
"""

import pytest
from sqlalchemy import select

from app.models import FinancialRecord
from tests.conftest import make_csv, upload_csv
from tests.factories import make_raw


@pytest.fixture
def records(client, batch):
    """Three records with no counterparty, which is the case in hand."""
    rows = [make_raw(reference=f"R-{index}", counterparty_name="") for index in range(3)]
    upload_csv(client, batch["id"], make_csv(rows), "three.csv")
    return client.get(f"/api/batches/{batch['id']}/records").json()["items"]


def correct(client, batch_id, ids, changes):
    return client.patch(
        f"/api/batches/{batch_id}/records", json={"record_ids": ids, "changes": changes}
    )


class TestOneCorrectionAcrossSeveralRecords:
    def test_it_applies_to_all_of_them(self, client, batch, records):
        ids = [record["id"] for record in records]

        response = correct(client, batch["id"], ids, {"counterparty_name": "Nordbank"})

        assert response.status_code == 200
        assert response.json()["updated"] == 3
        after = client.get(f"/api/batches/{batch['id']}/records").json()["items"]
        assert {record["counterparty_name"] for record in after} == {"Nordbank"}

    def test_it_reports_what_the_click_unblocked(self, client, batch, records):
        """The number a reviewer is after: how many rows this actually freed."""
        ids = [record["id"] for record in records]

        body = correct(client, batch["id"], ids, {"counterparty_name": "Nordbank"}).json()

        assert body["by_status"] == {"VALID": 3}

    def test_fields_that_were_not_sent_are_untouched(self, client, batch, records):
        """The invariant behind exclude_unset.

        RecordPatch carries fifteen fields; dumping it without that flag returns
        fourteen extra Nones, and a one-field correction would empty the record.
        """
        record = records[0]
        before = {name: record[name] for name in ("reference", "description", "net_amount")}

        correct(client, batch["id"], [record["id"]], {"counterparty_name": "Nordbank"})

        after = client.get(f"/api/records/{record['id']}").json()
        assert {name: after[name] for name in before} == before

    def test_it_normalises_like_the_single_route(self, client, batch, records):
        correct(client, batch["id"], [records[0]["id"]], {"gross_amount": "1 200,00"})

        assert client.get(f"/api/records/{records[0]['id']}").json()["gross_amount"] == "1200.00"

    def test_a_correction_drops_an_approval(self, client, batch, records):
        """Same rule as the single route: nothing rides on an earlier approval."""
        target = records[0]
        correct(client, batch["id"], [target["id"]], {"counterparty_name": "Nordbank"})
        assert client.post(f"/api/records/{target['id']}/validate").status_code == 200

        correct(client, batch["id"], [target["id"]], {"description": "reworded"})

        assert client.get(f"/api/records/{target['id']}").json()["status"] == "VALID"


class TestWhatIsRefused:
    def test_an_unknown_id_refuses_the_whole_request(self, client, batch, records, session):
        ids = [records[0]["id"], "does-not-exist"]

        assert correct(client, batch["id"], ids, {"counterparty_name": "X"}).status_code == 404

        untouched = session.scalars(
            select(FinancialRecord.counterparty_name).where(FinancialRecord.batch_id == batch["id"])
        ).all()
        assert all(name is None for name in untouched), "a refused request wrote something"

    def test_a_record_from_another_batch_is_unknown_here(self, client, batch, records):
        other = client.post("/api/batches", json={"name": "elsewhere"}).json()
        upload_csv(client, other["id"], make_csv([make_raw(reference="E-1")]), "e.csv")
        foreign = client.get(f"/api/batches/{other['id']}/records").json()["items"][0]

        response = correct(client, batch["id"], [foreign["id"]], {"country": "FR"})

        assert response.status_code == 404

    @pytest.mark.parametrize(
        ("label", "body"),
        [
            ("empty list", {"record_ids": [], "changes": {"country": "FR"}}),
            ("empty changes", {"record_ids": ["x"], "changes": {}}),
            ("duplicate ids", {"record_ids": ["x", "x"], "changes": {"country": "FR"}}),
            ("reference", {"record_ids": ["x"], "changes": {"reference": "SAME"}}),
            ("status", {"record_ids": ["x"], "changes": {"status": "VALIDATED"}}),
            ("unknown field", {"record_ids": ["x"], "changes": {"nope": "1"}}),
        ],
    )
    def test_the_request_shape_is_refused(self, client, batch, label, body):
        assert client.patch(f"/api/batches/{batch['id']}/records", json=body).status_code == 422

    def test_more_than_two_hundred_records_is_refused(self, client, batch):
        body = {"record_ids": [f"id-{n}" for n in range(201)], "changes": {"country": "FR"}}

        assert client.patch(f"/api/batches/{batch['id']}/records", json=body).status_code == 422


class TestOnlyTheOwner:
    def test_another_tenant_gets_404(self, other_client, batch, records):
        response = correct(other_client, batch["id"], [records[0]["id"]], {"country": "FR"})

        assert response.status_code == 404

    def test_an_anonymous_caller_is_refused(self, anonymous_client, batch, records):
        response = correct(anonymous_client, batch["id"], [records[0]["id"]], {"country": "FR"})

        assert response.status_code == 401
