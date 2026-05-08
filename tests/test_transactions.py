"""Service/schema integration tests for Transactions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType
from app.models.entry import EntryType
from app.models.transaction import Transaction
from app.schemas.transaction import EntryCreate, TransactionCreate
from app.services.transaction_service import create_transaction


async def _create_account(
    db_session: AsyncSession,
    name: str,
    account_type: AccountType,
) -> Account:
    account = Account(name=name, account_type=account_type)
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest.mark.asyncio
async def test_create_balanced_transaction_persists_rows(
    db_session: AsyncSession,
) -> None:
    debit = await _create_account(db_session, "Cash", AccountType.ASSET)
    credit = await _create_account(db_session, "Revenue", AccountType.REVENUE)

    payload = TransactionCreate(
        description="Balanced",
        transaction_date=date(2024, 1, 1),
        amount=Decimal("1000.00"),
        entries=[
            EntryCreate(
                account_id=debit.id,
                entry_type=EntryType.DEBIT,
                amount=Decimal("1000.00"),
            ),
            EntryCreate(
                account_id=credit.id,
                entry_type=EntryType.CREDIT,
                amount=Decimal("1000.00"),
            ),
        ],
    )

    tx = await create_transaction(db_session, payload)
    await db_session.commit()

    result = await db_session.execute(
        select(Transaction).where(Transaction.id == tx.id)
    )
    saved = result.scalar_one()

    assert saved.description == "Balanced"


@pytest.mark.asyncio
async def test_unbalanced_transaction_raises_http_422(
    db_session: AsyncSession,
) -> None:
    debit = await _create_account(db_session, "Cash-Unbal", AccountType.ASSET)
    credit = await _create_account(db_session, "Revenue-Unbal", AccountType.REVENUE)

    payload = TransactionCreate(
        description="Unbalanced",
        transaction_date=date(2024, 1, 1),
        amount=Decimal("1000.00"),
        entries=[
            EntryCreate(
                account_id=debit.id,
                entry_type=EntryType.DEBIT,
                amount=Decimal("1000.00"),
            ),
            EntryCreate(
                account_id=credit.id,
                entry_type=EntryType.CREDIT,
                amount=Decimal("500.00"),
            ),
        ],
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_transaction(db_session, payload)

    assert exc_info.value.status_code == 422
    assert "balanced" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_transaction_create_requires_at_least_two_entries() -> None:
    with pytest.raises(ValueError):
        TransactionCreate(
            description="Single entry",
            transaction_date=date(2024, 1, 1),
            amount=Decimal("500.00"),
            entries=[
                EntryCreate(
                    account_id="11111111-1111-1111-1111-111111111111",
                    entry_type=EntryType.DEBIT,
                    amount=Decimal("500.00"),
                )
            ],
        )


@pytest.mark.asyncio
async def test_transaction_response_shape_like_domain_object(
    db_session: AsyncSession,
) -> None:
    debit = await _create_account(db_session, "Cash-Resp", AccountType.ASSET)
    credit = await _create_account(db_session, "Revenue-Resp", AccountType.REVENUE)

    payload = TransactionCreate(
        description="Response shape",
        transaction_date=date(2024, 1, 1),
        amount=Decimal("700.00"),
        entries=[
            EntryCreate(
                account_id=debit.id,
                entry_type=EntryType.DEBIT,
                amount=Decimal("700.00"),
            ),
            EntryCreate(
                account_id=credit.id,
                entry_type=EntryType.CREDIT,
                amount=Decimal("700.00"),
            ),
        ],
    )

    tx = await create_transaction(db_session, payload)

    assert len(tx.entries) == 2
    entry_types = {entry.entry_type for entry in tx.entries}
    assert entry_types == {EntryType.DEBIT, EntryType.CREDIT}
