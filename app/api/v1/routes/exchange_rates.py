"""ExchangeRate endpoints."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AdminUser, CurrentUser
from app.db.session import get_db
from app.models.exchange_rate import ExchangeRate
from app.schemas.currency import ExchangeRateCreate, ExchangeRateRead
from app.services.currency_service import create_exchange_rate, get_exchange_rates

router = APIRouter(prefix="/exchange-rates", tags=["exchange-rates"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


# ✍️ return await get_exchange_rates(db, from_currency_id, to_currency_id, effective_date)
@router.get("", response_model=list[ExchangeRateRead])
async def list_exchange_rates(
    db: DbDep,
    _current_user: CurrentUser,
    from_currency_id: uuid.UUID | None = None,
    to_currency_id: uuid.UUID | None = None,
    effective_date: date | None = None,
) -> list[ExchangeRate]:
    pass


# ✍️ return await create_exchange_rate(db, payload, current_user)
@router.post("", response_model=ExchangeRateRead, status_code=201)
async def post_exchange_rate(
    payload: ExchangeRateCreate,
    db: DbDep,
    current_user: AdminUser,
) -> ExchangeRate:
    pass
