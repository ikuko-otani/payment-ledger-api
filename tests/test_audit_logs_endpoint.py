"""Integration tests for GET /audit-logs endpoint (S4-6)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_audit_logs_admin_returns_200_and_list(
    async_client: AsyncClient,
) -> None:
    """Admin can access GET /audit-logs and receives a JSON list."""
    await async_client.post(
        "/api/v1/accounts",
        json={
            "code": "1200",
            "name": "Bank",
            "account_type": "asset",
            "currency": "USD",
        },
    )

    resp = await async_client.get("/api/v1/audit-logs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_get_audit_logs_auditor_returns_403(
    auditor_client: AsyncClient,
) -> None:
    """Auditor role must be denied access to GET /audit-logs (403)."""
    resp = await auditor_client.get("/api/v1/audit-logs")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_audit_logs_entity_type_filter(
    async_client: AsyncClient,
) -> None:
    """entity_type filter restricts results to matching entity types only."""
    await async_client.post(
        "/api/v1/accounts",
        json={
            "code": "1201",
            "name": "Savings",
            "account_type": "asset",
            "currency": "USD",
        },
    )

    resp = await async_client.get("/api/v1/audit-logs?entity_type=account")
    assert resp.status_code == 200
    data = resp.json()
    assert all(item["entity_type"] == "account" for item in data)

    resp_none = await async_client.get("/api/v1/audit-logs?entity_type=nonexistent")
    assert resp_none.status_code == 200
    assert resp_none.json() == []


@pytest.mark.asyncio
async def test_get_audit_logs_pagination(
    async_client: AsyncClient,
) -> None:
    """limit caps result size; pages must not overlap."""
    for i in range(3):
        await async_client.post(
            "/api/v1/accounts",
            json={
                "code": f"12{i:02d}",
                "name": f"Account{i}",
                "account_type": "asset",
                "currency": "USD",
            },
        )

    resp_page1 = await async_client.get("/api/v1/audit-logs?limit=2&offset=0")
    assert resp_page1.status_code == 200
    assert len(resp_page1.json()) == 2

    resp_page2 = await async_client.get("/api/v1/audit-logs?limit=2&offset=2")
    assert resp_page2.status_code == 200

    ids1 = {item["id"] for item in resp_page1.json()}
    ids2 = {item["id"] for item in resp_page2.json()}
    assert ids1.isdisjoint(ids2)
