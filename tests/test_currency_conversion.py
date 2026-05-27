"""Currency conversion tests for POST /transactions (S4-3).

Design notes:
- All tests use authenticated_client("admin") to ensure ExchangeRate seeds
  can be created via POST /exchange-rates (FK: created_by_id → users.id).
- Base currency is USD; converted_amount_usd is stored in entries at write time.
- Exchange rates are seeded via POST /currencies + POST /exchange-rates.
- Rounding policy: ROUND_HALF_UP (see ARCHITECTURE.md ADR-006).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_account(
    db_session: AsyncSession,
    name: str,
    account_type: AccountType,
    code: str,
    currency: str = "USD",
) -> str:
    """Insert an account directly and return its id as str."""
    account = Account(name=name, account_type=account_type, code=code, currency=currency)
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return str(account.id)


async def _seed_currency(client: AsyncClient, code: str, name: str, decimal_places: int) -> str:
    """POST /currencies and return the created currency id."""
    # ✍️ TODO: implement — POST to /api/v1/currencies, return resp.json()["id"]
    ...


async def _seed_exchange_rate(
    client: AsyncClient,
    from_currency_id: str,
    to_currency_id: str,
    rate: str,
    effective_date: str,
) -> None:
    """POST /exchange-rates to seed a rate for a given date."""
    # ✍️ TODO: implement — POST to /api/v1/exchange-rates, assert 201
    ...


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usd_transaction_stores_identity_converted_amount(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """USD transaction: converted_amount_usd == amount (no rate lookup needed)."""
    # ✍️ TODO: implement
    ...


@pytest.mark.asyncio
async def test_jpy_transaction_converts_to_usd_correctly(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """JPY transaction: converted_amount_usd = amount * JPY/USD rate (ROUND_HALF_UP)."""
    # ✍️ TODO: implement
    ...


@pytest.mark.asyncio
async def test_eur_transaction_converts_to_usd_correctly(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """EUR transaction: converted_amount_usd = amount * EUR/USD rate (ROUND_HALF_UP)."""
    # ✍️ TODO: implement
    ...


@pytest.mark.asyncio
async def test_converted_amount_usd_rounds_half_up(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """Rounding: 0.5 fractional cent rounds UP (ROUND_HALF_UP, not banker's rounding)."""
    # ✍️ TODO: implement — choose an amount and rate that produce a .5 fractional result
    ...


@pytest.mark.asyncio
async def test_both_entries_get_converted_amount_usd(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """All entries in a transaction receive converted_amount_usd, not just one side."""
    # ✍️ TODO: implement — assert len(entries with converted_amount_usd > 0) == 2
    ...


# ---------------------------------------------------------------------------
# Error / edge case tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_exchange_rate_returns_422(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """422 when no ExchangeRate row exists for (currency_code, USD, transaction_date)."""
    # ✍️ TODO: implement — do NOT seed exchange rate; expect 422
    ...


@pytest.mark.asyncio
async def test_exchange_rate_wrong_date_returns_422(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """422 when ExchangeRate exists for a DIFFERENT date than transaction_date."""
    # ✍️ TODO: implement — seed rate for 2024-01-01 but POST with 2024-06-01
    ...


@pytest.mark.asyncio
async def test_unknown_currency_code_returns_422(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """422 when currency_code is not present in the currencies table."""
    # ✍️ TODO: implement — use currency_code="XXX" (no Currency row)
    ...
