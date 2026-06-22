from collections.abc import AsyncGenerator
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def _asyncpg_url(url: str) -> tuple[str, dict[str, object]]:
    """Strip query params that asyncpg does not accept (e.g. sslmode)."""
    parts = urlsplit(url)
    connect_args: dict[str, object] = {}
    if parts.query:
        qs = parse_qs(parts.query)
        sslmode = qs.pop("sslmode", [None])[0]
        if sslmode == "disable":
            connect_args["ssl"] = False
        cleaned = urlencode(qs, doseq=True)
        parts = parts._replace(query=cleaned)
    return urlunsplit(parts), connect_args


_url, _connect_args = _asyncpg_url(settings.database_url)

# pool_pre_ping=True detects broken connections before checkout
engine = create_async_engine(
    _url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    connect_args=_connect_args,
)

# expire_on_commit=False is required for async sessions —
#   allows attribute access after commit without a lazy-load
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a DB session for FastAPI Depends injection."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
