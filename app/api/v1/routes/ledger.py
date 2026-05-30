"""Ledger read endpoint — GET /ledger."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuditorOrAdminUser
from app.db.session import get_db
from app.models.entry import Entry
from app.schemas.ledger import LedgerEntryRead
from app.services.ledger_service import get_ledger_entries

router = APIRouter(prefix="/ledger", tags=["ledger"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[LedgerEntryRead])
async def get_ledger(
    db: DbDep,
    _current_user: AuditorOrAdminUser,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    account_id: uuid.UUID | None = Query(default=None),
    currency_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Entry]:
    # 🔧 Call get_ledger_entries and return the result (≤5 lines)
    # Pass all filter params as keyword arguments.
    # TODO: return await get_ledger_entries(
    #           db,
    #           from_date=from_date, to_date=to_date,
    #           account_id=account_id, currency_code=currency_code,
    #           limit=limit, offset=offset,
    #       )
    return []  # placeholder — remove after implementing
