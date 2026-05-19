"""Pytest fixtures: ephemeral PostgreSQL via testcontainers."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from alembic.config import Config as AlembicConfig
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from alembic import command as alembic_command
from app.db.session import get_db
from app.main import app as fastapi_app


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Start one PostgreSQL container for the whole test session."""
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def migrated_database_urls(
    postgres_container: PostgresContainer,
) -> Generator[tuple[str, str], None, None]:
    """Run Alembic once and provide sync/async DB URLs."""
    raw_url = postgres_container.get_connection_url()

    sync_url = raw_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1).replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    async_url = sync_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)

    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sync_url)
    alembic_command.upgrade(cfg, "head")

    yield sync_url, async_url


@pytest_asyncio.fixture()
async def engine(
    migrated_database_urls: tuple[str, str],
) -> AsyncGenerator[AsyncEngine, None]:
    """Create a fresh async engine per test."""
    _, async_url = migrated_database_urls
    engine = create_async_engine(async_url, echo=False)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_db(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Clean tables before and after each test."""
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE entries, transactions, accounts, users CASCADE"))

    yield

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE entries, transactions, accounts, users CASCADE"))


@pytest_asyncio.fixture()
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Provide one AsyncSession per test."""
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# HTTP layer fixtures (S2-1 re-introduced)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def async_client(
    engine: AsyncEngine,
) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient with DB dependency overridden to use testcontainer session.

    Key design: a NEW session is created per-request inside the override,
    not shared across requests. This avoids asyncpg 'another operation in
    progress' errors that occurred in S1-4 when a single session was reused.
    """
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Override get_db to yield a fresh session for each request
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=fastapi_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    fastapi_app.dependency_overrides.clear()
