"""Tests for /currencies and /exchange-rates endpoints (S4-2 DONE conditions)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

_CURRENCY_USD = {"code": "USD", "name": "US Dollar", "decimal_places": 2}
_CURRENCY_EUR = {"code": "EUR", "name": "Euro", "decimal_places": 2}


# ✍️ GET /api/v1/currencies → 200
@pytest.mark.asyncio
async def test_list_currencies_returns_200(async_client: AsyncClient) -> None:
    pass


# ✍️ POST /api/v1/currencies as admin → 201, body matches payload
@pytest.mark.asyncio
async def test_post_currency_as_admin_returns_201(async_client: AsyncClient) -> None:
    pass


# ✍️ POST /api/v1/currencies as auditor → 403
@pytest.mark.asyncio
async def test_post_currency_as_auditor_returns_403(auditor_client: AsyncClient) -> None:
    pass


# ✍️ POST /api/v1/exchange-rates twice with same pair+date → second returns 409
#    Setup: create USD + EUR, then POST exchange-rate twice
@pytest.mark.asyncio
async def test_post_duplicate_exchange_rate_returns_409(async_client: AsyncClient) -> None:
    pass
