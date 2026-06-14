# Counting SQL queries in tests with SQLAlchemy's `before_cursor_execute` event

> Date: 2026-06-14 | Goal: S7-2 (TD-030)
> Purpose: Reference note on how to assert "this code issues at most N queries"
> in a test, without mocking the database — used to guard against N+1
> regressions in `_resolve_usd_conversion_rate` (TD-030).

---

## 1. The problem this solves

TD-030 was an N+1: `_get_converted_amount_usd` was called once per `Entry`,
each call issuing up to 3 queries (`currencies` x2 + `exchange_rates` x1) even
though `currency_code` and `transaction_date` are the same for every entry in
one transaction. With N entries, that's up to `3 * N` queries.

After the fix, the rate is resolved **once per transaction** regardless of N.
A test that just checks the *result* (converted amounts) wouldn't catch a
regression back to the N+1 — the numbers would still be correct, just slower.
We need a test that asserts on **how many queries were issued**.

## 2. SQLAlchemy's event system: `before_cursor_execute`

SQLAlchemy fires a `before_cursor_execute` event immediately before any SQL
statement is sent to the DBAPI cursor. You can register a listener function
that receives the raw SQL text every time this happens:

```python
from sqlalchemy import event

def _capture(conn, cursor, statement, parameters, context, executemany):
    statements.append(statement)

event.listen(engine.sync_engine, "before_cursor_execute", _capture)
```

This is a general-purpose hook — it fires for *every* statement on that
engine (SELECT, INSERT, UPDATE, ...), not just ones you're interested in. You
filter afterwards.

💡 PHP/PDO comparison: PDO has no equivalent hook out of the box. The closest
analogue is Doctrine ORM's `Doctrine\DBAL\Logging\SQLLogger`, which you attach
to a `Connection` to log every query — same "subscribe to a stream of
executed statements" idea.

## 3. Why `engine.sync_engine`?

The test fixtures use `AsyncEngine` (asyncpg). `AsyncEngine` is a thin async
wrapper around a regular (sync) `Engine` — the event system itself is
implemented on the sync `Engine`/`Connection` objects underneath. So to attach
a `before_cursor_execute` listener, you go through `engine.sync_engine`:

```python
event.listen(engine.sync_engine, "before_cursor_execute", _capture)
```

The event still fires correctly for statements executed via `AsyncSession` —
async/await only affects *how* the coroutine waits for I/O, not which
SQLAlchemy core objects the statement execution flows through.

## 4. Scope the listener tightly: attach/detach around the call under test

```python
event.listen(engine.sync_engine, "before_cursor_execute", _capture)
try:
    tx = await create_transaction(db_session, payload, user_id=test_user_id)
finally:
    event.remove(engine.sync_engine, "before_cursor_execute", _capture)
```

If you attach the listener before seeding test data (creating `Currency`,
`User`, `ExchangeRate`, `Account` rows), those `INSERT` statements get
captured too, polluting the count. Attaching only around the function call
under test keeps the captured list focused on what that function actually
does. `event.remove` in a `finally` block ensures the listener doesn't leak
even if the call raises.

## 5. Filter the captured statements by table name

`create_transaction` issues many queries beyond the conversion-rate lookup
(account existence check, `INSERT` into `transactions`/`entries`, a final
`SELECT ... selectinload`, an audit-log insert). To isolate just the
conversion-rate queries:

```python
conversion_queries = [
    s for s in statements
    if "currencies" in s.lower() or "exchange_rates" in s.lower()
]
assert len(conversion_queries) <= 3
```

`_resolve_usd_conversion_rate` queries `currencies` twice (resolve
`from_currency`, resolve `USD`) and `exchange_rates` once — 3 queries total,
**called once per transaction**. With 4 entries:

- Before the fix: `4 * 3 = 12` conversion queries → `12 <= 3` fails.
- After the fix: `3` conversion queries regardless of entry count → `3 <= 3`
  passes.

The threshold `<= 3` isn't really about the number 3 — it's a proxy for "this
count doesn't grow with the number of entries."

## 6. General pattern for future N+1 checks

This same shape — `event.listen` around the call, filter by table name,
assert a fixed upper bound independent of input size — can be reused for any
future suspected N+1 (e.g. in `list_transactions` or `list_accounts` if a
related table is loaded per-row instead of via `selectinload`/`joinedload`).

---

## Related

- [[sqlalchemy-query-reuse]] (`docs/learning-notes/concepts/sqlalchemy-query-reuse.md`) —
  TD-024's "resolve once, reuse the result" pattern; TD-030 applies the same
  idea but to a value (`Decimal` rate) instead of a lookup dict.
- `docs/tech-debt.md` TD-030 — the N+1 this test guards against.
- `tests/test_transactions.py::test_non_usd_transaction_resolves_conversion_rate_once`
