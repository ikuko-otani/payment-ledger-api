"""RBAC integration tests: admin / auditor / inactive-user access control."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType

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
    account_id = await _seed_account(
        db_session, "Balance-Auditor", AccountType.ASSET, "9001"
    )
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
    account_id = await _seed_account(
        db_session, "Balance-Auditor", AccountType.ASSET, "9001"
    )
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
    credit_id = await _seed_account(
        db_session, "Revenue-RBAC", AccountType.REVENUE, "9004"
    )
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
async def test_inactive_user_jwt_claim_returns_401(
    unauthed_client: AsyncClient,
) -> None:
    """A JWT with is_active=False in the claim must return 401.

    After TD-015: get_current_user checks the is_active claim from the JWT
    payload rather than re-querying the database. Deactivating a user in the
    DB does not immediately revoke existing tokens; the revocation window is
    bounded by ACCESS_TOKEN_EXPIRE_MINUTES (see docs/adr/006-jwt-claims-no-db-per-request.md).
    This test verifies that a token explicitly carrying is_active=False is rejected.
    """
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    from app.core.config import settings

    payload = {
        "sub": "00000000-0000-0000-0000-000000000099",
        "role": "auditor",
        "is_active": False,
        "exp": datetime.now(UTC) + timedelta(minutes=30),
    }
    token = pyjwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
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
    debit_id = await _seed_account(db_session, "Cash-Auth", AccountType.ASSET, "9010")
    credit_id = await _seed_account(
        db_session, "Revenue-Auth", AccountType.REVENUE, "9011"
    )
    payload = {
        "description": "Authenticated admin transaction",
        "transaction_date": "2024-01-01",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 500,
                "currency": "JPY",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 500,
                "currency": "JPY",
            },
        ],
    }
    admin_c = await authenticated_client("admin")
    response = await admin_c.post("/api/v1/transactions", json=payload)
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_authenticated_auditor_cannot_post_transaction(
    authenticated_client,
) -> None:
    """POST /transactions with a real JWT-authenticated auditor must return 403."""
    auditor_c = await authenticated_client("auditor")
    response = await auditor_c.post("/api/v1/transactions", json={})
    assert response.status_code == 403
