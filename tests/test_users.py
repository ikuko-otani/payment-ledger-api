"""Integration tests for POST /users endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_user_success_returns_201(async_client: AsyncClient) -> None:
    # TODO: implement — POST /api/v1/users with valid payload
    #   assert status_code == 201
    #   assert response body contains id, email, role, is_active
    #   assert "hashed_password" not in response.json()
    raise NotImplementedError


@pytest.mark.asyncio
async def test_register_user_duplicate_email_returns_409(
    async_client: AsyncClient,
) -> None:
    # TODO: implement — POST same email twice
    #   first request: assert 201
    #   second request: assert 409
    raise NotImplementedError


@pytest.mark.asyncio
async def test_register_user_password_is_hashed_in_db(
    async_client: AsyncClient,
) -> None:
    # TODO: implement — POST a user, then query DB directly via db_session
    #   assert user.hashed_password != plain password
    #   assert user.hashed_password starts with "$2b$" (bcrypt prefix)
    raise NotImplementedError
