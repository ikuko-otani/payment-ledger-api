"""Service/schema integration tests for Transactions."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType
from app.models.entry import Direction
from app.models.transaction import Transaction
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


@pytest.mark.asyncio
async def test_create_balanced_transaction_persists_rows(
    db_session: AsyncSession,
) -> None:
    debit = await _create_account(db_session, "Cash", AccountType.ASSET, code="1100")
    credit = await _create_account(
        db_session, "Revenue", AccountType.REVENUE, code="4000"
    )

    payload = TransactionCreate(
        description="Balanced",
        transaction_date=date(2024, 1, 1),
        # amount removed from TransactionCreate
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

    tx = await create_transaction(db_session, payload)
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
                amount=500,  # intentionally unbalanced
                currency="EUR",
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

    tx = await create_transaction(db_session, payload)

    assert len(tx.entries) == 2
    entry_directions = {entry.direction for entry in tx.entries}
    assert entry_directions == {Direction.DEBIT, Direction.CREDIT}


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entry_amount_zero_raises_validation_error() -> None:
    """amount=0 must be rejected by Pydantic schema."""
    with pytest.raises(ValueError):
        EntryCreate(
            account_id="11111111-1111-1111-1111-111111111111",
            direction=Direction.DEBIT,
            amount=0,
            currency="EUR",
        )


@pytest.mark.asyncio
async def test_entry_amount_negative_raises_validation_error() -> None:
    """amount < 0 must be rejected by Pydantic schema."""
    with pytest.raises(ValueError):
        EntryCreate(
            account_id="11111111-1111-1111-1111-111111111111",
            direction=Direction.DEBIT,
            amount=-100,
            currency="EUR",
        )


@pytest.mark.asyncio
async def test_description_blank_raises_validation_error() -> None:
    """Blank description must be rejected by Pydantic schema."""
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
    """account_id not in accounts table must be rejected by service layer."""
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

    with pytest.raises(HTTPException) as exc_info:
        await create_transaction(db_session, payload)

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

    with pytest.raises(HTTPException) as exc_info:
        await create_transaction(db_session, payload)

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

    with pytest.raises(HTTPException) as exc_info:
        await create_transaction(db_session, payload)

    assert exc_info.value.status_code == 422
    assert "credit" in str(exc_info.value.detail).lower()
