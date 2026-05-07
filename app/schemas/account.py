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
    # ✍️ 自分で書く: name (str) と account_type (AccountType) を定義
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
