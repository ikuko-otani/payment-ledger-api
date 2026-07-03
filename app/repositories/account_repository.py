"""Account repository — abstract interface and SQLAlchemy implementation."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import cast

from fastapi import Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.account import Account
from app.models.entry import Direction, Entry
from app.models.transaction import Transaction, TransactionStatus


class AccountRepository(ABC):
    @abstractmethod
    async def save(self, account: Account) -> Account: ...

    @abstractmethod
    async def find_by_id(self, account_id: uuid.UUID) -> Account | None: ...

    @abstractmethod
    async def list_all(self, limit: int = 20, offset: int = 0) -> list[Account]: ...

    @abstractmethod
    async def find_active_by_ids(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]: ...

    @abstractmethod
    async def calculate_balance(
        self, account_id: uuid.UUID, as_of: datetime
    ) -> int: ...


class SQLAlchemyAccountRepository(AccountRepository):
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def save(self, account: Account) -> Account:
        self._db.add(account)
        await self._db.flush()
        await self._db.refresh(account)
        return account

    async def find_by_id(self, account_id: uuid.UUID) -> Account | None:
        return await self._db.get(Account, account_id)

    async def list_all(self, limit: int = 20, offset: int = 0) -> list[Account]:
        result = await self._db.execute(
            select(Account).order_by(Account.code).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def find_active_by_ids(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        result = await self._db.execute(
            select(Account.id, Account.currency).where(
                Account.id.in_(ids),
                Account.is_active.is_(True),
            )
        )
        return {account_id: currency for account_id, currency in result.all()}

    async def calculate_balance(self, account_id: uuid.UUID, as_of: datetime) -> int:
        result = await self._db.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (Entry.direction == Direction.DEBIT, Entry.amount), else_=0
                        )
                    ),
                    0,
                )
                - func.coalesce(
                    func.sum(
                        case(
                            (Entry.direction == Direction.CREDIT, Entry.amount), else_=0
                        )
                    ),
                    0,
                )
            )
            .join(Transaction, Entry.transaction_id == Transaction.id)
            .where(
                Entry.account_id == account_id,
                Transaction.transaction_date <= as_of.date(),
                Transaction.status.in_(
                    [TransactionStatus.POSTED, TransactionStatus.VOIDED]
                ),
            )
        )
        return cast(int, result.scalar_one())


def get_account_repository(
    db: AsyncSession = Depends(get_db),
) -> AccountRepository:
    return SQLAlchemyAccountRepository(db)
