"""Transaction model — a double-entry transaction header.

One Transaction links to two or more Entry rows (debit + credit).
Balance rule (debit_sum == credit_sum) is enforced at the application layer.
Transactions are immutable once POSTED; corrections use reversal transactions.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.entry import Entry


# ✍️ class TransactionStatus(str, enum.Enum):
#    hint: 3 members — PENDING = "pending", POSTED = "posted", VOIDED = "voided"
#    purpose: lifecycle state; POSTED means committed to ledger; VOIDED means
#             cancelled (a new reversal transaction is created, not deleted)


class Transaction(Base):
    """Transaction header table."""

    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    description: Mapped[str] = mapped_column(nullable=False)
    transaction_date: Mapped[date] = mapped_column(nullable=False)
    # amount column removed: derived from SUM(entries.amount WHERE direction=DEBIT)
    # storing it here would create a denormalisation inconsistency risk — see ADR-004
    # ✍️ status: Mapped[TransactionStatus]
    #    hint: mapped_column(Enum(TransactionStatus), nullable=False,
    #                        default=TransactionStatus.POSTED)
    #    for MVP, transactions are POSTED immediately on creation
    # ✍️ posted_at: Mapped[datetime | None]
    #    hint: mapped_column(nullable=True, default=None)
    #    set to datetime.utcnow() in the service layer when status → POSTED
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    # ✍️ metadata_: Mapped[dict | None]
    #    hint: mapped_column("metadata", JSON, nullable=True, default=None)
    #    column name "metadata" in DB; metadata_ in Python to avoid conflict
    #    with SQLAlchemy's internal MetaData object

    entries: Mapped[list["Entry"]] = relationship(
        back_populates="transaction",
        cascade="save-update, merge",
        # not "delete-orphan": immutable ledger never deletes posted entries
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} "
            f"date={self.transaction_date}>"
        )
