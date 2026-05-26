"""Pydantic schemas for Currency and ExchangeRate endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


# ✍️ CurrencyCreate: fields (code: str, name: str, decimal_places: int)
class CurrencyCreate(BaseModel):
    pass


# ✍️ CurrencyRead: fields (id, code, name, decimal_places, is_active, created_at)
#    + model_config = {"from_attributes": True}
class CurrencyRead(BaseModel):
    pass


# ✍️ ExchangeRateCreate: fields
#    (from_currency_id: uuid.UUID, to_currency_id: uuid.UUID,
#     rate: Decimal, effective_date: date)
class ExchangeRateCreate(BaseModel):
    pass


# ✍️ ExchangeRateRead: fields (id, from_currency_id, to_currency_id, rate,
#    effective_date, created_by_id, created_at)
#    + model_config = {"from_attributes": True}
class ExchangeRateRead(BaseModel):
    pass
