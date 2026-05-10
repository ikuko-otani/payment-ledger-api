# Alembic: `failed to resolve host 'db'`

## Date
2026-05-06

## Problem

Running `alembic revision --autogenerate` directly from the host (Windows) fails with:

```
psycopg.OperationalError: failed to resolve host 'db': [Errno 11001] getaddrinfo failed
sqlalchemy.exc.OperationalError: (psycopg.OperationalError) failed to resolve host 'db'
```

## Root Cause

Two issues were compounding each other.

### Cause 1: `DATABASE_URL` host set to `db` (Docker service name)

The `db` service name in `docker-compose.yml` is only resolvable within the Docker network.
When running `alembic` directly from the host OS, `localhost` must be used instead.

```dotenv
# .env (before)
DATABASE_URL=postgresql+psycopg://ledger_user:password@db:5432/ledger_db

# .env (after)
DATABASE_URL=postgresql+psycopg://ledger_user:password@localhost:5432/ledger_db
```

### Cause 2: `alembic/env.py` was not loading `.env`

`uv run alembic` does not automatically load `.env`.
`load_dotenv()` from `python-dotenv` must be called explicitly.

```python
# Add to the top of alembic/env.py
import os
from dotenv import load_dotenv

load_dotenv()  # Load .env into environment variables
```

If `python-dotenv` is not installed:

```bash
uv add python-dotenv
```

## Fix

1. Change the `DATABASE_URL` host in `.env` from `db` to `localhost`
2. Run `uv add python-dotenv`
3. Add `load_dotenv()` at the top of `alembic/env.py`
4. Confirm PostgreSQL is running via Docker:

```bash
docker compose up -d db
```

5. Re-run the migration:

```bash
uv run alembic revision --autogenerate -m "your message"
```

## Lesson Learned

The correct host depends on the execution context:

| Execution context | `DATABASE_URL` host |
|---|---|
| Host OS (`uv run alembic`, etc.) | `localhost` |
| Inside Docker container (`api` service, etc.) | `db` (Docker service name) |

## References

- [python-dotenv documentation](https://saurabh-kumar.com/python-dotenv/)
- [Alembic: Customizing env.py](https://alembic.sqlalchemy.org/en/latest/tutorial.html#editing-the-migration-script)
