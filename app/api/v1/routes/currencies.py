"""Currency endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import AdminUser, CurrentUser
from app.models.currency import Currency
from app.repositories.audit_repository import AuditRepository, get_audit_repository
from app.repositories.currency_repository import (
    CurrencyRepository,
    get_currency_repository,
)
from app.schemas.currency import CurrencyCreate, CurrencyRead
from app.services.currency_service import create_currency, get_currencies

router = APIRouter(prefix="/currencies", tags=["currencies"])

CurrencyRepoDep = Annotated[CurrencyRepository, Depends(get_currency_repository)]
AuditRepoDep = Annotated[AuditRepository, Depends(get_audit_repository)]


@router.get("", response_model=list[CurrencyRead])
async def list_currencies(
    repo: CurrencyRepoDep,
    _current_user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Currency]:
    return await get_currencies(repo, limit=limit, offset=offset)


@router.post("", response_model=CurrencyRead, status_code=201)
async def post_currency(
    payload: CurrencyCreate,
    repo: CurrencyRepoDep,
    audit_repo: AuditRepoDep,
    current_user: AdminUser,
) -> Currency:
    return await create_currency(repo, audit_repo, payload, current_user)
