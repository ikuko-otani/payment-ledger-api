"""Integration tests for POST /users endpoint."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import ConflictError
from app.models.user import User
from app.schemas.user import UserCreate
from app.services import user_service


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
    result = await db_session.execute(
        select(User).where(User.email == "carol@example.com")
    )
    user = result.scalar_one()
    assert user.hashed_password != "plaintext"
    assert user.hashed_password.startswith("$2b$")


@pytest.mark.asyncio
async def test_create_user_concurrent_duplicate_email_returns_conflict(
    engine: AsyncEngine,
) -> None:
    """TOCTOU race (TD-031): two concurrent create_user calls with the same
    email both pass the pre-check SELECT (neither has committed yet), so
    both proceed to INSERT. The users.email UNIQUE constraint lets exactly
    one succeed; the loser's flush() raises IntegrityError, which
    create_user converts to ConflictError instead of a raw 500.
    """
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    payload = UserCreate(email="race@example.com", password="secret123")

    async def _attempt() -> User | ConflictError:
        async with session_factory() as session:
            try:
                user = await user_service.create_user(session, payload)
                await session.commit()
                return user
            except ConflictError as e:
                await session.rollback()
                return e

    results = await asyncio.gather(_attempt(), _attempt())

    successes = [r for r in results if isinstance(r, User)]
    conflicts = [r for r in results if isinstance(r, ConflictError)]

    assert len(successes) == 1
    assert len(conflicts) == 1
