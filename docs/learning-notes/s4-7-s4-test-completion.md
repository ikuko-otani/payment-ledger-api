# S4-7: S4 Test Completion (Currency Conversion / AuditLog / Ledger Query)

**Date**: 2026-06-01
**Branch**: feature/s4-7-s4-test-completion
**PR**: https://github.com/ikuko-otani/payment-ledger-api/pull/31

---

## Goal Summary

Completed the S4 test suite by adding boundary-value tests for currency conversion,
and parametrized date-boundary tests for GET /ledger. Also fixed a schema design issue
in `LedgerEntryRead` / `TransactionSummary`.

---

## Step C Walkthrough

### Step 1: Add zero-rate validation to `ExchangeRateCreate`

Added `Field(gt=Decimal("0"))` to `ExchangeRateCreate.rate` in `app/schemas/currency.py`.

```python
from pydantic import BaseModel, Field

class ExchangeRateCreate(BaseModel):
    from_currency_id: uuid.UUID
    to_currency_id: uuid.UUID
    rate: Decimal = Field(gt=Decimal("0"))
    effective_date: date
```

**Why `Field` not `@field_validator`**: Simple numeric constraints belong in `Field`
annotations (Pydantic v2 idiom). Use `@field_validator` only for value transformation
or complex logic; use `@model_validator` for cross-field constraints.

FastAPI automatically returns HTTP 422 when Pydantic rejects the value — no manual
error handling needed.

### Step 2: Add two currency conversion boundary tests

Added to `tests/test_currency_conversion.py`:

- `test_zero_rate_returns_422_on_exchange_rate_creation` — POST /exchange-rates with
  `rate=0` must be rejected with 422.
- `test_reverse_direction_rate_only_returns_422` — When only EUR→JPY rate exists
  (not EUR→USD), a EUR transaction must return 422.

The reverse-direction test is important because the `exchange_rates` table is
directional: `from_currency_id` / `to_currency_id` are separate columns. Having
EUR→JPY does not satisfy a lookup for EUR→USD.

Currency conversion test total: 10 tests (DONE condition: 8+).

### Step 3: Add parametrized boundary-date tests for GET /ledger

Added to `tests/test_ledger.py` using `@pytest.mark.parametrize`:

```python
@pytest.mark.parametrize(
    "tx_date, query_params, should_be_included",
    [
        ("2026-03-01", "from=2026-03-01", True),   # from boundary — inclusive
        ("2026-03-31", "to=2026-03-31", True),     # to boundary — inclusive
        ("2026-02-28", "from=2026-03-01", False),  # one day before from — excluded
        ("2026-04-01", "to=2026-03-31", False),    # one day after to — excluded
    ],
)
async def test_get_ledger_date_boundary(...):
```

`parametrize` runs the same test function once per data row, producing four
independent test cases (`test_get_ledger_date_boundary[...]`). Equivalent to PHP's
`@dataProvider`.

### Step 4: Schema design fix — move `id` into `TransactionSummary`

During debugging (KeyError: 'id'), discovered a REST design inconsistency:
`TransactionSummary` (the embedded sub-resource) had no `id`, while `LedgerEntryRead`
exposed `transaction_id` as a top-level FK.

**Decision**: Add `id: uuid.UUID` to `TransactionSummary` and remove `transaction_id`
from `LedgerEntryRead`.

**Rationale**: In REST, embedded sub-resources should carry their own `id` so
consumers can navigate to the full resource (`GET /transactions/{id}`). Having the id
only at the parent level (`transaction_id`) breaks this expectation and creates an
awkward split between identity and context.

```python
# Before
class TransactionSummary(BaseModel):
    transaction_date: date
    description: str
    status: TransactionStatus

class LedgerEntryRead(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID   # redundant once transaction.id exists
    ...
    transaction: TransactionSummary

# After
class TransactionSummary(BaseModel):
    id: uuid.UUID               # sub-resource owns its identity
    transaction_date: date
    description: str
    status: TransactionStatus

class LedgerEntryRead(BaseModel):
    id: uuid.UUID
    # transaction_id removed
    ...
    transaction: TransactionSummary
```

---

## Debugging Notes

### KeyError: 'id' in parametrized boundary tests

**Symptom**: `test_get_ledger_date_boundary[...-True]` cases failed with
`KeyError: 'id'` at line accessing `item["transaction"]["id"]`.

**Cause 1 (immediate)**: `TransactionSummary` had no `id` field.
**Cause 2 (discovered during investigation)**: `ledger.py` had `TransactionSummary`
defined twice — the second definition had overwritten `LedgerEntryRead` entirely
due to a copy-paste error during editing.

**Resolution**: Fixed the duplicate class definition, then added `id` to
`TransactionSummary` and removed `transaction_id` from `LedgerEntryRead`.

**Why the `False` cases passed**: When the filter excluded the transaction,
`resp.json()` was empty and the set comprehension never executed — so the KeyError
was never triggered.

---

## Key Takeaways

### What did I learn?

- **`pytest.mark.parametrize`** lets you run one test function against multiple data
  rows, keeping the assertion logic in one place. PHP's `@dataProvider` is the direct
  equivalent. The test IDs (`[2026-03-01-from=...-True]`) make it easy to identify
  which case failed.

- **`Field(gt=Decimal("0"))` in Pydantic v2** is the idiomatic way to express simple
  numeric constraints. FastAPI turns the validation failure into an automatic HTTP 422
  — no manual error handling needed. More complex logic (transformation, cross-field
  checks) belongs in `@field_validator` or `@model_validator`.

- **Embedded sub-resources in REST should carry their own `id`**.
  `TransactionSummary` initially had no `id`, while `LedgerEntryRead` exposed
  `transaction_id` as a top-level FK instead. This split identity and context
  awkwardly across two levels. The correct design is to put `id` inside the embedded
  object and remove the redundant top-level FK. That way consumers can navigate to
  the full resource (`GET /transactions/{id}`) from the embedded data directly.

### What would I do differently?

- Catch the `transaction_id` redundancy at schema design time (S4-6) rather than
  during test writing. When adding a nested object to a response schema, the question
  "does this sub-resource need its own `id`?" should be asked up front.

### What surprised me?

- Most DONE conditions were already satisfied at the start of S4-7 — the currency
  conversion test count (8) had been met since S4-3. S4-7 turned out to be about
  quality and completeness rather than quantity.

- The `should_be_included=False` parametrize cases passed even while the `True` cases
  had a `KeyError` bug. Because the filter excluded the transaction, `resp.json()` was
  an empty list and the set comprehension never executed — so the bug was invisible
  until a `True` case ran. This showed that passing tests do not always mean correct
  tests.

### What is worth remembering for future goals?

- **REST sub-resource identity rule**: if a response embeds an entity object, that
  object should have `id`. A top-level FK (`transaction_id`) and a nested `id`
  (`transaction.id`) serving the same purpose is a design smell — pick one, and
  prefer the nested form.

- **Boundary-value tests need boundary-day data**: it is not enough to test that
  dates "within range" appear. Create a record on exactly the boundary date and assert
  it is included. The `>=` / `<=` vs `>` / `<` distinction is a one-character bug
  that only boundary data can catch.

---

## Related

- `docs/learning-notes/concepts/pydantic-field-validation.md` — `Field(gt=)` concept note
- `app/schemas/ledger.py` — `TransactionSummary` with `id`, `LedgerEntryRead`
- `app/schemas/currency.py` — `ExchangeRateCreate.rate` with `Field(gt=Decimal("0"))`
- PR #31: https://github.com/ikuko-otani/payment-ledger-api/pull/31
