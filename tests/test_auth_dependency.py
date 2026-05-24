"""Integration tests for JWT-protected endpoints (S3-4, S3-7)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _register_and_login(
    async_client: AsyncClient,
    email: str = "dep_user@example.com",
    password: str = "secret123",
) -> str:
    """Register a user and return a valid JWT access token."""
    await async_client.post("/api/v1/users", json={"email": email, "password": password})
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return str(response.json()["access_token"])


def _expired_token() -> str:
    """Return a syntactically valid but expired JWT."""
    from datetime import datetime, timedelta, timezone

    from jose import jwt as jose_jwt

    from app.core.config import settings

    payload = {
        "sub": "00000000-0000-0000-0000-000000000000",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
    }
    return jose_jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


# ---------------------------------------------------------------------------
# S3-7: token-forgery helpers
# ---------------------------------------------------------------------------


def _invalid_signature_token() -> str:
    """Return a JWT signed with the wrong secret key."""
    from uuid import uuid4

    from jose import jwt as jose_jwt

    from app.core.config import settings

    payload = {"sub": str(uuid4())}
    return jose_jwt.encode(payload, "wrong-secret", algorithm=settings.algorithm)


def _nonexistent_user_token() -> str:
    """Return a JWT with a random UUID sub that does not exist in the DB."""
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    from jose import jwt as jose_jwt

    from app.core.config import settings

    payload = {
        "sub": str(uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    return jose_jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


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
