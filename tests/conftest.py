"""Pytest fixtures: ephemeral PostgreSQL via testcontainers."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import AsyncExitStack

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
from app.core.deps import get_current_user
from app.core.security import get_password_hash
from app.db.session import get_db
from app.main import app as fastapi_app
from app.models.user import User, UserRole


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

    # get_current_user を常に固定ユーザーで返す mock
    async def override_get_current_user() -> User:
        return User(
            id=uuid.uuid4(),
            email="fixture@example.com",
            hashed_password="",
            role=UserRole.ADMIN,
        )

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=fastapi_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def unauthed_client(engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient without get_current_user override — for testing auth itself."""
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = override_get_db
    # get_current_user は override しない → 実際の JWT 検証が走る

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# S3-6: Token-based authenticated client fixtures
# ---------------------------------------------------------------------------


async def _seed_user(
    engine: AsyncEngine,
    email: str,
    password: str,
    role: UserRole,
) -> None:
    """Insert a User row directly into the test DB with a hashed password."""
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        user = User(
            email=email,
            hashed_password=get_password_hash(password),
            role=role,
        )
        session.add(user)
        await session.commit()


def _make_db_override(
    engine: AsyncEngine,
) -> Callable[[], AsyncGenerator[AsyncSession, None]]:
    """Return an override_get_db callable suitable for dependency_overrides[get_db]."""
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return override_get_db


@pytest_asyncio.fixture()
async def admin_token(engine: AsyncEngine) -> AsyncGenerator[str, None]:
    """Seed an admin user into the test DB and yield a valid JWT access token."""
    email = "admin@fixture.test"
    password = "AdminTest123!"

    await _seed_user(engine, email, password, UserRole.ADMIN)

    fastapi_app.dependency_overrides[get_db] = _make_db_override(engine)
    transport = ASGITransport(app=fastapi_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        resp = await tmp.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
    token: str = resp.json()["access_token"]

    yield token
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def auditor_token(engine: AsyncEngine) -> AsyncGenerator[str, None]:
    """Seed an auditor user into the test DB and yield a valid JWT access token."""
    email = "auditor@fixture.test"
    password = "AuditorTest123!"

    await _seed_user(engine, email, password, UserRole.AUDITOR)

    fastapi_app.dependency_overrides[get_db] = _make_db_override(engine)
    transport = ASGITransport(app=fastapi_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        resp = await tmp.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
    token: str = resp.json()["access_token"]

    yield token  # placeholder
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def authenticated_client(
    engine: AsyncEngine,
) -> AsyncGenerator[Callable[[str], AsyncClient], None]:
    """Factory fixture: yields a coroutine factory that creates authenticated AsyncClients.

    Usage in tests::

        async def test_foo(authenticated_client):
            client = await authenticated_client("admin")
            resp = await client.post("/api/v1/transactions", ...)
    """
    stack = AsyncExitStack()

    async def _factory(role: str) -> AsyncClient:
        email = f"{role}@fixture.test"
        password = f"{role.capitalize()}Test123!"
        role_enum = UserRole.ADMIN if role == "admin" else UserRole.AUDITOR

        await _seed_user(engine, email, password, role_enum)

        fastapi_app.dependency_overrides[get_db] = _make_db_override(engine)
        transport = ASGITransport(app=fastapi_app)  # type: ignore[arg-type]
        client = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://test")
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        token: str = resp.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})
        return client

    yield _factory  # type: ignore[misc]
    await stack.aclose()
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def auditor_client(
    engine: AsyncEngine,
) -> AsyncGenerator[AsyncClient, None]:
    """Token-based AsyncClient with AUDITOR role (replaces the override-based version)."""
    email = "auditor@fixture.test"
    password = "AuditorTest123!"

    await _seed_user(engine, email, password, UserRole.AUDITOR)

    fastapi_app.dependency_overrides[get_db] = _make_db_override(engine)
    transport = ASGITransport(app=fastapi_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        token: str = resp.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})
        yield client

    fastapi_app.dependency_overrides.clear()
