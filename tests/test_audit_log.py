"""Integration tests for audit log write logic (S4-5)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType
from app.models.audit_log import AuditLog
from app.models.entry import Direction
from app.models.transaction import Transaction
from app.schemas.transaction import EntryCreate, TransactionCreate
from app.services.transaction_service import create_transaction
from app.repositories.account_repository import SQLAlchemyAccountRepository
from app.repositories.audit_repository import SQLAlchemyAuditRepository
from app.repositories.currency_repository import SQLAlchemyCurrencyRepository
from app.repositories.transaction_repository import SQLAlchemyTransactionRepository


async def _seed_account(
    db: AsyncSession,
    name: str,
    account_type: AccountType,
    code: str,
    currency: str = "EUR",
) -> str:
    """Insert an account and return its id as str."""
    account = Account(
        name=name, account_type=account_type, code=code, currency=currency
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@pytest.mark.asyncio
async def test_create_transaction_writes_audit_log(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    debit = await _seed_account(db_session, "Cash-Audit", AccountType.ASSET, "1100")
    credit = await _seed_account(
        db_session, "Revenue-Audit", AccountType.REVENUE, "4000"
    )

    payload = {
        "description": "Audit test",
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": str(debit.id),
                "direction": "debit",
                "amount": 1000,
                "currency": "EUR",
            },
            {
                "account_id": str(credit.id),
                "direction": "credit",
                "amount": 1000,
                "currency": "EUR",
            },
        ],
    }
    response = await async_client.post("/api/v1/transactions", json=payload)
    assert response.status_code == 201

    result = await db_session.execute(select(AuditLog))
    logs = result.scalars().all()
    assert len(logs) == 1
    assert logs[0].entity_type == "transaction"
    assert logs[0].action == "create"
    assert logs[0].before_value is None
    assert "id" in logs[0].after_value


@pytest.mark.asyncio
async def test_create_account_writes_audit_log(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    payload = {
        "code": "1200",
        "name": "Bank Account",
        "account_type": "asset",
        "currency": "USD",
    }
    response = await async_client.post("/api/v1/accounts", json=payload)
    assert response.status_code == 201

    result = await db_session.execute(select(AuditLog))
    logs = result.scalars().all()
    assert len(logs) == 1
    assert logs[0].entity_type == "account"
    assert logs[0].action == "create"
    assert logs[0].after_value["code"] == "1200"


@pytest.mark.asyncio
async def test_create_currency_writes_audit_log(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    response = await async_client.post(
        "/api/v1/currencies",
        json={"code": "USD", "name": "US Dollar", "decimal_places": 2},
    )
    assert response.status_code == 201

    result = await db_session.execute(select(AuditLog))
    logs = result.scalars().all()
    assert len(logs) == 1
    assert logs[0].entity_type == "currency"
    assert logs[0].action == "create"
    assert logs[0].before_value is None
    assert logs[0].after_value["code"] == "USD"


@pytest.mark.asyncio
async def test_create_exchange_rate_writes_audit_log(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    r_usd = await async_client.post(
        "/api/v1/currencies",
        json={"code": "USD", "name": "US Dollar", "decimal_places": 2},
    )
    r_eur = await async_client.post(
        "/api/v1/currencies",
        json={"code": "EUR", "name": "Euro", "decimal_places": 2},
    )
    usd_id = r_usd.json()["id"]
    eur_id = r_eur.json()["id"]

    response = await async_client.post(
        "/api/v1/exchange-rates",
        json={
            "from_currency_id": usd_id,
            "to_currency_id": eur_id,
            "rate": "1.08000000",
            "effective_date": "2024-01-01",
        },
    )
    assert response.status_code == 201

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_type == "exchange_rate")
    )
    logs = result.scalars().all()
    assert len(logs) == 1
    assert logs[0].action == "create"
    assert logs[0].before_value is None
    assert logs[0].after_value["from_currency_id"] == usd_id


@pytest.mark.asyncio
async def test_register_user_writes_audit_log(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    response = await async_client.post(
        "/api/v1/users",
        json={"email": "audit-user@example.com", "password": "secret123"},
    )
    assert response.status_code == 201
    new_user_id = response.json()["id"]

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_type == "user")
    )
    logs = result.scalars().all()
    assert len(logs) == 1
    assert logs[0].action == "create"
    assert logs[0].before_value is None
    assert logs[0].after_value["email"] == "audit-user@example.com"
    # Self-registration: the audit row references the new user itself.
    assert str(logs[0].user_id) == new_user_id
    assert str(logs[0].entity_id) == new_user_id


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_transaction(
    db_session: AsyncSession,
) -> None:
    debit = await _seed_account(db_session, "Cash-Atomic", AccountType.ASSET, "1101")
    credit = await _seed_account(
        db_session, "Revenue-Atomic", AccountType.REVENUE, "4001"
    )

    payload = TransactionCreate(
        description="Atomicity test",
        transaction_date="2024-06-01",
        entries=[
            EntryCreate(
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=500,
                currency="EUR",
            ),
            EntryCreate(
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=500,
                currency="EUR",
            ),
        ],
    )

    account_repo = SQLAlchemyAccountRepository(db_session)
    currency_repo = SQLAlchemyCurrencyRepository(db_session)
    tx_repo = SQLAlchemyTransactionRepository(db_session)
    audit_repo = SQLAlchemyAuditRepository(db_session)

    nonexistent_user_id = uuid.uuid4()
    with pytest.raises((IntegrityError, Exception)):
        await create_transaction(
            account_repo,
            currency_repo,
            tx_repo,
            audit_repo,
            payload,
            user_id=nonexistent_user_id,
        )
        await db_session.flush()

    await db_session.rollback()

    tx_result = await db_session.execute(select(Transaction))
    assert tx_result.scalars().all() == []
