"""Currency repository — abstract interface and SQLAlchemy implementation."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.db.session import get_db
from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate


class CurrencyRepository(ABC):
    @abstractmethod
    async def list_all(self, limit: int = 20, offset: int = 0) -> list[Currency]: ...

    @abstractmethod
    async def save(self, currency: Currency) -> Currency: ...

    @abstractmethod
    async def find_by_code(self, code: str) -> Currency | None: ...

    @abstractmethod
    async def list_exchange_rates(
        self,
        from_currency_id: uuid.UUID | None,
        to_currency_id: uuid.UUID | None,
        effective_date: date | None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ExchangeRate]: ...

    @abstractmethod
    async def save_exchange_rate(self, rate: ExchangeRate) -> ExchangeRate: ...

    @abstractmethod
    async def find_exchange_rate(
        self,
        from_currency_id: uuid.UUID,
        to_currency_id: uuid.UUID,
        effective_date: date,
    ) -> ExchangeRate | None: ...


class SQLAlchemyCurrencyRepository(CurrencyRepository):
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_all(self, limit: int = 20, offset: int = 0) -> list[Currency]:
        result = await self._db.execute(
            select(Currency).order_by(Currency.code).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def save(self, currency: Currency) -> Currency:
        self._db.add(currency)
        await self._db.flush()
        await self._db.refresh(currency)
        return currency

    async def find_by_code(self, code: str) -> Currency | None:
        result = await self._db.execute(select(Currency).where(Currency.code == code))
        return result.scalar_one_or_none()

    async def list_exchange_rates(
        self,
        from_currency_id: uuid.UUID | None,
        to_currency_id: uuid.UUID | None,
        effective_date: date | None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ExchangeRate]:
        stmt = select(ExchangeRate)
        if from_currency_id is not None:
            stmt = stmt.where(ExchangeRate.from_currency_id == from_currency_id)
        if to_currency_id is not None:
            stmt = stmt.where(ExchangeRate.to_currency_id == to_currency_id)
        if effective_date is not None:
            stmt = stmt.where(ExchangeRate.effective_date == effective_date)
        stmt = stmt.order_by(ExchangeRate.effective_date.desc(), ExchangeRate.id)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def save_exchange_rate(self, rate: ExchangeRate) -> ExchangeRate:
        self._db.add(rate)
        try:
            await self._db.flush()
        except IntegrityError as e:
            raise ConflictError(
                detail="Exchange rate for this currency pair and date already exists"
            ) from e
        await self._db.refresh(rate)
        return rate

    async def find_exchange_rate(
        self,
        from_currency_id: uuid.UUID,
        to_currency_id: uuid.UUID,
        effective_date: date,
    ) -> ExchangeRate | None:
        result = await self._db.execute(
            select(ExchangeRate).where(
                ExchangeRate.from_currency_id == from_currency_id,
                ExchangeRate.to_currency_id == to_currency_id,
                ExchangeRate.effective_date == effective_date,
            )
        )
        return result.scalar_one_or_none()


def get_currency_repository(
    db: AsyncSession = Depends(get_db),
) -> CurrencyRepository:
    return SQLAlchemyCurrencyRepository(db)
