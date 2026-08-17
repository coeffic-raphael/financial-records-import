"""Two imports landing in the same batch at the same time.

The concurrency modelled here is not hypothetical. PDF extraction runs as a
sync background task, which FastAPI dispatches to a threadpool: two documents
uploaded together are persisted by two threads on two connections. The CSV
route is `async`, so a single worker serialises it on the event loop, but
nothing serialises it across workers.
"""

import inspect
import threading
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinancialRecord, ImportBatch
from app.services.ingestion import persist_records
from app.services.records import lock_batch_for_import
from tests.factories import make_raw

THRESHOLD = Decimal("0.70")


def _import_in_thread(engine, batch_id, rows, barrier, failures):
    """One import, in its own transaction, exactly as a background task runs it."""
    try:
        with Session(engine) as session:
            batch = session.get(ImportBatch, batch_id)
            # Both threads are inside a transaction before either writes.
            barrier.wait(timeout=10)
            # The same two steps, in the same order, that run_extraction and the
            # CSV route perform. TestTheCallersTakeIt below is what checks they
            # really do.
            lock_batch_for_import(session, batch_id)
            persist_records(
                session,
                batch,
                rows,
                source_type="CSV",
                document_name="concurrent.csv",
                confidence_threshold=THRESHOLD,
            )
            session.commit()
    except Exception as error:  # noqa: BLE001 -- reported to the test, not swallowed
        failures.append(error)


def _run_together(engine, jobs):
    """jobs: list of (batch_id, rows). Each runs in its own thread."""
    barrier = threading.Barrier(len(jobs), timeout=10)
    failures: list[Exception] = []
    threads = [
        threading.Thread(target=_import_in_thread, args=(engine, batch_id, rows, barrier, failures))
        for batch_id, rows in jobs
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not failures, f"an import raised: {failures[0]!r}"


def _sequences(session, batch_id) -> list[int]:
    return sorted(
        session.scalars(
            select(FinancialRecord.import_sequence).where(FinancialRecord.batch_id == batch_id)
        )
    )


@pytest.fixture
def second_batch(client):
    return client.post("/api/batches", json={"name": "second"}).json()


class TestTwoImportsIntoTheSameBatch:
    def test_no_position_is_used_twice(self, client, batch, engine, session):
        """Each import takes several rows, which is what exposes the defect.

        A counter that reserved one position per import would look correct with
        one row each and overlap the moment either carries more.
        """
        first = [make_raw(reference=f"A-{index}") for index in range(8)]
        second = [make_raw(reference=f"B-{index}") for index in range(3)]

        _run_together(engine, [(batch["id"], first), (batch["id"], second)])

        positions = _sequences(session, batch["id"])
        assert len(positions) == 11
        assert positions == sorted(set(positions)), f"overlapping positions: {positions}"

    def test_the_positions_form_one_unbroken_range(self, client, batch, engine, session):
        first = [make_raw(reference=f"A-{index}") for index in range(8)]
        second = [make_raw(reference=f"B-{index}") for index in range(3)]

        _run_together(engine, [(batch["id"], first), (batch["id"], second)])

        assert _sequences(session, batch["id"]) == list(range(11))

    def test_a_reference_shared_by_both_imports_is_reported(self, client, batch, engine, session):
        """The half a sequence counter cannot fix.

        Under READ COMMITTED neither transaction sees the other's uncommitted
        rows, so without serialisation both would call the shared reference
        valid and the duplicate would go unreported.
        """
        first = [make_raw(reference="SHARED"), make_raw(reference="A-1")]
        second = [make_raw(reference="SHARED"), make_raw(reference="B-1")]

        _run_together(engine, [(batch["id"], first), (batch["id"], second)])

        shared = session.scalars(
            select(FinancialRecord).where(
                FinancialRecord.batch_id == batch["id"],
                FinancialRecord.reference == "SHARED",
            )
        ).all()
        assert len(shared) == 2
        codes = [{error["code"] for error in record.validation_errors} for record in shared]
        assert sum("DUPLICATE_REFERENCE" in entry for entry in codes) == 1, (
            f"exactly one of the two should be flagged, got {codes}"
        )


class TestTwoImportsIntoDifferentBatches:
    def test_they_do_not_block_each_other(self, client, batch, second_batch, engine, session):
        """Serialising per batch, not globally: otherwise the fix is a bottleneck."""
        rows_a = [make_raw(reference=f"A-{index}") for index in range(4)]
        rows_b = [make_raw(reference=f"B-{index}") for index in range(4)]

        _run_together(engine, [(batch["id"], rows_a), (second_batch["id"], rows_b)])

        assert _sequences(session, batch["id"]) == list(range(4))
        assert _sequences(session, second_batch["id"]) == list(range(4))


class TestTheCallersTakeIt:
    """The lock only helps where it is actually taken.

    Both call sites are checked by reading them: the PDF path is the one that
    genuinely runs in parallel, and TestClient executes background tasks inline,
    so an end-to-end test cannot reach that concurrency. A source check is a
    weaker instrument than a behavioural one, and it is used here because the
    stronger one is not available -- not as a shortcut.
    """

    @staticmethod
    def _source(module) -> str:
        return inspect.getsource(module)

    def test_the_csv_route_locks_before_storing_the_document(self):
        """Order matters: store() inserts a child row that locks the parent."""
        from app.api import batches

        source = self._source(batches)
        lock_at = source.index("lock_batch_for_import(session, batch.id)")
        store_at = source.index("document = store(")
        assert lock_at < store_at, (
            "the lock must be taken before store() inserts the source_document row, "
            "or two imports deadlock promoting FOR KEY SHARE to FOR UPDATE"
        )

    def test_the_extraction_task_locks_before_persisting(self):
        from app.services import pdf_extraction

        source = self._source(pdf_extraction)
        lock_at = source.index("lock_batch_for_import(session, job.batch_id)")
        persist_at = source.index("by_status = persist_records(")
        assert lock_at < persist_at
