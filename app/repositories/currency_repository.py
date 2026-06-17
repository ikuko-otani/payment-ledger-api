"""Currency repository — abstract interface (SQLAlchemy impl in S7-8)."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date

from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate


class CurrencyRepository(ABC):
    @abstractmethod
    async def list_all(self) -> list[Currency]: ...

    @abstractmethod
    async def save(self, currency: Currency) -> Currency: ...

    @abstractmethod
    async def find_by_code(self, code: str) -> Currency | None: ...

    @abstractmethod
    async def list_exchange_rates(
        self,
        from_currency_id: uuid.UUID | None,
        to_currency_id: uuid.UUID | None,
        effective_date: date | None,
    ) -> list[ExchangeRate]: ...

    @abstractmethod
    async def save_exchange_rate(self, rate: ExchangeRate) -> ExchangeRate: ...

    @abstractmethod
    async def find_exchange_rate(
        self,
        from_currency_id: uuid.UUID,
        to_currency_id: uuid.UUID,
        effective_date: date,
    ) -> ExchangeRate | None: ...
