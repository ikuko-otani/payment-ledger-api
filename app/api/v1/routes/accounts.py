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
from app.services.audit_service import log_action
from app.services.balance import calculate_balance

router = APIRouter(prefix="/accounts", tags=["accounts"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[AccountRead])
async def list_accounts(db: DbDep, _current_user: AuditorOrAdminUser) -> list[Account]:
    result = await db.execute(select(Account))
    return list(result.scalars().all())


@router.post("", response_model=AccountRead, status_code=201)
async def create_account(
    payload: AccountCreate,
    db: DbDep,
    current_user: AdminUser,
) -> Account:
    account = Account(
        code=payload.code,
        name=payload.name,
        account_type=payload.account_type,
        currency=payload.currency,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)

    after_value = {
        "id": str(account.id),
        "code": account.code,
        "name": account.name,
        "account_type": account.account_type.value,
        "currency": account.currency,
    }
    await log_action(
        db,
        user_id=current_user.id,
        entity_type="account",
        entity_id=account.id,
        action="create",
        before=None,
        after=after_value,
    )
    return account


@router.get("/{id}/balance", response_model=BalanceResponse)
async def get_account_balance(
    id: uuid.UUID,
    as_of: datetime,
    db: DbDep,
    redis: RedisDep,
    _current_user: AuditorOrAdminUser,
) -> BalanceResponse:
    cache_key = f"balance:{id}:{as_of.date()}"
    # 🔧 Fill-in: Cache-Aside (Lazy Loading) pattern
    # TODO: step 1 — try cache hit
    #   cached = await redis.get(cache_key)
    #   if cached is not None:
    #       return BalanceResponse(balance=int(cached), as_of=as_of)
    # TODO: step 2 — cache miss: query DB
    #   balance = await calculate_balance(db, id, as_of)
    # TODO: step 3 — store result in Redis with TTL
    #   await redis.set(cache_key, str(balance), ex=settings.balance_cache_ttl_seconds)
    # TODO: step 4 — return
    #   return BalanceResponse(balance=balance, as_of=as_of)
    balance = await calculate_balance(db, id, as_of)
    return BalanceResponse(balance=balance, as_of=as_of)
