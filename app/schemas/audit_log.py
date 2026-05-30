"""Pydantic schemas for the GET /audit-logs endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


# ✍️ AuditLogRead — type hints and field names only (≤10 lines)
# Hint: id (uuid.UUID), user_id (uuid.UUID), entity_type (str),
#       entity_id (uuid.UUID), action (str),
#       before_value (dict[str, Any] | None), after_value (dict[str, Any] | None),
#       created_at (datetime)
class AuditLogRead(BaseModel):
    # TODO: add the eight fields
    ...

    model_config = {"from_attributes": True}
