"""User model — application user for authentication and role-based access."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRole(str, enum.Enum):
    """Allowed roles for application users."""
    ADMIN = "admin"
    AUDITOR = "auditor"


class User(Base):
    """Application user table."""

    __tablename__ = "users"
