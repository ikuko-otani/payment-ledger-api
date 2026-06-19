"""Transaction CRUD endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AdminUser, AuditorOrAdminUser
from app.core.redis import RedisDep
from app.db.session import get_db
from app.dependencies.idempotency import IdempotencyDep
from app.models.transaction import Transaction
from app.repositories.account_repository import (
    AccountRepository,
    get_account_repository,
)
from app.repositories.audit_repository import AuditRepository, get_audit_repository
from app.repositories.currency_repository import (
    CurrencyRepository,
    get_currency_repository,
)
from app.repositories.transaction_repository import (
    TransactionRepository,
    get_transaction_repository,
)
from app.schemas.transaction import TransactionCreate, TransactionRead
from app.services.transaction_service import create_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
AccountRepoDep = Annotated[AccountRepository, Depends(get_account_repository)]
CurrencyRepoDep = Annotated[CurrencyRepository, Depends(get_currency_repository)]
TransactionRepoDep = Annotated[
    TransactionRepository, Depends(get_transaction_repository)
]
AuditRepoDep = Annotated[AuditRepository, Depends(get_audit_repository)]


@router.get("", response_model=list[TransactionRead])
async def list_transactions(
    tx_repo: TransactionRepoDep,
    _current_user: AuditorOrAdminUser,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Transaction]:
    return await tx_repo.list_all(limit, offset)


@router.post("", response_model=TransactionRead, status_code=201)
async def post_transaction(
    payload: TransactionCreate,
    db: DbDep,
    account_repo: AccountRepoDep,
    currency_repo: CurrencyRepoDep,
    tx_repo: TransactionRepoDep,
    audit_repo: AuditRepoDep,
    redis: RedisDep,
    idempotency: IdempotencyDep,
    current_user: AdminUser,
) -> Transaction | JSONResponse:
    if idempotency.replay is not None:
        return JSONResponse(content=idempotency.replay, status_code=200)

    transaction = await create_transaction(
        account_repo, currency_repo, tx_repo, audit_repo, payload, current_user.id
    )
    await db.commit()
    for entry in payload.entries:
        pattern = f"balance:{entry.account_id}:*"
        keys = await redis.keys(pattern)
        if keys:
            await redis.delete(*keys)

    response_data = TransactionRead.model_validate(transaction).model_dump(mode="json")
    await idempotency.cache(response_data)

    return transaction
