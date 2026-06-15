"""Currency and ExchangeRate service layer."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate
from app.models.user import User
from app.schemas.currency import CurrencyCreate, ExchangeRateCreate


# SELECT all rows from currencies and return as list
async def get_currencies(db: AsyncSession) -> list[Currency]:
    result = await db.execute(select(Currency))
    return list(result.scalars().all())


async def create_currency(db: AsyncSession, payload: CurrencyCreate) -> Currency:
    currency = Currency(
        code=payload.code,
        name=payload.name,
        decimal_places=payload.decimal_places,
    )
    db.add(currency)
    await db.flush()
    await db.refresh(currency)
    return currency


async def get_exchange_rates(
    db: AsyncSession,
    from_currency_id: uuid.UUID | None = None,
    to_currency_id: uuid.UUID | None = None,
    effective_date: date | None = None,
) -> list[ExchangeRate]:
    stmt = select(ExchangeRate)
    if from_currency_id is not None:
        stmt = stmt.where(ExchangeRate.from_currency_id == from_currency_id)
    if to_currency_id is not None:
        stmt = stmt.where(ExchangeRate.to_currency_id == to_currency_id)
    if effective_date is not None:
        stmt = stmt.where(ExchangeRate.effective_date == effective_date)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_exchange_rate(
    db: AsyncSession,
    payload: ExchangeRateCreate,
    created_by: User,
) -> ExchangeRate:
    exchange_rate = ExchangeRate(
        from_currency_id=payload.from_currency_id,
        to_currency_id=payload.to_currency_id,
        rate=payload.rate,
        effective_date=payload.effective_date,
        created_by_id=created_by.id,
    )
    db.add(exchange_rate)
    try:
        await db.flush()
    except IntegrityError as e:
        raise ConflictError(
            detail="Exchange rate for this currency pair and date already exists"
        ) from e
    await db.refresh(exchange_rate)
    return exchange_rate
