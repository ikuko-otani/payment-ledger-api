"""Currency and ExchangeRate service layer."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate
from app.schemas.currency import CurrencyCreate, ExchangeRateCreate
from app.schemas.token import TokenUser
from app.services.audit_service import log_action


# SELECT all rows from currencies and return as list
async def get_currencies(db: AsyncSession) -> list[Currency]:
    result = await db.execute(select(Currency).order_by(Currency.code))
    return list(result.scalars().all())


async def create_currency(
    db: AsyncSession,
    payload: CurrencyCreate,
    current_user: TokenUser,
) -> Currency:
    currency = Currency(
        code=payload.code,
        name=payload.name,
        decimal_places=payload.decimal_places,
    )
    db.add(currency)
    await db.flush()
    await db.refresh(currency)

    after_value: dict[str, Any] = {
        "id": str(currency.id),
        "code": currency.code,
        "name": currency.name,
        "decimal_places": currency.decimal_places,
    }
    await log_action(
        db,
        user_id=current_user.id,
        entity_type="currency",
        entity_id=currency.id,
        action="create",
        before=None,
        after=after_value,
    )
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
    stmt = stmt.order_by(ExchangeRate.effective_date.desc(), ExchangeRate.id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_exchange_rate(
    db: AsyncSession,
    payload: ExchangeRateCreate,
    created_by: TokenUser,
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

    after_value: dict[str, Any] = {
        "id": str(exchange_rate.id),
        "from_currency_id": str(exchange_rate.from_currency_id),
        "to_currency_id": str(exchange_rate.to_currency_id),
        "rate": str(exchange_rate.rate),
        "effective_date": exchange_rate.effective_date.isoformat(),
    }
    await log_action(
        db,
        user_id=created_by.id,
        entity_type="exchange_rate",
        entity_id=exchange_rate.id,
        action="create",
        before=None,
        after=after_value,
    )
    return exchange_rate
