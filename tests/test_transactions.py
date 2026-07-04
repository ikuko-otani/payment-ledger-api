"""Service/schema integration tests for Transactions."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import ConflictError, ValidationError
from app.models.account import Account, AccountType
from app.models.currency import Currency
from app.models.entry import Direction, Entry
from app.models.exchange_rate import ExchangeRate
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User, UserRole
from app.repositories.account_repository import SQLAlchemyAccountRepository
from app.repositories.audit_repository import SQLAlchemyAuditRepository
from app.repositories.currency_repository import SQLAlchemyCurrencyRepository
from app.repositories.transaction_repository import SQLAlchemyTransactionRepository
from app.schemas.transaction import EntryCreate, TransactionCreate
from app.services.transaction_service import create_transaction, void_transaction


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
    result = await db_session.execute(
        select(Currency).where(Currency.code.in_(["EUR", "USD"]))
    )
    currencies = {c.code: c for c in result.scalars().all()}
    eur = currencies["EUR"]
    usd = currencies["USD"]

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


@pytest.mark.asyncio
async def test_weekend_date_uses_most_recent_exchange_rate(
    db_session: AsyncSession,
) -> None:
    """TD-039: transaction on Saturday uses Friday's exchange rate."""
    result = await db_session.execute(
        select(Currency).where(Currency.code.in_(["EUR", "USD"]))
    )
    currencies = {c.code: c for c in result.scalars().all()}
    eur = currencies["EUR"]
    usd = currencies["USD"]

    test_user_id = uuid.uuid4()
    db_session.add(
        User(
            id=test_user_id,
            email="fx-weekend@example.com",
            hashed_password="",
            role=UserRole.ADMIN,
        )
    )
    await db_session.flush()

    # Register rate on Friday 2026-07-03
    db_session.add(
        ExchangeRate(
            from_currency_id=eur.id,
            to_currency_id=usd.id,
            rate=Decimal("1.08"),
            effective_date=date(2026, 7, 3),
            created_by_id=test_user_id,
        )
    )
    await db_session.commit()

    debit = await _create_account(
        db_session, "Cash-FX-WE", AccountType.ASSET, code="1160"
    )
    credit = await _create_account(
        db_session, "Revenue-FX-WE", AccountType.REVENUE, code="4060"
    )

    # Transaction on Saturday 2026-07-04 — should fall back to Friday's rate
    payload = TransactionCreate(
        currency_code="EUR",
        description="Weekend fallback",
        transaction_date=date(2026, 7, 4),
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

    # 1000 EUR * 1.08 = 1080 USD cents
    assert all(e.converted_amount_usd == 1080 for e in tx.entries)


@pytest.mark.asyncio
async def test_no_exchange_rate_on_or_before_date_returns_422(
    db_session: AsyncSession,
) -> None:
    """TD-039: transaction before any available rate returns 422."""
    result = await db_session.execute(
        select(Currency).where(Currency.code.in_(["EUR", "USD"]))
    )
    currencies = {c.code: c for c in result.scalars().all()}
    eur = currencies["EUR"]
    usd = currencies["USD"]

    test_user_id = uuid.uuid4()
    db_session.add(
        User(
            id=test_user_id,
            email="fx-norate@example.com",
            hashed_password="",
            role=UserRole.ADMIN,
        )
    )
    await db_session.flush()

    # Register rate on 2026-07-03
    db_session.add(
        ExchangeRate(
            from_currency_id=eur.id,
            to_currency_id=usd.id,
            rate=Decimal("1.08"),
            effective_date=date(2026, 7, 3),
            created_by_id=test_user_id,
        )
    )
    await db_session.commit()

    debit = await _create_account(
        db_session, "Cash-FX-NR", AccountType.ASSET, code="1170"
    )
    credit = await _create_account(
        db_session, "Revenue-FX-NR", AccountType.REVENUE, code="4070"
    )

    # Transaction on 2026-07-01 — before any rate exists → 422
    payload = TransactionCreate(
        currency_code="EUR",
        description="No rate before date",
        transaction_date=date(2026, 7, 1),
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
    with pytest.raises(ValidationError) as exc_info:
        await create_transaction(
            account_repo,
            currency_repo,
            tx_repo,
            audit_repo,
            payload,
            user_id=test_user_id,
        )

    assert exc_info.value.status_code == 422
    assert "on or before" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_db_trigger_rejects_unbalanced_entries_on_commit(
    db_session: AsyncSession,
) -> None:
    """Defense-in-depth: DB constraint trigger rejects unbalanced entries
    even when the application-layer validation is bypassed (e.g. direct SQL).
    """
    from sqlalchemy.exc import IntegrityError

    debit_acct = await _create_account(
        db_session, "Cash-Trigger", AccountType.ASSET, code="1200"
    )
    credit_acct = await _create_account(
        db_session, "Revenue-Trigger", AccountType.REVENUE, code="4200"
    )

    # Build a transaction header directly (bypass service layer)
    tx = Transaction(
        description="Trigger test — unbalanced",
        transaction_date=date(2024, 1, 1),
        status=TransactionStatus.POSTED,
    )
    db_session.add(tx)
    await db_session.flush()

    # Insert unbalanced entries: debit=1000, credit=500
    db_session.add(
        Entry(
            transaction_id=tx.id,
            account_id=debit_acct.id,
            direction=Direction.DEBIT,
            amount=1000,
            currency="EUR",
            converted_amount_usd=1000,
        )
    )
    db_session.add(
        Entry(
            transaction_id=tx.id,
            account_id=credit_acct.id,
            direction=Direction.CREDIT,
            amount=500,
            currency="EUR",
            converted_amount_usd=500,
        )
    )
    await db_session.flush()

    # The deferred trigger fires at COMMIT — should raise
    with pytest.raises(IntegrityError, match="not balanced"):
        await db_session.commit()


async def _create_posted_transaction(
    db_session: AsyncSession,
    debit_code: str,
    credit_code: str,
    amount: int = 1000,
) -> tuple[Transaction, uuid.UUID]:
    """Helper: create a user, two accounts, and a posted balanced transaction.

    Returns (transaction, user_id). user_id is persisted in users table so
    it satisfies the audit_logs.user_id FK on commit.
    """
    user_id = uuid.uuid4()
    db_session.add(
        User(
            id=user_id,
            email=f"void-test-{debit_code}@example.com",
            hashed_password="",
            role=UserRole.ADMIN,
        )
    )
    await db_session.flush()

    debit = await _create_account(
        db_session, f"Cash-{debit_code}", AccountType.ASSET, code=debit_code
    )
    credit = await _create_account(
        db_session, f"Revenue-{credit_code}", AccountType.REVENUE, code=credit_code
    )
    payload = TransactionCreate(
        description="Original transaction",
        transaction_date=date(2024, 6, 1),
        entries=[
            EntryCreate(
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=amount,
                currency="EUR",
            ),
            EntryCreate(
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=amount,
                currency="EUR",
            ),
        ],
    )
    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    tx = await create_transaction(
        account_repo, currency_repo, tx_repo, audit_repo, payload, user_id=user_id
    )
    await db_session.commit()
    return tx, user_id


@pytest.mark.asyncio
async def test_void_posted_transaction_marks_original_voided(
    db_session: AsyncSession,
) -> None:
    tx, user_id = await _create_posted_transaction(db_session, "2000", "5000")
    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    voided, reversal = await void_transaction(tx_repo, audit_repo, tx.id, user_id)
    await db_session.commit()

    assert voided.status == TransactionStatus.VOIDED
    assert reversal.status == TransactionStatus.POSTED
    assert reversal.metadata_ == {"reversal_of": str(tx.id)}


@pytest.mark.asyncio
async def test_void_already_voided_raises_409(
    db_session: AsyncSession,
) -> None:
    tx, user_id = await _create_posted_transaction(db_session, "2001", "5001")
    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    await void_transaction(tx_repo, audit_repo, tx.id, user_id)
    await db_session.commit()

    with pytest.raises(ConflictError) as exc_info:
        await void_transaction(tx_repo, audit_repo, tx.id, user_id)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_void_reversal_entries_are_balanced_and_directions_inverted(
    db_session: AsyncSession,
) -> None:
    tx, user_id = await _create_posted_transaction(
        db_session, "2002", "5002", amount=3000
    )
    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    _, reversal = await void_transaction(tx_repo, audit_repo, tx.id, user_id)
    await db_session.commit()

    reversal_debits = sum(
        e.amount for e in reversal.entries if e.direction == Direction.DEBIT
    )
    reversal_credits = sum(
        e.amount for e in reversal.entries if e.direction == Direction.CREDIT
    )
    assert reversal_debits == reversal_credits == 3000


@pytest.mark.asyncio
async def test_void_writes_two_audit_logs_for_original_and_reversal(
    db_session: AsyncSession,
) -> None:
    from app.models.audit_log import AuditLog

    tx, user_id = await _create_posted_transaction(db_session, "2003", "5003")
    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    voided, reversal = await void_transaction(tx_repo, audit_repo, tx.id, user_id)
    await db_session.commit()

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_id.in_([voided.id, reversal.id]))
    )
    logs = {(row.entity_id, row.action): row for row in result.scalars().all()}

    # void log on original — lets auditors trace who voided and when
    void_log = logs.get((voided.id, "void"))
    assert void_log is not None
    assert void_log.before_value["status"] == "posted"
    assert void_log.after_value["status"] == "voided"
    assert void_log.after_value["reversal_transaction_id"] == str(reversal.id)

    # create log on reversal — lets auditors locate reversal by its own entity_id
    create_log = logs.get((reversal.id, "create"))
    assert create_log is not None
    assert create_log.before_value is None
    assert create_log.after_value["reversal_of"] == str(voided.id)


@pytest.mark.asyncio
async def test_void_reversal_amounts_mirror_original(
    db_session: AsyncSession,
) -> None:
    """Reversal entry amounts are copied from the original, with directions swapped.

    original DEBIT total  == reversal CREDIT total
    original CREDIT total == reversal DEBIT total
    """
    tx, user_id = await _create_posted_transaction(
        db_session, "2004", "5004", amount=7500
    )
    account_repo, currency_repo, tx_repo, audit_repo = _make_repos(db_session)
    voided, reversal = await void_transaction(tx_repo, audit_repo, tx.id, user_id)
    await db_session.commit()

    original_debit_total = sum(
        e.amount for e in voided.entries if e.direction == Direction.DEBIT
    )
    original_credit_total = sum(
        e.amount for e in voided.entries if e.direction == Direction.CREDIT
    )
    reversal_debit_total = sum(
        e.amount for e in reversal.entries if e.direction == Direction.DEBIT
    )
    reversal_credit_total = sum(
        e.amount for e in reversal.entries if e.direction == Direction.CREDIT
    )

    assert original_debit_total == reversal_credit_total
    assert original_credit_total == reversal_debit_total


@pytest.mark.asyncio
async def test_concurrent_void_returns_single_conflict(
    engine: AsyncEngine,
) -> None:
    """Two concurrent void requests for the same transaction must resolve to
    exactly one success and one 409 — not two reversals.

    Regression guard for the check-then-write race described in ADR-002's
    "Where row-level protection IS used" note: without the CAS-based
    mark_voided_if_posted, both requests could read status == POSTED before
    either commits, producing two reversal transactions and a net balance
    of -original instead of 0.
    """
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as setup_session:
        tx, user_id = await _create_posted_transaction(setup_session, "9000", "9001")
        transaction_id = tx.id

    async def _attempt() -> tuple[Transaction, Transaction] | ConflictError:
        async with session_factory() as session:
            tx_repo = SQLAlchemyTransactionRepository(session)
            audit_repo = SQLAlchemyAuditRepository(session)
            try:
                result = await void_transaction(
                    tx_repo, audit_repo, transaction_id, user_id
                )
                await session.commit()
                assert result is not None
                return result
            except ConflictError as e:
                await session.rollback()
                return e

    results = await asyncio.gather(_attempt(), _attempt())

    successes = [r for r in results if not isinstance(r, ConflictError)]
    conflicts = [r for r in results if isinstance(r, ConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1

    async with session_factory() as check_session:
        result = await check_session.execute(select(Transaction))
        reversals = [
            t
            for t in result.scalars().all()
            if t.metadata_ == {"reversal_of": str(transaction_id)}
        ]
        assert len(reversals) == 1
