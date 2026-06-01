# Pydantic Field Validation — `Field(gt=)` and Constraint Annotations

**Date**: 2026-06-01
**Context**: S4-7 — Adding `gt=Decimal("0")` constraint to `ExchangeRateCreate.rate`

---

## What is `Field(gt=)`?

A way to embed input constraints directly into a Pydantic field definition,
so that any object of that class is guaranteed to contain only valid data
at construction time.

```python
from decimal import Decimal
from pydantic import BaseModel, Field

class ExchangeRateCreate(BaseModel):
    rate: Decimal = Field(gt=Decimal("0"))  # rejects 0 and negative values
```

---

## Comparison with PHP

In PHP, validation is typically written separately from the data class:

```php
// PHP — validation written "after the fact"
if ($rate <= 0) {
    throw new InvalidArgumentException("rate must be positive");
}
```

In Pydantic, the constraint lives with the field definition. By the time an
object exists, it has already passed validation — no separate check needed.

---

## Common `Field()` Constraints

| Argument | Meaning | Example use |
|---|---|---|
| `gt=0` | greater than | `rate > 0` |
| `ge=0` | greater than or equal | `amount >= 0` |
| `lt=100` | less than | `percent < 100` |
| `le=100` | less than or equal | `percent <= 100` |
| `min_length=1` | minimum string length | non-empty name |
| `max_length=50` | maximum string length | |
| `description="..."` | shown in OpenAPI docs | |

---

## FastAPI Integration

FastAPI uses Pydantic for request parsing, so `Field(gt=0)` automatically
produces an HTTP 422 response — no manual error handling required.

```
POST /exchange-rates  {"rate": "0", ...}
         ↓
  Pydantic checks Field(gt=0)
         ↓
  FastAPI returns 422 Unprocessable Entity automatically
```

---

## `Field()` vs `@field_validator` vs `@model_validator`

```python
# Use Field — simple numeric or string constraints
rate: Decimal = Field(gt=Decimal("0"))
name: str = Field(min_length=1, max_length=50)

# Use @field_validator — value transformation or complex single-field logic
@field_validator("code")
@classmethod
def code_must_be_uppercase(cls, v: str) -> str:
    return v.upper()

# Use @model_validator — constraints that span multiple fields
@model_validator(mode="after")
def debit_must_equal_credit(self) -> "Self":
    if self.debit_amount != self.credit_amount:
        raise ValueError("debit must equal credit")
    return self
```

**Decision rule**: constraint only → `Field`; value transformation or
cross-field logic → `@field_validator` / `@model_validator`.

---

## Related

- `app/schemas/currency.py` — `ExchangeRateCreate.rate` uses `Field(gt=Decimal("0"))`
- Pydantic v2 docs: https://docs.pydantic.dev/latest/concepts/fields/
