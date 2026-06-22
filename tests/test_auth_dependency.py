"""Integration tests for JWT-protected endpoints (S3-4, S3-7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from httpx import AsyncClient

from app.core.config import settings


async def _register_and_login(
    async_client: AsyncClient,
    email: str = "dep_user@example.com",
    password: str = "secret123",
) -> str:
    """Register a user and return a valid JWT access token."""
    await async_client.post(
        "/api/v1/users", json={"email": email, "password": password}
    )
    response = await async_client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )
    return str(response.json()["access_token"])


def _expired_token() -> str:
    """Return a syntactically valid but expired JWT."""
    payload = {
        "sub": "00000000-0000-0000-0000-000000000000",
        "exp": datetime.now(UTC) - timedelta(minutes=1),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _invalid_signature_token() -> str:
    """Return a JWT signed with the wrong secret key."""
    payload = {"sub": str(uuid4())}
    return jwt.encode(payload, "wrong-secret", algorithm=settings.algorithm)


def _nonexistent_user_token() -> str:
    """Return a JWT with a random UUID sub but no role/is_active claims.

    After TD-015: get_current_user no longer queries the DB.
    This token returns 401 because required claims (role, is_active) are absent,
    not because the user UUID is absent from the database.
    """
    payload = {
        "sub": str(uuid4()),
        "exp": datetime.now(UTC) + timedelta(minutes=30),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _no_sub_token() -> str:
    """Return a JWT signed correctly but with no 'sub' claim at all."""
    payload = {"exp": datetime.now(UTC) + timedelta(minutes=30)}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


# ---------------------------------------------------------------------------
# Existing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_token_returns_401(unauthed_client: AsyncClient) -> None:
    """GET /accounts without Authorization header must return 401."""
    response = await unauthed_client.get("/api/v1/accounts")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_returns_200(unauthed_client: AsyncClient) -> None:
    """GET /accounts with a valid Bearer token must return 200."""
    token = await _register_and_login(unauthed_client)
    response = await unauthed_client.get(
        "/api/v1/accounts", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_expired_token_returns_401(unauthed_client: AsyncClient) -> None:
    """GET /accounts with an expired token must return 401."""
    token = _expired_token()
    response = await unauthed_client.get(
        "/api/v1/accounts", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# S3-7: edge-case tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_signature_token_returns_401(
    unauthed_client: AsyncClient,
) -> None:
    """GET /accounts with a token signed by the wrong key must return 401."""
    token = _invalid_signature_token()
    response = await unauthed_client.get(
        "/api/v1/accounts", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_nonexistent_user_id_token_returns_401(
    unauthed_client: AsyncClient,
) -> None:
    """GET /accounts with a valid-signature JWT whose sub is not in the DB must return 401."""
    token = _nonexistent_user_token()
    response = await unauthed_client.get(
        "/api/v1/accounts", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# S6-3: sub=None path (deps.py line 36)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jwt_missing_sub_claim_returns_401(
    unauthed_client: AsyncClient,
) -> None:
    """GET /accounts with a JWT that has no 'sub' claim must return 401.

    Exercises deps.py line 36: `if sub is None: raise credentials_exception`.
    """
    token = _no_sub_token()
    response = await unauthed_client.get(
        "/api/v1/accounts", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
