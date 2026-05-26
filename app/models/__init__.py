"""Public model exports.

Importing this package registers all models on Base.metadata,
which is required for Alembic autogenerate to work correctly.
"""

from app.models.account import Account, AccountType
from app.models.currency import Currency
from app.models.entry import Direction, Entry
from app.models.exchange_rate import ExchangeRate
from app.models.transaction import Transaction
from app.models.user import User, UserRole

__all__ = [
    "Account",
    "AccountType",
    "Currency",
    "Direction",
    "Entry",
    "ExchangeRate",
    "Transaction",
    "User",
    "UserRole",
]
