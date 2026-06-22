# S9-1-5: Swagger UI Auth Fix & Demo User Seed

Date: 2026-06-22
Goal: Fix Swagger UI Authorize button and seed demo data so recruiters can try the API at the public URL

## Summary

### Problem

The Swagger UI Authorize button did not work because the login endpoint
(`POST /api/v1/auth/login`) expected a JSON body (`LoginRequest` with `email`
+ `password`), while Swagger UI sends OAuth2 Password Flow form data
(`application/x-www-form-urlencoded` with `username` + `password`).

### Solution

1. Replaced `LoginRequest` (Pydantic BaseModel) with `OAuth2PasswordRequestForm`
   (FastAPI's built-in form data parser via `Depends()`)
2. Added `python-multipart` dependency (required for form data parsing)
3. Updated all test files to send `data={"username": ..., "password": ...}`
   instead of `json={"email": ..., "password": ...}`
4. Created `scripts/seed_demo_user.py` to idempotently insert demo data
5. Fixed `app/db/session.py` to handle `sslmode=disable` in DATABASE_URL

## Implementation Steps

### C-1: Login endpoint change

Switched `app/api/v1/routes/auth.py` from `LoginRequest` (JSON body) to
`OAuth2PasswordRequestForm` (form data via `Depends()`). The key insight:
`OAuth2PasswordBearer(tokenUrl=...)` in `deps.py` tells Swagger UI to use
OAuth2 Password Flow, which requires `application/x-www-form-urlencoded` at
the token URL per RFC 6749 Section 4.3.

### C-2: Test updates

Updated login calls in `tests/test_auth.py`, `tests/test_auth_dependency.py`,
and `tests/conftest.py` (4 fixtures). The change is mechanical:
`json={"email": x}` → `data={"username": x}`.

### C-3: Remove unused LoginRequest

Deleted `LoginRequest` from `app/schemas/auth.py` since it was no longer
imported anywhere.

### C-4: Seed script

Created `scripts/seed_demo_user.py` with idempotent inserts for:
- Demo user (admin role, `demo@example.com` / `demo1234`)
- Currency (USD)
- Accounts (Cash 1000, Sales Revenue 4000)
- Transaction with double-entry (debit Cash, credit Revenue, $50.00)

### C-5: Production deployment issues (multiple iterations)

Several issues surfaced only in the Fly.io production environment:

1. **No sync driver**: Production image has only `asyncpg`, not `psycopg2`.
   Rewrote seed script from sync `create_engine` to async
   `create_async_engine` with `asyncio.run()`.

2. **`sslmode=disable` incompatible with asyncpg**: Fly.io sets
   `?sslmode=disable` in DATABASE_URL, but asyncpg does not accept this
   parameter. Solution: parse URL, extract `sslmode`, pass `ssl=False` via
   `connect_args`. This fix was also needed in `app/db/session.py` for the
   app itself.

3. **Enum values must be uppercase**: Alembic migrations create PostgreSQL
   enums using Python enum member **names** (`ADMIN`) not values (`admin`).
   SQLAlchemy ORM handles the mapping, but raw SQL does not. Additionally,
   asyncpg rejects enum values as bind parameters even with CAST — they must
   be embedded as SQL literals.

4. **`python-multipart` missing**: `OAuth2PasswordRequestForm` requires this
   package for form data parsing. Not needed when using JSON bodies.

## Key Takeaways

### What did I learn?

- FastAPI's `OAuth2PasswordBearer` and `OAuth2PasswordRequestForm` are
  designed to work together. The `tokenUrl` in `OAuth2PasswordBearer`
  determines what Swagger UI sends, and the endpoint at that URL must accept
  the OAuth2 form data format — not arbitrary JSON.
- `python-multipart` is a silent dependency: FastAPI doesn't error at import
  time without it, only at request time when form data arrives. This is easy
  to miss in development if you only test with JSON payloads.
- asyncpg is significantly stricter than psycopg2. Query parameters like
  `sslmode` and enum bind parameters that work with psycopg2 fail silently
  or with cryptic errors in asyncpg. When writing raw SQL for asyncpg,
  always check the driver-level behavior, not just SQLAlchemy's abstraction.
- PostgreSQL enum values created by `sa.Enum('ADMIN', 'AUDITOR')` use the
  literal strings passed to the constructor — which are the Python enum
  member **names**, not the `.value` attributes. The ORM layer translates
  transparently, but raw SQL operates at the database level.

### What would I do differently?

- Would have tested the seed script locally against a real PostgreSQL
  instance with the same `DATABASE_URL` format as production, rather than
  iterating via `fly deploy` cycles. Each deploy + SSH round-trip added
  significant feedback latency.
- Would check `pyproject.toml` for `python-multipart` immediately when
  switching from JSON body to form data — this is a known requirement
  documented in the FastAPI tutorial.
- Would read the Alembic migration files before writing raw SQL with enum
  values, to check what case the DB actually stores.

### What surprised me?

- The `sslmode` issue affected not just the seed script but the app itself.
  The app had been deployed previously (S9-1-3) without encountering this
  because the VM auto-stops and no DB-connected requests had been made
  during the brief window before it stopped.
- asyncpg's prepared statement system infers parameter types from the server
  schema. Even `CAST(:param AS enumtype)` fails because asyncpg validates
  the parameter type before the CAST is applied. This is fundamentally
  different from psycopg2's text-based parameter substitution.
- The `fly ssh console -C "cd /app && ..."` syntax doesn't work because
  the `-C` flag executes a binary directly, not through a shell. Wrapping
  with `sh -c '...'` is required for shell builtins like `cd`.
