"""Integration tests for GET /ledger endpoint."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType
from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate

_FIXTURE_ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def _seed_eur_rate(db: AsyncSession, tx_date: str) -> None:
    result = await db.execute(select(Currency).where(Currency.code.in_(["EUR", "USD"])))
    currencies = {c.code: c for c in result.scalars().all()}
    eur = currencies["EUR"]
    usd = currencies["USD"]
    db.add(
        ExchangeRate(
            from_currency_id=eur.id,
            to_currency_id=usd.id,
            rate=Decimal("1.10"),
            effective_date=date.fromisoformat(tx_date),
            created_by_id=_FIXTURE_ADMIN_ID,
        )
    )
    await db.commit()


async def _seed_account(
    db: AsyncSession,
    name: str,
    code: str,
    account_type: AccountType = AccountType.ASSET,
    currency: str = "USD",
) -> Account:
    account = Account(
        name=name, code=code, account_type=account_type, currency=currency
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


def _tx_payload(
    debit_id: str,
    credit_id: str,
    amount: int,
    tx_date: str,
    currency: str = "USD",
) -> dict:
    return {
        "description": f"Test tx {tx_date}",
        "transaction_date": tx_date,
        "currency_code": currency,
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": amount,
                "currency": currency,
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": amount,
                "currency": currency,
            },
        ],
    }


@pytest.mark.asyncio
async def test_get_ledger_period_filter_returns_only_entries_in_range(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Entries whose transaction_date falls outside [from, to] must be excluded."""
    debit = await _seed_account(db_session, "Cash-L1", "1100")
    credit = await _seed_account(db_session, "Revenue-L1", "4000", AccountType.REVENUE)

    resp_in = await async_client.post(
        "/api/v1/transactions",
        json=_tx_payload(str(debit.id), str(credit.id), 500, "2026-03-01"),
    )
    assert resp_in.status_code == 201

    resp_out = await async_client.post(
        "/api/v1/transactions",
        json=_tx_payload(str(debit.id), str(credit.id), 500, "2025-12-01"),
    )
    assert resp_out.status_code == 201

    resp = await async_client.get("/api/v1/ledger?from=2026-01-01&to=2026-06-30")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0
    dates = {item["transaction"]["transaction_date"] for item in data}
    assert all("2026-01-01" <= d <= "2026-06-30" for d in dates)
    assert "2025-12-01" not in dates


@pytest.mark.asyncio
async def test_get_ledger_currency_filter_returns_only_matching_currency(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """currency_code filter must exclude entries of other currencies."""
    await _seed_eur_rate(db_session, "2026-04-01")

    debit_usd = await _seed_account(db_session, "Cash-L2-USD", "1101")
    credit_usd = await _seed_account(
        db_session, "Revenue-L2-USD", "4001", AccountType.REVENUE
    )
    debit_eur = await _seed_account(db_session, "Cash-L2-EUR", "1105", currency="EUR")
    credit_eur = await _seed_account(
        db_session, "Revenue-L2-EUR", "4005", AccountType.REVENUE, "EUR"
    )

    # USD transaction
    resp_usd = await async_client.post(
        "/api/v1/transactions",
        json=_tx_payload(
            str(debit_usd.id), str(credit_usd.id), 300, "2026-04-01", "USD"
        ),
    )
    assert resp_usd.status_code == 201

    # EUR transaction
    resp_eur = await async_client.post(
        "/api/v1/transactions",
        json=_tx_payload(
            str(debit_eur.id), str(credit_eur.id), 110, "2026-04-01", "EUR"
        ),
    )
    assert resp_eur.status_code == 201

    # EUR filter
    resp = await async_client.get("/api/v1/ledger?currency_code=EUR")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0
    assert all(item["currency"] == "EUR" for item in data)

    # USD filter
    resp_usd_filter = await async_client.get("/api/v1/ledger?currency_code=USD")
    assert all(item["currency"] == "USD" for item in resp_usd_filter.json())


@pytest.mark.asyncio
async def test_get_ledger_account_id_filter_returns_only_matching_entries(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """account_id filter must restrict results to entries on that account."""
    acct_a = await _seed_account(db_session, "Cash-L3", "1102")
    acct_b = await _seed_account(db_session, "Revenue-L3", "4002", AccountType.REVENUE)

    resp = await async_client.post(
        "/api/v1/transactions",
        json=_tx_payload(str(acct_a.id), str(acct_b.id), 200, "2026-05-01"),
    )
    assert resp.status_code == 201

    resp_filter = await async_client.get(f"/api/v1/ledger?account_id={acct_a.id}")
    assert resp_filter.status_code == 200
    data = resp_filter.json()
    assert len(data) > 0
    assert all(item["account_id"] == str(acct_a.id) for item in data)


@pytest.mark.asyncio
async def test_get_ledger_pagination_limit_and_offset(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """limit caps result size; offset skips rows; pages must not overlap."""
    debit = await _seed_account(db_session, "Cash-L4", "1103")
    credit = await _seed_account(db_session, "Revenue-L4", "4003", AccountType.REVENUE)

    for i in range(3):
        r = await async_client.post(
            "/api/v1/transactions",
            json=_tx_payload(
                str(debit.id), str(credit.id), 100 + i, f"2026-0{i + 1}-01"
            ),
        )
        assert r.status_code == 201

    resp_page1 = await async_client.get("/api/v1/ledger?limit=2&offset=0")
    assert resp_page1.status_code == 200
    page1 = resp_page1.json()
    assert len(page1) == 2

    resp_page2 = await async_client.get("/api/v1/ledger?limit=2&offset=2")
    assert resp_page2.status_code == 200
    page2 = resp_page2.json()

    ids1 = {item["id"] for item in page1}
    ids2 = {item["id"] for item in page2}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tx_date, query_params, should_be_included",
    [
        ("2026-03-01", "from=2026-03-01", True),
        ("2026-03-31", "to=2026-03-31", True),
        ("2026-02-28", "from=2026-03-01", False),
        ("2026-04-01", "to=2026-03-31", False),
    ],
)
async def test_get_ledger_date_boundary(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tx_date: str,
    query_params: str,
    should_be_included: bool,
) -> None:
    debit = await _seed_account(
        db_session, f"Cash-B-{tx_date}", f"BD{tx_date[:7].replace('-', '')}"
    )
    credit = await _seed_account(
        db_session,
        f"Revenue-B-{tx_date}",
        f"BR{tx_date[:7].replace('-', '')}",
        AccountType.REVENUE,
    )

    resp_post = await async_client.post(
        "/api/v1/transactions",
        json=_tx_payload(str(debit.id), str(credit.id), 250, tx_date),
    )
    assert resp_post.status_code == 201
    tx_id = resp_post.json()["id"]

    resp = await async_client.get(f"/api/v1/ledger?{query_params}")
    assert resp.status_code == 200
    returned_tx_ids = {item["transaction"]["id"] for item in resp.json()}

    if should_be_included:
        assert tx_id in returned_tx_ids, (
            f"Expected tx on {tx_date} to be included with {query_params}"
        )
    else:
        assert tx_id not in returned_tx_ids, (
            f"Expected tx on {tx_date} to be excluded with {query_params}"
        )
