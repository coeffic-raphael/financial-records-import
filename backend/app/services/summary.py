"""Batch summary.

Amounts are aggregated in Python rather than in SQL. `NUMERIC(18, 2)` could be
summed in the query; at the scale of a batch (tens of records) moving it would
buy nothing measurable, and currencies must stay separated either way. It stays
in Python until a profile says otherwise.
"""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExtractionJob, FinancialRecord, ImportBatch
from app.schemas import BatchSummary, CurrencyTotal, DocumentCount


def build_summary(session: Session, batch: ImportBatch) -> BatchSummary:
    records = list(
        session.scalars(select(FinancialRecord).where(FinancialRecord.batch_id == batch.id))
    )

    by_status: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    by_document: dict[str, int] = defaultdict(int)
    by_currency: dict[str, Decimal] = defaultdict(Decimal)

    for record in records:
        by_status[record.status] += 1
        by_source[record.source_type] += 1
        by_document[record.source_document_name] += 1
        # Never sum across currencies: adding EUR to USD is accounting nonsense.
        if record.currency and record.net_amount is not None:
            by_currency[record.currency] += record.net_amount

    jobs: dict[str, int] = defaultdict(int)
    for job_status in session.scalars(
        select(ExtractionJob.status).where(ExtractionJob.batch_id == batch.id)
    ):
        jobs[job_status] += 1

    return BatchSummary(
        batch_id=batch.id,
        batch_name=batch.name,
        total_records=len(records),
        by_status=dict(by_status),
        by_source_type=dict(by_source),
        documents=[
            DocumentCount(source_document_name=name, count=count)
            for name, count in sorted(by_document.items())
        ],
        extraction_jobs=dict(jobs),
        totals_by_currency=[
            CurrencyTotal(currency=currency, net_amount=total)
            for currency, total in sorted(by_currency.items())
        ],
    )
