"""Account CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import RedisDep
from app.core.config import settings
from app.core.deps import AdminUser, AuditorOrAdminUser
from app.db.session import get_db
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountRead, BalanceResponse
from app.services import account_service
from app.services.balance import calculate_balance

router = APIRouter(prefix="/accounts", tags=["accounts"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[AccountRead])
async def list_accounts(db: DbDep, _current_user: AuditorOrAdminUser) -> list[Account]:
    result = await db.execute(select(Account).order_by(Account.code))
    return list(result.scalars().all())


@router.post("", response_model=AccountRead, status_code=201)
async def create_account(
    payload: AccountCreate,
    db: DbDep,
    current_user: AdminUser,
) -> Account:
    return await account_service.create_account(db, payload, current_user)


@router.get("/{id}/balance", response_model=BalanceResponse)
async def get_account_balance(
    id: uuid.UUID,
    as_of: datetime,
    db: DbDep,
    redis: RedisDep,
    _current_user: AuditorOrAdminUser,
) -> BalanceResponse:
    cache_key = f"balance:{id}:{as_of.date()}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return BalanceResponse(balance=int(cached), as_of=as_of)
    balance = await calculate_balance(db, id, as_of)
    await redis.set(cache_key, str(balance), ex=settings.balance_cache_ttl_seconds)
    return BalanceResponse(balance=balance, as_of=as_of)
