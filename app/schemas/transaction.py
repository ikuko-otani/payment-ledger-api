"""Pydantic schemas for Transaction endpoints.

Double-entry rule: sum(debit amounts) == sum(credit amounts).
This constraint is validated in the service layer, not here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.entry import EntryType


# ---------------------------------------------------------------------------
# Entry sub-schemas
# ---------------------------------------------------------------------------

class EntryCreate(BaseModel):
    # ✍️ 自分で書く: account_id (uuid.UUID), entry_type (EntryType), amount (Decimal) を定義
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


class TransactionRead(BaseModel):
    id: uuid.UUID
    description: str
    transaction_date: date
    amount: Decimal
    created_at: datetime
    entries: list[EntryRead]

    model_config = {"from_attributes": True}
