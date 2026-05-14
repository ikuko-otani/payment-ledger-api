# ADR-004: Store Monetary Amounts as BIGINT (Minor Currency Units)

## Status

Accepted — implemented in Sprint S2-X-1

## Context

<!-- 🔧 TODO: explain the problem with floating-point and Numeric types for money
hint: IEEE 754 floating point cannot represent 0.1 exactly;
      even Numeric(18,4) has an arbitrary scale that doesn't map to real currencies
      (EUR needs 2 decimal places, JPY needs 0, some crypto needs 8)
-->

## Decision

Store all monetary amounts in `entries.amount` as `BIGINT` representing
the smallest indivisible unit of the currency (minor units).

Examples:
- `1000` = €10.00 (EUR, scale 2)
- `1000` = ¥1000 (JPY, scale 0)
- `1000` = $10.00 (USD, scale 2)

## Rationale

<!-- 🔧 TODO: explain the benefits concisely
hint: integer arithmetic is exact; no rounding errors;
      matches the convention used by Stripe, Mollie, Adyen, Square
      in their public APIs (amount=1099 means €10.99)
-->

| Approach | Rounding risk | Industry standard | Multi-currency |
|----------|--------------|-------------------|----------------|
| `FLOAT` / `DOUBLE` | High | No | Poor |
| `NUMERIC(18,4)` | None | No | Poor (fixed scale) |
| `BIGINT` (minor units) | None | Yes (Stripe, Mollie) | Good (scale per currency) |

## Trade-offs

<!-- 🔧 TODO: note the one real downside
hint: you need to know the currency's decimal scale to display the amount correctly
      (look up ISO 4217 scale table, or store scale alongside currency code)
-->

## Consequences

- All API inputs and outputs for `amount` are integers
- Clients must divide by the currency's scale factor to display human-readable amounts
- `BIGINT` supports up to ~9.2 × 10¹⁸ — sufficient for any real-world financial amount
- Cryptoassets with 8-decimal precision (e.g. BTC satoshis) are within range

## References

- [Stripe API: amounts](https://stripe.com/docs/currencies#zero-decimal)
- [ISO 4217 currency codes and minor units](https://www.iso.org/iso-4217-currency-codes.html)
- Implementation: `app/models/entry.py`
