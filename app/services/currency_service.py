"""Currency and ExchangeRate service layer."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate
from app.models.user import User
from app.schemas.currency import CurrencyCreate, ExchangeRateCreate


# ✍️ SELECT all rows from currencies and return as list
async def get_currencies(db: AsyncSession) -> list[Currency]:
    pass


# ✍️ INSERT a new Currency row from payload, flush + refresh, return it
async def create_currency(db: AsyncSession, payload: CurrencyCreate) -> Currency:
    pass


# ✍️ SELECT exchange_rates with optional filters:
#    from_currency_id, to_currency_id, effective_date (each applied only if not None)
async def get_exchange_rates(
    db: AsyncSession,
    from_currency_id: uuid.UUID | None = None,
    to_currency_id: uuid.UUID | None = None,
    effective_date: date | None = None,
) -> list[ExchangeRate]:
    pass


# ✍️ INSERT a new ExchangeRate row (set created_by_id = created_by.id),
#    catch IntegrityError → raise HTTPException(409)
async def create_exchange_rate(
    db: AsyncSession,
    payload: ExchangeRateCreate,
    created_by: User,
) -> ExchangeRate:
    pass
