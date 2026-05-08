"""Pydantic schemas for Transaction endpoints.

Validation layers:
  - Pydantic (this file): value shape, amount > 0, entries >= 2
  - Service layer       : double-entry balance, account_id existence
  - DB constraints      : FK integrity (last line of defence)

Double-entry rule: sum(debit amounts) == sum(credit amounts).
This constraint is validated in the service layer, not here.

Entries minimum: at least 2 entries required (one debit + one credit).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, field_validator

from app.models.entry import EntryType

# ---------------------------------------------------------------------------
# Entry sub-schemas
# ---------------------------------------------------------------------------


class EntryCreate(BaseModel):
    account_id: uuid.UUID
    entry_type: EntryType
    amount: Decimal

    # ✍️ Validate that amount is strictly positive (> 0)
    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        # TODO: raise ValueError if v <= 0
        #   Hint: use Decimal("0") for comparison to stay type-safe
        ...
        return v


class EntryRead(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    entry_type: EntryType
    amount: Decimal

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Transaction schemas
# ---------------------------------------------------------------------------


class TransactionCreate(BaseModel):
    description: str
    transaction_date: date
    amount: Decimal
    entries: list[EntryCreate]

    @field_validator("entries")
    @classmethod
    def entries_must_have_at_least_two(cls, v: list[EntryCreate]) -> list[EntryCreate]:
        if len(v) < 2:
            raise ValueError("entries must have at least 2 items")
        return v

    # ✍️ Validate that description is not blank (strip whitespace)
    @field_validator("description")
    @classmethod
    def description_must_not_be_blank(cls, v: str) -> str:
        # TODO: raise ValueError if v.strip() is empty
        #   Hint: stripped = v.strip(); if not stripped: raise ValueError(...)
        ...
        return v


class TransactionRead(BaseModel):
    id: uuid.UUID
    description: str
    transaction_date: date
    amount: Decimal
    created_at: datetime
    entries: list[EntryRead]

    model_config = {"from_attributes": True}
