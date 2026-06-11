# SQL injection defense layers: type validation vs. parameterized queries

> Date: 2026-06-11 | Goals: S6-6 (security tests)
> Purpose: Explain why `tests/test_security.py`'s SQLi test on `account_id` returns 422,
> and why that is *not* the same mechanism that protects string-typed parameters.

---

## 1. Summary (TL;DR)

There are **two independent defense layers** against SQL injection in this codebase:

| Layer | Mechanism | What it catches | Example |
|---|---|---|---|
| ① Type validation (Pydantic/FastAPI) | Reject input that can't be coerced to the declared type → 422 | Only **narrow types** (UUID, int, date, bool, Enum) — an SQLi payload can never be a valid value of these types | `account_id: uuid.UUID` |
| ② Parameterized queries (SQLAlchemy → asyncpg → Postgres bind parameters) | SQL text is parsed *before* parameter values are sent; values are never re-parsed as SQL | **All types**, especially strings | `Entry.currency == currency_code` |

`tests/test_security.py::test_sql_injection_in_account_id_path_param_returns_422` only
exercises **layer ①**. A payload in a *string-typed* query parameter (e.g.
`currency_code: str | None` in `app/services/ledger_service.py`) would pass layer ① (it's
a valid string) but is still safe because of layer ②.

---

## 2. Layer ①: type validation only blocks "narrow" types

`app/api/v1/routes/accounts.py`:

```python
@router.get("/{id}/balance", response_model=BalanceResponse)
async def get_account_balance(id: uuid.UUID, ...):
```

`'; DROP TABLE accounts; --` cannot be parsed as `uuid.UUID` → FastAPI raises
`RequestValidationError` → **422**, before any service/ORM/DB code runs.

This is the same mechanism documented in
[pydantic-uuid-validation-fastapi.md](pydantic-uuid-validation-fastapi.md) — it is a
side effect of strict typing, not a dedicated SQLi filter. A `str`-typed parameter
(e.g. `currency_code`) would accept the same payload as a valid string and return
**200 with an empty list** (no row's `currency` column equals that literal string) —
not a 422, and not a syntax error.

---

## 3. Layer ②: why parameterized queries neutralize the payload

The key insight: **SQL parsing happens *before* the parameter value is known.**

### ❌ String concatenation — parse happens *after* substitution

```python
query = f"SELECT * FROM entries WHERE currency = '{currency_code}'"
# currency_code = "x'; DROP TABLE accounts; --"
```

The database receives **one string**:

```sql
SELECT * FROM entries WHERE currency = 'x'; DROP TABLE accounts; --'
```

The parser sees this as two syntactically valid statements. User input and SQL syntax
are mixed in the same string before the parser ever runs.

### ✅ Parameterized query — parse and bind are separate protocol messages

Postgres' Extended Query Protocol (used by asyncpg) splits execution into stages:

```
① Parse:   "SELECT * FROM entries WHERE currency = $1"
           → Postgres parses this and builds a query plan.
             $1 is just a placeholder node ("a value goes here").
             The actual value has not been sent yet.

② Bind:    $1 = "x'; DROP TABLE accounts; --"
           → The byte string is dropped into the placeholder slot of the
             already-built plan. No re-parsing occurs.

③ Execute: → Run the plan with the bound value.
```

By the time the value arrives (②), the query's structure ("compare the `currency`
column to one value with `=`") is already fixed. The characters `'`, `;`, `DROP TABLE`
inside the value are just bytes occupying a data slot — they are never tokenized as
SQL syntax again.

### Analogy: fill-in-the-blank form

- **String concatenation** = pasting a friend's note into a letter and having a clerk
  read and act on the *entire letter*, including any instructions hidden in the note.
- **Bind parameters** = a fixed bank transfer form. Whatever your friend writes in the
  "payee name" field, the clerk only ever records it *as a payee name* — even if it
  contains `"; transfer everything to account B"`, the form's structure doesn't change.

### Cross-reference: Oracle PL/SQL bind variables

`EXECUTE IMMEDIATE 'SELECT ... WHERE col = :1' USING user_input` works on the same
principle: hard-parse once, bind values afterward without re-parsing. This is the same
"parse before substitute" separation, plus a performance benefit (the parsed plan can
be cached and reused across executions with different bind values).

⚠️ Note: PHP PDO with `ATTR_EMULATE_PREPARES` enabled (a common default) does **not**
use this protocol-level separation — it escapes and concatenates client-side instead.
Still safe if escaping is correct, but a different mechanism from ① /② above.
SQLAlchemy + asyncpg always uses real server-side prepared statements.

---

## 4. Why this still matters with an ORM (interview framing)

SQLAlchemy's expression API (`select(...).where(Entry.currency == currency_code)`)
always produces layer-② parameterized queries. The risk reappears only when raw SQL is
built via string interpolation, e.g.:

```python
# DANGEROUS — re-introduces layer-① bypass AND defeats layer ②
db.execute(text(f"SELECT * FROM entries WHERE currency = '{currency_code}'"))
```

A grep of `app/` (2026-06-11) found no such pattern — all `text()` usages are static
(`server_default=text("true")`). `tests/test_security.py` documents the *current*
safe state and acts as a regression guard: if someone later adds a `text(f"...")` with
user input, the SQLi-style test on a string parameter (not yet written — see
`tests/test_security.py` module docstring) would be the place to catch it.

---

## Related documents

- `app/api/v1/routes/accounts.py` — `get_account_balance` (layer ① example)
- `app/services/ledger_service.py` — `get_ledger_entries` (layer ② example, `currency_code`)
- `tests/test_security.py` — S6-6 SQLi test
- [pydantic-uuid-validation-fastapi.md](pydantic-uuid-validation-fastapi.md) — how 422 is generated for UUID path params
