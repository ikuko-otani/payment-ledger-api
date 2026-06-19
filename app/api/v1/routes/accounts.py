"""Account CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.deps import AdminUser, AuditorOrAdminUser
from app.core.redis import RedisDep
from app.models.account import Account
from app.repositories.account_repository import (
    AccountRepository,
    get_account_repository,
)
from app.repositories.audit_repository import AuditRepository, get_audit_repository
from app.repositories.currency_repository import (
    CurrencyRepository,
    get_currency_repository,
)
from app.schemas.account import AccountCreate, AccountRead, BalanceResponse
from app.services import account_service

router = APIRouter(prefix="/accounts", tags=["accounts"])

AccountRepoDep = Annotated[AccountRepository, Depends(get_account_repository)]
AuditRepoDep = Annotated[AuditRepository, Depends(get_audit_repository)]
CurrencyRepoDep = Annotated[CurrencyRepository, Depends(get_currency_repository)]


@router.get("", response_model=list[AccountRead])
async def list_accounts(
    repo: AccountRepoDep,
    _current_user: AuditorOrAdminUser,
) -> list[Account]:
    return await repo.list_all()


@router.post("", response_model=AccountRead, status_code=201)
async def create_account(
    payload: AccountCreate,
    repo: AccountRepoDep,
    audit_repo: AuditRepoDep,
    currency_repo: CurrencyRepoDep,
    current_user: AdminUser,
) -> Account:
    return await account_service.create_account(
        repo, audit_repo, currency_repo, payload, current_user
    )


@router.get("/{id}/balance", response_model=BalanceResponse)
async def get_account_balance(
    id: uuid.UUID,
    as_of: datetime,
    repo: AccountRepoDep,
    redis: RedisDep,
    _current_user: AuditorOrAdminUser,
) -> BalanceResponse:
    cache_key = f"balance:{id}:{as_of.date()}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return BalanceResponse(balance=int(cached), as_of=as_of)
    balance = await repo.calculate_balance(id, as_of)
    await redis.set(cache_key, str(balance), ex=settings.balance_cache_ttl_seconds)
    return BalanceResponse(balance=balance, as_of=as_of)
