"""Duplicate policy: first occurrence wins, and it must stay that way.

Two properties are asserted here, both of which were broken before an explicit
`import_sequence` existed:

- uniqueness is scoped to the BATCH, so a second upload sees the first one;
- the verdict is STABLE, so revalidating a record returns the same answer it
  got at import time unless the data actually changed.
"""

from tests.conftest import make_csv, upload_csv
from tests.factories import make_raw


def _references(client, batch_id):
    return [
        (r["reference"], r["status"], [e["code"] for e in r["validation_errors"]])
        for r in client.get(f"/api/batches/{batch_id}/records").json()
    ]


class TestAcrossUploads:
    def test_second_upload_sees_the_first(self, client, batch):
        """Uniqueness is batch-scoped, not file-scoped.

        Starting each import from an empty set of seen references would let the
        same reference through twice, and the record would then disagree with
        itself the moment it was revalidated.
        """
        upload_csv(client, batch["id"], make_csv([make_raw()]), "first.csv")
        upload_csv(client, batch["id"], make_csv([make_raw()]), "second.csv")

        rows = _references(client, batch["id"])
        assert rows[0][1] == "VALID"
        assert rows[1][1] == "NEEDS_REVIEW"
        assert rows[1][2] == ["DUPLICATE_REFERENCE"]

    def test_distinct_references_across_uploads_stay_valid(self, client, batch):
        upload_csv(client, batch["id"], make_csv([make_raw()]), "first.csv")
        upload_csv(client, batch["id"], make_csv([make_raw(reference="TX-B")]), "second.csv")

        assert [row[1] for row in _references(client, batch["id"])] == ["VALID", "VALID"]

    def test_uniqueness_does_not_leak_between_batches(self, client):
        """Within an import means within a batch: another batch is unaffected."""
        first = client.post("/api/batches", json={"name": "A"}).json()["id"]
        second = client.post("/api/batches", json={"name": "B"}).json()["id"]

        upload_csv(client, first, make_csv([make_raw()]))
        upload_csv(client, second, make_csv([make_raw()]))

        assert _references(client, second)[0][1] == "VALID"


class TestStability:
    """Revalidation must not change a verdict on its own."""

    def test_revalidating_the_first_occurrence_keeps_it_valid(self, client, batch):
        """The regression this whole design exists to prevent.

        Comparing a record against every sibling rather than against those that
        arrived before it made the first of two duplicates flip to
        NEEDS_REVIEW -- a VALID record becoming invalid with no correction.
        """
        upload_csv(client, batch["id"], make_csv([make_raw(), make_raw()]))
        first = client.get(f"/api/batches/{batch['id']}/records").json()[0]

        response = client.post(f"/api/records/{first['id']}/revalidate")

        assert response.json()["status"] == "VALID"
        assert response.json()["validation_errors"] == []

    def test_revalidating_the_second_occurrence_keeps_it_duplicated(self, client, batch):
        upload_csv(client, batch["id"], make_csv([make_raw(), make_raw()]))
        second = client.get(f"/api/batches/{batch['id']}/records").json()[1]

        response = client.post(f"/api/records/{second['id']}/revalidate")

        assert [e["code"] for e in response.json()["validation_errors"]] == [
            "DUPLICATE_REFERENCE"
        ]

    def test_repeated_revalidation_is_stable(self, client, batch):
        upload_csv(client, batch["id"], make_csv([make_raw(), make_raw()]))
        records = client.get(f"/api/batches/{batch['id']}/records").json()

        for _ in range(3):
            for record, expected in zip(records, ["VALID", "NEEDS_REVIEW"], strict=True):
                got = client.post(f"/api/records/{record['id']}/revalidate").json()
                assert got["status"] == expected

    def test_editing_an_unrelated_field_does_not_change_the_verdict(self, client, batch):
        upload_csv(client, batch["id"], make_csv([make_raw(), make_raw()]))
        first = client.get(f"/api/batches/{batch['id']}/records").json()[0]

        response = client.patch(
            f"/api/records/{first['id']}", json={"description": "Renamed"}
        )
        assert response.json()["status"] == "VALID"

    def test_renaming_the_duplicate_frees_both(self, client, batch):
        upload_csv(client, batch["id"], make_csv([make_raw(), make_raw()]))
        records = client.get(f"/api/batches/{batch['id']}/records").json()

        client.patch(f"/api/records/{records[1]['id']}", json={"reference": "TX-B"})

        for record in records:
            got = client.post(f"/api/records/{record['id']}/revalidate").json()
            assert got["status"] == "VALID"
