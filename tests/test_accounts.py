"""DB-level integration tests for Account model operations."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType


@pytest.mark.asyncio
async def test_create_account_persists_row(db_session: AsyncSession) -> None:
    account = Account(
        # ✍️ add: code="1100", currency="EUR"
        name="Cash",
        account_type=AccountType.ASSET,
    )
    db_session.add(account)
    await db_session.commit()

    result = await db_session.execute(select(Account).where(Account.name == "Cash"))
    saved = result.scalar_one()

    assert saved.name == "Cash"
    assert saved.account_type == AccountType.ASSET
    # ✍️ add assertions: saved.code == "1100", saved.currency == "EUR", saved.is_active is True


@pytest.mark.asyncio
async def test_list_accounts_returns_created_rows(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Account(
                # ✍️ add: code="1100", currency="EUR"
                name="Cash",
                account_type=AccountType.ASSET,
            ),
            Account(
                # ✍️ add: code="4000", currency="EUR"
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
    db_session.add(Account(
        # ✍️ add: code="9001", currency="EUR"
        name="Duplicate",
        account_type=AccountType.ASSET,
    ))
    await db_session.commit()

    db_session.add(Account(
        # ✍️ add: code="9002", currency="EUR"  ← different code, same name
        name="Duplicate",
        account_type=AccountType.EXPENSE,
    ))

    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_duplicate_account_code_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    # ✍️ new test: code UNIQUE constraint
    # hint: create two accounts with same code="1100" but different names
    #       assert IntegrityError is raised on second commit
    ...
