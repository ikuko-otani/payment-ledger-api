"""Currency endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AdminUser, CurrentUser
from app.db.session import get_db
from app.models.currency import Currency
from app.schemas.currency import CurrencyCreate, CurrencyRead
from app.services.currency_service import create_currency, get_currencies

router = APIRouter(prefix="/currencies", tags=["currencies"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


# ✍️ return await get_currencies(db)
@router.get("", response_model=list[CurrencyRead])
async def list_currencies(db: DbDep, _current_user: CurrentUser) -> list[Currency]:
    pass


# ✍️ return await create_currency(db, payload)
@router.post("", response_model=CurrencyRead, status_code=201)
async def post_currency(
    payload: CurrencyCreate,
    db: DbDep,
    _current_user: AdminUser,
) -> Currency:
    pass
