# asyncpg: PostgreSQL enum values must match DB definition exactly

## Error

```
asyncpg.exceptions.InvalidTextRepresentationError: invalid input value for enum userrole: "admin"
```

## Root Cause

When using raw SQL (`text()`) with asyncpg, enum values must match the
PostgreSQL enum definition **exactly**. In this project, Alembic migrations
create enums using Python enum member **names** (uppercase), not values
(lowercase):

```python
# Migration creates: ENUM ('ADMIN', 'AUDITOR')
sa.Enum('ADMIN', 'AUDITOR', name='userrole')
```

SQLAlchemy ORM handles the name-to-value mapping automatically, but raw SQL
bypasses this. Additionally, asyncpg's prepared statement system rejects enum
values passed as bind parameters entirely — even with `CAST(:param AS enumtype)`.

## Resolution

For raw SQL with asyncpg, embed enum values directly as SQL literals (safe
when values are constants, not user input):

```python
# Does NOT work — asyncpg rejects enum bind params
text("INSERT INTO users (..., role) VALUES (..., :role)")  # {'role': 'ADMIN'}

# Does NOT work — CAST doesn't help
text("INSERT INTO users (..., role) VALUES (..., CAST(:role AS userrole))")

# Works — literal in SQL
text("INSERT INTO users (..., role) VALUES (..., 'ADMIN')")
```

### Enum values in this project (all uppercase)

| Enum name | Values |
|-----------|--------|
| `userrole` | `ADMIN`, `AUDITOR` |
| `accounttype` | `ASSET`, `LIABILITY`, `EQUITY`, `REVENUE`, `EXPENSE` |
| `transactionstatus` | `PENDING`, `POSTED`, `VOIDED` |
| `direction` | `DEBIT`, `CREDIT` |

## References

- asyncpg prepared statement documentation
- Applied in: `scripts/seed_demo_user.py`
- Commit: `fix(s9-1-5): use uppercase enum values matching PostgreSQL definition`
