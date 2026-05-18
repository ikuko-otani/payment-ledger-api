# S2-10: S2 Integration Check + Refactor

Date: 2026-05-18
Branch: `feature/s2-10-integration-check-refactor`
Status: ✅ Done

---

## Goal

Run all four S2 DONE criteria against a live `docker compose` stack, add GitHub
Actions CI (lint + test), configure ruff, and create a PR with curl screenshots.

---

## Step C Walkthrough

### Step C-1 — Verify pytest passes locally

```bash
uv run pytest --cov=app --cov-report=term-missing -q
```

Testcontainers starts ephemeral PostgreSQL and Redis containers; no `docker compose`
needed for tests.

### Step C-2 — Push branch and verify CI

```bash
git push -u origin feature/s2-10-integration-check-refactor
```

#### CI workflow structure (`.github/workflows/ci.yml`)

Two parallel jobs:

- **lint** — `uv run ruff check .`
- **test** — `uv run pytest --cov=app --cov-report=term-missing`

#### Ruff configuration added to `pyproject.toml`

```toml
[tool.ruff]
target-version = "py312"
line-length = 100
exclude = ["alembic/"]

[tool.ruff.lint]
select = ["E", "F", "I"]
```

Rules enabled:
- `E` — pycodestyle errors
- `F` — pyflakes (unused imports, bare f-strings, etc.)
- `I` — isort (import ordering)

`alembic/` is excluded because migration files are auto-generated and follow
a different import ordering convention.

#### Errors found and fixed by `ruff check --fix .`

| Rule | Location | Fix |
|------|----------|-----|
| I001 (import order) | `app/dependencies/idempotency.py`, `app/models/__init__.py`, `app/models/transaction.py`, `app/services/transaction_service.py`, `tests/conftest.py`, `tests/test_idempotency.py` | Auto-sorted |
| F541 (f-string without placeholder) | `app/services/transaction_service.py:53` | Removed `f` prefix |
| F401 (unused import) | `tests/conftest.py` — `typing.AsyncGenerator as AG`, `fastapi.FastAPI` | Removed |

All 9 errors were auto-fixable with `--fix`.

#### CI failure encountered: `database_url` validation error

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
database_url
  Field required [type=missing, ...]
```

**Root cause**: `settings = Settings()` is executed at module import time
(`app/core/config.py:12`). `database_url` has no default value, so pydantic-settings
raises a `ValidationError` when `.env` is absent — which is the case in CI.

**Why tests don't need the real URL**: `conftest.py` overrides `get_db` to use
the testcontainers-provided PostgreSQL URL. `settings.database_url` is never
actually read during test execution.

**Fix**: Add a dummy `DATABASE_URL` env var to the CI `test` job.

```yaml
test:
  runs-on: ubuntu-latest
  env:
    DATABASE_URL: "postgresql+asyncpg://notused/notused"
```

The dummy value satisfies pydantic-settings at import time; the test fixtures
override the DB connection before any query runs.

### Step C-3 — Start docker compose stack

```bash
docker compose up -d
docker compose ps          # confirm api / db / redis are running
docker compose logs api    # wait for "Application startup complete."
```

### Step C-4 — Curl verification of all four S2 DONE criteria

#### ① Debit ≠ Credit → 422

```bash
curl -s -X POST http://localhost:8000/api/v1/transactions \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Unbalanced test",
    "transaction_date": "2024-06-01",
    "entries": [
      {"account_id": "<DEBIT_ID>",  "direction": "debit",  "amount": 100, "currency": "EUR"},
      {"account_id": "<CREDIT_ID>", "direction": "credit", "amount": 50,  "currency": "EUR"}
    ]
  }' | python -m json.tool
# Expected: 422 Unprocessable Content
```

#### ② Same Idempotency-Key → 409 on second request

```bash
KEY=$(python -c "import uuid; print(uuid.uuid4())")
# First request → 201
curl -s -X POST http://localhost:8000/api/v1/transactions \
  -H "Content-Type: application/json" -H "Idempotency-Key: $KEY" \
  -d '{ ... balanced payload ... }' | python -m json.tool
# Second request → 409
curl -s -X POST http://localhost:8000/api/v1/transactions \
  -H "Content-Type: application/json" -H "Idempotency-Key: $KEY" \
  -d '{ ... same payload ... }' | python -m json.tool
```

Tip: Swagger UI (`http://localhost:8000/docs`) also works — the `idempotency-key`
header appears as a parameter field in `POST /api/v1/transactions`.

#### ③ Balance at arbitrary date

```bash
curl -s "http://localhost:8000/api/v1/accounts/<DEBIT_ID>/balance?as_of=2024-06-02T00%3A00%3A00" \
  | python -m json.tool
# Expected: {"balance": 100, "as_of": "..."}
```

#### ④ Coverage ≥ 60%

```bash
uv run pytest --cov=app --cov-report=term-missing -q
# Confirmed: 94% coverage
```

### Step C-5 — Create PR and attach screenshots

```bash
gh pr create --title "feat(s2-10): S2 integration check + ruff lint CI" --body "..."
```

---

## Key Takeaways

### What did I learn?

- **Ruff** replaces multiple Python lint tools (flake8, isort, pyupgrade) with a
  single Rust-based binary. Running `ruff check --fix .` auto-corrects the majority
  of issues. Adding it to CI via `uv run ruff check .` takes minutes to set up.
- **GitHub Actions + testcontainers** work together without extra setup. The
  `ubuntu-latest` runner has Docker pre-installed, so testcontainers can pull and
  start real PostgreSQL and Redis containers — no mocking needed in CI.
- **pydantic-settings validates at import time**, not at first use. Required fields
  without defaults cause `ValidationError` on `import`, even if the value is never
  actually read during the test. The fix is either a dummy env var in CI or a
  default value in `Settings`.

### What would I do differently?

- Add `DATABASE_URL` to the CI env from the start rather than discovering the
  import-time validation error after the first CI run. The pattern is predictable:
  any required field in `Settings` without a default will break CI.
- Consider making `database_url` optional (`str = ""`) in `Settings` from the
  beginning of the project, since tests always override `get_db` anyway.

### What surprised me?

- All 9 ruff errors were auto-fixable with `--fix`. I expected some manual
  intervention, but `ruff` handled import reordering, f-string cleanup, and
  unused import removal automatically.
- The `Idempotency-Key` header appears as a named parameter field in Swagger UI,
  making manual testing straightforward without writing curl commands.

### What is worth remembering for future goals?

- **CI env var pattern for pydantic-settings**: any `Settings` field without a
  default requires a dummy value in CI. Document this near the `Settings` class or
  in the CI workflow as a comment.
- **`ruff check --fix .` as first step of any new lint integration**: run it
  immediately after configuring ruff to clear the initial backlog before adding CI.
- **`exclude = ["alembic/"]` in ruff config**: always exclude generated migration
  files from lint to avoid noise.
