# S4-1: Currency / ExchangeRate Model + Alembic Migration

**Date**: 2026-05-26
**Branch**: feature/s4-1-currency-exchangerate-model
**Goal**: Design and create two tables as the foundation for multi-currency support.
Resolves TD-012.

---

## Step C Walkthrough

### What was built

Two new SQLAlchemy mapped models and an Alembic migration:

| File | Purpose |
|---|---|
| `app/models/currency.py` | ISO 4217 currency master (`currencies` table) |
| `app/models/exchange_rate.py` | Point-in-time FX rates (`exchange_rates` table) |
| `app/models/__init__.py` | Both models registered on `Base.metadata` |
| `alembic/versions/…add_currencies_and_exchange_rates_tables.py` | Migration |

### Currency model

```python
class Currency(Base):
    __tablename__ = "currencies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(3), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    decimal_places: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

Key design point: `decimal_places` column resolves **TD-012** — clients no longer need
to know ISO 4217 scales externally (JPY=0, EUR=2, USD=2). The DB is the source of truth.

### ExchangeRate model

```python
class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint(
            "from_currency_id",
            "to_currency_id",
            "effective_date",
            name="uq_exchange_rate_pair_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    from_currency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("currencies.id"), nullable=False)
    to_currency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("currencies.id"), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

### Design decisions

**1. `Numeric(18, 8)` not `Float`**

`Float` is IEEE 754 binary floating-point. It cannot represent base-10 fractions
exactly: `1.1 + 2.2 = 3.3000000000000003`. `NUMERIC` is decimal fixed-point.
In Python, `Mapped[Decimal]` pairs with `Numeric` so arithmetic uses `decimal.Decimal`,
where `Decimal("1.1") + Decimal("2.2") == Decimal("3.3")` holds exactly.
This is a non-negotiable fintech requirement.

**2. Composite UNIQUE on `(from_currency_id, to_currency_id, effective_date)`**

Without this constraint, multiple rows for the same currency pair on the same day
would be valid — the DB could not determine which rate is authoritative.
The constraint eliminates ambiguity at the storage layer with no application-side
guard code needed.

**3. `effective_date` as `Date` not `DateTime`**

FX rates apply for an entire calendar day regardless of timezone. Using `DateTime`
would require timezone-aware comparisons and could cause "wrong day" bugs for users
in different timezones. `Date` makes the intent explicit and timezone-independent.

**4. `__table_args__` tuple syntax**

`__table_args__` receives a tuple of constraint/index objects. Even a single item
requires a trailing comma: `(UniqueConstraint(...),)`. Without the comma, Python
parses it as a parenthesized expression, not a tuple, and SQLAlchemy raises an error.

**5. Registering models in `app/models/__init__.py`**

Alembic's `env.py` does `import app.models`, which executes `__init__.py` and
registers every model on `Base.metadata`. A model file that is not imported here
will be silently ignored by `autogenerate` — the migration will be empty.

### Alembic autogenerate output (expected)

```
op.create_table("currencies", ...)          # decimal_places as sa.Integer()
op.create_table("exchange_rates", ...)      # rate as sa.Numeric(precision=18, scale=8)
op.create_unique_constraint(
    "uq_exchange_rate_pair_date",
    "exchange_rates",
    ["from_currency_id", "to_currency_id", "effective_date"]
)
op.create_foreign_key(...)                  # → currencies.id (x2)
op.create_foreign_key(...)                  # → users.id
```

---

## Key Takeaways

**What did I learn?**

I learned that `Numeric(18, 8)` is the correct SQLAlchemy type for financial rate
columns, paired with `Mapped[Decimal]` on the Python side. I had seen this rule
stated before but this was the first time I wired it end-to-end: column type →
Python type annotation → `decimal.Decimal` arithmetic. I also learned that
`__table_args__` is where composite constraints live in SQLAlchemy 2.0, and that
the trailing comma in the tuple is a real gotcha.

**What would I do differently?**

I would verify that `app/models/__init__.py` is up to date *before* running
`autogenerate` rather than after noticing the migration came out empty.
The check is cheap (two lines) and prevents a wasted migration file.

**What surprised me?**

The `effective_date: Mapped[date]` annotation requires `from datetime import date`
as a separate import — not just `datetime`. Easy to overlook when all other
timestamp columns use `datetime`. The `Date` SQLAlchemy type also needs its own
import (`from sqlalchemy import Date`).

**What is worth remembering for future goals?**

- `Numeric(precision, scale)` + `Mapped[Decimal]` = exact decimal arithmetic in fintech.
  Never use `Float` for money or rates.
- `__table_args__ = (Constraint(...),)` — the trailing comma is mandatory.
- Composite UNIQUE constraints should include a named `name=` argument for readable
  migration output and easier DB administration.
- `decimal_places` on the Currency master table resolves TD-012 cleanly: one column
  addition at model creation time costs nothing, whereas adding it later requires a
  new migration that touches an already-referenced table.
