"""SQLAlchemy models.

Two schema-level decisions deserve attention, because both are cases where the
"obviously correct" constraint would break an explicit requirement.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base, Money
from app.domain.enums import RecordStatus, SourceType


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


# UUIDs are stored as CHAR(36) rather than a native type: PostgreSQL has UUID,
# SQLite does not, and a portable column keeps the migration honest.
UUID_LEN = 36


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[str] = mapped_column(String(UUID_LEN), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    batches: Mapped[list["ImportBatch"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class ImportBatch(Base):
    __tablename__ = "import_batch"

    id: Mapped[str] = mapped_column(String(UUID_LEN), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    # The single edge carrying tenant isolation. financial_record inherits it
    # through batch_id and deliberately does NOT duplicate tenant_id: two
    # sources of truth for one fact eventually diverge.
    tenant_id: Mapped[str] = mapped_column(
        String(UUID_LEN), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )

    tenant: Mapped[Tenant] = relationship(back_populates="batches")
    records: Mapped[list["FinancialRecord"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_import_batch_tenant", "tenant_id"),)


class FinancialRecord(Base):
    """The common model from the data dictionary, plus technical columns.

    NO UNIQUE(batch_id, reference) CONSTRAINT -- deliberately.
    The assignment requires importing every row rather than rejecting the file,
    and the supplied CSV contains an intentional duplicate (TX-2026-0003).
    A uniqueness constraint would crash that insert instead of persisting the
    row as NEEDS_REVIEW. Uniqueness is an application-level validation rule.
    Please do not "fix" this by adding the constraint.

    CHECK CONSTRAINTS ONLY ON SYSTEM-CONTROLLED ENUMS.
    `status` and `source_type` are set by the application, so they are
    constrained. `currency`, `category` and `payment_method` carry USER data and
    must be able to hold unsupported values -- that is the whole point of
    persisting an invalid row as NEEDS_REVIEW. A CHECK on `currency` would
    reject the JPY row and break the import, exactly like the UNIQUE above.
    """

    __tablename__ = "financial_record"

    id: Mapped[str] = mapped_column(String(UUID_LEN), primary_key=True, default=_uuid)
    batch_id: Mapped[str] = mapped_column(
        String(UUID_LEN), ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False
    )

    # --- Data dictionary fields ---
    reference: Mapped[str | None] = mapped_column(String(100))
    # Real Date columns: normalization already turned unreadable input into
    # None, and the original string is preserved in raw_payload.
    transaction_date: Mapped[date | None] = mapped_column(Date)
    value_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    gross_amount: Mapped[Decimal | None] = mapped_column(Money)
    fee_amount: Mapped[Decimal | None] = mapped_column(Money)
    tax_amount: Mapped[Decimal | None] = mapped_column(Money)
    net_amount: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str | None] = mapped_column(String(32))
    counterparty_name: Mapped[str | None] = mapped_column(String(300))
    counterparty_account: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(2))
    category: Mapped[str | None] = mapped_column(String(64))
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    payment_method: Mapped[str | None] = mapped_column(String(32))

    source_type: Mapped[str] = mapped_column(String(8), nullable=False)
    source_document_name: Mapped[str] = mapped_column(String(300), nullable=False)
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Money)
    field_confidence: Mapped[dict | None] = mapped_column(JSON)

    status: Mapped[str] = mapped_column(String(16), nullable=False)
    validation_errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Source of truth for revalidation: a correction merges into raw_payload and
    # replays the exact same pipeline as the initial import.
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    batch: Mapped[ImportBatch] = relationship(back_populates="records")

    __table_args__ = (
        CheckConstraint(
            "status IN ({})".format(", ".join(f"'{s.value}'" for s in RecordStatus)),
            name="ck_financial_record_status",
        ),
        CheckConstraint(
            "source_type IN ({})".format(", ".join(f"'{s.value}'" for s in SourceType)),
            name="ck_financial_record_source_type",
        ),
        Index("ix_financial_record_batch_status", "batch_id", "status"),
    )


class ExtractionJob(Base):
    """Tracks one PDF extraction. Populated by the AI connector.

    PROCESSING lives here, never on FinancialRecord.status: the data dictionary
    fixes that enum to three values and adding a technical state would break
    conformance with the common model.
    """

    __tablename__ = "extraction_job"

    id: Mapped[str] = mapped_column(String(UUID_LEN), primary_key=True, default=_uuid)
    batch_id: Mapped[str] = mapped_column(
        String(UUID_LEN), ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False
    )
    document_name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    record_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (Index("ix_extraction_job_batch", "batch_id"),)
