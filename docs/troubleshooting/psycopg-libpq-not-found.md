# psycopg: `libpq library not found`

## Date
2026-05-06

## Problem

Running `alembic revision --autogenerate` fails with:

```
ImportError: no pq wrapper available.
- couldn't import psycopg 'c' implementation: No module named 'psycopg_c'
- couldn't import psycopg 'binary' implementation: No module named 'psycopg_binary'
- couldn't import psycopg 'python' implementation: libpq library not found
```

## Root Cause

The `python:3.12-slim` base image does not include the PostgreSQL client library (`libpq`).
The pure-Python implementation of `psycopg` (psycopg3) dynamically links to `libpq` at runtime,
so it cannot start inside a container that lacks the library.

## Fix

Change the dependency in `pyproject.toml` from `psycopg` to `psycopg[binary]`.
The `[binary]` extra uses a wheel with `libpq` statically bundled, so no OS-level library installation is needed.

```toml
# pyproject.toml (before)
"psycopg>=3.3.4",

# pyproject.toml (after)
"psycopg[binary]>=3.3.4",
```

After the change, rebuild the container:

```bash
docker compose build --no-cache api
docker compose up -d
```

## Lesson Learned

When using `python:3.12-slim` (or any slim image), system-level libraries like `libpq` are stripped out.
Prefer `psycopg[binary]` over bare `psycopg` in containerized environments to avoid runtime dependency issues.

## References

- [psycopg3 installation docs](https://www.psycopg.org/psycopg3/docs/basic/install.html)
