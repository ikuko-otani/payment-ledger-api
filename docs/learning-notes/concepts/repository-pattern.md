# Repository Pattern

**Date**: 2026-06-17  
**Context**: S7-7 — TD-008 リポジトリ層分離

---

## What is the Repository Pattern?

A design pattern that introduces a dedicated class between the service layer and the database. Services declare *what data they need* using domain-language method names; the repository handles *how to fetch it* using the ORM.

```
Without Repository:
  Route → Service(db: AsyncSession) → db.execute(select(Account)...)

With Repository:
  Route → Service(repo: AccountRepository) → repo.find_active_by_ids(ids)
                                           ↘ SQLAlchemyAccountRepository._db.execute(...)
```

**PHP analogy**: Replacing `$pdo->query("SELECT ...")` with `$accountRepository->findActiveByIds($ids)`.

---

## Why Use It? (Key Benefits)

### 1. Intent expressed through method names

```python
# Before — reader must parse SQLAlchemy to understand the intent
result = await db.execute(
    select(Account.id, Account.currency).where(
        Account.id.in_(account_ids),
        Account.is_active.is_(True),
    )
)

# After — intent is clear from the name
found_ids = await account_repo.find_active_by_ids(account_ids)
```

### 2. Unit-testable services (the primary motivation)

Without Repository, every service test requires a real PostgreSQL instance (via testcontainers). With Repository, a fake in-memory implementation suffices:

```python
class FakeAccountRepository(AccountRepository):
    def __init__(self):
        self._accounts: dict[uuid.UUID, Account] = {}

    async def save(self, account: Account) -> Account:
        account.id = uuid.uuid4()
        self._accounts[account.id] = account
        return account

    async def list_all(self) -> list[Account]:
        return list(self._accounts.values())

# Test — no DB, no testcontainers, fast
async def test_create_account_sets_correct_type():
    result = await create_account(
        FakeAccountRepository(), FakeAuditRepository(), payload, current_user
    )
    assert result.account_type == AccountType.ASSET
```

This is the **single biggest reason** the Repository pattern is recommended for service-layer code.

### 3. ORM change is localized

```
Without Repository: changing ORM requires rewriting every service
With Repository:    only the SQLAlchemy*Repository classes need rewriting;
                    services depend on the ABC, not SQLAlchemy
```

---

## Trade-offs

| Downside | Mitigation |
|---|---|
| More files (5–6 new files for this repo) | Pays off as the codebase grows |
| Can feel over-engineered for simple CRUD | Acceptable to omit in small personal projects |
| Extra abstraction layer — harder to trace in debugger | IDE jump-to-definition lands on `SQLAlchemy*Repository` |

---

## Python Implementation: ABC vs Protocol

Two options for defining the abstract interface:

| | `ABC` + `@abstractmethod` | `Protocol` |
|---|---|---|
| Subtyping | Nominal (explicit inheritance required) | Structural (duck typing — no inheritance needed) |
| PHP analogy | `abstract class AccountRepository` | No direct PHP equivalent |
| Runtime enforcement | `TypeError` on instantiation if method missing | No runtime check (type-checker only) |
| When to prefer | When the intent to implement an interface should be explicit | When mocking / third-party integration where inheritance is impractical |

This repo uses `ABC` for explicitness. The ABC base class conveys "this class is intentionally implementing a contract."

---

## FastAPI Depends Chain — Why Overriding `get_db` Is Sufficient

```
Route parameter:
  repo: AccountRepository = Depends(get_account_repository)

get_account_repository:
  def get_account_repository(db: AsyncSession = Depends(get_db)) -> AccountRepository:
      return SQLAlchemyAccountRepository(db)
```

FastAPI resolves dependencies as a DAG (directed acyclic graph). Overriding `get_db` in tests propagates automatically through the entire graph — `get_account_repository` receives the test session without any additional override.

```python
# conftest.py — one override covers all repositories
fastapi_app.dependency_overrides[get_db] = override_get_db
```

---

## Interview Question

**"Why did you introduce the Repository pattern?"**

Strong answer: *"To decouple the service layer from SQLAlchemy so that service unit tests can run without a database. The service depends on an abstract interface (ABC), so tests can inject a fast in-memory fake instead of a real PostgreSQL instance."*

---

## Related

- `docs/adr/` — no ADR for this yet; may warrant one when TD-008 is fully closed
- `docs/learning-notes/concepts/three-layer-architecture-route-vs-service.md`
- `docs/tech-debt.md` TD-008
