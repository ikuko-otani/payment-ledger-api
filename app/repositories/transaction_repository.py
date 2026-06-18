"""Transaction repository — abstract interface (SQLAlchemy impl in S7-8)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.entry import Entry
from app.models.transaction import Transaction


class TransactionRepository(ABC):
    @abstractmethod
    async def save(
        self, transaction: Transaction, entries: list[Entry]
    ) -> Transaction: ...

    @abstractmethod
    async def list_all(self, limit: int, offset: int) -> list[Transaction]: ...
