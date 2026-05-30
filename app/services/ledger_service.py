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
    # 🔧 Build the filter list (≤20 lines)
    # Accumulate non-None conditions into `filters: list`.
    # Use Transaction.transaction_date for date range, Entry columns for the rest.
    filters = []
    # TODO: if from_date is not None → append Transaction.transaction_date >= from_date
    # TODO: if to_date is not None   → append Transaction.transaction_date <= to_date
    # TODO: if account_id is not None → append Entry.account_id == account_id
    # TODO: if currency_code is not None → append Entry.currency == currency_code

    # 🔧 Build and execute the query (≤10 lines)
    # Chain: select(Entry) → .join(Entry.transaction) → .options(contains_eager(...))
    #        → .where(*filters) → .order_by(date desc, Entry.id) → .offset/.limit
    stmt = (
        # TODO: select(Entry)
        # TODO: .join(Entry.transaction)
        # TODO: .options(contains_eager(Entry.transaction))
        # TODO: .where(*filters)
        # TODO: .order_by(Transaction.transaction_date.desc(), Entry.id)
        # TODO: .offset(offset).limit(limit)
        select(Entry)  # placeholder — replace with full chain above
    )
    result = await db.execute(stmt)
    # .unique() de-duplicates rows that contain_eager can produce from the JOIN
    return list(result.scalars().unique().all())
