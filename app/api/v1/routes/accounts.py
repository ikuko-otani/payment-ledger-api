"""Account CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountRead, BalanceResponse

from decimal import Decimal

router = APIRouter(prefix="/accounts", tags=["accounts"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[AccountRead])
async def list_accounts(db: DbDep) -> list[Account]:
    # accounts テーブルを全件取得して返す
    result = await db.execute(select(Account))
    return list(result.scalars().all())


@router.post("", response_model=AccountRead, status_code=201)
async def create_account(payload: AccountCreate, db: DbDep) -> Account:
    account = Account(
        name=payload.name,
        account_type=payload.account_type,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


@router.get("/{id}/balance", response_model=BalanceResponse)
async def get_account_balance(
    id: uuid.UUID,
    as_of: datetime,
) -> BalanceResponse:
    # Return stub
    # TODO: replace with actual DB balance query (future goal)
    return BalanceResponse(balance=Decimal("0.00"), as_of=as_of)
