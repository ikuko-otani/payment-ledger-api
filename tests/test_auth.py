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
    # 🔧 TODO: implement
    # hint: _register_user → POST /api/v1/auth/login → assert 200
    # check body has "access_token" (non-empty string) and "token_type" == "bearer"
    ...


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(async_client: AsyncClient) -> None:
    # 🔧 TODO: implement
    # hint: _register_user → POST with wrong password → assert 401
    # check body["detail"] == "Incorrect email or password"
    ...


@pytest.mark.asyncio
async def test_login_unknown_email_returns_401(async_client: AsyncClient) -> None:
    # 🔧 TODO: implement
    # hint: POST with never-registered email → assert 401
    # check body["detail"] == "Incorrect email or password"
    ...
