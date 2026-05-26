"""Pydantic schemas for Currency and ExchangeRate endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class CurrencyCreate(BaseModel):
    code: str
    name: str
    decimal_places: int


class CurrencyRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    decimal_places: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ExchangeRateCreate(BaseModel):
    from_currency_id: uuid.UUID
    to_currency_id: uuid.UUID
    rate: Decimal
    effective_date: date


class ExchangeRateRead(BaseModel):
    id: uuid.UUID
    from_currency_id: uuid.UUID
    to_currency_id: uuid.UUID
    rate: Decimal
    effective_date: date
    created_by_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
