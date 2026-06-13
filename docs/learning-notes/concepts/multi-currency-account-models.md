# Multi-currency accounting: currency-restricted accounts vs. functional-currency accounts

> Date: 2026-06-13 | Goal: S7-1 (TD-024)
> Purpose: Reference note on why `entry.currency == account.currency` (TD-024) is a
> deliberate scope choice, not "the only correct rule" — and how it maps to patterns
> used in real-world accounting ERPs.

---

## 1. Two models exist in real ERPs

### Model A — Currency-restricted account (this repo's TD-024)

The account itself is denominated in one currency (e.g. a USD bank account held by
a EUR company), and **every entry posted to it must be in that same currency**. No
conversion happens at posting time for that account.

```
entry.currency == account.currency   (always — enforced, 422 on mismatch)
```

### Model B — Functional-currency account (conversion is the normal case)

Most P&L accounts (revenue, expense) and many balance-sheet accounts are held in
the company's **functional/base currency**. Entries can be posted in *any*
transaction currency; the system stores both the original transaction-currency
amount and the converted functional-currency amount, and the account's balance is
computed from the converted amounts.

```
entry.currency != account.currency   (normal — converted_amount stored alongside)
```

---

## 2. SAP's "Account Currency" (Kontowährung) as a concrete reference point

SAP FI's G/L account master has an explicit **Account Currency** field:

- If `account currency == company code currency` → the account is a Model B
  account. Postings in any currency are allowed; SAP converts to the account
  currency for the balance, while still recording the original transaction
  currency on the line item.
- If `account currency != company code currency` → the account is a Model A
  account (typically a foreign-currency bank account or similar). Only postings
  in that exact currency are allowed — SAP rejects anything else.

So **both models are standard**; which one applies is a per-account configuration,
not a global rule.

---

## 3. Where this codebase sits today

This repo currently implements **Model A globally** via TD-024:

```python
# app/services/transaction_service.py — create_transaction
mismatched = [e for e in payload.entries if e.currency != found_ids[e.account_id]]
if mismatched:
    raise HTTPException(status_code=422, detail="Entry currency does not match account currency: ...")
```

Interestingly, the infrastructure for Model B **already exists**:
`_get_converted_amount_usd` computes `Entry.converted_amount_usd` for every entry,
regardless of `entry.currency`. This was originally built to support
`TransactionCreate.currency_code` (transaction-level currency) being different
from `BASE_CURRENCY` ("USD").

---

## 4. Why Model A (strict equality) was chosen for TD-024

The choice was driven by an existing invariant elsewhere in the code, not by a
business rule that "mixed currencies are always wrong":

`app/services/balance.py`'s `calculate_balance` sums the **raw** `Entry.amount`
(minor units in `entry.currency`), not `converted_amount_usd`. If TD-024 allowed
`entry.currency != account.currency` (Model B), `calculate_balance` would sum
minor units across different currencies — numerically meaningless — *unless*
`calculate_balance` were also changed to sum `converted_amount_usd`.

TD-024's original write-up explicitly listed this as the alternative:

> (2) or have `calculate_balance` sum `converted_amount_usd` instead of raw
> `amount` to support genuinely multi-currency accounts.

S7-1's scope explicitly excluded changing `calculate_balance`. So Model A (strict
equality, 422 on mismatch) was the choice that:
- closes the TD-024 data-integrity gap immediately, and
- does **not** require touching `calculate_balance` (kept S7-1 small).

This is a "which existing invariant can I satisfy without expanding scope"
decision, not a claim that Model B is invalid.

---

## 5. Extension path to Model B (future work, not S7-1)

If/when a genuinely multi-currency account is needed (e.g. a USD revenue account
that also receives EUR sales):

1. Add a flag to `Account`, e.g. `currency_restricted: bool` (or
   `allowed_currencies: list[str]`).
2. TD-024's check only applies when `currency_restricted` is true.
3. `calculate_balance` switches to summing `converted_amount_usd` for
   non-restricted accounts (ties into TD-030's N+1 fix — the conversion rate
   would need to be resolved efficiently for every entry).

---

## Interview-relevant points

1. **"Is entry.currency == account.currency always required?"** — No; it's a
   per-account configuration in real ERPs (SAP's Kontowährung). TD-024 applies it
   globally as a simplification, with a documented extension path.
2. **Scope-driven design choice** — TD-024 picked the option that didn't require
   changing `calculate_balance`, demonstrating how an existing invariant
   (`calculate_balance` sums raw `amount`) constrains which fix is "small enough"
   for the current goal.
3. **Infrastructure built ahead of its use** — `converted_amount_usd` /
   `_get_converted_amount_usd` already exist (for `TransactionCreate.currency_code`
   conversion) but aren't yet used by `calculate_balance`. Recognizing "the pieces
   for Model B already exist, just not wired together" is a useful way to read an
   evolving codebase.

---

## Related documents

- `docs/tech-debt.md` — TD-024 (resolved, S7-1), TD-030 (N+1 in
  `_get_converted_amount_usd`, relevant to a future Model B switch)
- `app/services/transaction_service.py` — `create_transaction`,
  `_get_converted_amount_usd`
- `app/services/balance.py` — `calculate_balance`
