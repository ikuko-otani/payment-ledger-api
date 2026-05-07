"""Integration tests for GET/POST /api/v1/accounts."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


POST_URL = "/api/v1/accounts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _account_payload(name: str = "Cash", account_type: str = "asset") -> dict:
    return {"name": name, "account_type": account_type}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_account_returns_201(client: AsyncClient) -> None:
    """POST /accounts with valid payload should return 201 and the created account."""
    response = await client.post(POST_URL, json=_account_payload())
    # TODO: assert status code is 201
    # Hint: assert response.status_code == 201
    assert response.status_code == 201
    data = response.json()
    # TODO: assert the returned name matches the payload
    # Hint: assert data["name"] == "Cash"
    assert data["name"] == "Cash"
    assert data["account_type"] == "asset"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_accounts_returns_created(client: AsyncClient) -> None:
    """GET /accounts should include a previously created account."""
    await client.post(POST_URL, json=_account_payload(name="Revenue", account_type="revenue"))
    response = await client.get(POST_URL)
    assert response.status_code == 200
    names = [a["name"] for a in response.json()]
    # ✍️ Write an assertion that "Revenue" is in names
    assert "Revenue" in names


@pytest.mark.asyncio
async def test_create_account_duplicate_name_returns_error(client: AsyncClient) -> None:
    """POST /accounts with a duplicate name should return 4xx."""
    payload = _account_payload(name="Duplicate")
    await client.post(POST_URL, json=payload)
    response = await client.post(POST_URL, json=payload)
    # TODO: assert the status code indicates an error (4xx)
    # Hint: assert response.status_code >= 400
    assert response.status_code >= 400
