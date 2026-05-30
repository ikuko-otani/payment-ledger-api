"""Ledger query service — JOIN + dynamic WHERE + offset pagination over entries."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.models.entry import Entry
from app.models.transaction import Transaction


async def get_ledger_entries(
    db: AsyncSession,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    account_id: uuid.UUID | None = None,
    currency_code: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Entry]:
    """Return Entry rows matching the given filters, with Transaction eagerly loaded.

    Design notes:
    - JOIN Entry → Transaction so transaction_date is available for WHERE filtering.
    - contains_eager reuses the JOIN columns to populate Entry.transaction,
      avoiding the second SELECT that selectinload would issue.
    - Dynamic WHERE: accumulate conditions in a list, then unpack into
      .where(*filters) — None params are silently skipped.
    - .unique() is required after scalars() when contains_eager is used,
      because the JOIN can produce duplicate Entry rows in the raw result set.
    """
    filters = []
    if from_date is not None:
        filters.append(Transaction.transaction_date >= from_date)
    if to_date is not None:
        filters.append(Transaction.transaction_date <= to_date)
    if account_id is not None:
        filters.append(Entry.account_id == account_id)
    if currency_code is not None:
        filters.append(Entry.currency == currency_code)

    stmt = (
        select(Entry)
        .join(Entry.transaction)
        .options(contains_eager(Entry.transaction))
        .where(*filters)
        .order_by(Transaction.transaction_date.desc(), Entry.id)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    # .unique() de-duplicates rows that contain_eager can produce from the JOIN
    return list(result.scalars().unique().all())
