"""Ledger repository — abstract interface and SQLAlchemy implementation."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.entry import Entry


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
        # TODO: implement
        raise NotImplementedError


def get_ledger_repository(
    db: AsyncSession = Depends(get_db),
) -> LedgerRepository:
    return SQLAlchemyLedgerRepository(db)
