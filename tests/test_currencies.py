"""Tests for /currencies and /exchange-rates endpoints (S4-2 DONE conditions)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

_CURRENCY_USD = {"code": "USD", "name": "US Dollar", "decimal_places": 2}
_CURRENCY_EUR = {"code": "EUR", "name": "Euro", "decimal_places": 2}


# GET /api/v1/currencies → 200
@pytest.mark.asyncio
async def test_list_currencies_returns_200(async_client: AsyncClient) -> None:
    response = await async_client.get("/api/v1/currencies")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# POST /api/v1/currencies as admin → 201, body matches payload
@pytest.mark.asyncio
async def test_post_currency_as_admin_returns_201(async_client: AsyncClient) -> None:
    response = await async_client.post("/api/v1/currencies", json=_CURRENCY_USD)
    assert response.status_code == 201
    data = response.json()
    assert data["code"] == "USD"
    assert data["decimal_places"] == 2


# POST /api/v1/currencies as auditor → 403
@pytest.mark.asyncio
async def test_post_currency_as_auditor_returns_403(
    auditor_client: AsyncClient,
) -> None:
    response = await auditor_client.post("/api/v1/currencies", json=_CURRENCY_USD)
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# S6-3: GET /exchange-rates filter combinations (currency_service.py lines 43–51)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_rates_no_filter_returns_all(async_client: AsyncClient) -> None:
    """GET /exchange-rates without filters returns all seeded rates."""
    r_usd = await async_client.post("/api/v1/currencies", json=_CURRENCY_USD)
    r_eur = await async_client.post("/api/v1/currencies", json=_CURRENCY_EUR)
    usd_id = r_usd.json()["id"]
    eur_id = r_eur.json()["id"]

    for from_id, to_id, d in [
        (usd_id, eur_id, "2024-01-01"),
        (eur_id, usd_id, "2024-01-01"),
    ]:
        await async_client.post(
            "/api/v1/exchange-rates",
            json={"from_currency_id": from_id, "to_currency_id": to_id, "rate": "1.08000000", "effective_date": d},
        )

    # TODO: implement (hint: GET /exchange-rates → assert len(response.json()) == 2)


@pytest.mark.asyncio
async def test_exchange_rates_filtered_by_from_currency_id(
    async_client: AsyncClient,
) -> None:
    """GET /exchange-rates?from_currency_id=X returns only rows where from == X."""
    r_usd = await async_client.post("/api/v1/currencies", json=_CURRENCY_USD)
    r_eur = await async_client.post("/api/v1/currencies", json=_CURRENCY_EUR)
    usd_id = r_usd.json()["id"]
    eur_id = r_eur.json()["id"]

    # Seed USD→EUR and EUR→USD rates
    for from_id, to_id in [(usd_id, eur_id), (eur_id, usd_id)]:
        await async_client.post(
            "/api/v1/exchange-rates",
            json={"from_currency_id": from_id, "to_currency_id": to_id, "rate": "1.08000000", "effective_date": "2024-01-01"},
        )

    # TODO: implement (hint: GET /exchange-rates?from_currency_id=usd_id → only 1 row, and it has from_currency_id == usd_id)


@pytest.mark.asyncio
async def test_exchange_rates_filtered_by_effective_date(
    async_client: AsyncClient,
) -> None:
    """GET /exchange-rates?effective_date=X returns only rows for that date."""
    r_usd = await async_client.post("/api/v1/currencies", json=_CURRENCY_USD)
    r_eur = await async_client.post("/api/v1/currencies", json=_CURRENCY_EUR)
    usd_id = r_usd.json()["id"]
    eur_id = r_eur.json()["id"]

    # Seed the same pair for two different dates
    for d in ["2024-01-01", "2024-06-01"]:
        await async_client.post(
            "/api/v1/exchange-rates",
            json={"from_currency_id": usd_id, "to_currency_id": eur_id, "rate": "1.08000000", "effective_date": d},
        )

    # TODO: implement (hint: GET /exchange-rates?effective_date=2024-01-01 → 1 row, effective_date == "2024-01-01")


# POST /api/v1/exchange-rates twice with same pair+date → second returns 409
# Setup: create USD + EUR, then POST exchange-rate twice
@pytest.mark.asyncio
async def test_post_duplicate_exchange_rate_returns_409(
    authenticated_client,
) -> None:
    client = await authenticated_client("admin")
    r_usd = await client.post("/api/v1/currencies", json=_CURRENCY_USD)
    r_eur = await client.post("/api/v1/currencies", json=_CURRENCY_EUR)
    usd_id = r_usd.json()["id"]
    eur_id = r_eur.json()["id"]

    payload = {
        "from_currency_id": usd_id,
        "to_currency_id": eur_id,
        "rate": "1.08000000",
        "effective_date": "2024-01-01",
    }

    r1 = await client.post("/api/v1/exchange-rates", json=payload)
    assert r1.status_code == 201

    r2 = await client.post("/api/v1/exchange-rates", json=payload)
    assert r2.status_code == 409
