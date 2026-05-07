"""Account CRUD endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountRead

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
