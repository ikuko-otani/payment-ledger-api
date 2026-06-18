"""ExchangeRate endpoints."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import AdminUser, CurrentUser
from app.models.exchange_rate import ExchangeRate
from app.repositories.audit_repository import AuditRepository, get_audit_repository
from app.repositories.currency_repository import (
    CurrencyRepository,
    get_currency_repository,
)
from app.schemas.currency import ExchangeRateCreate, ExchangeRateRead
from app.services.currency_service import create_exchange_rate, get_exchange_rates

router = APIRouter(prefix="/exchange-rates", tags=["exchange-rates"])

CurrencyRepoDep = Annotated[CurrencyRepository, Depends(get_currency_repository)]
AuditRepoDep = Annotated[AuditRepository, Depends(get_audit_repository)]


@router.get("", response_model=list[ExchangeRateRead])
async def list_exchange_rates(
    repo: CurrencyRepoDep,
    _current_user: CurrentUser,
    from_currency_id: uuid.UUID | None = None,
    to_currency_id: uuid.UUID | None = None,
    effective_date: date | None = None,
) -> list[ExchangeRate]:
    return await get_exchange_rates(
        repo, from_currency_id, to_currency_id, effective_date
    )


@router.post("", response_model=ExchangeRateRead, status_code=201)
async def post_exchange_rate(
    payload: ExchangeRateCreate,
    repo: CurrencyRepoDep,
    audit_repo: AuditRepoDep,
    current_user: AdminUser,
) -> ExchangeRate:
    return await create_exchange_rate(repo, audit_repo, payload, current_user)
