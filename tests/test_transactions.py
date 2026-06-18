"""Service/schema integration tests for Transactions."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.exceptions import ValidationError
from app.models.account import Account, AccountType
from app.models.currency import Currency
from app.models.entry import Direction
from app.models.exchange_rate import ExchangeRate
from app.models.transaction import Transaction
from app.models.user import User, UserRole
from app.repositories.account_repository import SQLAlchemyAccountRepository
from app.repositories.audit_repository import SQLAlchemyAuditRepository
from app.repositories.currency_repository import SQLAlchemyCurrencyRepository
from app.repositories.transaction_repository import SQLAlchemyTransactionRepository
from app.schemas.transaction import EntryCreate, TransactionCreate
from app.services.transaction_service import create_transaction


async def _create_account(
    db_session: AsyncSession,
    name: str,
    account_type: AccountType,
    code: str,
    currency: str = "EUR",
) -> Account:
    account = Account(
        name=name,
        account_type=account_type,
        code=code,
        currency=currency,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


def _make_repos(db_session: AsyncSession):
    return (
        SQLAlchemyAccountRepository(db_session),
        SQLAlchemyCurrencyRepository(db_session),
        SQLAlchemyTransactionRepository(db_session),
        SQLAlchemyAuditRepository(db_session),
    )


@pytest.mark.asyncio
async def test_create_balanced_transaction_persists_rows(
    db_session: AsyncSession,
) -> None:
    debit = await _create_account(db_session, "Cash", AccountType.ASSET, code="1100")
    credit = await _create_account(
        db_session, "Revenue", AccountType.REVENUE, code="4000"
    )

    test_user_id = uuid.uuid4()
    db_session.add(
        User(
            id=test_user_id,
            email="tx-test@example.com",
            hashed_password="",
            role=UserRole.ADMIN,
        )
    )
    await db_session.commit()

    payload = TransactionCreate(
        description="Balanced",
        transaction_date=date(2024, 1, 1),
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
        account_repo, currency_repo, tx_repo, audit_repo, payload, user_id=test_user_id
    )
    await db_session.commit()

    result = await db_session.execute(
        select(Transaction).where(Transaction.id == tx.id)
    )
    saved = result.scalar_one()

    assert saved.description == "Balanced"
    from app.models.transaction import TransactionStatus

    assert saved.status == TransactionStatus.POSTED


@pytest.mark.asyncio
async def test_unbalanced_transaction_raises_http_422(
    db_session: AsyncSession,
) -> None:
    debit = await _create_account(
        db_session, "Cash-Unbal", AccountType.ASSET, code="1101"
    )
    credit = await _create_account(
        db_session, "Revenue-Unbal", AccountType.REVENUE, code="4001"
    )

    payload = TransactionCreate(
        description="Unbalanced",
        transaction_date=date(2024, 1, 1),
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
                amount=500,
                currency="EUR",
            ),
        ],
    )

    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    with pytest.raises(ValidationError) as exc_info:
        await create_transaction(
            account_repo,
            currency_repo,
            tx_repo,
            audit_repo,
            payload,
            user_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 422
    assert "balanced" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_transaction_create_requires_at_least_two_entries() -> None:
    with pytest.raises(ValueError):
        TransactionCreate(
            description="Single entry",
            transaction_date=date(2024, 1, 1),
            entries=[
                EntryCreate(
                    account_id="11111111-1111-1111-1111-111111111111",
                    direction=Direction.DEBIT,
                    amount=500,
                    currency="EUR",
                )
            ],
        )


@pytest.mark.asyncio
async def test_transaction_response_shape_like_domain_object(
    db_session: AsyncSession,
) -> None:
    debit = await _create_account(
        db_session, "Cash-Resp", AccountType.ASSET, code="1102"
    )
    credit = await _create_account(
        db_session, "Revenue-Resp", AccountType.REVENUE, code="4002"
    )

    payload = TransactionCreate(
        description="Response shape",
        transaction_date=date(2024, 1, 1),
        entries=[
            EntryCreate(
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=700,
                currency="EUR",
            ),
            EntryCreate(
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=700,
                currency="EUR",
            ),
        ],
    )

    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    tx = await create_transaction(
        account_repo, currency_repo, tx_repo, audit_repo, payload, user_id=uuid.uuid4()
    )

    assert len(tx.entries) == 2
    entry_directions = {entry.direction for entry in tx.entries}
    assert entry_directions == {Direction.DEBIT, Direction.CREDIT}


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entry_amount_zero_raises_validation_error() -> None:
    with pytest.raises(ValueError):
        EntryCreate(
            account_id="11111111-1111-1111-1111-111111111111",
            direction=Direction.DEBIT,
            amount=0,
            currency="EUR",
        )


@pytest.mark.asyncio
async def test_entry_amount_negative_raises_validation_error() -> None:
    with pytest.raises(ValueError):
        EntryCreate(
            account_id="11111111-1111-1111-1111-111111111111",
            direction=Direction.DEBIT,
            amount=-100,
            currency="EUR",
        )


@pytest.mark.asyncio
async def test_description_blank_raises_validation_error() -> None:
    with pytest.raises(ValueError):
        TransactionCreate(
            description="   ",
            transaction_date=date(2024, 1, 1),
            entries=[
                EntryCreate(
                    account_id="11111111-1111-1111-1111-111111111111",
                    direction=Direction.DEBIT,
                    amount=100,
                    currency="EUR",
                ),
                EntryCreate(
                    account_id="22222222-2222-2222-2222-222222222222",
                    direction=Direction.CREDIT,
                    amount=100,
                    currency="EUR",
                ),
            ],
        )


@pytest.mark.asyncio
async def test_unknown_account_id_raises_http_422(
    db_session: AsyncSession,
) -> None:
    payload = TransactionCreate(
        description="Ghost account",
        transaction_date=date(2024, 1, 1),
        entries=[
            EntryCreate(
                account_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                direction=Direction.DEBIT,
                amount=500,
                currency="EUR",
            ),
            EntryCreate(
                account_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                direction=Direction.CREDIT,
                amount=500,
                currency="EUR",
            ),
        ],
    )

    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    with pytest.raises(ValidationError) as exc_info:
        await create_transaction(
            account_repo,
            currency_repo,
            tx_repo,
            audit_repo,
            payload,
            user_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_all_debit_entries_raises_http_422(
    db_session: AsyncSession,
) -> None:
    debit = await _create_account(
        db_session, "Cash-AD1", AccountType.ASSET, code="1110"
    )
    debit2 = await _create_account(
        db_session, "Cash-AD2", AccountType.ASSET, code="1111"
    )

    payload = TransactionCreate(
        description="All debit",
        transaction_date=date(2024, 1, 1),
        entries=[
            EntryCreate(
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=500,
                currency="EUR",
            ),
            EntryCreate(
                account_id=debit2.id,
                direction=Direction.DEBIT,
                amount=500,
                currency="EUR",
            ),
        ],
    )

    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    with pytest.raises(ValidationError) as exc_info:
        await create_transaction(
            account_repo,
            currency_repo,
            tx_repo,
            audit_repo,
            payload,
            user_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 422
    assert "debit" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_all_credit_entries_raises_http_422(
    db_session: AsyncSession,
) -> None:
    credit = await _create_account(
        db_session, "Revenue-AC1", AccountType.REVENUE, code="4010"
    )
    credit2 = await _create_account(
        db_session, "Revenue-AC2", AccountType.REVENUE, code="4011"
    )

    payload = TransactionCreate(
        description="All credit",
        transaction_date=date(2024, 1, 1),
        entries=[
            EntryCreate(
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=500,
                currency="EUR",
            ),
            EntryCreate(
                account_id=credit2.id,
                direction=Direction.CREDIT,
                amount=500,
                currency="EUR",
            ),
        ],
    )

    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    with pytest.raises(ValidationError) as exc_info:
        await create_transaction(
            account_repo,
            currency_repo,
            tx_repo,
            audit_repo,
            payload,
            user_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 422
    assert "credit" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_inactive_account_raises_http_422(
    db_session: AsyncSession,
) -> None:
    debit = await _create_account(
        db_session, "Cash-Inactive", AccountType.ASSET, code="1130"
    )
    credit = await _create_account(
        db_session, "Revenue-Inactive", AccountType.REVENUE, code="4030"
    )

    debit.is_active = False
    db_session.add(debit)
    await db_session.commit()

    payload = TransactionCreate(
        description="Post to inactive account",
        transaction_date=date(2024, 1, 1),
        entries=[
            EntryCreate(
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=500,
                currency="EUR",
            ),
            EntryCreate(
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=500,
                currency="EUR",
            ),
        ],
    )

    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    with pytest.raises(ValidationError) as exc_info:
        await create_transaction(
            account_repo,
            currency_repo,
            tx_repo,
            audit_repo,
            payload,
            user_id=uuid.uuid4(),
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_mixed_currency_entries_raises_http_422(
    db_session: AsyncSession,
) -> None:
    debit = await _create_account(
        db_session, "Cash-EUR", AccountType.ASSET, code="1120"
    )
    credit = await _create_account(
        db_session, "Revenue-USD", AccountType.REVENUE, code="4020"
    )

    payload = TransactionCreate(
        description="Mixed currency",
        transaction_date=date(2024, 1, 1),
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
                currency="USD",
            ),
        ],
    )

    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    with pytest.raises(ValidationError) as exc_info:
        await create_transaction(
            account_repo,
            currency_repo,
            tx_repo,
            audit_repo,
            payload,
            user_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 422
    assert "currency" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_entry_currency_mismatched_with_account_returns_422(
    db_session: AsyncSession,
) -> None:
    debit = await _create_account(
        db_session, "Cash-EUR-Acct", AccountType.ASSET, code="1140", currency="EUR"
    )
    credit = await _create_account(
        db_session, "Revenue-EUR-Acct", AccountType.REVENUE, code="4040", currency="EUR"
    )

    payload = TransactionCreate(
        description="Currency mismatch",
        transaction_date=date(2024, 1, 1),
        entries=[
            EntryCreate(
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=1000,
                currency="USD",
            ),
            EntryCreate(
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=1000,
                currency="USD",
            ),
        ],
    )

    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    with pytest.raises(ValidationError) as exc_info:
        await create_transaction(
            account_repo,
            currency_repo,
            tx_repo,
            audit_repo,
            payload,
            user_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 422
    assert "currency" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_non_usd_transaction_resolves_conversion_rate_once(
    db_session: AsyncSession,
    engine: AsyncEngine,
) -> None:
    eur = Currency(code="EUR", name="Euro", decimal_places=2)
    usd = Currency(code="USD", name="US Dollar", decimal_places=2)
    db_session.add_all([eur, usd])
    await db_session.flush()

    test_user_id = uuid.uuid4()
    db_session.add(
        User(
            id=test_user_id,
            email="td030-test@example.com",
            hashed_password="",
            role=UserRole.ADMIN,
        )
    )
    await db_session.flush()

    db_session.add(
        ExchangeRate(
            from_currency_id=eur.id,
            to_currency_id=usd.id,
            rate=Decimal("1.10"),
            effective_date=date(2024, 1, 1),
            created_by_id=test_user_id,
        )
    )
    await db_session.commit()

    debit = await _create_account(
        db_session, "Cash-EUR-N1", AccountType.ASSET, code="1150"
    )
    credit = await _create_account(
        db_session, "Revenue-EUR-N1", AccountType.REVENUE, code="4050"
    )

    payload = TransactionCreate(
        currency_code="EUR",
        description="N+1 check",
        transaction_date=date(2024, 1, 1),
        entries=[
            EntryCreate(
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=500,
                currency="EUR",
            ),
            EntryCreate(
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=500,
                currency="EUR",
            ),
            EntryCreate(
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=500,
                currency="EUR",
            ),
            EntryCreate(
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=500,
                currency="EUR",
            ),
        ],
    )

    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    event.listen(engine.sync_engine, "before_cursor_execute", _capture)
    try:
        tx = await create_transaction(
            account_repo,
            currency_repo,
            tx_repo,
            audit_repo,
            payload,
            user_id=test_user_id,
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)

    conversion_queries = [
        s
        for s in statements
        if "currencies" in s.lower() or "exchange_rates" in s.lower()
    ]
    assert len(conversion_queries) <= 3

    assert all(e.converted_amount_usd == 550 for e in tx.entries)
