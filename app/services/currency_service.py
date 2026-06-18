"""Currency and ExchangeRate service layer."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from app.core.exceptions import ConflictError
from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate
from app.repositories.audit_repository import AuditRepository
from app.repositories.currency_repository import CurrencyRepository
from app.schemas.currency import CurrencyCreate, ExchangeRateCreate
from app.schemas.token import TokenUser


async def get_currencies(repo: CurrencyRepository) -> list[Currency]:
    return await repo.list_all()


async def create_currency(
    repo: CurrencyRepository,
    audit_repo: AuditRepository,
    payload: CurrencyCreate,
    current_user: TokenUser,
) -> Currency:
    currency = Currency(
        code=payload.code,
        name=payload.name,
        decimal_places=payload.decimal_places,
    )
    saved = await repo.save(currency)

    after_value: dict[str, Any] = {
        "id": str(saved.id),
        "code": saved.code,
        "name": saved.name,
        "decimal_places": saved.decimal_places,
    }
    await audit_repo.log(
        user_id=current_user.id,
        entity_type="currency",
        entity_id=saved.id,
        action="create",
        before=None,
        after=after_value,
    )
    return saved


async def get_exchange_rates(
    repo: CurrencyRepository,
    from_currency_id: uuid.UUID | None = None,
    to_currency_id: uuid.UUID | None = None,
    effective_date: date | None = None,
) -> list[ExchangeRate]:
    return await repo.list_exchange_rates(
        from_currency_id, to_currency_id, effective_date
    )


async def create_exchange_rate(
    repo: CurrencyRepository,
    audit_repo: AuditRepository,
    payload: ExchangeRateCreate,
    created_by: TokenUser,
) -> ExchangeRate:
    exchange_rate = ExchangeRate(
        from_currency_id=payload.from_currency_id,
        to_currency_id=payload.to_currency_id,
        rate=payload.rate,
        effective_date=payload.effective_date,
        created_by_id=created_by.id,
    )
    saved = await repo.save_exchange_rate(exchange_rate)

    after_value: dict[str, Any] = {
        "id": str(saved.id),
        "from_currency_id": str(saved.from_currency_id),
        "to_currency_id": str(saved.to_currency_id),
        "rate": str(saved.rate),
        "effective_date": saved.effective_date.isoformat(),
    }
    await audit_repo.log(
        user_id=created_by.id,
        entity_type="exchange_rate",
        entity_id=saved.id,
        action="create",
        before=None,
        after=after_value,
    )
    return saved
