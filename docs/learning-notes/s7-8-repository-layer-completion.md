# S7-8: Repository Layer Completion (TD-008 Close)

**Date**: 2026-06-18
**Branch**: `feature/s7-8-repository-layer-completion`
**PR**: #81
**Goal**: Implement `SQLAlchemyCurrencyRepository` and `SQLAlchemyTransactionRepository`,
migrate all remaining routes to the repository pattern, and close TD-008.

---

## Step C Walkthrough

### What was implemented

#### C-1: `SQLAlchemyCurrencyRepository`

Added to `app/repositories/currency_repository.py`. Six methods:

- `list_all()` — `SELECT ... ORDER BY code`
- `save(currency)` — `add` + `flush` + `refresh`
- `find_by_code(code)` — used by `_resolve_usd_conversion_rate`
- `list_exchange_rates(from_id, to_id, effective_date)` — dynamic WHERE
- `save_exchange_rate(rate)` — catches `IntegrityError` → `ConflictError`
- `find_exchange_rate(from_id, to_id, date)` — used by `_resolve_usd_conversion_rate`

#### C-2: `SQLAlchemyTransactionRepository`

Added to `app/repositories/transaction_repository.py`.

- `save(transaction, entries)` — flushes Transaction first to obtain its ID, then sets
  `entry.transaction_id` for each entry, flushes entries, and reloads with `selectinload`.
  The key design choice: the repository owns the `transaction_id` assignment, not the service.
- `list_all(limit, offset)` — `selectinload(Transaction.entries)` with deterministic `ORDER BY`.

#### C-3: `SQLAlchemyLedgerRepository`

New file `app/repositories/ledger_repository.py`. Moved the `contains_eager` JOIN query
from `ledger_service.get_ledger_entries` into `list_entries()`. `LedgerRepository` was
outside the DONE conditions but added for route consistency.

#### C-4: `currency_service.py` rewrite

Changed all function signatures from `db: AsyncSession` to `repo: CurrencyRepository` +
`audit_repo: AuditRepository`. Removed all SQLAlchemy direct imports. The `log_action`
calls became `audit_repo.log(...)`.

#### C-5: `transaction_service.py` rewrite

- `_resolve_usd_conversion_rate(db, ...)` → `_resolve_usd_conversion_rate(currency_repo, ...)`
  The two `select(Currency)` calls replaced by `currency_repo.find_by_code()`.
  The `select(ExchangeRate)` call replaced by `currency_repo.find_exchange_rate()`.
- `create_transaction(db, ...)` → takes four repos: `account_repo`, `currency_repo`,
  `tx_repo`, `audit_repo`. Entries are now built *without* `transaction_id`
  (the repository assigns it during `save()`).

#### C-6: `audit_service.py` deleted

After C-4 and C-5, both `log_action` and `list_audit_logs` had zero callers in
production code — `audit_logs.py` already used `repo.list_logs()` since S7-7.
The file was deleted as dead code.

#### C-7 / C-8: Route migrations

- `currencies.py` / `exchange_rates.py`: `DbDep` removed, `CurrencyRepoDep` +
  `AuditRepoDep` added. Service calls updated to pass repos.
- `ledger.py`: `DbDep` removed, `LedgerRepoDep` added. Route now calls `repo.list_entries(...)`.
- `transactions.py`: `DbDep` **kept** for the explicit `await db.commit()` (TD-018 fix).
  Four `*RepoDep` aliases added. `list_transactions` uses `tx_repo.list_all()`.
  `post_transaction` passes all four repos to `create_transaction`.

#### C-9: Test updates (11 call sites)

All tests that called `create_transaction(db_session, payload, user_id=...)` were updated
to construct four `SQLAlchemy*Repository(db_session)` instances and pass them.

A `_make_repos(db_session)` helper was introduced in `test_transactions.py` and
`test_transactions_multi_currency.py` to reduce repetition.

`test_audit_log.py::test_audit_failure_rolls_back_transaction` updated with the same
pattern (no helper, repos created inline for clarity).

---

## Key Takeaways

### What did I learn?

I learned that the Repository pattern's real value shows up at the **boundary of
responsibility**: the service layer owns business rules (validation, conversion rate
calculation, balance checking), and the repository owns persistence mechanics
(how objects are saved, in what order, which SELECT strategy is used).

The clearest example was `TransactionRepository.save(transaction, entries)`: the service
builds Entry objects *without* `transaction_id`, passes them to the repo, and the repo
assigns the ID after the first `flush()`. This was a concrete answer to the question
"who decides when and how an entity gets its database-generated ID."

I also learned how FastAPI's **dependency injection caching** makes it safe to have both
`db: DbDep` and `tx_repo: TransactionRepoDep` in the same route handler. Because FastAPI
caches `Depends(get_db)` within a single request, both parameters share the same
`AsyncSession` object. The explicit `await db.commit()` in `post_transaction` commits
everything that the repositories flushed — this is why we can keep repos *and* still
commit from the route.

### What would I do differently?

I would define the `_make_repos(db_session)` helper at the start of the test update
work, before writing any of the 11 test changes. In this goal, I recognized the pattern
during the first change and extracted it — but doing it proactively from the beginning
would have been cleaner.

### What surprised me?

I was surprised that `audit_service.py` became *entirely* dead code. I expected
`log_action` to be dead after this migration, but I had forgotten that `list_audit_logs`
was also already dead since S7-7 (when `audit_logs.py` switched to `repo.list_logs()`).
Deleting the whole file felt more satisfying than I expected.

The other surprise: `ledger.py` was the simplest migration because `get_ledger_entries`
had no repos or audit calls — just one query that moved directly into
`SQLAlchemyLedgerRepository.list_entries()`.

### What is worth remembering for future goals?

1. **FastAPI DI caching = shared session within a request.** All `Depends(get_db)` calls
   in one request return the same `AsyncSession`. This is the invariant that allows
   mixing `db: DbDep` with `*RepoDep` in one route handler without session divergence.

2. **`transaction_id` assignment belongs to the repository.** When a child entity's FK
   depends on a parent entity's DB-generated ID, the repository's `save()` must flush
   the parent first, then set the FK on the children. The service should not need to
   know this ordering.

3. **`CurrencyRepository` as a cross-service dependency.** `TransactionRepository`
   (via the service) depends on `CurrencyRepository` for USD conversion rate resolution.
   In future architectures, this kind of cross-cutting repository dependency is a signal
   that the shared data (`Currency`, `ExchangeRate`) may benefit from a dedicated
   read-model or caching layer.

4. **Dead-code deletion at the migration boundary.** When all callers of a module are
   replaced in the same PR, delete the module in the same PR — not in a follow-up.
   Leaving dead code behind creates confusion about whether it's intentionally kept.

---

## References

- `ARCHITECTURE.md` — Repository layer design
- `docs/tech-debt.md` — TD-008 (now Resolved)
- `docs/learning-notes/s7-7-repository-layer-separation.md` — S7-7 foundation
- `docs/adr/` — No new ADR; this goal completes a pattern established in S7-7
