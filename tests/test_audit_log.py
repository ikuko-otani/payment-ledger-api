"""Integration tests for audit log write logic (S4-5)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType
from app.models.audit_log import AuditLog


async def _seed_account(
    db: AsyncSession,
    name: str,
    account_type: AccountType,
    code: str,
    currency: str = "EUR",
) -> str:
    """Insert an account and return its id as str."""
    # TODO: implement (hint: same pattern as test_transactions_http._seed_account)
    pass


@pytest.mark.asyncio
async def test_create_transaction_writes_audit_log(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    # TODO: implement
    # hint:
    #   1. seed two accounts via db_session (_seed_account)
    #   2. POST /api/v1/transactions with a balanced payload
    #   3. assert status_code == 201
    #   4. select all AuditLog rows via db_session
    #   5. assert len(logs) == 1
    #   6. assert logs[0].entity_type == "transaction"
    #   7. assert logs[0].action == "create"
    #   8. assert logs[0].before_value is None
    #   9. assert "id" in logs[0].after_value
    pass


@pytest.mark.asyncio
async def test_create_account_writes_audit_log(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    # TODO: implement
    # hint:
    #   1. POST /api/v1/accounts with a valid payload
    #   2. assert status_code == 201
    #   3. select all AuditLog rows via db_session
    #   4. assert len(logs) == 1
    #   5. assert logs[0].entity_type == "account"
    #   6. assert logs[0].action == "create"
    pass


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_transaction(
    db_session: AsyncSession,
) -> None:
    # TODO: implement
    # hint:
    #   1. seed two Account rows directly via db_session
    #   2. call create_transaction(db_session, payload, user_id=uuid.uuid4())
    #      where user_id is NOT in the users table → FK violation at flush
    #   3. use pytest.raises(Exception) to capture the IntegrityError
    #   4. await db_session.rollback()
    #   5. select Transaction rows and assert the list is empty
    pass
