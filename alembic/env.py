import os
from dotenv import load_dotenv

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

load_dotenv()  # ← これがないと .env が読まれない

# 📋 Alembic Config object
config = context.config

# 📋 Setup loggers from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import Base so Alembic can detect models automatically.
from app.db.base import Base  # noqa: E402

# Import all models so their tables are registered on Base.metadata
import app.models  # noqa: F401, E402

target_metadata = Base.metadata


def get_url() -> str:
    """Resolve DB URL for Alembic.

    Priority:
    1. sqlalchemy.url passed via Alembic Config (used by pytest/testcontainers)
    2. DATABASE_URL environment variable (used in normal app/docker runs)
    """
    config_url = config.get_main_option("sqlalchemy.url")
    if config_url:
        return config_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")

    env_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://ledger_user:password@db:5432/ledger_db",
    )
    return env_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection needed)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (live DB connection)."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
