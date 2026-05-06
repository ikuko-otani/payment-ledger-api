"""Account model — represents a ledger account (e.g. Cash, Revenue)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import func, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AccountType(str, Enum):
    """Double-entry bookkeeping account types.

    Assets & Expenses increase on debit.
    Liabilities, Equity & Revenue increase on credit.
    """

    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class Account(Base):
    """Ledger account table."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )
    account_type: Mapped[AccountType] = mapped_column(
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Account id={self.id} name={self.name!r} type={self.account_type}>"
