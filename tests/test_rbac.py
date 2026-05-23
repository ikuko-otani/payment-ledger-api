"""RBAC integration tests: admin / auditor / inactive-user access control (S3-5)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACCOUNT_PAYLOAD = {
    "code": "9000",
    "name": "RBAC-Test-Cash",
    "account_type": "asset",
    "currency": "JPY",
}


async def _seed_account(
    db_session: AsyncSession,
    name: str,
    account_type: AccountType,
    code: str,
) -> str:
    """Insert an account directly and return its id as str."""
    account = Account(name=name, account_type=account_type, code=code, currency="JPY")
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return str(account.id)


# ---------------------------------------------------------------------------
# Account endpoint RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auditor_cannot_create_account(auditor_client: AsyncClient) -> None:
    """POST /accounts as auditor must return 403."""
    response = await auditor_client.post("/api/v1/accounts", json=_ACCOUNT_PAYLOAD)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_account(async_client: AsyncClient) -> None:
    """POST /accounts as admin must return 201."""
    response = await async_client.post("/api/v1/accounts", json=_ACCOUNT_PAYLOAD)
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_auditor_can_list_accounts(auditor_client: AsyncClient) -> None:
    """GET /accounts as auditor must return 200."""
    response = await auditor_client.get("/api/v1/accounts")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_can_list_accounts(async_client: AsyncClient) -> None:
    """GET /accounts as admin must return 200."""
    response = await async_client.get("/api/v1/accounts")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_auditor_can_get_account_balance(
    async_client: AsyncClient,
    auditor_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /accounts/{id}/balance as auditor must return 200."""
    account_id = await _seed_account(db_session, "Balance-Auditor", AccountType.ASSET, "9001")
    response = await auditor_client.get(
        f"/api/v1/accounts/{account_id}/balance",
        params={"as_of": "2024-01-01T00:00:00"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_can_get_account_balance(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /accounts/{id}/balance as admin must return 200."""
    account_id = await _seed_account(db_session, "Balance-Auditor", AccountType.ASSET, "9001")
    response = await async_client.get(
        f"/api/v1/accounts/{account_id}/balance",
        params={"as_of": "2024-01-01T00:00:00"},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Transaction endpoint RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auditor_cannot_post_transaction(auditor_client: AsyncClient) -> None:
    """POST /transactions as auditor must return 403.

    ⚠️ Note: {} body is sent intentionally. Role check fires via Depends(require_admin)
    before (or alongside) body validation. If 422 is returned instead of 403,
    provide a valid body here and recheck the dependency resolution order.
    """
    response = await auditor_client.post(
        "/api/v1/transactions",
        json={},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_post_transaction(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /transactions as admin must return 201."""
    debit_id = await _seed_account(db_session, "Cash-RBAC", AccountType.ASSET, "9003")
    credit_id = await _seed_account(db_session, "Revenue-RBAC", AccountType.REVENUE, "9004")
    payload = {
        "description": "RBAC test transaction",
        "transaction_date": "2024-01-01",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 1000,
                "currency": "JPY",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 1000,
                "currency": "JPY",
            },
        ],
    }
    response = await async_client.post("/api/v1/transactions", json=payload)
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_auditor_can_list_transactions(auditor_client: AsyncClient) -> None:
    """GET /transactions as auditor must return 200."""
    response = await auditor_client.get("/api/v1/transactions")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_can_list_transactions(async_client: AsyncClient) -> None:
    """GET /transactions as admin must return 200."""
    response = await async_client.get("/api/v1/transactions")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# is_active=False / unauthenticated guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inactive_user_returns_401(
    unauthed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A token belonging to a deactivated user must return 401.

    Flow: register → login (get token) → deactivate via db_session → call endpoint.
    """
    await unauthed_client.post(
        "/api/v1/users", json={"email": "inactive@example.com", "password": "pass1234"}
    )
    resp = await unauthed_client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@example.com", "password": "pass1234"},
    )
    token = resp.json()["access_token"]
    await db_session.execute(
        update(User).where(User.email == "inactive@example.com").values(is_active=False)
    )
    await db_session.commit()
    resp = await unauthed_client.get(
        "/api/v1/accounts", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401(
    unauthed_client: AsyncClient,
) -> None:
    """Request with no Authorization header must return 401."""
    response = await unauthed_client.get("/api/v1/accounts")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# S3-6: authenticated_client factory — DONE condition tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticated_admin_can_post_transaction(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """POST /transactions with a real JWT-authenticated admin must return 201."""
    # TODO: seed debit + credit accounts via _seed_account,
    #       admin_c = await authenticated_client("admin"),
    #       build valid transaction payload,
    #       POST to /api/v1/transactions, assert response.status_code == 201
    ...


@pytest.mark.asyncio
async def test_authenticated_auditor_cannot_post_transaction(
    authenticated_client,
) -> None:
    """POST /transactions with a real JWT-authenticated auditor must return 403."""
    # TODO: auditor_c = await authenticated_client("auditor"),
    #       POST {} to /api/v1/transactions, assert response.status_code == 403
    ...
