# Pydantic UUID validation in FastAPI

> Date: 2026-05-12 | Goals: S2-4 onwards  
> Purpose: Reference note for implementing UUID format validation in FastAPI dependencies and endpoints

---

## 1. Summary (TL;DR)

Annotating a FastAPI `Depends` function argument with `uuid.UUID` causes Pydantic to
validate the format automatically. Invalid values return **HTTP 422** with no manual
`try/except` required.

```python
import uuid
from typing import Annotated
from fastapi import Header

async def check_idempotency(
    idempotency_key: Annotated[uuid.UUID | None, Header()] = None,
) -> None:
    ...  # 422 is returned automatically by Pydantic on invalid input
```

---

## 2. How 422 is generated

```
Client sends header: Idempotency-Key: not-a-uuid

FastAPI processing:
  1. Header() extracts the HTTP header → "not-a-uuid" (str)
  2. Pydantic attempts to coerce str → uuid.UUID
  3. uuid.UUID("not-a-uuid") → ValueError
  4. FastAPI catches it as RequestValidationError
  5. HTTP 422 Unprocessable Entity is returned automatically
```

Only the type annotation needs to be written correctly — everything else is automatic.

---

## 3. uuid.UUID vs. pydantic.UUID4

| | `uuid.UUID` (stdlib) | `pydantic.UUID4` |
|---|---|---|
| Accepted versions | v1, v2, v3, v4, v5, v7 (any valid UUID) | v4 only |
| Import | `import uuid` | `from pydantic import UUID4` |
| Use when | Any valid UUID format is acceptable | UUID v4 must be enforced (Stripe-style) |

### Why UUID v4 is recommended for Idempotency-Key

UUID v4 is fully random (122 bits of entropy), which provides:

- **Near-zero collision probability** — independent clients can generate keys without coordination.
- **Unpredictability** — unlike time-based v1, there is no embedded timestamp to exploit.
- **Industry convention** — Stripe, Adyen, and Mollie all require UUID v4 for idempotency keys.

### Choice for this project

`uuid.UUID` (stdlib) was used in S2-4. For MVP purposes, restricting to v4 was considered
unnecessary. Switching to `pydantic.UUID4` later is a one-line change if stricter enforcement
is needed.

---

## 4. Pydantic Field validators — when to use which (common interview topic)

This implementation used **implicit validation via type annotation**, but Pydantic provides
explicit validator decorators for more complex rules.

### 4.1 Implicit validation via type annotation (this implementation)

```python
from uuid import UUID
from pydantic import BaseModel

class MyModel(BaseModel):
    idempotency_key: UUID  # Pydantic validates and coerces automatically
```

Pydantic has built-in support for `UUID` and converts a valid string to a `UUID` object.
If conversion fails, a `ValidationError` is raised (FastAPI turns this into a 422 response).

### 4.2 @field_validator (explicit, single-field rule)

```python
from pydantic import BaseModel, field_validator
from decimal import Decimal

class EntryCreate(BaseModel):
    amount: Decimal

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v
```

Use `@field_validator` for business rules that cannot be expressed as a type conversion alone.

### 4.3 @model_validator (cross-field rule)

```python
from pydantic import BaseModel, model_validator

class TransactionCreate(BaseModel):
    entries: list[EntryCreate]

    @model_validator(mode="after")
    def entries_must_be_balanced(self) -> "TransactionCreate":
        debit = sum(e.amount for e in self.entries if e.entry_type == "debit")
        credit = sum(e.amount for e in self.entries if e.entry_type == "credit")
        if debit != credit:
            raise ValueError(f"Entries not balanced: debit={debit} credit={credit}")
        return self
```

### 4.4 Decision guide

| Situation | Approach |
|---|---|
| Expressible as a type conversion (UUID, int, date, Decimal) | Type annotation |
| Single-field business rule (range, length, format) | `@field_validator` |
| Cross-field consistency (debit == credit, min entries count) | `@model_validator` |

---

## 5. Depends arguments and Pydantic validation

FastAPI applies the same Pydantic validation engine to `Depends` function arguments
as it does to request body models.

```python
# Request body (Pydantic model)
class Payload(BaseModel):
    idempotency_key: UUID  # validated at model level

# Header parameter (Depends function argument)
async def check_idempotency(
    idempotency_key: Annotated[UUID | None, Header()] = None,
) -> None:
    ...
```

Both paths run through the same Pydantic validation engine.
Type annotation-based validation works with `Header()`, `Query()`, and `Path()` alike.

---

## Related documents

- `app/dependencies/idempotency.py` — UUID validation implementation
- `tests/test_idempotency.py` — UUID validation tests
