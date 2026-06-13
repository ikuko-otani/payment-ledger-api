# SQLAlchemy 2.0 — what `select(Model)` generates, and reusing one query result for multiple purposes

> Date: 2026-06-13 | Goal: S7-1 (TD-024)
> Purpose: Reference note on what `select(Account).where(...)` actually sends to
> PostgreSQL, what `.scalars().all()` returns, and why building a lookup dict from
> an already-fetched result avoids a second round trip.

---

## 1. `select(Account).where(...)` is not magic — it's generated SQL

```python
result = await db.execute(
    select(Account).where(
        Account.id.in_(account_ids),
        Account.is_active.is_(True),
    )
)
```

This generates (conceptually):

```sql
SELECT accounts.id, accounts.code, accounts.name, accounts.account_type,
       accounts.currency, accounts.is_active, accounts.created_at, accounts.updated_at
FROM accounts
WHERE accounts.id IN (:id_1, :id_2, ...)
  AND accounts.is_active = true
```

`select(Account)` enumerates every mapped column of `Account` — functionally the
same as `SELECT *` for that table. `account_ids` (a Python `set[UUID]`) is expanded
into bind parameters, exactly like a parameterized `IN (...)` clause.

### PHP/PDO comparison

```php
$placeholders = implode(',', array_fill(0, count($ids), '?'));
$stmt = $pdo->prepare("SELECT * FROM accounts WHERE id IN ($placeholders) AND is_active = true");
$stmt->execute($ids);
```

`.in_(account_ids)` is the SQLAlchemy equivalent of building that placeholder list
and binding the params — including the same SQL-injection protection.

---

## 2. `.scalars().all()` is the ORM equivalent of `fetchAll()`

```python
accounts = result.scalars().all()
```

Where PDO's `fetchAll(PDO::FETCH_ASSOC)` returns a list of associative arrays,
`.scalars().all()` returns a list of `Account` **objects** (one per row), with
attribute access (`account.id`, `account.currency`, ...) instead of array keys.

---

## 3. Reuse vs. re-query: avoid a second round trip

Context — TD-024 needed to check `entry.currency == account.currency` for every
entry, but the existing code only used the query result to build a *set* of found
IDs (`found_ids = {row.id for row in ...}`) for an existence check.

The first idea was: keep fetching full `Account` objects (already happening for
the existence check), and just also read `.currency` off the same objects:

```python
accounts = result.scalars().all()
found_ids = {account.id: account.currency for account in accounts}  # dict, not set
missing = account_ids - found_ids.keys()
```

**This is not about the dict comprehension being "fast."** It's pure in-memory
Python over a handful of rows — negligible either way. The actual point is:

> The `Account` rows were already fetched for the existence check. `currency` is
> already one of the columns on each `Account` object. Building a dict from data
> you already have in memory costs nothing extra — issuing a **second query** to
> fetch `(id, currency)` pairs would cost a full DB round trip.

| Approach | DB round trips |
|---|:---:|
| Reuse the existing query result → build dict in Python | 1 |
| Separate "existence check" query + separate "get currencies" query | 2 |

DB round trips are typically orders of magnitude slower than in-process loops, so
"fetch everything you need in one query, then shape it in Python" is the default
heuristic — never add a second query just to get one more column you could have
selected in the first one.

---

## 4. But narrow the SELECT to the columns actually used

The follow-up question is sharper: does the *first* query need to be
`select(Account)` (all ~8 columns) at all?

Looking at `create_transaction` end-to-end, the `Account` rows fetched here are
**only ever used for `.id` and `.currency`** — `code`, `name`, `account_type`,
`is_active`, `created_at`, `updated_at` are never read afterwards (`is_active` is
only used as a `WHERE` filter, which doesn't require selecting the column).

So the right query is the narrow one from the start:

```python
result = await db.execute(
    select(Account.id, Account.currency).where(
        Account.id.in_(account_ids),
        Account.is_active.is_(True),
    )
)
found_ids = {account_id: currency for account_id, currency in result.all()}
missing = account_ids - found_ids.keys()
```

Two mechanical changes from the `select(Account)` version:
- `select(Account.id, Account.currency)` — select only the columns this function
  needs. `WHERE Account.is_active` still works even though `is_active` isn't in
  the SELECT list — the WHERE clause is independent of the SELECT list.
- `result.all()` instead of `result.scalars().all()` — `.scalars()` unwraps a
  single-column/ORM-object result. With multiple columns, `result.all()` returns
  `Row` objects, which unpack like tuples: `for account_id, currency in result.all()`.

**Interview-relevant framing:** "fetch full ORM objects you can reuse for
multiple checks" vs. "fetch only the columns you need" — the right choice depends
on whether the result is reused for more than the columns being selected. Here it
isn't, so the narrow query is strictly better: same number of round trips, less
data transferred, and the code is more honest about what this function actually
depends on.

---

## Related documents

- `app/services/transaction_service.py` — `create_transaction` (TD-024 fix)
- [sqlalchemy-async-session-commit-pattern.md](sqlalchemy-async-session-commit-pattern.md)
  — related note on session/query lifecycle
- `docs/tech-debt.md` — TD-024
