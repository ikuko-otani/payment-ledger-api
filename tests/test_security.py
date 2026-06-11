"""Security-focused integration tests: auth bypass + SQL injection."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Unauthenticated access -> 401
# ---------------------------------------------------------------------------

_PROTECTED_ENDPOINTS: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/transactions", {"json": {}}),
    (
        "GET",
        "/api/v1/accounts/00000000-0000-0000-0000-000000000000/balance",
        {"params": {"as_of": "2024-01-01T00:00:00"}},
    ),
    ("GET", "/api/v1/ledger", {}),
    ("POST", "/api/v1/accounts", {"json": {}}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "kwargs"), _PROTECTED_ENDPOINTS)
async def test_unauthenticated_request_to_protected_endpoint_returns_401(
    unauthed_client: AsyncClient, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    """A request with no Authorization header to a protected endpoint must return 401."""
    response = await unauthed_client.request(method, path, **kwargs)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tampered JWT -> 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tampered_jwt_returns_401(unauthed_client: AsyncClient) -> None:
    """A garbage token 'xxx.yyy.zzz' must return 401 (JWTError -> credentials_exception)."""
    response = await unauthed_client.get(
        "/api/v1/accounts", headers={"Authorization": "Bearer xxx.yyy.zzz"}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# SQL injection attempt via path parameter -> 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sql_injection_in_account_id_path_param_returns_422(
    async_client: AsyncClient,
) -> None:
    """A SQLi-style payload as the account_id path param must fail UUID validation (422)."""
    payload = "'; DROP TABLE accounts; --"
    response = await async_client.get(
        f"/api/v1/accounts/{payload}/balance",
        params={"as_of": "2024-01-01T00:00:00"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# SQL injection attempt via string query parameter -> 200 + empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sql_injection_in_currency_code_query_param_returns_empty_list(
    async_client: AsyncClient,
) -> None:
    """A SQLi-style payload in currency_code (str) is bound as a literal value.

    Unlike account_id (uuid.UUID), currency_code (str) passes type validation.
    SQLAlchemy sends it to Postgres as a bind parameter -- never as SQL syntax --
    so the WHERE clause becomes a literal equality check against a 27-character
    string. Entry.currency is VARCHAR(3) (ISO 4217 codes), so no row can ever
    match: the query executes safely and returns 200 + [].
    """
    response = await async_client.get(
        "/api/v1/ledger",
        params={"currency_code": "'; DROP TABLE accounts; --"},
    )
    assert response.status_code == 200
    assert response.json() == []
