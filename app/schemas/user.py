"""Pydantic schemas for User endpoints."""

from __future__ import annotations

from pydantic import BaseModel

from app.models.user import UserRole


class UserCreate(BaseModel):
    pass


class UserResponse(BaseModel):
    model_config = {"from_attributes": True}
