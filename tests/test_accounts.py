"""DB-level integration tests for Account model operations."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType


@pytest.mark.asyncio
async def test_create_account_persists_row(db_session: AsyncSession) -> None:
    account = Account(
        code="1100",
        currency="EUR",
        name="Cash",
        account_type=AccountType.ASSET,
    )
    db_session.add(account)
    await db_session.commit()

    result = await db_session.execute(select(Account).where(Account.name == "Cash"))
    saved = result.scalar_one()

    assert saved.name == "Cash"
    assert saved.account_type == AccountType.ASSET
    assert saved.code == "1100"
    assert saved.currency == "EUR"
    assert saved.is_active is True


@pytest.mark.asyncio
async def test_list_accounts_returns_created_rows(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Account(
                code="1100",
                currency="EUR",
                name="Cash",
                account_type=AccountType.ASSET,
            ),
            Account(
                code="4000",
                currency="EUR",
                name="Revenue",
                account_type=AccountType.REVENUE,
            ),
        ]
    )
    await db_session.commit()

    result = await db_session.execute(select(Account).order_by(Account.name))
    rows = result.scalars().all()
    names = [row.name for row in rows]

    assert names == ["Cash", "Revenue"]


@pytest.mark.asyncio
async def test_duplicate_account_name_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        Account(
            code="9001",
            currency="EUR",
            name="Duplicate",
            account_type=AccountType.ASSET,
        )
    )
    await db_session.commit()

    db_session.add(
        Account(
            code="9002",
            currency="EUR",
            name="Duplicate",
            account_type=AccountType.EXPENSE,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_duplicate_account_code_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        Account(
            code="1100",
            currency="EUR",
            name="Account1",
            account_type=AccountType.ASSET,
        )
    )
    await db_session.commit()

    db_session.add(
        Account(
            code="1100",
            currency="EUR",
            name="Account2",
            account_type=AccountType.ASSET,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_list_accounts_returns_rows_ordered_by_code(
    async_client: AsyncClient,
) -> None:
    """GET /accounts must return rows ordered by code, not insertion order (TD-025)."""
    for code, name in [
        ("3000", "Acct-3000"),
        ("1000", "Acct-1000"),
        ("2000", "Acct-2000"),
    ]:
        resp = await async_client.post(
            "/api/v1/accounts",
            json={
                "code": code,
                "name": name,
                "account_type": "asset",
                "currency": "EUR",
            },
        )
        assert resp.status_code == 201

    response = await async_client.get("/api/v1/accounts")
    assert response.status_code == 200
    codes = [item["code"] for item in response.json()]

    assert codes == ["1000", "2000", "3000"]


@pytest.mark.asyncio
async def test_create_account_unknown_currency_returns_422(
    async_client: AsyncClient,
) -> None:
    """POST /accounts with a currency code not in currencies table returns 422."""
    resp = await async_client.post(
        "/api/v1/accounts",
        json={
            "code": "9999",
            "name": "InvalidCurrencyAccount",
            "account_type": "asset",
            "currency": "XYZ",
        },
    )
    assert resp.status_code == 422
    assert "XYZ" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_accounts_respects_limit_and_offset(
    async_client: AsyncClient,
) -> None:
    """GET /accounts with limit/offset returns the correct page."""
    for code, name in [
        ("1000", "Acct-A"),
        ("2000", "Acct-B"),
        ("3000", "Acct-C"),
    ]:
        resp = await async_client.post(
            "/api/v1/accounts",
            json={
                "code": code,
                "name": name,
                "account_type": "asset",
                "currency": "EUR",
            },
        )
        assert resp.status_code == 201

    # limit=2 → first 2 rows (ordered by code)
    resp = await async_client.get("/api/v1/accounts", params={"limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["code"] == "1000"
    assert data[1]["code"] == "2000"

    # offset=2 → skip first 2, get the third
    resp = await async_client.get("/api/v1/accounts", params={"limit": 10, "offset": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["code"] == "3000"
