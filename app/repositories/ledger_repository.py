"""Ledger repository — abstract interface and SQLAlchemy implementation."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.db.session import get_db
from app.models.entry import Entry
from app.models.transaction import Transaction


class LedgerRepository(ABC):
    @abstractmethod
    async def list_entries(
        self,
        from_date: date | None,
        to_date: date | None,
        account_id: uuid.UUID | None,
        currency_code: str | None,
        limit: int,
        offset: int,
    ) -> list[Entry]: ...


class SQLAlchemyLedgerRepository(LedgerRepository):
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_entries(
        self,
        from_date: date | None,
        to_date: date | None,
        account_id: uuid.UUID | None,
        currency_code: str | None,
        limit: int,
        offset: int,
    ) -> list[Entry]:
        filters = []
        if from_date is not None:
            filters.append(Transaction.transaction_date >= from_date)
        if to_date is not None:
            filters.append(Transaction.transaction_date <= to_date)
        if account_id is not None:
            filters.append(Entry.account_id == account_id)
        if currency_code is not None:
            filters.append(Entry.currency == currency_code)

        stmt = (
            select(Entry)
            .join(Entry.transaction)
            .options(contains_eager(Entry.transaction))
            .where(*filters)
            .order_by(
                Transaction.transaction_date.desc(),
                Transaction.posted_at.desc(),
                Entry.id,
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().unique().all())


def get_ledger_repository(
    db: AsyncSession = Depends(get_db),
) -> LedgerRepository:
    return SQLAlchemyLedgerRepository(db)
