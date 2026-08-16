"""Paging a batch's records.

The assignment asks a user to "view valid records and records requiring
review". A batch holds as many records as the uploaded file had rows, so that
list is the one place where a single upload decides the size of a response.
These tests pin the two properties a reviewer depends on: a page is bounded,
and walking the pages sees every record exactly once.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.api.batches import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.models import FinancialRecord
from tests.conftest import make_csv, upload_csv
from tests.factories import make_raw

TOTAL = 120
ONE_DAY = timedelta(days=1)


@pytest.fixture
def large_batch(client, batch):
    """A batch larger than one default page, in a known order."""
    rows = [make_raw(reference=f"TX-{index:04d}") for index in range(TOTAL)]
    upload_csv(client, batch["id"], make_csv(rows))
    return batch["id"]


def page(client, batch_id, **params):
    return client.get(f"/api/batches/{batch_id}/records", params=params).json()


class TestAPageIsBounded:
    def test_an_oversized_batch_does_not_come_back_whole(self, client, large_batch):
        body = page(client, large_batch)
        assert len(body["items"]) == DEFAULT_PAGE_SIZE
        assert body["total"] == TOTAL

    def test_the_caller_cannot_ask_for_an_unbounded_page(self, client, large_batch):
        response = client.get(
            f"/api/batches/{large_batch}/records", params={"limit": MAX_PAGE_SIZE + 1}
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": -1}, {"offset": -1}])
    def test_meaningless_paging_is_refused(self, client, large_batch, params):
        assert client.get(f"/api/batches/{large_batch}/records", params=params).status_code == 422


class TestWalkingThePages:
    def test_every_record_is_seen_exactly_once(self, client, large_batch):
        """The property that matters: no record is skipped and none is shown twice.

        The walk is bounded rather than looping until an empty page. An
        endpoint that ignored `limit` would return everything every time and a
        "loop until empty" walk would never end -- it would hang the suite
        instead of reporting the regression it exists to catch.
        """
        limit = 25
        seen = []
        for offset in range(0, TOTAL + limit, limit):
            body = page(client, large_batch, limit=limit, offset=offset)
            assert len(body["items"]) <= limit
            seen += [item["reference"] for item in body["items"]]

        assert len(seen) == TOTAL
        assert len(set(seen)) == TOTAL

    def test_the_order_is_the_order_of_the_imported_file(self, client, large_batch):
        first = page(client, large_batch, limit=5)["items"]
        assert [item["reference"] for item in first] == [f"TX-{i:04d}" for i in range(5)]

    def test_the_same_page_asked_twice_is_the_same_page(self, client, large_batch):
        """Ordering is total, so a page cannot shift between two identical requests."""
        once = [item["id"] for item in page(client, large_batch, limit=10, offset=30)["items"]]
        twice = [item["id"] for item in page(client, large_batch, limit=10, offset=30)["items"]]
        assert once == twice

    def test_the_sort_key_is_the_import_order_not_the_clock(self, client, session, large_batch):
        """`created_at` is deliberately not the sort key.

        Timestamps within one import are only as distinct as the clock's
        resolution, so ordering on them makes a record's page depend on how
        fast the machine was. Reversing them here is a stand-in for that: the
        order must follow `import_sequence` regardless of what the clock said.
        """
        records = session.scalars(
            select(FinancialRecord).where(FinancialRecord.batch_id == large_batch)
        ).all()
        for record in records:
            record.created_at = datetime(2026, 1, 1) - record.import_sequence * ONE_DAY
        session.commit()

        first = page(client, large_batch, limit=5)["items"]
        assert [item["reference"] for item in first] == [f"TX-{index:04d}" for index in range(5)]

    def test_pages_do_not_overlap(self, client, large_batch):
        first = {item["id"] for item in page(client, large_batch, limit=40)["items"]}
        second = {item["id"] for item in page(client, large_batch, limit=40, offset=40)["items"]}
        assert first.isdisjoint(second)

    def test_reading_past_the_end_is_empty_rather_than_an_error(self, client, large_batch):
        body = page(client, large_batch, offset=TOTAL + 10)
        assert body["items"] == []
        # The total still describes the set, not the empty page in front of us.
        assert body["total"] == TOTAL


class TestTheTotalDescribesTheFilteredSet:
    def test_a_filter_narrows_the_count_too(self, client, batch, sample_csv):
        """A count taken from `items` would silently become "up to 50"."""
        upload_csv(client, batch["id"], sample_csv)
        body = page(client, batch["id"], status="NEEDS_REVIEW", limit=5)
        assert len(body["items"]) == 5
        assert body["total"] == 12

    def test_paging_stays_inside_the_filter(self, client, batch, sample_csv):
        upload_csv(client, batch["id"], sample_csv)
        seen = []
        for offset in range(0, 12, 5):
            seen += page(client, batch["id"], status="NEEDS_REVIEW", limit=5, offset=offset)[
                "items"
            ]
        assert len(seen) == 12
        assert {item["status"] for item in seen} == {"NEEDS_REVIEW"}


class TestPagingIsStillTenantScoped:
    def test_paging_parameters_do_not_open_another_tenants_batch(self, other_client, batch):
        """Paging is not a side door: the batch check happens first."""
        response = other_client.get(
            f"/api/batches/{batch['id']}/records", params={"limit": 1, "offset": 0}
        )
        assert response.status_code == 404
