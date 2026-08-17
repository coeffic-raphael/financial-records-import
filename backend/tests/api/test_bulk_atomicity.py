"""One correction, several records, one transaction.

`apply_correction` used to be the only entry point and it committed. Looping
over it gave a commit per record, so a failure on the third left the first two
written -- while the caller was told nothing had been modified.

The assertions here read from a SEPARATE session on purpose. Querying the
session that failed proves nothing: its identity map still holds the mutated
objects even when no commit ever reached PostgreSQL.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinancialRecord
from app.services import records as records_service
from app.services.records import apply_corrections
from tests.conftest import make_csv, upload_csv
from tests.factories import make_raw

THRESHOLD = Decimal("0.70")


@pytest.fixture
def three_records(client, batch, session):
    rows = [make_raw(reference=f"R-{index}") for index in range(3)]
    upload_csv(client, batch["id"], make_csv(rows), "three.csv")
    return session.scalars(
        select(FinancialRecord)
        .where(FinancialRecord.batch_id == batch["id"])
        .order_by(FinancialRecord.import_sequence)
    ).all()


def _names_from_a_fresh_session(engine, batch_id) -> list[str | None]:
    with Session(engine) as fresh:
        return list(
            fresh.scalars(
                select(FinancialRecord.counterparty_name)
                .where(FinancialRecord.batch_id == batch_id)
                .order_by(FinancialRecord.import_sequence)
            )
        )


def test_all_three_are_corrected_together(three_records, session, engine, batch):
    apply_corrections(session, three_records, {"counterparty_name": "Nordbank"}, THRESHOLD)

    assert _names_from_a_fresh_session(engine, batch["id"]) == ["Nordbank"] * 3


def test_a_failure_part_way_leaves_nothing_written(
    three_records, session, engine, batch, monkeypatch
):
    """The whole contract: a refusal must not leave the rows it prevents."""
    before = _names_from_a_fresh_session(engine, batch["id"])
    calls = {"n": 0}
    real = records_service.correct_in_transaction

    def fail_on_the_second(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(records_service, "correct_in_transaction", fail_on_the_second)

    with pytest.raises(RuntimeError):
        records_service.apply_corrections(
            session, three_records, {"counterparty_name": "Nordbank"}, THRESHOLD
        )
    session.rollback()

    assert calls["n"] == 2, "the first record must have been mutated before the failure"
    assert _names_from_a_fresh_session(engine, batch["id"]) == before


def test_the_reported_statuses_come_from_the_database(three_records, session, engine, batch):
    """`by_status` is what a reviewer reads to know what the click unblocked."""
    by_status = apply_corrections(session, three_records, {"country": "ZZZ"}, THRESHOLD)

    assert by_status == {"NEEDS_REVIEW": 3}
