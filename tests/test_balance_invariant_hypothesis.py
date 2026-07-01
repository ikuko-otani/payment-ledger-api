"""Property-based tests for the double-entry balance invariant using Hypothesis.

Uses Hypothesis to verify that create_transaction:
  - accepts any balanced entry set (debit_total == credit_total) → no error
  - rejects any unbalanced entry set (debit_total != credit_total) → ValidationError 422
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.exceptions import ValidationError
from app.models.account import Account, AccountType
from app.models.entry import Direction
from app.models.user import User, UserRole
from app.repositories.account_repository import SQLAlchemyAccountRepository
from app.repositories.audit_repository import SQLAlchemyAuditRepository
from app.repositories.currency_repository import SQLAlchemyCurrencyRepository
from app.repositories.transaction_repository import SQLAlchemyTransactionRepository
from app.schemas.transaction import EntryCreate, TransactionCreate
from app.services.transaction_service import _convert_amount_usd, create_transaction

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def _amounts_summing_to(draw: st.DrawFn, total: int, n: int) -> list[int]:
    """Generate n positive integers that sum to total.

    Requires total >= n so that [1, total-1] has room for n-1 unique cut points.
    """
    if n == 1:
        return [total]
    cuts = draw(
        st.lists(
            st.integers(min_value=1, max_value=total - 1),
            min_size=n - 1,
            max_size=n - 1,
            unique=True,
        )
    )
    boundaries = sorted([0] + cuts + [total])
    return [boundaries[i + 1] - boundaries[i] for i in range(n)]


@st.composite
def balanced_payload(
    draw: st.DrawFn,
    debit_id: uuid.UUID,
    credit_id: uuid.UUID,
) -> TransactionCreate:
    """Generate a TransactionCreate where debit_total == credit_total, across N entries."""
    n_debits = draw(st.integers(min_value=1, max_value=3))
    n_credits = draw(st.integers(min_value=1, max_value=3))
    # total must be at least n_debits + n_credits so each amount is >= 1
    total = draw(st.integers(min_value=n_debits + n_credits, max_value=100_000))
    debit_amounts = draw(_amounts_summing_to(total, n_debits))
    credit_amounts = draw(_amounts_summing_to(total, n_credits))

    debit_entries = [
        EntryCreate(
            account_id=debit_id,
            direction=Direction.DEBIT,
            amount=amount,
            currency="EUR",
        )
        for amount in debit_amounts
    ]
    credit_entries = [
        EntryCreate(
            account_id=credit_id,
            direction=Direction.CREDIT,
            amount=amount,
            currency="EUR",
        )
        for amount in credit_amounts
    ]
    return TransactionCreate(
        description="Hypothesis: balanced N entries",
        transaction_date=date(2024, 1, 1),
        entries=debit_entries + credit_entries,
    )


@st.composite
def unbalanced_payload(
    draw: st.DrawFn,
    debit_id: uuid.UUID,
    credit_id: uuid.UUID,
) -> TransactionCreate:
    """Generate a TransactionCreate where debit_total != credit_total, across N entries."""
    n_debits = draw(st.integers(min_value=1, max_value=3))
    n_credits = draw(st.integers(min_value=1, max_value=3))
    debit_total = draw(st.integers(min_value=n_debits, max_value=100_000))
    credit_total = draw(st.integers(min_value=n_credits, max_value=100_000))
    assume(debit_total != credit_total)
    debit_amounts = draw(_amounts_summing_to(debit_total, n_debits))
    credit_amounts = draw(_amounts_summing_to(credit_total, n_credits))

    debit_entries = [
        EntryCreate(
            account_id=debit_id,
            direction=Direction.DEBIT,
            amount=amount,
            currency="EUR",
        )
        for amount in debit_amounts
    ]
    credit_entries = [
        EntryCreate(
            account_id=credit_id,
            direction=Direction.CREDIT,
            amount=amount,
            currency="EUR",
        )
        for amount in credit_amounts
    ]
    return TransactionCreate(
        description="Hypothesis: unbalanced N entries",
        transaction_date=date(2024, 1, 1),
        entries=debit_entries + credit_entries,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_accounts(
    async_url: str,
) -> tuple[AsyncSession, AsyncEngine, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create a fresh engine + session and seed two EUR accounts + one user.

    Returns (session, engine, debit_id, credit_id, user_id).
    Caller must call ``await session.close(); await engine.dispose()`` when done.
    """
    engine = create_async_engine(async_url, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    session = session_factory()

    suffix = uuid.uuid4().hex[:8]
    debit = Account(
        name=f"HypD-{suffix}",
        account_type=AccountType.ASSET,
        code=f"HD{suffix}",
        currency="EUR",
    )
    credit = Account(
        name=f"HypC-{suffix}",
        account_type=AccountType.REVENUE,
        code=f"HC{suffix}",
        currency="EUR",
    )
    user = User(
        email=f"hyp-{suffix}@test.com",
        hashed_password="",
        role=UserRole.ADMIN,
    )
    session.add_all([debit, credit, user])
    await session.commit()
    await session.refresh(debit)
    await session.refresh(credit)
    await session.refresh(user)
    return session, engine, debit.id, credit.id, user.id


def _make_repos(
    session: AsyncSession,
) -> tuple[
    SQLAlchemyAccountRepository,
    SQLAlchemyCurrencyRepository,
    SQLAlchemyTransactionRepository,
    SQLAlchemyAuditRepository,
]:
    return (
        SQLAlchemyAccountRepository(session),
        SQLAlchemyCurrencyRepository(session),
        SQLAlchemyTransactionRepository(session),
        SQLAlchemyAuditRepository(session),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(data=st.data())
@pytest.mark.asyncio
async def test_balanced_entries_create_transaction_succeeds(
    migrated_database_urls: tuple[str, str],
    data: st.DataObject,
) -> None:
    """Any balanced entry set (debit_total == credit_total) must be accepted."""
    _, async_url = migrated_database_urls
    session, engine, debit_id, credit_id, user_id = await _seed_accounts(async_url)
    try:
        payload = data.draw(balanced_payload(debit_id, credit_id))
        account_repo, currency_repo, tx_repo, audit_repo = _make_repos(session)
        tx = await create_transaction(
            account_repo, currency_repo, tx_repo, audit_repo, payload, user_id=user_id
        )
        await session.commit()

        debit_sum = sum(e.amount for e in tx.entries if e.direction == Direction.DEBIT)
        credit_sum = sum(
            e.amount for e in tx.entries if e.direction == Direction.CREDIT
        )
        assert debit_sum == credit_sum
    finally:
        await session.close()
        await engine.dispose()


@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(data=st.data())
@pytest.mark.asyncio
async def test_unbalanced_entries_raise_422(
    migrated_database_urls: tuple[str, str],
    data: st.DataObject,
) -> None:
    """Any unbalanced entry set must raise ValidationError with status_code 422."""
    _, async_url = migrated_database_urls
    session, engine, debit_id, credit_id, user_id = await _seed_accounts(async_url)
    try:
        payload = data.draw(unbalanced_payload(debit_id, credit_id))
        account_repo, currency_repo, tx_repo, audit_repo = _make_repos(session)
        with pytest.raises(ValidationError) as exc_info:
            await create_transaction(
                account_repo,
                currency_repo,
                tx_repo,
                audit_repo,
                payload,
                user_id=user_id,
            )
        assert exc_info.value.status_code == 422
        assert "balanced" in str(exc_info.value.detail).lower()
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# FX Rounding Property Tests (pure-function, no DB)
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    amount=st.integers(min_value=0, max_value=1_000_000),
    rate=st.decimals(
        min_value="0.0001",
        max_value="100.0",
        places=6,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_convert_amount_usd_returns_non_negative_int(
    amount: int,
    rate: Decimal,
) -> None:
    """_convert_amount_usd always returns a non-negative int for valid inputs."""
    result = _convert_amount_usd(amount, rate)
    assert isinstance(result, int)
    assert result >= 0


@settings(max_examples=200, deadline=None)
@given(
    debit_amounts=st.lists(
        st.integers(min_value=1, max_value=10_000),
        min_size=2,
        max_size=5,
    ),
    rate=st.decimals(
        min_value="0.0001",
        max_value="10.0",
        places=6,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_fx_rounding_error_bounded_by_entry_count(
    debit_amounts: list[int],
    rate: Decimal,
) -> None:
    """Per-entry ROUND_HALF_UP may cause USD imbalance; error is bounded by entry count.

    When N debit amounts sum to the same total as one credit entry (balanced in EUR),
    converting each debit individually can produce a different USD sum than converting
    the aggregate credit. This documents the known per-entry rounding design and asserts
    the error stays within N (one rounding unit per entry).
    """
    credit_total = sum(debit_amounts)
    converted_debit_sum = sum(_convert_amount_usd(a, rate) for a in debit_amounts)
    converted_credit = _convert_amount_usd(credit_total, rate)
    assert abs(converted_debit_sum - converted_credit) <= len(debit_amounts)
