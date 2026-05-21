"""Integration tests for JWT-protected endpoints (S3-4)."""

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
    # TODO: implement (hint: jose.jwt.encode with exp = datetime.now(utc) - timedelta(minutes=1))
    raise NotImplementedError


@pytest.mark.asyncio
async def test_no_token_returns_401(async_client: AsyncClient) -> None:
    """GET /accounts without Authorization header must return 401."""
    response = await async_client.get("/api/v1/accounts")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_returns_200(async_client: AsyncClient) -> None:
    """GET /accounts with a valid Bearer token must return 200."""
    # TODO: implement (hint: _register_and_login → Authorization header → assert 200)
    raise NotImplementedError


@pytest.mark.asyncio
async def test_expired_token_returns_401(async_client: AsyncClient) -> None:
    """GET /accounts with an expired token must return 401."""
    # TODO: implement (hint: _expired_token() → Authorization header → assert 401)
    raise NotImplementedError
