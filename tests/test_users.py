"""Integration tests for POST /users endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_register_user_success_returns_201(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/users",
        json={"email": "alice@example.com", "password": "secret123"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "auditor"
    assert body["is_active"] is True
    assert "hashed_password" not in body


@pytest.mark.asyncio
async def test_register_user_duplicate_email_returns_409(
    async_client: AsyncClient,
) -> None:
    payload = {"email": "bob@example.com", "password": "secret123"}
    first = await async_client.post("/api/v1/users", json=payload)
    assert first.status_code == 201
    second = await async_client.post("/api/v1/users", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_register_user_password_is_hashed_in_db(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await async_client.post(
        "/api/v1/users",
        json={"email": "carol@example.com", "password": "plaintext"},
    )
    result = await db_session.execute(select(User).where(User.email == "carol@example.com"))
    user = result.scalar_one()
    assert user.hashed_password != "plaintext"
    assert user.hashed_password.startswith("$2b$")
