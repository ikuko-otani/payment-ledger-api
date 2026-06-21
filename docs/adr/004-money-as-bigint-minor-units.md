# ADR-004: Store Monetary Amounts as BIGINT (Minor Currency Units)

## Status

Accepted

## Context

Monetary values stored as `FLOAT` or `DOUBLE` are subject to IEEE 754
rounding errors — `0.1 + 0.2` does not equal `0.3` in binary floating point.
`NUMERIC(18,4)` avoids rounding but uses a fixed scale of 4 decimal places,
which does not map to real currencies:
- EUR needs 2
- JPY needs 0
- some cryptocurrencies need 8.

A fixed scale either wastes storage or truncates values depending on the currency.

## Decision

Store all monetary amounts in `entries.amount` as `BIGINT` representing
the smallest indivisible unit of the currency (minor units).

Examples:
- `1000` = €10.00 (EUR, scale 2)
- `1000` = ¥1000 (JPY, scale 0)
- `1000` = $10.00 (USD, scale 2)

## Rationale

Integer arithmetic is exact — there are no rounding errors
regardless of the number of operations.
This convention is also the industry standard:
Stripe, Mollie, Adyen, and Square all represent amounts as integers
in their public APIs (`amount=1099` means €10.99).
Using the same convention reduces friction when integrating with payment processors.

| Approach | Rounding risk | Industry standard | Multi-currency |
|----------|--------------|-------------------|----------------|
| `FLOAT` / `DOUBLE` | High | No | Poor |
| `NUMERIC(18,4)` | None | No | Poor (fixed scale) |
| `BIGINT` (minor units) | None | Yes (Stripe, Mollie) | Good (scale per currency) |

## Trade-offs

The one real downside is that displaying a human-readable amount requires
knowing the currency's decimal scale (ISO 4217 exponent).
For example, dividing by 100 is correct for EUR/USD
but wrong for JPY (scale 0) or BHD (scale 3).
Clients must look up the scale from an ISO 4217 table or rely onthe `currency` field
stored alongside `amount`.

Currency scale management is deferred — see TD-012.

## Consequences

- All API inputs and outputs for `amount` are integers
- Clients must divide by the currency's scale factor to display human-readable amounts
- `BIGINT` supports up to ~9.2 × 10¹⁸ — sufficient for any real-world financial amount
- Cryptoassets with 8-decimal precision (e.g. BTC satoshis) are within range

## References

- [Stripe API: amounts](https://stripe.com/docs/currencies#zero-decimal)
- [ISO 4217 currency codes and minor units](https://www.iso.org/iso-4217-currency-codes.html)
- Implementation: `app/models/entry.py`
