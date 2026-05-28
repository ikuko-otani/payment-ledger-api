# S4-3: Currency Conversion Logic + Multi-Currency POST /transactions

**Date**: 2026-05-28
**Branch**: `feature/s4-3-currency-conversion-multi-currency`
**Goal**: Add `currency_code` to `TransactionCreate`, implement USD conversion via
`ExchangeRate`, store `converted_amount_usd` (NOT NULL) on every `Entry` at write time.

---

## Step C Walkthrough

### Step C-1: Alembic Migration

Added `converted_amount_usd BIGINT NOT NULL` to the `entries` table.

Key technique: add with a temporary `server_default='0'` so existing rows satisfy
the NOT NULL constraint, then immediately remove the server default so future inserts
must supply the value explicitly.

```python
def upgrade() -> None:
    op.add_column(
        "entries",
        sa.Column("converted_amount_usd", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.alter_column("entries", "converted_amount_usd", server_default=None)
```

### Step C-2: `_get_converted_amount_usd`

Standalone async helper in `transaction_service.py`.

Design decisions:
- `currency_code == BASE_CURRENCY` → identity (no DB lookup needed)
- Two `scalar_one_or_none()` queries: resolve from/to currency UUIDs
- One query for `ExchangeRate` on (from_id, to_id, effective_date)
- 422 at each failure point: unknown currency, USD not in table, rate not found

Rounding pattern:
```python
converted = (Decimal(amount) * exchange_rate.rate).quantize(
    Decimal("1"), rounding=ROUND_HALF_UP
)
return int(converted)
```

`Decimal("1")` as the quantum means "round to the nearest integer" (USD cents are integers).

### Step C-3: Integration into `create_transaction`

`await` cannot be used inside the same list comprehension that also builds `Entry` objects,
so the conversion is done in two separate steps:

```python
# Step 1: compute converted amounts (async, sequential)
converted_amounts = [
    await _get_converted_amount_usd(
        db, entry.amount, payload.currency_code, payload.transaction_date
    )
    for entry in payload.entries
]

# Step 2: build Entry objects using zip
entries = [
    Entry(..., converted_amount_usd=converted_amount)
    for entry, converted_amount in zip(payload.entries, converted_amounts)
]
```

### Step C-4 to C-7: Tests

8 tests in `tests/test_currency_conversion.py`:
- Happy path: USD identity, JPY conversion, EUR conversion
- Rounding: amount × rate = 0.5 → ROUND_HALF_UP → 1 (not 0)
- All entries: both debit and credit sides receive `converted_amount_usd`
- Error cases: missing rate, wrong date, unknown currency code

All tests use `authenticated_client("admin")` because `POST /exchange-rates` requires
a real user in DB for the `created_by_id` FK.

### Step C-8: ARCHITECTURE.md

Added ADR-006 (ROUND_HALF_UP rounding policy) and ADR-007 (Hub-and-Spoke base currency)
to `ARCHITECTURE.md` Section 8.

---

## Bugs Encountered During Implementation

### Bug 1: Argument order in `_get_converted_amount_usd` call

**Error**: `operator does not exist: date = character varying` — PostgreSQL was
comparing `effective_date` (DATE) against `'EUR'` (VARCHAR).

**Root cause**: `payload.currency_code` and `payload.transaction_date` were passed
in the wrong order to `_get_converted_amount_usd`.

**Fix**: Verify positional argument order matches the function signature:
`(db, amount, currency_code, transaction_date)`.

### Bug 2: `test_balance.py` direct Entry creation

**Error**: `null value in column "converted_amount_usd" violates not-null constraint`

**Root cause**: `test_balance.py` creates `Entry` objects directly (not via
`create_transaction`). After adding `converted_amount_usd NOT NULL`, all direct
`Entry()` constructor calls must include `converted_amount_usd=amount`.

**Lesson**: When adding a NOT NULL column to an ORM model, search the entire test
suite for direct model instantiation (not just service-layer calls) and update
every constructor call.

---

## Key Takeaways

### What did I learn?

I learned that Python's `Decimal.quantize()` is the correct tool for controlling
rounding precision in currency arithmetic. The quantum argument (`Decimal("1")`)
defines the target scale, not the number of decimal places as an integer — which
is different from Oracle's `ROUND(x, 0)` or PHP's `round($x, 0)` syntax.
I also learned the Hub-and-Spoke pattern for multi-currency systems: storing N
rates (each currency → USD) instead of N×(N-1)/2 pairs, and why the `converted_amount_usd`
must be stored at write time rather than recomputed (exchange rates change, but
the value recorded at transaction time must be immutable).

### What would I do differently?

After adding a NOT NULL column to any model, I would immediately grep the entire
test suite for direct instantiation of that model class to catch missing fields
before running pytest. The `test_balance.py` failure was predictable in hindsight —
any test that constructs an `Entry()` object directly needed updating.

### What surprised me?

I was surprised that `assert condition, message` in Python shows the message (the
response body) only on failure, not on success. This is different from what I
expected. It makes debugging test failures much clearer without adding noise when
tests pass.

I was also surprised by how easy it is to introduce an argument-order bug when a
function takes two parameters of similar types (`str` and `date`). Mypy would
catch a type mismatch between unrelated types, but it cannot distinguish between
two `str` arguments in the wrong order.

### What is worth remembering for future goals?

1. **Decimal rounding**: always use `Decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP)`
   for financial amounts, never `round()` or float arithmetic. Be ready to explain
   the difference between ROUND_HALF_UP and ROUND_HALF_EVEN in interviews.

2. **NOT NULL migration pattern**: `server_default` → backfill → `alter_column(server_default=None)`.
   Use this two-step approach whenever adding a NOT NULL column to a table that may
   have existing rows.

3. **Test suite blast radius**: adding a NOT NULL column to a model affects every
   place in the codebase (tests included) that creates that model directly. Always
   search for all constructor calls, not just service layer code.

4. **State-dependent nullable columns**: columns that only have meaning in certain
   states (like `posted_at` for POSTED status) are nullable by design. The rigorous
   DB enforcement is a `CHECK` constraint, not `NOT NULL` alone.
   See: `docs/learning-notes/concepts/state-dependent-nullable-columns.md`

5. **Hub-and-Spoke + point-in-time snapshot**: storing `converted_amount_usd` at
   write time with the exchange rate of that date is a fintech standard pattern.
   It ensures historical balance reports are immutable even as exchange rates change.

---

## Related

- `ARCHITECTURE.md` — ADR-006 (ROUND_HALF_UP), ADR-007 (Hub-and-Spoke base currency)
- `docs/learning-notes/concepts/state-dependent-nullable-columns.md`
- `app/services/transaction_service.py` — `_get_converted_amount_usd`, `BASE_CURRENCY`
- `tests/test_currency_conversion.py` — 8 currency conversion tests
