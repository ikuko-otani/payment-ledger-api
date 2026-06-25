"""Transaction model — a double-entry transaction header.

One Transaction links to two or more Entry rows (debit + credit).
Balance rule (debit_sum == credit_sum) is enforced at the service layer
and re-checked by a deferred constraint trigger at COMMIT.
Transactions are immutable once POSTED; corrections use reversal transactions.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.entry import Entry


# purpose: lifecycle state
#   POSTED means committed to ledger
#   VOIDED means cancelled (a new reversal transaction is created, not deleted)
class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    POSTED = "posted"
    VOIDED = "voided"


class Transaction(Base):
    """Transaction header table."""

    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    description: Mapped[str] = mapped_column(nullable=False)
    transaction_date: Mapped[date] = mapped_column(nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus, name="transactionstatus"),
        nullable=False,
        default=TransactionStatus.POSTED,
    )
    # set to datetime.utcnow() in the service layer when status → POSTED
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # column name "metadata" in DB
    # metadata_ in Python to avoid conflict with SQLAlchemy's internal MetaData object
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True, default=None
    )

    entries: Mapped[list[Entry]] = relationship(
        back_populates="transaction",
        cascade="save-update, merge",
        # not "delete-orphan": immutable ledger never deletes posted entries
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} date={self.transaction_date}>"
