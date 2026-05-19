"""Entry model — a single debit or credit line within a Transaction.

One Transaction must have at least two Entry rows whose
total debit amount equals total credit amount (double-entry rule).
Amounts are stored as BIGINT (minor currency units e.g. cents for EUR/USD).
Row-level CHECK ensures amount is positive.
"""

from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.transaction import Transaction


class Direction(str, enum.Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class Entry(Base):
    """Journal entry line table (debit or credit side of a transaction)."""

    __tablename__ = "entries"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_entries_amount_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        # RESTRICT replaces CASCADE: immutable ledger — DB blocks raw DELETE on transactions
        nullable=False,
        index=True,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    direction: Mapped[Direction] = mapped_column(
        Enum(Direction, name="direction"),
        nullable=False,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,  # ISO 4217 code e.g. "EUR", "USD", "JPY"
    )
    transaction: Mapped[Transaction] = relationship(back_populates="entries")
    account: Mapped[Account] = relationship()

    def __repr__(self) -> str:
        return f"<Entry id={self.id} tx={self.transaction_id}>"
