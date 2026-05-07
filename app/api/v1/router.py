"""Aggregate router for API v1."""

from fastapi import APIRouter

from app.api.v1.routes import accounts, transactions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(accounts.router)
api_router.include_router(transactions.router)
