"""Transaction CRUD endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.transaction import Transaction
from app.schemas.transaction import TransactionCreate, TransactionRead
from app.services.transaction_service import create_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[TransactionRead])
async def list_transactions(db: DbDep) -> list[Transaction]:
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
) -> Transaction:
    # 🔧 穴埋め: create_transaction サービスを呼び出して返す
    # TODO: ここを実装（ヒント: await create_transaction(db, payload)）
    return await create_transaction(db, payload)
