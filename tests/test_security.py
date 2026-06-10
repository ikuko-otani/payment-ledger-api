"""Security-focused integration tests (S6-6): auth bypass + SQL injection.

Covers the S6-6 DONE conditions: unauthenticated access to protected
endpoints, a tampered/malformed JWT, and a SQL-injection-style payload in a
path parameter.

Some S6-6 "やること" items are already covered elsewhere and are
intentionally NOT duplicated here:
- Expired JWT -> 401: see
  tests/test_auth_dependency.py::test_expired_token_returns_401
- Auditor role on admin-only endpoints -> 403: see tests/test_rbac.py
  (test_auditor_cannot_create_account, test_auditor_cannot_post_transaction)

Note on DONE-condition wording: the Notion DONE condition for "tampered JWT"
says 403, but app/core/deps.py raises 401 for any JWTError (signature or
format errors) -- 403 is reserved for role checks (require_admin /
require_auditor_or_admin). This file tests the actual behavior (401); no
auth code was changed (out of scope per "やらないこと").
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Unauthenticated access -> 401
# ---------------------------------------------------------------------------

# TODO: implement (hint: list (method, path, kwargs) tuples for the 4
# protected endpoints from the Notion "やること" section:
#   POST /api/v1/transactions, GET /api/v1/accounts/{id}/balance,
#   GET /api/v1/ledger, POST /api/v1/accounts
# - For POST endpoints, pass kwargs={"json": {}} -- auth must short-circuit
#   before body validation, same as test_auditor_cannot_post_transaction
#   in tests/test_rbac.py.
# - For GET /accounts/{id}/balance, use any syntactically valid UUID string
#   for {id} (the DB is never reached) and pass
#   kwargs={"params": {"as_of": "2024-01-01T00:00:00"}} so the 401 isn't
#   masked by a 422 on the missing required query param.)
_PROTECTED_ENDPOINTS: list[tuple[str, str, dict[str, Any]]] = [
    # ("POST", "/api/v1/transactions", {"json": {}}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "kwargs"), _PROTECTED_ENDPOINTS)
async def test_unauthenticated_request_to_protected_endpoint_returns_401(
    unauthed_client: AsyncClient, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    """A request with no Authorization header to a protected endpoint must return 401."""
    # TODO: implement (hint: response = await unauthed_client.request(method, path, **kwargs);
    # assert response.status_code == 401)
    ...


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
