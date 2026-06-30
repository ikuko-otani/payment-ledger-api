"""Property-based tests for the double-entry balance invariant using Hypothesis.

Uses Hypothesis to verify that create_transaction:
  - accepts any balanced entry set (debit_total == credit_total) → no error
  - rejects any unbalanced entry set (debit_total != credit_total) → ValidationError 422
"""

from __future__ import annotations

import uuid
from datetime import date

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
from app.services.transaction_service import create_transaction

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def balanced_payload(
    draw: st.DrawFn,
    debit_id: uuid.UUID,
    credit_id: uuid.UUID,
) -> TransactionCreate:
    """Generate a TransactionCreate where debit_total == credit_total."""
    total = draw(st.integers(min_value=1, max_value=100_000))
    return TransactionCreate(
        description="Hypothesis: balanced",
        transaction_date=date(2024, 1, 1),
        entries=[
            EntryCreate(
                account_id=debit_id,
                direction=Direction.DEBIT,
                amount=total,
                currency="EUR",
            ),
            EntryCreate(
                account_id=credit_id,
                direction=Direction.CREDIT,
                amount=total,
                currency="EUR",
            ),
        ],
    )


@st.composite
def unbalanced_payload(
    draw: st.DrawFn,
    debit_id: uuid.UUID,
    credit_id: uuid.UUID,
) -> TransactionCreate:
    """Generate a TransactionCreate where debit_total != credit_total."""
    debit_amount = draw(st.integers(min_value=1, max_value=100_000))
    credit_amount = draw(st.integers(min_value=1, max_value=100_000))
    assume(debit_amount != credit_amount)
    return TransactionCreate(
        description="Hypothesis: unbalanced",
        transaction_date=date(2024, 1, 1),
        entries=[
            EntryCreate(
                account_id=debit_id,
                direction=Direction.DEBIT,
                amount=debit_amount,
                currency="EUR",
            ),
            EntryCreate(
                account_id=credit_id,
                direction=Direction.CREDIT,
                amount=credit_amount,
                currency="EUR",
            ),
        ],
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
