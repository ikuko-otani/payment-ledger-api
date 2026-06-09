"""Transaction CRUD endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import RedisDep
from app.core.deps import AdminUser, AuditorOrAdminUser
from app.db.session import get_db
from app.dependencies.idempotency import IdempotencyDep
from app.models.transaction import Transaction
from app.schemas.transaction import TransactionCreate, TransactionRead
from app.services.transaction_service import create_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[TransactionRead])
async def list_transactions(
    db: DbDep, _current_user: AuditorOrAdminUser
) -> list[Transaction]:
    result = await db.execute(
        # 💡 selectinload: Transaction を取得するとき entries も一緒にロードする。
        #    N+1 問題を避けるための eager loading。
        select(Transaction).options(selectinload(Transaction.entries))
    )
    return list(result.scalars().all())


@router.post("", response_model=TransactionRead, status_code=201)
async def post_transaction(
    payload: TransactionCreate,
    db: DbDep,
    redis: RedisDep,
    _: IdempotencyDep,
    current_user: AdminUser,
) -> Transaction:
    transaction = await create_transaction(db, payload, current_user.id)
    await db.commit()
    for entry in payload.entries:
        pattern = f"balance:{entry.account_id}:*"
        keys = await redis.keys(pattern)
        if keys:
            await redis.delete(*keys)
    return transaction
