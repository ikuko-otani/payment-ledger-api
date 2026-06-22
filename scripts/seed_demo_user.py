"""Seed demo user and sample data for Swagger UI demonstration.

Usage (on Fly.io):
    fly ssh console -C "sh -c 'cd /app && uv run --no-sync python -m scripts.seed_demo_user'"

Usage (local):
    uv run python -m scripts.seed_demo_user
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, date, datetime

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo1234"

DEMO_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
CASH_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
REVENUE_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000011")
TRANSACTION_ID = uuid.UUID("00000000-0000-0000-0000-000000000020")
ENTRY_DEBIT_ID = uuid.UUID("00000000-0000-0000-0000-000000000030")
ENTRY_CREDIT_ID = uuid.UUID("00000000-0000-0000-0000-000000000031")


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    # asyncpg does not accept sslmode — strip it
    if "?" in url:
        base, qs = url.split("?", 1)
        params = [p for p in qs.split("&") if not p.startswith("sslmode=")]
        url = f"{base}?{'&'.join(params)}" if params else base
    return url


async def seed() -> None:
    engine = create_async_engine(_get_database_url())
    now = datetime.now(UTC)
    hashed = _hash_password(DEMO_PASSWORD)

    async with engine.begin() as conn:
        # 1. Demo user (admin role)
        existing = (await conn.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": DEMO_EMAIL},
        )).fetchone()
        if existing is None:
            await conn.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, role, is_active, created_at)"
                    " VALUES (:id, :email, :hashed_password, :role, :is_active, :created_at)"
                ),
                {
                    "id": str(DEMO_USER_ID),
                    "email": DEMO_EMAIL,
                    "hashed_password": hashed,
                    "role": "admin",
                    "is_active": True,
                    "created_at": now,
                },
            )
            print(f"Created demo user: {DEMO_EMAIL}")
        else:
            print(f"Demo user already exists: {DEMO_EMAIL}")

        # 2. Currency (USD)
        existing = (await conn.execute(
            text("SELECT code FROM currencies WHERE code = :code"),
            {"code": "USD"},
        )).fetchone()
        if existing is None:
            await conn.execute(
                text(
                    "INSERT INTO currencies (id, code, name, decimal_places, is_active, created_at)"
                    " VALUES (:id, :code, :name, :decimal_places, :is_active, :created_at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "code": "USD",
                    "name": "US Dollar",
                    "decimal_places": 2,
                    "is_active": True,
                    "created_at": now,
                },
            )
            print("Created currency: USD")
        else:
            print("Currency USD already exists")

        # 3. Accounts (Cash + Revenue)
        for acct_id, code, name, acct_type in [
            (CASH_ACCOUNT_ID, "1000", "Cash", "asset"),
            (REVENUE_ACCOUNT_ID, "4000", "Sales Revenue", "revenue"),
        ]:
            existing = (await conn.execute(
                text("SELECT id FROM accounts WHERE code = :code"),
                {"code": code},
            )).fetchone()
            if existing is None:
                await conn.execute(
                    text(
                        "INSERT INTO accounts (id, code, name, account_type, currency, is_active, created_at, updated_at)"
                        " VALUES (:id, :code, :name, :account_type, :currency, :is_active, :created_at, :updated_at)"
                    ),
                    {
                        "id": str(acct_id),
                        "code": code,
                        "name": name,
                        "account_type": acct_type,
                        "currency": "USD",
                        "is_active": True,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                print(f"Created account: {name} ({code})")
            else:
                print(f"Account {code} already exists")

        # 4. Transaction + Entries (double-entry: debit Cash, credit Revenue)
        existing = (await conn.execute(
            text("SELECT id FROM transactions WHERE id = :id"),
            {"id": str(TRANSACTION_ID)},
        )).fetchone()
        if existing is None:
            await conn.execute(
                text(
                    "INSERT INTO transactions (id, description, transaction_date, status, posted_at, created_at)"
                    " VALUES (:id, :description, :transaction_date, :status, :posted_at, :created_at)"
                ),
                {
                    "id": str(TRANSACTION_ID),
                    "description": "Demo: Cash sale $50.00",
                    "transaction_date": date.today(),
                    "status": "posted",
                    "posted_at": now,
                    "created_at": now,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO entries (id, transaction_id, account_id, direction, amount, currency, converted_amount_usd)"
                    " VALUES (:id, :transaction_id, :account_id, :direction, :amount, :currency, :converted_amount_usd)"
                ),
                {
                    "id": str(ENTRY_DEBIT_ID),
                    "transaction_id": str(TRANSACTION_ID),
                    "account_id": str(CASH_ACCOUNT_ID),
                    "direction": "debit",
                    "amount": 5000,
                    "currency": "USD",
                    "converted_amount_usd": 5000,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO entries (id, transaction_id, account_id, direction, amount, currency, converted_amount_usd)"
                    " VALUES (:id, :transaction_id, :account_id, :direction, :amount, :currency, :converted_amount_usd)"
                ),
                {
                    "id": str(ENTRY_CREDIT_ID),
                    "transaction_id": str(TRANSACTION_ID),
                    "account_id": str(REVENUE_ACCOUNT_ID),
                    "direction": "credit",
                    "amount": 5000,
                    "currency": "USD",
                    "converted_amount_usd": 5000,
                },
            )
            print("Created demo transaction: Cash sale $50.00")
        else:
            print("Demo transaction already exists")

    print("\nSeed complete!")
    print(f"  Login: {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())
