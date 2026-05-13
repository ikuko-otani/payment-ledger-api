# S2-5: GET /accounts/{id}/balance Endpoint Design

**Date**: 2026-05-13
**Goal**: Add `GET /accounts/{id}/balance` endpoint with `as_of: datetime` query parameter (stub implementation)
**Branch**: `feature/s2-5-get-accounts-id-balance`
**Support level**: balanced

---

## Step C Walkthrough

### C-1. Add `BalanceResponse` schema (`app/schemas/account.py`)

Added a new Pydantic response model under the existing response schemas section.

```python
class BalanceResponse(BaseModel):
    balance: Decimal
    as_of: datetime
```

Key decisions:
- `balance: Decimal` — avoids floating-point rounding errors inherent in `float`
  (same motivation as Oracle `NUMBER(15,2)` or PHP BC Math)
- `as_of: datetime` — uses `datetime` (not `date`) to leave room for intra-day
  balance queries in future goals
- No `model_config = {"from_attributes": True}` — `BalanceResponse` is assembled
  from code values, not converted from an ORM instance

### C-2. Add stub endpoint (`app/api/v1/routes/accounts.py`)

Added imports (`uuid`, `datetime`, `Decimal`) and the new route handler:

```python
@router.get("/{id}/balance", response_model=BalanceResponse)
async def get_account_balance(
    id: uuid.UUID,
    as_of: datetime,
) -> BalanceResponse:
    # TODO: replace with actual DB balance query (future goal)
    return BalanceResponse(balance=Decimal("0.00"), as_of=as_of)
```

How FastAPI dispatches parameters:
- `id` appears in the path pattern `/{id}/balance` → **path parameter**
- `as_of` does not appear in the path → **query parameter** (auto-inferred)
- Declaring `as_of: datetime` causes FastAPI to parse ISO 8601 input and return
  422 automatically on malformed input — no manual validation needed

### C-3. DONE condition verification

```bash
# Create an account to obtain a UUID
curl -s -X POST http://localhost:8000/accounts \
  -H "Content-Type: application/json" \
  -d '{"name":"Cash","account_type":"asset"}' | python -m json.tool

# Verify the balance endpoint (replace <UUID> with the returned id)
curl -s "http://localhost:8000/accounts/<UUID>/balance?as_of=2026-05-20T00:00:00" \
  | python -m json.tool
# Expected: {"balance": "0.00", "as_of": "2026-05-20T00:00:00"}
```

Note: The Notion DONE condition uses `1` as the account ID, but Account IDs are
`uuid.UUID`. Passing an integer returns 422 — always use a real UUID in tests.

---

## Key Takeaways

**What did I learn?**

I learned how FastAPI automatically distinguishes path parameters from query
parameters purely by whether the argument name appears in the path pattern. No
decorator arguments are needed — the type annotation alone (`as_of: datetime`)
activates ISO 8601 parsing and 422 validation. This is more implicit than PHP
frameworks where query parameters are fetched explicitly via `$request->query()`.

I also reinforced why `Decimal` is the right type for monetary amounts in Python.
`float` is a binary floating-point type and cannot represent 0.1 exactly, which
causes silent rounding errors in financial calculations.

**What would I do differently?**

I would double-check DONE condition URLs for ID type consistency upfront (the
condition used `1` but accounts use UUID). Catching this in Step A avoids a
confusion point during DONE verification.

**What surprised me?**

How little code is required to satisfy the DONE condition. Two fields in a schema
and a four-line function body — yet the full validation contract (correct datetime
parsing, correct path/query dispatch, correct response serialization) is already
enforced by FastAPI + Pydantic. The framework does substantial work from type
annotations alone.

**What is worth remembering for future goals?**

- FastAPI path vs query parameter dispatch: if the argument name is in the path
  template, it's a path parameter; otherwise it's a query parameter.
- `Decimal` for all monetary fields — never `float`.
- `from_attributes = True` is only needed when converting ORM model instances
  to Pydantic; it is unnecessary for manually constructed response objects.
- Stub-first endpoint design lets the interface contract (schema + validation)
  be tested independently from business logic — useful when frontend/client work
  needs to start before the DB query is ready.
