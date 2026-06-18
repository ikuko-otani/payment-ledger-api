"""Integration tests: multi-currency transactions and pagination boundary."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType
from app.models.currency import Currency
from app.models.entry import Direction
from app.models.exchange_rate import ExchangeRate
from app.models.user import User, UserRole
from app.repositories.account_repository import SQLAlchemyAccountRepository
from app.repositories.audit_repository import SQLAlchemyAuditRepository
from app.repositories.currency_repository import SQLAlchemyCurrencyRepository
from app.repositories.transaction_repository import SQLAlchemyTransactionRepository
from app.schemas.transaction import EntryCreate, TransactionCreate
from app.services.transaction_service import create_transaction


async def _seed_currency(
    db: AsyncSession, code: str, name: str, decimal_places: int
) -> Currency:
    c = Currency(code=code, name=name, decimal_places=decimal_places)
    db.add(c)
    await db.flush()
    return c


async def _seed_user(db: AsyncSession, email: str) -> User:
    user = User(id=uuid.uuid4(), email=email, hashed_password="", role=UserRole.ADMIN)
    db.add(user)
    await db.flush()
    return user


async def _seed_exchange_rate(
    db: AsyncSession,
    from_id: uuid.UUID,
    to_id: uuid.UUID,
    rate: Decimal,
    tx_date: date,
    created_by_id: uuid.UUID,
) -> ExchangeRate:
    er = ExchangeRate(
        from_currency_id=from_id,
        to_currency_id=to_id,
        rate=rate,
        effective_date=tx_date,
        created_by_id=created_by_id,
    )
    db.add(er)
    await db.flush()
    return er


async def _seed_account(
    db: AsyncSession,
    name: str,
    account_type: AccountType,
    code: str,
    currency: str,
) -> Account:
    account = Account(
        name=name, account_type=account_type, code=code, currency=currency
    )
    db.add(account)
    await db.flush()
    return account


def _make_repos(db_session: AsyncSession):
    return (
        SQLAlchemyAccountRepository(db_session),
        SQLAlchemyCurrencyRepository(db_session),
        SQLAlchemyTransactionRepository(db_session),
        SQLAlchemyAuditRepository(db_session),
    )


@pytest.mark.asyncio
async def test_eur_transaction_sets_converted_amount_usd(
    db_session: AsyncSession,
) -> None:
    eur = await _seed_currency(db_session, "EUR", "Euro", 2)
    usd = await _seed_currency(db_session, "USD", "US Dollar", 2)
    user = await _seed_user(db_session, "eur-conv@example.com")
    await _seed_exchange_rate(
        db_session,
        from_id=eur.id,
        to_id=usd.id,
        rate=Decimal("1.10"),
        tx_date=date(2024, 6, 1),
        created_by_id=user.id,
    )
    debit = await _seed_account(
        db_session, "Cash EUR-A", AccountType.ASSET, "MC-1100", "EUR"
    )
    credit = await _seed_account(
        db_session, "Revenue EUR-A", AccountType.REVENUE, "MC-4000", "EUR"
    )
    await db_session.commit()

    payload = TransactionCreate(
        currency_code="EUR",
        description="EUR sale",
        transaction_date=date(2024, 6, 1),
        entries=[
            EntryCreate(
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=1000,
                currency="EUR",
            ),
            EntryCreate(
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=1000,
                currency="EUR",
            ),
        ],
    )

    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    tx = await create_transaction(
        account_repo, currency_repo, tx_repo, audit_repo, payload, user_id=user.id
    )

    assert all(e.converted_amount_usd == 1100 for e in tx.entries)


@pytest.mark.asyncio
async def test_jpy_transaction_converted_amount_usd_rounded_half_up(
    db_session: AsyncSession,
) -> None:
    jpy = await _seed_currency(db_session, "JPY", "Japanese Yen", 0)
    usd = await _seed_currency(db_session, "USD", "US Dollar", 2)
    user = await _seed_user(db_session, "jpy-conv@example.com")
    await _seed_exchange_rate(
        db_session,
        from_id=jpy.id,
        to_id=usd.id,
        rate=Decimal("0.5"),
        tx_date=date(2024, 6, 1),
        created_by_id=user.id,
    )
    debit = await _seed_account(
        db_session, "Cash JPY-A", AccountType.ASSET, "MC-1101", "JPY"
    )
    credit = await _seed_account(
        db_session, "Revenue JPY-A", AccountType.REVENUE, "MC-4001", "JPY"
    )
    await db_session.commit()

    payload = TransactionCreate(
        currency_code="JPY",
        description="JPY sale",
        transaction_date=date(2024, 6, 1),
        entries=[
            EntryCreate(
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=5,
                currency="JPY",
            ),
            EntryCreate(
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=5,
                currency="JPY",
            ),
        ],
    )

    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    tx = await create_transaction(
        account_repo, currency_repo, tx_repo, audit_repo, payload, user_id=user.id
    )

    assert all(e.converted_amount_usd == 3 for e in tx.entries)


@pytest.mark.asyncio
async def test_list_transactions_pagination_no_duplicates_across_pages(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    debit = await _seed_account(
        db_session, "Cash Pag", AccountType.ASSET, "PAG-1100", "EUR"
    )
    credit = await _seed_account(
        db_session, "Revenue Pag", AccountType.REVENUE, "PAG-4000", "EUR"
    )
    await db_session.commit()

    entries = [
        {
            "account_id": str(debit.id),
            "direction": "debit",
            "amount": 10,
            "currency": "EUR",
        },
        {
            "account_id": str(credit.id),
            "direction": "credit",
            "amount": 10,
            "currency": "EUR",
        },
    ]
    for tx_date, description in [
        ("2024-06-02", "pag-middle"),
        ("2024-06-04", "pag-newest"),
        ("2024-06-01", "pag-oldest"),
        ("2024-06-03", "pag-second"),
    ]:
        r = await async_client.post(
            "/api/v1/transactions",
            json={
                "transaction_date": tx_date,
                "description": description,
                "entries": entries,
            },
        )
        assert r.status_code == 201

    page_size = 3
    p1 = await async_client.get(
        "/api/v1/transactions", params={"limit": page_size, "offset": 0}
    )
    p2 = await async_client.get(
        "/api/v1/transactions", params={"limit": page_size, "offset": page_size}
    )

    assert p1.status_code == 200
    assert p2.status_code == 200

    ids_p1 = {item["id"] for item in p1.json()}
    ids_p2 = {item["id"] for item in p2.json()}
    assert len(ids_p1) == page_size
    assert len(ids_p2) == 1
    assert ids_p1.isdisjoint(ids_p2), f"Duplicate IDs across pages: {ids_p1 & ids_p2}"

    dates_p1 = [item["transaction_date"] for item in p1.json()]
    assert dates_p1 == ["2024-06-04", "2024-06-03", "2024-06-02"]


@pytest.mark.asyncio
async def test_list_transactions_offset_beyond_total_returns_empty(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    debit = await _seed_account(
        db_session, "Cash Empty", AccountType.ASSET, "EMP-1100", "EUR"
    )
    credit = await _seed_account(
        db_session, "Revenue Empty", AccountType.REVENUE, "EMP-4000", "EUR"
    )
    await db_session.commit()

    base: dict = {
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": str(debit.id),
                "direction": "debit",
                "amount": 10,
                "currency": "EUR",
            },
            {
                "account_id": str(credit.id),
                "direction": "credit",
                "amount": 10,
                "currency": "EUR",
            },
        ],
    }
    for i in range(2):
        await async_client.post(
            "/api/v1/transactions", json={**base, "description": f"empty-{i}"}
        )

    response = await async_client.get(
        "/api/v1/transactions", params={"limit": 20, "offset": 100}
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_currencies_list_returns_stable_ascending_order(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    for code, name, dp in [
        ("USD", "US Dollar", 2),
        ("JPY", "Japanese Yen", 0),
        ("EUR", "Euro", 2),
    ]:
        db_session.add(Currency(code=code, name=name, decimal_places=dp))
    await db_session.commit()

    response = await async_client.get("/api/v1/currencies")

    assert response.status_code == 200
    codes = [c["code"] for c in response.json()]
    assert codes == sorted(codes), f"Expected ascending code order, got {codes}"
