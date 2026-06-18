# S7-7: Repository Layer Separation (TD-008 partial)

**Date**: 2026-06-17 – 2026-06-18  
**Branch**: `feature/s7-7-repository-layer-separation`  
**PR**: #80  
**Status**: Merged to main

---

## Goal

Introduce the Repository pattern (TD-008) for Account, Audit, and User services.
Define abstract interfaces (ABC) for all 5 repositories; provide SQLAlchemy implementations
for 3 of them. Migrate 4 routes away from direct `AsyncSession` usage.

---

## Step C Walkthrough

### What changed

| File | Change |
|------|--------|
| `app/repositories/__init__.py` | New package |
| `app/repositories/account_repository.py` | `AccountRepository` ABC + `SQLAlchemyAccountRepository` (save, list_all, find_active_by_ids, calculate_balance) |
| `app/repositories/audit_repository.py` | `AuditRepository` ABC + `SQLAlchemyAuditRepository` (log, list_logs) |
| `app/repositories/user_repository.py` | `UserRepository` ABC + `SQLAlchemyUserRepository` (save, find_by_email) |
| `app/repositories/transaction_repository.py` | `TransactionRepository` ABC only (impl in S7-8) |
| `app/repositories/currency_repository.py` | `CurrencyRepository` ABC only (impl in S7-8) |
| `app/services/account_service.py` | Signature: `(db) →` `(repo, audit_repo)` |
| `app/services/user_service.py` | Signature: `(db) →` `(repo, audit_repo)` |
| `app/api/v1/routes/accounts.py` | `DbDep` removed; `AccountRepoDep` + `AuditRepoDep` injected |
| `app/api/v1/routes/audit_logs.py` | `DbDep` removed; `AuditRepoDep` injected; calls `repo.list_logs()` directly |
| `app/api/v1/routes/users.py` | `DbDep` removed; `UserRepoDep` + `AuditRepoDep` injected |
| `app/api/v1/routes/auth.py` | `DbDep` removed; `UserRepoDep` injected; calls `user_repo.find_by_email()` |
| `tests/test_users.py` | `test_create_user_concurrent_duplicate_email_returns_conflict` updated to construct `SQLAlchemyUserRepository` / `SQLAlchemyAuditRepository` directly |

### Key design choices

**ABC over Protocol**  
`ABC` + `@abstractmethod` chosen for explicitness — mirrors PHP `abstract class` semantics.
Subclasses must explicitly inherit and implement all abstract methods; violation surfaces as
`TypeError` at instantiation. `Protocol` (structural subtyping) would also work but is
less familiar and harder to explain in an interview.

**Session ownership stays in `get_db`**  
Repositories accept `AsyncSession` in `__init__` but do not call `commit()` or control the
transaction boundary. `get_db` (the FastAPI generator dependency) still owns commit/rollback.
This preserves the existing transaction semantics unchanged.

**`calculate_balance` moved into `AccountRepository`**  
The `accounts.py` route calls `/balance`, which previously called `services/balance.py`.
Moving the query into `AccountRepository.calculate_balance()` lets `accounts.py` use only
`AccountRepoDep` — no residual `DbDep`. `balance.py` is now dead code in production
(tracked as TD-036); `test_balance.py` still imports it directly.

**`audit_service.log_action(db, ...)` kept unchanged**  
`transaction_service.py` and `currency_service.py` (migrated in S7-8) still call
`log_action(db, ...)`. Changing the signature now would break those services before
their own migration. Backward compatibility maintained through S7-8.

**`SQLAlchemyUserRepository.save()` handles IntegrityError**  
The TOCTOU race-condition guard (TD-031) moved from `user_service.py` into the repository:
`save()` wraps `flush()` in `try/except IntegrityError` and raises `ConflictError`.
Services no longer need to catch SQLAlchemy exceptions directly.

### FastAPI Depends propagation

```
AccountRepoDep = Depends(get_account_repository)
get_account_repository(db: AsyncSession = Depends(get_db))
```

Overriding `get_db` in `conftest.py` automatically propagates to all repository factories.
No changes to `conftest.py` were needed.

---

## Key Takeaways

### What did I learn?

I learned that Python `ABC` maps almost directly to PHP `abstract class`: you inherit from `ABC`,
mark methods with `@abstractmethod`, and Python raises `TypeError` if a subclass fails to
implement one. The `Protocol` alternative exists for structural subtyping (duck typing) but
requires more explanation in interviews.

I also learned how FastAPI resolves dependencies as a directed acyclic graph. Overriding a
leaf dependency (`get_db`) propagates to every function that depends on it — including
repository factories defined in separate files. This meant the entire test suite needed
only one test file updated despite four routes and two services being migrated.

### What would I do differently?

I would add TD-036 (`balance.py` dead code) to `tech-debt.md` immediately during
implementation rather than at the end of Step D. The CLAUDE.md rule is "register debt
the moment it is identified" — I caught it late this time.

I would also think earlier about whether `audit_service.log_action` needs a backward-
compatible wrapper or whether it should be removed entirely. The current approach
(keeping it unchanged) is pragmatic but leaves a mixed-migration state across services
for the duration of S7-7 → S7-8.

### What surprised me?

Only one test file needed updating. I expected more direct service calls scattered across
the test suite, but most tests go through the HTTP client. The only exception was the
TOCTOU concurrency test, which by design creates two independent `AsyncSession` objects —
that cannot be done through the HTTP layer.

### What is worth remembering for future goals?

- **Incremental migration**: refactor one service/route at a time. Keeping `audit_service.log_action(db, ...)` unchanged for unmigrated services is a safe pattern.
- **Repository owns IntegrityError translation**: mapping `sqlalchemy.exc.IntegrityError` → domain `ConflictError` inside `save()` keeps services clean. Services no longer need SQLAlchemy imports for error handling.
- **Test granularity**: concurrency tests (TOCTOU) must call service functions directly — they cannot be expressed through the HTTP layer because request-session isolation hides the race.
- **`get_db` override is sufficient**: in FastAPI, a single `dependency_overrides[get_db]` covers all downstream repository factories. No need to override each repository individually in tests.

---

## Related

- `docs/learning-notes/concepts/repository-pattern.md` — concept explanation with PHP analogies
- `docs/tech-debt.md` TD-008 (partially resolved), TD-036 (new)
- S7-8 will complete TD-008: TransactionRepository + CurrencyRepository implementations
