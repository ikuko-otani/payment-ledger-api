"""Entry model — a single debit or credit line within a Transaction.

One Transaction must have at least two Entry rows whose
total debit amount equals total credit amount (double-entry rule).
Row-level CHECK ensures amount is positive.
"""
from __future__ import annotations

import enum
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.transaction import Transaction


class EntryType(str, enum.Enum):
    """Whether this entry line is a debit or a credit."""

    DEBIT = "debit"
    CREDIT = "credit"


class Entry(Base):
    """Journal entry line table (debit or credit side of a transaction)."""

    __tablename__ = "entries"
    __table_args__ = (
        # 💡 Row-level guard: amount must be positive.
        CheckConstraint("amount > 0", name="ck_entries_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    entry_type: Mapped[EntryType] = mapped_column(
        Enum(EntryType),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=4),
        nullable=False,
    )

    # Relationships
    transaction: Mapped[Transaction] = relationship(
        back_populates="entries",
    )
    account: Mapped[Account] = relationship()

    def __repr__(self) -> str:
        return (
            f"<Entry id={self.id} type={self.entry_type} "
            f"amount={self.amount} tx={self.transaction_id}>"
        )
