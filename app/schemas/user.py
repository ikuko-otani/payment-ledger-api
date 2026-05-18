"""Pydantic schemas for User endpoints."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.models.user import UserRole


class UserCreate(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool

    model_config = {"from_attributes": True}
