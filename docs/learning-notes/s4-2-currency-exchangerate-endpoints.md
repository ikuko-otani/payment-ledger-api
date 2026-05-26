# S4-2: GET /currencies + POST /exchange-rates Endpoints

**Date**: 2026-05-26
**Branch**: `feature/s4-2-currency-exchangerate-endpoints`
**Goal**: Add CRUD endpoints for currencies and exchange rates, reusing S3 auth layer.

---

## Step C Walkthrough

### Step 1 — `app/schemas/currency.py`

Defined four Pydantic schemas:

- `CurrencyCreate` — input: `code: str`, `name: str`, `decimal_places: int`
- `CurrencyRead` — output: above + `id`, `is_active`, `created_at`; `model_config = {"from_attributes": True}`
- `ExchangeRateCreate` — input: `from_currency_id`, `to_currency_id`, `rate: Decimal`, `effective_date`
- `ExchangeRateRead` — output: above + `id`, `created_by_id`, `created_at`; `model_config = {"from_attributes": True}`

Key point: `rate: Decimal` (not `float`) to avoid floating-point precision loss. Pydantic v2
serializes `Decimal` as a JSON number by default.

### Step 2 — `app/services/currency_service.py`: get_currencies + create_currency

```python
async def get_currencies(db: AsyncSession) -> list[Currency]:
    result = await db.execute(select(Currency))
    return list(result.scalars().all())

async def create_currency(db: AsyncSession, payload: CurrencyCreate) -> Currency:
    currency = Currency(code=payload.code, name=payload.name, decimal_places=payload.decimal_places)
    db.add(currency)
    await db.flush()
    await db.refresh(currency)  # needed to populate server_default created_at
    return currency
```

`flush()` sends SQL to DB (transaction stays open); `refresh()` re-reads the row to get
`server_default` values like `created_at`. `commit()` is handled by `get_db`.

### Step 3 — `app/services/currency_service.py`: get_exchange_rates + create_exchange_rate

```python
async def get_exchange_rates(db, from_currency_id=None, to_currency_id=None, effective_date=None):
    stmt = select(ExchangeRate)
    if from_currency_id is not None:
        stmt = stmt.where(ExchangeRate.from_currency_id == from_currency_id)
    if to_currency_id is not None:
        stmt = stmt.where(ExchangeRate.to_currency_id == to_currency_id)
    if effective_date is not None:
        stmt = stmt.where(ExchangeRate.effective_date == effective_date)
    result = await db.execute(stmt)
    return list(result.scalars().all())
```

SQLAlchemy's `Select` is immutable; `stmt = stmt.where(...)` returns a new object each time.

```python
async def create_exchange_rate(db, payload, created_by):
    exchange_rate = ExchangeRate(
        from_currency_id=payload.from_currency_id,
        to_currency_id=payload.to_currency_id,
        rate=payload.rate,
        effective_date=payload.effective_date,
        created_by_id=created_by.id,
    )
    db.add(exchange_rate)
    try:
        await db.flush()
    except IntegrityError as e:
        # sqlstate 23505 = unique_violation; 23503 = FK violation (re-raise as 500)
        if getattr(e.orig, "sqlstate", None) == "23505":
            raise HTTPException(status_code=409, detail="Exchange rate for this currency pair and date already exists")
        raise
    await db.refresh(exchange_rate)
    return exchange_rate
```

### Step 4-5 — Route handlers

Both route files are thin delegators to the service layer:

```python
# currencies.py
async def list_currencies(db, _current_user: CurrentUser) -> list[Currency]:
    return await get_currencies(db)

async def post_currency(payload, db, _current_user: AdminUser) -> Currency:
    return await create_currency(db, payload)

# exchange_rates.py
async def list_exchange_rates(db, _current_user, from_currency_id, to_currency_id, effective_date):
    return await get_exchange_rates(db, from_currency_id, to_currency_id, effective_date)

async def post_exchange_rate(payload, db, current_user: AdminUser) -> ExchangeRate:
    return await create_exchange_rate(db, payload, current_user)
```

Note: `current_user` (no underscore) in `post_exchange_rate` because it must be passed to the service.

### Step 6 — Tests and a debugging detour

#### The IntegrityError / FK bug

The first attempt to test `POST /exchange-rates` returned 409 on the *first* request (expected 201).

**Root cause**: `async_client` injects a mock `User` with `id=uuid.uuid4()` that does not exist in
the `users` table. `ExchangeRate.created_by_id` is a `ForeignKey("users.id")`, so the INSERT raised
a `ForeignKeyViolationError` (sqlstate 23503). SQLAlchemy wraps this as `IntegrityError` — the same
class as `UniqueViolationError`. The original `except IntegrityError` caught it and returned 409.

**Fix 1 — Service layer**: Narrow the catch to unique violations only by checking `sqlstate`:
```python
except IntegrityError as e:
    if getattr(e.orig, "sqlstate", None) == "23505":
        raise HTTPException(status_code=409, ...)
    raise  # FK violations and other errors propagate as 500
```

**Fix 2 — Test**: Use `authenticated_client("admin")` for exchange-rate tests. This fixture seeds
a real user into the DB and provides a real JWT, so `created_by_id` satisfies the FK constraint.

#### conftest.py: TRUNCATE scope for new tables

`clean_db` needed `currencies` added explicitly — it has no FK pointing to the existing tables, so
CASCADE from `users`/`accounts` would not reach it. `exchange_rates` is already covered by CASCADE
from `users` (via `created_by_id`), but was added explicitly for readability.

Line-length issue (E501): the TRUNCATE string exceeded ruff's 100-char limit and was split using
Python's implicit string concatenation:
```python
text(
    "TRUNCATE TABLE exchange_rates, entries, "
    "transactions, accounts, users, currencies CASCADE"
)
```

---

## Key Takeaways

**What did I learn?**

I learned that `IntegrityError` in SQLAlchemy is a catch-all for multiple PostgreSQL constraint
violations — unique violations (23505), FK violations (23503), not-null violations (23502), etc.
Catching it without checking `sqlstate` causes unrelated errors to be silently converted to wrong
HTTP responses. The fix was to check `e.orig.sqlstate` for the specific error code.

I also reinforced the difference between `flush()` and `commit()` in SQLAlchemy async sessions:
`flush()` executes the SQL statement (and triggers constraint checks for non-deferred constraints),
while `commit()` finalizes the transaction. Server defaults like `created_at` require an explicit
`refresh()` after `flush()` to be populated on the Python object.

**What would I do differently?**

I would check upfront whether the test fixture injects a real or mock user before writing service
functions that store `created_by_id`. The FK constraint mismatch between the mock user and the DB
was entirely predictable — seeing `ForeignKey("users.id")` in the model should have prompted me to
use `authenticated_client` from the start for exchange-rate tests.

**What surprised me?**

The `async_client` fixture works well for endpoints that don't write `created_by_id`-style FK
columns, but silently breaks for those that do. The same fixture used in 10+ existing tests is
not universal — the applicability depends on what FK columns the new endpoint writes. This is a
design limitation worth noting for future endpoints.

**What is worth remembering for future goals?**

- Always check `sqlstate` when catching `IntegrityError` — never catch it blindly for 409.
- Use `authenticated_client` for any endpoint that writes a `created_by_id` (or similar user FK).
- `Select` objects are immutable in SQLAlchemy 2.0; building dynamic queries requires re-assignment
  (`stmt = stmt.where(...)`), not in-place mutation.
- Pydantic v2 serializes `Decimal` as a JSON number (not a string). If clients expect a string,
  add `json_encoders = {Decimal: str}` to `model_config`.
