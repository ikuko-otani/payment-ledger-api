"""Transaction repository — abstract interface and SQLAlchemy implementation."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.entry import Entry
from app.models.transaction import Transaction


class TransactionRepository(ABC):
    @abstractmethod
    async def save(
        self, transaction: Transaction, entries: list[Entry]
    ) -> Transaction: ...

    @abstractmethod
    async def list_all(self, limit: int, offset: int) -> list[Transaction]: ...

    @abstractmethod
    async def find_by_id_with_entries(
        self, transaction_id: uuid.UUID
    ) -> Transaction | None: ...


class SQLAlchemyTransactionRepository(TransactionRepository):
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def save(self, transaction: Transaction, entries: list[Entry]) -> Transaction:
        self._db.add(transaction)
        await self._db.flush()

        for entry in entries:
            entry.transaction_id = transaction.id
        self._db.add_all(entries)
        await self._db.flush()

        result = await self._db.execute(
            select(Transaction)
            .where(Transaction.id == transaction.id)
            .options(selectinload(Transaction.entries))
        )
        return result.scalar_one()

    async def list_all(self, limit: int, offset: int) -> list[Transaction]:
        result = await self._db.execute(
            select(Transaction)
            .options(selectinload(Transaction.entries))
            .order_by(
                Transaction.transaction_date.desc(),
                Transaction.posted_at.desc(),
                Transaction.id,
            )
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_by_id_with_entries(
        self, transaction_id: uuid.UUID
    ) -> Transaction | None:
        result = await self._db.execute(
            select(Transaction)
            .where(Transaction.id == transaction_id)
            .options(selectinload(Transaction.entries))
        )
        return result.scalar_one_or_none()


def get_transaction_repository(
    db: AsyncSession = Depends(get_db),
) -> TransactionRepository:
    return SQLAlchemyTransactionRepository(db)
