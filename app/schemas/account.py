"""Pydantic schemas for Account endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.account import AccountType

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class AccountCreate(BaseModel):
    name: str
    account_type: AccountType


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AccountRead(BaseModel):
    id: uuid.UUID
    name: str
    account_type: AccountType
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Balance response schema
# ---------------------------------------------------------------------------


class BalanceResponse(BaseModel):
    pass  # ✍️  Step C-1: add balance and as_of fields
