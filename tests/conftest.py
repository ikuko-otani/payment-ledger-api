"""Pytest fixtures: ephemeral PostgreSQL via testcontainers."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer


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

    sync_url = (
        raw_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
        .replace("postgresql://", "postgresql+psycopg://", 1)
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
        await conn.execute(
            text("TRUNCATE TABLE entries, transactions, accounts CASCADE")
        )

    yield

    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE entries, transactions, accounts CASCADE")
        )


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
