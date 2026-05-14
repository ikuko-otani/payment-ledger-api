"""Pydantic schemas for Transaction endpoints.

Validation layers:
  - Pydantic (this file): value shape, amount > 0, entries >= 2
  - Service layer       : double-entry balance, account_id existence
  - DB constraints      : FK integrity (last line of defence)

Double-entry rule: sum(debit amounts) == sum(credit amounts).
This constraint is validated in the service layer, not here.

Amounts are BIGINT (minor currency units): 1000 = €10.00, 500 = ¥500.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, field_validator

from app.models.entry import Direction
from app.models.transaction import TransactionStatus

# ---------------------------------------------------------------------------
# Entry sub-schemas
# ---------------------------------------------------------------------------


class EntryCreate(BaseModel):
    account_id: uuid.UUID
    direction: Direction
    amount: int  # BIGINT minor units (was Decimal); e.g. 1000 for €10.00
    currency: str  # ISO 4217 e.g. "EUR"

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: int):
        if v <= 0:
            raise ValueError("amount must be greater than 0")
        return v


class EntryRead(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    direction: Direction
    amount: int
    currency: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Transaction schemas
# ---------------------------------------------------------------------------


class TransactionCreate(BaseModel):
    description: str
    transaction_date: date
    # amount removed: redundant in double-entry — derived from SUM(entries.amount)
    entries: list[EntryCreate]

    @field_validator("entries")
    @classmethod
    def entries_must_have_at_least_two(cls, v: list[EntryCreate]) -> list[EntryCreate]:
        if len(v) < 2:
            raise ValueError("entries must have at least 2 items")
        return v

    @field_validator("description")
    @classmethod
    def description_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("description must not be blank")
        return v


class TransactionRead(BaseModel):
    id: uuid.UUID
    description: str
    transaction_date: date
    # amount removed
    # ✍️ status: TransactionStatus  — add after TransactionStatus import is in place
    created_at: datetime
    entries: list[EntryRead]

    model_config = {"from_attributes": True}
