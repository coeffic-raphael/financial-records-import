"""Rows that are broken as CSV, not merely invalid as data.

The assignment's CSV carries rows that are *semantically* wrong -- a bad
country, an amount that does not add up -- and the oracle test covers those.
This file covers the other kind: rows a spreadsheet export mangles, where the
question is whether a record survives at all.

The requirement is "import all rows rather than rejecting the whole file", so
the property under test is that a mangled row still becomes a record someone
can look at, and never becomes a plausible-looking record with wrong values.
"""

from tests.conftest import upload_csv

HEADER = (
    "reference,transaction_date,description,gross_amount,fee_amount,tax_amount,"
    "net_amount,currency,counterparty_name,counterparty_account,country,category,"
    "invoice_number,payment_method,value_date"
)
COMPLETE = (
    "TX-1,2026-07-01,Fee,100.00,0.00,20.00,120.00,EUR,ACME,FR76,FR,SOFTWARE,INV-1,CARD,2026-07-02"
)


def upload(client, batch, *rows: str):
    body = "\n".join([HEADER, *rows]) + "\n"
    return upload_csv(client, batch["id"], body.encode(), "export.csv")


def records(client, batch):
    return client.get(f"/api/batches/{batch['id']}/records", params={"limit": 200}).json()


class TestARowThatDoesNotMatchTheHeader:
    def test_a_short_row_is_imported_rather_than_skipped(self, client, batch):
        """Fewer columns than the header: the missing ones are simply absent."""
        upload(client, batch, "TX-2,2026-07-01,Truncated")
        page = records(client, batch)

        assert page["total"] == 1
        record = page["items"][0]
        assert record["reference"] == "TX-2"
        assert record["status"] == "NEEDS_REVIEW"
        assert "REQUIRED_FIELD_MISSING" in {e["code"] for e in record["validation_errors"]}

    def test_trailing_extra_columns_do_not_disturb_the_mapped_ones(self, client, batch):
        """More columns than the header: the surplus is past every known field.

        Nothing is silently altered here -- the values that matter are the ones
        the header names, and they are all present and correct.
        """
        upload(client, batch, COMPLETE + ", a trailing note")
        record = records(client, batch)["items"][0]

        assert record["status"] == "VALID"
        assert record["gross_amount"] == "100.00"
        assert record["currency"] == "EUR"

    def test_a_comma_that_shifts_the_columns_is_loud_not_silent(self, client, batch):
        """The failure mode that would actually hurt.

        An unescaped comma inside a field shifts every later value by one
        position. The danger is not that the row is refused -- it is that it
        could be stored as a confident, plausible record holding another
        column's value. It must land in review instead.
        """
        upload(
            client,
            batch,
            "TX-3,2026-07-01,Fee, quarterly,100.00,0.00,20.00,120.00,"
            "EUR,ACME,FR76,FR,SOFTWARE,INV,CARD,2026-07-02",
        )
        record = records(client, batch)["items"][0]

        assert record["status"] == "NEEDS_REVIEW"
        # The shift is caught in several places at once, which is the point:
        # a currency holding "120.00" cannot pass for data anyone would trust.
        assert {"NOT_NUMERIC", "UNSUPPORTED_CURRENCY"} <= {
            error["code"] for error in record["validation_errors"]
        }


class TestWhitespaceAndQuoting:
    def test_a_blank_line_is_not_a_record(self, client, batch):
        """Deliberate: an empty line carries no row to import.

        Exports routinely end with one, and turning it into a NEEDS_REVIEW
        record with every field missing would add noise to the reviewer's
        queue for something the file never claimed was a transaction.
        """
        upload(client, batch, COMPLETE, "", COMPLETE.replace("TX-1", "TX-4"))
        page = records(client, batch)

        assert page["total"] == 2
        assert {r["reference"] for r in page["items"]} == {"TX-1", "TX-4"}

    def test_a_row_of_separators_is_a_record(self, client, batch):
        """Unlike a blank line, this one does claim to be a row -- an empty one."""
        upload(client, batch, "," * 14)
        page = records(client, batch)

        assert page["total"] == 1
        assert page["items"][0]["status"] == "NEEDS_REVIEW"

    def test_a_quoted_field_may_span_several_lines(self, client, batch):
        """A newline inside quotes is one record, not two broken ones."""
        upload(
            client,
            batch,
            'TX-5,2026-07-01,"Line one\nline two",100.00,0.00,20.00,120.00,'
            "EUR,ACME,FR76,FR,SOFTWARE,INV,CARD,2026-07-02",
        )
        page = records(client, batch)

        assert page["total"] == 1
        assert page["items"][0]["description"] == "Line one\nline two"
        assert page["items"][0]["status"] == "VALID"


class TestTheFileItselfIsNeverTheUnitOfRejection:
    def test_one_unreadable_row_does_not_cost_the_others(self, client, batch):
        """The explicit requirement, stated as a mix rather than as a single row."""
        response = upload(
            client,
            batch,
            COMPLETE,
            "TX-6,not-a-date,Broken,abc,0.00,20.00,120.00,XXX,ACME,FR76,ZZ,NOPE,INV,CARD,",
            COMPLETE.replace("TX-1", "TX-7"),
        )
        assert response.status_code == 201
        assert response.json()["by_status"] == {"VALID": 2, "NEEDS_REVIEW": 1}

    def test_every_row_keeps_the_name_of_the_file_it_came_from(self, client, batch):
        """Two files, one batch: the filename is a property of the record."""
        upload_csv(client, batch["id"], f"{HEADER}\n{COMPLETE}\n".encode(), "january.csv")
        upload_csv(
            client,
            batch["id"],
            f"{HEADER}\n{COMPLETE.replace('TX-1', 'TX-8')}\n".encode(),
            "february.csv",
        )
        page = records(client, batch)

        assert {r["reference"]: r["source_document_name"] for r in page["items"]} == {
            "TX-1": "january.csv",
            "TX-8": "february.csv",
        }

    def test_records_belong_to_the_batch_they_were_uploaded_into(self, client, batch):
        other = client.post("/api/batches", json={"name": "another"}).json()
        upload(client, batch, COMPLETE)
        upload_csv(
            client, other["id"], f"{HEADER}\n{COMPLETE.replace('TX-1', 'TX-9')}\n".encode(), "o.csv"
        )

        here = records(client, batch)
        there = client.get(f"/api/batches/{other['id']}/records").json()

        assert {r["reference"] for r in here["items"]} == {"TX-1"}
        assert {r["reference"] for r in there["items"]} == {"TX-9"}
        assert {r["batch_id"] for r in here["items"]} == {batch["id"]}
