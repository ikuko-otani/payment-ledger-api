"""Account model — represents a ledger account (e.g. Cash, Revenue)."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import func
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

    # ✍️ 自分で書く: 以下4フィールドの型ヒントとカラム名だけ見て、
    #    mapped_column() の引数を埋めてください（primary_key, nullable, server_default等）
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        # TODO: ここを実装（ヒント: nullable=False, unique=True, 最大100文字）
        nullable=False,
        unique=True,
    )
    account_type: Mapped[AccountType] = mapped_column(
        # TODO: ここを実装（ヒント: nullable=False。SQLAlchemy は Enum 型を自動認識）
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        # TODO: ここを実装（ヒント: server_default=func.now(), nullable=False）
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Account id={self.id} name={self.name!r} type={self.account_type}>"
