"""Pydantic schemas for the GET /ledger endpoint."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel

from app.models.entry import Direction
from app.models.transaction import TransactionStatus


class TransactionSummary(BaseModel):
    id: uuid.UUID
    transaction_date: date
    description: str
    status: TransactionStatus

    model_config = {"from_attributes": True}


class LedgerEntryRead(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    direction: Direction
    amount: int
    currency: str
    transaction: TransactionSummary

    model_config = {"from_attributes": True}
