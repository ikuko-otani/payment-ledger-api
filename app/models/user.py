"""User model — application user for authentication and role-based access."""

from __future__ import annotations

import enum

from app.db.base import Base


class UserRole(str, enum.Enum):
    """Allowed roles for application users."""

    pass


class User(Base):
    """Application user table."""

    __tablename__ = "users"
