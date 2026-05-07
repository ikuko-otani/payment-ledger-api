"""Pydantic schemas for Transaction endpoints.

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

    # ✍️ Implement this validator: raise ValueError if len(v) < 2
    @field_validator("entries")
    @classmethod
    def entries_must_have_at_least_two(cls, v: list[EntryCreate]) -> list[EntryCreate]:
        # TODO: validate that entries has at least 2 items
        # Hint: if len(v) < 2: raise ValueError("entries must have at least 2 items")
        if len(v) < 2:
            raise ValueError("entries must have at least 2 items (one debit + one credit)")
        return v


class TransactionRead(BaseModel):
    id: uuid.UUID
    description: str
    transaction_date: date
    amount: Decimal
    created_at: datetime
    entries: list[EntryRead]

    model_config = {"from_attributes": True}
