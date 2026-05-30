"""Pydantic schemas for the GET /ledger endpoint."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel

from app.models.entry import Direction
from app.models.transaction import TransactionStatus


# ✍️ TransactionSummary — type hints and field names only (≤10 lines)
# Hint: 3 fields — transaction_date (date), description (str), status (TransactionStatus)
class TransactionSummary(BaseModel):
    # TODO: add the three fields
    ...

    model_config = {"from_attributes": True}


# ✍️ LedgerEntryRead — type hints and field names only (≤10 lines)
# Hint: id, transaction_id, account_id (all uuid.UUID),
#       direction (Direction), amount (int), currency (str),
#       transaction (TransactionSummary)
class LedgerEntryRead(BaseModel):
    # TODO: add the seven fields
    ...

    model_config = {"from_attributes": True}
