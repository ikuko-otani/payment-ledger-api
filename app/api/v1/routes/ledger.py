"""Ledger read endpoint — GET /ledger."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import AuditorOrAdminUser
from app.models.entry import Entry
from app.repositories.ledger_repository import LedgerRepository, get_ledger_repository
from app.schemas.ledger import LedgerEntryRead

router = APIRouter(prefix="/ledger", tags=["ledger"])

LedgerRepoDep = Annotated[LedgerRepository, Depends(get_ledger_repository)]


@router.get("", response_model=list[LedgerEntryRead])
async def get_ledger(
    repo: LedgerRepoDep,
    _current_user: AuditorOrAdminUser,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    account_id: uuid.UUID | None = Query(default=None),
    currency_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Entry]:
    return await repo.list_entries(
        from_date=from_date,
        to_date=to_date,
        account_id=account_id,
        currency_code=currency_code,
        limit=limit,
        offset=offset,
    )
