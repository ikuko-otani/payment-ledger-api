# pytest + testcontainers + Alembic troubleshooting

## Summary

During S1-4 (`pytest` foundation), several issues appeared while trying to run PostgreSQL-backed tests with `pytest`, `testcontainers`, Alembic, FastAPI, and async SQLAlchemy.

Final stable outcome:
- `uv run pytest -v` passes with 7 tests.
- The stable solution uses **DB/service/schema integration tests** instead of HTTP-layer API integration tests.
- PostgreSQL is still provided by `testcontainers`, and schema setup still uses Alembic.

---

## Errors observed

### 1. `cannot attach stdin to a TTY-enabled container because stdin is not a terminal`

**When it happened**
- Running heredoc commands such as:

```bash
docker compose exec api uv run python - <<'EOF'
...
EOF
```

**Cause**
- `docker compose exec` allocates a TTY by default.
- Heredoc input is piped stdin, which conflicts with TTY expectations.

**Fix**
- Use `-T`:

```bash
docker compose exec -T api uv run python - <<'EOF'
...
EOF
```

---

### 2. `failed to resolve host 'db': [Errno 11001] getaddrinfo failed`

**When it happened**
- Running `uv run pytest -v` from the host machine.

**Cause**
- `db` is a Docker Compose service name, so it only resolves inside the Compose network.
- Alembic was still using the default `DATABASE_URL` / Docker-oriented host, instead of the testcontainers database URL.

**Fix**
- Update `alembic/env.py` so Alembic prefers `config.get_main_option("sqlalchemy.url")` when provided by tests.
- Fall back to `DATABASE_URL` only when no test-specific URL is injected.

**Key idea**
- Docker runtime URL and pytest runtime URL are different concerns.
- Alembic must support externally injected database URLs.

---

### 3. `ModuleNotFoundError: No module named 'psycopg2'`

**When it happened**
- Running Alembic against the testcontainers database.

**Cause**
- `PostgresContainer.get_connection_url()` may return a `postgresql+psycopg2://...` style URL.
- The project uses `psycopg` (psycopg3), not `psycopg2`.

**Fix**
- Normalize URLs in `tests/conftest.py`:

```python
sync_url = (
    raw_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    .replace("postgresql://", "postgresql+psycopg://", 1)
)
async_url = sync_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
```

---

### 4. `asyncpg.exceptions._base.InterfaceError: cannot perform operation: another operation is in progress`

**When it happened**
- During HTTP-layer integration tests using FastAPI dependency overrides.
- Also appeared during teardown/cleanup paths.

**Likely cause**
- Async session / connection lifecycle was being shared or overlapped across test, request, and cleanup boundaries.
- The combination of:
  - async SQLAlchemy session management,
  - FastAPI dependency override,
  - `httpx.AsyncClient` / `TestClient`,
  - cleanup logic,
  created connection-state conflicts.

**What was tried**
- Shared session fixture.
- Transaction rollback pattern.
- TRUNCATE cleanup pattern.
- `httpx.AsyncClient`.
- `fastapi.testclient.TestClient`.
- Session-scoped engine, then function-scoped engine.

**Result**
- The HTTP-layer API integration approach remained unstable for this project at this stage.

**Stable resolution for S1-4**
- Move test scope one layer down:
  - test **DB/model/service/schema behavior** directly,
  - do **not** run HTTP-layer integration tests in this Goal.

This preserved the real PostgreSQL test environment while removing unstable ASGI/dependency-lifecycle interactions.

---

### 5. `AttributeError: 'NoneType' object has no attribute 'send'`

**When it happened**
- During API-style tests after the DB/session state had already become inconsistent.

**Interpretation**
- This looked like a secondary failure in the request/transport lifecycle rather than the root cause.
- The underlying database/session concurrency issue had to be solved first.

**Resolution**
- Same as above: stop using HTTP-layer integration tests for S1-4 and move to DB/service/schema integration tests.

---

### 6. Git Bash path conversion issue with `/var/run/docker.sock`

**Observed symptom**

```text
ls: cannot access 'C:/Users/.../Git/var/run/docker.sock': No such file or directory
```

**Cause**
- On Windows Git Bash, Unix-like paths may be rewritten into Windows paths before they reach Docker.
- This made socket checks misleading.

**Lesson**
- If Docker socket debugging is necessary on Windows, prefer PowerShell/CMD for validation.
- For this Goal, host-side `uv run pytest -v` was the better direction than Docker-in-Docker style execution.

---

## Final stable test strategy for S1-4

The final working approach was:

1. Start PostgreSQL with `testcontainers`.
2. Run Alembic once against the test DB.
3. Create a fresh async engine per test.
4. Clean tables before/after each test.
5. Use one `AsyncSession` per test.
6. Test domain behavior directly:
   - account persistence/list/duplicate constraints,
   - balanced transaction creation,
   - unbalanced transaction rejection,
   - minimum entry count validation,
   - returned transaction domain shape.

This produced:

```bash
uv run pytest -v
# 7 passed
```

---

## Why this was the right trade-off

For S1-4, the main goal was a stable pytest foundation with real PostgreSQL.
The most important achievement was:
- ephemeral DB startup,
- automatic schema setup,
- green tests against a real database,
- validation of core bookkeeping invariants.

HTTP-layer API integration tests are still worth doing later, but they should be reintroduced in a separate, smaller Goal after isolating the FastAPI dependency/session lifecycle more carefully.

---

## Follow-up tasks

- Add a dedicated troubleshooting note if HTTP-layer async integration tests are retried later.
- Revisit API integration testing in a separate Goal with a minimal reproducible setup first.
- Clean up warnings:
  - Alembic `path_separator=os`
  - deprecation around `HTTP_422_UNPROCESSABLE_ENTITY`
