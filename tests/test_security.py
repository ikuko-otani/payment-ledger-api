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
    # TODO: implement (hint: GET /api/v1/accounts with
    # headers={"Authorization": "Bearer xxx.yyy.zzz"}; assert 401)
    ...


# ---------------------------------------------------------------------------
# SQL injection attempt via path parameter -> 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sql_injection_in_account_id_path_param_returns_422(
    async_client: AsyncClient,
) -> None:
    """A SQLi-style payload as the account_id path param must fail UUID validation (422)."""
    # TODO: implement (hint: payload = "'; DROP TABLE accounts; --"
    # GET f"/api/v1/accounts/{payload}/balance" with
    # params={"as_of": "2024-01-01T00:00:00"} via async_client
    # (already authenticated as admin); assert response.status_code == 422)
    ...
