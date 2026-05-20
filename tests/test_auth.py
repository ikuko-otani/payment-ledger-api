"""Integration tests for POST /auth/login endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _register_user(
    async_client: AsyncClient,
    email: str = "auth_user@example.com",
    password: str = "secret123",
) -> None:
    await async_client.post("/api/v1/users", json={"email": email, "password": password})


@pytest.mark.asyncio
async def test_login_success_returns_200_with_jwt(async_client: AsyncClient) -> None:
    await _register_user(async_client)
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "auth_user@example.com", "password": "secret123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(async_client: AsyncClient) -> None:
    await _register_user(async_client)
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "auth_user@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


@pytest.mark.asyncio
async def test_login_unknown_email_returns_401(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "secret123"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"
