"""Aggregate router for API v1."""

from fastapi import APIRouter

from app.api.v1.routes import (
    accounts,
    audit_logs,
    auth,
    currencies,
    exchange_rates,
    ledger,
    transactions,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(accounts.router)
api_router.include_router(audit_logs.router)
api_router.include_router(auth.router)
api_router.include_router(currencies.router)
api_router.include_router(exchange_rates.router)
api_router.include_router(ledger.router)
api_router.include_router(transactions.router)
api_router.include_router(users.router)
