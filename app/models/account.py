"""Account model — represents a ledger account (e.g. Cash, Revenue)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, String, func, text
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
    # ✍️ code: Mapped[str]
    #    hint: mapped_column(String, unique=True, nullable=False)
    #    purpose: Chart of Accounts code e.g. "1100", "2000"
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )
    account_type: Mapped[AccountType] = mapped_column(
        nullable=False,
    )
    # ✍️ currency: Mapped[str]
    #    hint: mapped_column(String(3), nullable=False)
    #    purpose: ISO 4217 code e.g. "EUR", "USD", "JPY"
    # ✍️ is_active: Mapped[bool]
    #    hint: mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    # ✍️ updated_at: Mapped[datetime]
    #    hint: mapped_column(server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<Account id={self.id} name={self.name!r} type={self.account_type}>"
