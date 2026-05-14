"""Pydantic schemas for Account endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.account import AccountType

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class AccountCreate(BaseModel):
    # ✍️ code: str  — Chart of Accounts code e.g. "1100", "2000"
    name: str
    account_type: AccountType
    # ✍️ currency: str  — ISO 4217 code e.g. "EUR"


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AccountRead(BaseModel):
    id: uuid.UUID
    # ✍️ code: str
    name: str
    account_type: AccountType
    # ✍️ currency: str
    # ✍️ is_active: bool
    created_at: datetime
    # ✍️ updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Balance response schema
# ---------------------------------------------------------------------------


class BalanceResponse(BaseModel):
    balance: int  # BIGINT minor units e.g. 1000 = €10.00; changed from Decimal
    as_of: datetime
