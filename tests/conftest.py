"""Pytest fixtures: ephemeral PostgreSQL via testcontainers.

Lifecycle:
  session-scoped PostgreSQL container
    └─ session-scoped async engine  (Alembic migrations run once)
         └─ function-scoped AsyncSession  (rolled back after each test)
              └─ function-scoped AsyncClient  (app DI overridden)
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from app.db.base import Base
from app.db.session import get_db
from app.main import app

# ---------------------------------------------------------------------------
# Session-scoped: start container once per pytest session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container():
    """Start a throwaway PostgreSQL container for the whole test session."""
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use the default asyncio event loop policy (required by pytest-asyncio)."""
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="session")
async def engine(
    postgres_container: PostgresContainer,
) -> AsyncGenerator[AsyncEngine, None]:
    """Create async engine and run Alembic migrations once per session."""
    # TODO: build the asyncpg URL from postgres_container and create the engine
    # Hint: postgres_container.get_connection_url() returns a psycopg2 URL.
    #       Replace the scheme with "postgresql+asyncpg" to get an asyncpg URL.

    # --- (1) engine fixture ---
    # testcontainersのURLをasyncpg形式に変換してAlembicマイグレーションを実行
    sync_url = postgres_container.get_connection_url()
    async_url = sync_url.replace("psycopg2", "asyncpg", 1).replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )

    _engine = create_async_engine(async_url, echo=False)

    # Run Alembic migrations so the schema matches production
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sync_url)  # Alembic uses sync psycopg2
    alembic_command.upgrade(cfg, "head")

    yield _engine
    await _engine.dispose()


# ---------------------------------------------------------------------------
# Function-scoped: fresh session per test (rolled back automatically)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional AsyncSession that rolls back after each test."""
    # TODO: open a connection, begin a SAVEPOINT transaction, yield the session,
    #       then rollback so each test starts from a clean state.

    # --- (2) db_session fixture ---
    # トランザクションを開いてテスト後にROLLBACKする（DBを汚さない）
    async with engine.connect() as conn:
        await conn.begin()  # ← outer transaction
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await conn.rollback()  # ← undo everything after the test


@pytest_asyncio.fixture()
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient with the DB dependency overridden to use db_session."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # TODO: create AsyncClient with ASGITransport pointing to `app`
    # Hint:
    #   transport = ASGITransport(app=app)
    #   async with AsyncClient(transport=transport, base_url="http://test") as c:
    #       yield c
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
