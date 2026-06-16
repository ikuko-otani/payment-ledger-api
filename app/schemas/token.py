"""Token-related Pydantic schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.models.user import UserRole


class TokenUser(BaseModel):
    """Lightweight user representation built from JWT claims.

    Replaces the ORM User object returned by get_current_user after removing
    the per-request DB lookup (TD-015). Fields are populated directly from
    the JWT payload; no database query is required.
    """

    id: uuid.UUID
    role: UserRole
    is_active: bool
