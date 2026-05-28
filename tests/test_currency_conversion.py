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
    account = Account(
        name=name, account_type=account_type, code=code, currency=currency
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return str(account.id)


async def _seed_currency(
    client: AsyncClient, code: str, name: str, decimal_places: int
) -> str:
    """POST /currencies and return the created currency id."""
    resp = await client.post(
        "/api/v1/currencies",
        json={"code": code, "name": name, "decimal_places": decimal_places},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seed_exchange_rate(
    client: AsyncClient,
    from_currency_id: str,
    to_currency_id: str,
    rate: str,
    effective_date: str,
) -> None:
    """POST /exchange-rates to seed a rate for a given date."""
    resp = await client.post(
        "/api/v1/exchange-rates",
        json={
            "from_currency_id": from_currency_id,
            "to_currency_id": to_currency_id,
            "rate": rate,
            "effective_date": effective_date,
        },
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usd_transaction_stores_identity_converted_amount(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """USD transaction: converted_amount_usd == amount (no rate lookup needed)."""
    client = await authenticated_client("admin")
    await _seed_currency(client, "USD", "US Dollar", 2)
    debit_id = await _seed_account(db_session, "Cash-USD", AccountType.ASSET, "CV-1000")
    credit_id = await _seed_account(
        db_session, "Revenue-USD", AccountType.REVENUE, "CV-4000"
    )

    payload = {
        "currency_code": "USD",
        "description": "USD identity conversion",
        "transaction_date": "2024-01-15",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 5000,
                "currency": "USD",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 5000,
                "currency": "USD",
            },
        ],
    }
    resp = await client.post("/api/v1/transactions", json=payload)
    assert resp.status_code == 201
    for entry in resp.json()["entries"]:
        assert entry["converted_amount_usd"] == 5000


@pytest.mark.asyncio
async def test_jpy_transaction_converts_to_usd_correctly(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """JPY transaction: converted_amount_usd = amount * JPY/USD rate (ROUND_HALF_UP)."""
    client = await authenticated_client("admin")
    jpy_id = await _seed_currency(client, "JPY", "Japanese Yen", 0)
    usd_id = await _seed_currency(client, "USD", "US Dollar", 2)
    await _seed_exchange_rate(client, jpy_id, usd_id, "0.00670000", "2024-01-15")

    debit_id = await _seed_account(db_session, "Cash-JPY", AccountType.ASSET, "CV-1001")
    credit_id = await _seed_account(
        db_session, "Revenue-JPY", AccountType.REVENUE, "CV-4001"
    )

    # 15000 JPY × 0.0067 = 100.5 USD → 100 cents (ROUND_HALF_UP → 101)
    # Wait: 15000 * 0.0067 = 100.5 → ROUND_HALF_UP → 101 USD cents = $1.01
    # Let's use 10000 JPY × 0.0067 = 67.0 USD cents = 67 cents
    payload = {
        "currency_code": "JPY",
        "description": "JPY to USD conversion",
        "transaction_date": "2024-01-15",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 10000,
                "currency": "JPY",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 10000,
                "currency": "JPY",
            },
        ],
    }
    resp = await client.post("/api/v1/transactions", json=payload)
    assert resp.status_code == 201
    # 10000 * 0.00670000 = 67.0 → 67 cents
    for entry in resp.json()["entries"]:
        assert entry["converted_amount_usd"] == 67


@pytest.mark.asyncio
async def test_eur_transaction_converts_to_usd_correctly(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """EUR transaction: converted_amount_usd = amount * EUR/USD rate (ROUND_HALF_UP)."""
    client = await authenticated_client("admin")
    eur_id = await _seed_currency(client, "EUR", "Euro", 2)
    usd_id = await _seed_currency(client, "USD", "US Dollar", 2)
    await _seed_exchange_rate(client, eur_id, usd_id, "1.08000000", "2024-01-15")

    debit_id = await _seed_account(db_session, "Cash-EUR", AccountType.ASSET, "CV-1002")
    credit_id = await _seed_account(
        db_session, "Revenue-EUR", AccountType.REVENUE, "CV-4002"
    )

    # 500 EUR cents (= €5.00) × 1.08 = 540 USD cents (= $5.40)
    payload = {
        "currency_code": "EUR",
        "description": "EUR to USD conversion",
        "transaction_date": "2024-01-15",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 500,
                "currency": "EUR",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 500,
                "currency": "EUR",
            },
        ],
    }
    resp = await client.post("/api/v1/transactions", json=payload)
    assert resp.status_code == 201
    # 500 * 1.08 = 540.0 → 540 cents
    for entry in resp.json()["entries"]:
        assert entry["converted_amount_usd"] == 540


@pytest.mark.asyncio
async def test_converted_amount_usd_rounds_half_up(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """Rounding: 0.5 fractional cent rounds UP (ROUND_HALF_UP, not banker's rounding)."""
    client = await authenticated_client("admin")
    jpy_id = await _seed_currency(client, "JPY", "Japanese Yen", 0)
    usd_id = await _seed_currency(client, "USD", "US Dollar", 2)
    # rate = 0.00500000: 1 JPY = 0.005 USD cents → 100 JPY = 0.5 cents → rounds to 1
    await _seed_exchange_rate(client, jpy_id, usd_id, "0.00500000", "2024-02-01")

    debit_id = await _seed_account(
        db_session, "Cash-Round", AccountType.ASSET, "CV-1010"
    )
    credit_id = await _seed_account(
        db_session, "Rev-Round", AccountType.REVENUE, "CV-4010"
    )

    payload = {
        "currency_code": "JPY",
        "description": "Rounding test",
        "transaction_date": "2024-02-01",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 100,
                "currency": "JPY",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 100,
                "currency": "JPY",
            },
        ],
    }
    resp = await client.post("/api/v1/transactions", json=payload)
    assert resp.status_code == 201
    # 100 * 0.005 = 0.5 → ROUND_HALF_UP → 1
    for entry in resp.json()["entries"]:
        assert entry["converted_amount_usd"] == 1


@pytest.mark.asyncio
async def test_both_entries_get_converted_amount_usd(
    authenticated_client,
    db_session: AsyncSession,
) -> None:
    """All entries in a transaction receive converted_amount_usd, not just one side."""
    client = await authenticated_client("admin")
    eur_id = await _seed_currency(client, "EUR", "Euro", 2)
    usd_id = await _seed_currency(client, "USD", "US Dollar", 2)
    await _seed_exchange_rate(client, eur_id, usd_id, "1.08000000", "2024-01-15")

    debit_id = await _seed_account(
        db_session, "Cash-Both", AccountType.ASSET, "CV-1020"
    )
    credit_id = await _seed_account(
        db_session, "Rev-Both", AccountType.REVENUE, "CV-4020"
    )

    payload = {
        "currency_code": "EUR",
        "description": "Both entries converted",
        "transaction_date": "2024-01-15",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 200,
                "currency": "EUR",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 200,
                "currency": "EUR",
            },
        ],
    }
    resp = await client.post("/api/v1/transactions", json=payload)
    assert resp.status_code == 201
    entries = resp.json()["entries"]
    assert len(entries) == 2
    assert all(e["converted_amount_usd"] == 216 for e in entries)  # 200 * 1.08 = 216


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
