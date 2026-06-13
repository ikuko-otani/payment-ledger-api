# S7-1: Transaction Currency Consistency Check + ORDER BY for List Endpoints (TD-024/TD-025)

> Branch: `feature/s7-1-currency-check-order-by`
> support_level: guided (with full code shown per established preference)

## Goal

- **TD-024**: `create_transaction` validated that all `entries[]` share the same
  `currency`, but never checked that `currency` against `Account.currency`.
  `calculate_balance` sums raw `Entry.amount` without any currency filter, so an
  entry whose currency differs from its account's `currency` would produce a
  numerically meaningless balance. Fix: reject with 422 when
  `entry.currency != account.currency`.
- **TD-025**: `list_accounts` and `list_transactions` executed `select(...)`
  without `.order_by(...)`, so PostgreSQL did not guarantee row order —
  non-deterministic for `list_accounts`, and a pagination-correctness risk
  (`LIMIT`/`OFFSET` without `ORDER BY`) for `list_transactions`. Fix: add
  `.order_by(Account.code)` and
  `.order_by(Transaction.transaction_date.desc(), Transaction.id)` respectively.

Explicitly **not** in scope: changing `calculate_balance` to sum
`converted_amount_usd` (the alternative fix for TD-024) — see
[multi-currency-account-models.md](concepts/multi-currency-account-models.md)
for why.

---

## Step C walkthrough

### C-1: TD-024 — entry currency vs. account currency validation

In `app/services/transaction_service.py`'s `create_transaction`, the existing
account-existence check already queried `accounts` for the `account_ids` used in
the payload. The fix reuses that query result instead of issuing a second query:

```python
# ------------------------------------------------------------------
# Validate: all account_ids must exist in the accounts table
# ------------------------------------------------------------------
account_ids = {e.account_id for e in payload.entries}
result = await db.execute(
    select(Account.id, Account.currency).where(
        Account.id.in_(account_ids),
        Account.is_active.is_(True),
    )
)
found_ids = {account_id: currency for account_id, currency in result.all()}
missing = account_ids - found_ids.keys()
if missing:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=f"Unknown or inactive account_ids: {[str(i) for i in missing]}",
    )
```

```python
# ------------------------------------------------------------------
# Validate: each entry's currency must match its account's currency (TD-024)
# ------------------------------------------------------------------
mismatched = [e for e in payload.entries if e.currency != found_ids[e.account_id]]
if mismatched:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=(
            "Entry currency does not match account currency: "
            + ", ".join(
                f"account_id={e.account_id} entry_currency={e.currency} "
                f"account_currency={found_ids[e.account_id]}"
                for e in mismatched
            )
        ),
    )
```

💡 The query was narrowed from `select(Account)` (all ~8 columns via
`.scalars().all()`) to `select(Account.id, Account.currency)` (via `.all()`,
unpacked as `Row` tuples) — see
[sqlalchemy-query-reuse.md](concepts/sqlalchemy-query-reuse.md) for the full
reasoning. Two mechanical changes: only select columns actually used downstream,
and use `.all()` instead of `.scalars().all()` for multi-column results.

⏱ ~15 min | Verification: `uv run python -c "import app.services.transaction_service"`
Commits: `971e8b2`, `10036b7`

---

### C-2: TD-024 test

Validation order in `create_transaction` is: account existence → debit/credit
presence → all entries same currency (TD-023) → entry vs. account currency
(TD-024, new) → balance check. To exercise TD-024 in isolation, the test needs
entries that agree with **each other** (passes TD-023) but disagree with the
**account** (fails TD-024) — i.e. accounts at the default `currency="EUR"`
(`_create_account`'s default) with entries at `currency="USD"`.

```python
@pytest.mark.asyncio
async def test_entry_currency_mismatched_with_account_returns_422(
    db_session: AsyncSession,
) -> None:
    """Entry currency must match its account's currency (TD-024)."""
    debit = await _create_account(
        db_session, "Cash-EUR-Acct", AccountType.ASSET, code="1140", currency="EUR"
    )
    credit = await _create_account(
        db_session, "Revenue-EUR-Acct", AccountType.REVENUE, code="4040", currency="EUR"
    )

    payload = TransactionCreate(
        description="Currency mismatch",
        transaction_date=date(2024, 1, 1),
        entries=[
            EntryCreate(
                account_id=debit.id, direction=Direction.DEBIT, amount=1000, currency="USD"
            ),
            EntryCreate(
                account_id=credit.id, direction=Direction.CREDIT, amount=1000, currency="USD"
            ),
        ],
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_transaction(db_session, payload, user_id=uuid.uuid4())

    assert exc_info.value.status_code == 422
    assert "currency" in str(exc_info.value.detail).lower()
```

⏱ ~5 min | Verification:
`uv run pytest tests/test_transactions.py -k currency_mismatched_with_account -v`
Commit: `e753c15`

---

### C-3: TD-025 — `ORDER BY` for `list_accounts` / `list_transactions`

```python
# app/api/v1/routes/accounts.py
@router.get("", response_model=list[AccountRead])
async def list_accounts(db: DbDep, _current_user: AuditorOrAdminUser) -> list[Account]:
    result = await db.execute(select(Account).order_by(Account.code))
    return list(result.scalars().all())
```

```python
# app/api/v1/routes/transactions.py
@router.get("", response_model=list[TransactionRead])
async def list_transactions(
    db: DbDep,
    _current_user: AuditorOrAdminUser,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Transaction]:
    result = await db.execute(
        select(Transaction)
        .options(selectinload(Transaction.entries))
        .order_by(Transaction.transaction_date.desc(), Transaction.id)
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())
```

💡 `Transaction.id` is included as a tie-breaker because `transaction_date` alone
can have ties (multiple transactions on the same date) — without a unique
second key, the sort is not a total order and `LIMIT`/`OFFSET` pagination can
return duplicate or skipped rows across pages under concurrent writes.
`Account.code` alone is sufficient for `list_accounts` because `code` is unique.

⏱ ~10 min | Verification:
`uv run pytest tests/test_accounts.py tests/test_transactions_http.py -v`
Commit: `2226dba`

---

### C-4: TD-025 ordering tests

Both tests deliberately POST in an order *different* from the expected sort
order, so that an `ORDER BY`-less implementation would fail (avoids a
false-green test that happens to pass because insertion order == sort order).

```python
# tests/test_accounts.py
@pytest.mark.asyncio
async def test_list_accounts_returns_rows_ordered_by_code(
    async_client: AsyncClient,
) -> None:
    """GET /accounts must return rows ordered by code, not insertion order (TD-025)."""
    for code, name in [
        ("3000", "Acct-3000"),
        ("1000", "Acct-1000"),
        ("2000", "Acct-2000"),
    ]:
        resp = await async_client.post(
            "/api/v1/accounts",
            json={"code": code, "name": name, "account_type": "asset", "currency": "EUR"},
        )
        assert resp.status_code == 201

    response = await async_client.get("/api/v1/accounts")
    assert response.status_code == 200
    codes = [item["code"] for item in response.json()]
    assert codes == ["1000", "2000", "3000"]
```

```python
# tests/test_transactions_http.py
@pytest.mark.asyncio
async def test_list_transactions_ordered_by_transaction_date_desc(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /transactions must be ordered by transaction_date desc (TD-025)."""
    debit_id = await _seed_account(db_session, "Cash-Order", AccountType.ASSET, code="1120")
    credit_id = await _seed_account(db_session, "Revenue-Order", AccountType.REVENUE, code="4020")

    def _payload(tx_date: str, description: str) -> dict:
        return {
            "description": description,
            "transaction_date": tx_date,
            "entries": [
                {"account_id": debit_id, "direction": "debit", "amount": 10, "currency": "EUR"},
                {"account_id": credit_id, "direction": "credit", "amount": 10, "currency": "EUR"},
            ],
        }

    for tx_date, description in [
        ("2024-01-01", "oldest"),
        ("2024-03-01", "newest"),
        ("2024-02-01", "middle"),
    ]:
        resp = await async_client.post("/api/v1/transactions", json=_payload(tx_date, description))
        assert resp.status_code == 201

    response = await async_client.get("/api/v1/transactions")
    assert response.status_code == 200
    dates = [item["transaction_date"] for item in response.json()]
    assert dates == ["2024-03-01", "2024-02-01", "2024-01-01"]
```

⏱ ~10 min | Verification:
`uv run pytest tests/test_accounts.py tests/test_transactions_http.py -v`
Commit: `d699424`

---

### C-5: tech-debt.md cleanup, fallout fixes, full test run

Moved TD-024 and TD-025 from "Open Items" to "Resolved" in `docs/tech-debt.md`
with a summary of the fix actually applied.

**Fallout from TD-024**: 7 existing tests failed because they constructed
accounts and entries with *different* currencies — a combination TD-024 now
rejects. Root cause fell into two categories:

1. **Mismatched test fixtures** (`test_currency_conversion.py` ×4,
   `test_idempotency.py` ×2) — the account's `currency=` argument (often left at
   a helper's default) didn't match the entries' `currency`. Fixed by passing the
   correct `currency=` to `_seed_account`/`_create_account` so it matches the
   entries.

2. **Invalid test premise** (`test_ledger.py::test_get_ledger_currency_filter_returns_only_matching_currency`)
   — the test posted both a USD transaction and a EUR transaction against the
   *same pair of accounts*. Under TD-024, an account can only receive entries in
   its own currency, so this premise is no longer valid. Fixed by creating
   separate USD and EUR account pairs and posting each transaction against its
   matching pair.

⚠️ Case 2 is not a workaround — it's TD-024 correctly rejecting a scenario that
was always semantically wrong (an account holding entries in two different
currencies, summed by `calculate_balance` as if they were the same unit).

⏱ ~20 min | Verification: `uv run pytest -q` → **111 passed**, coverage 92.24%
Commits: `90f842d`, `368241d`

---

## Side findings registered as new tech debt

While reviewing `create_transaction`'s query patterns for TD-024, two additional
inefficiencies were found and registered (not fixed in S7-1):

- **TD-030** (performance): `_get_converted_amount_usd` is called once per entry
  but its arguments (`currency_code`, `transaction_date`) are transaction-level —
  up to 3×N queries for an N-entry non-USD transaction. Registered against S7-2.
- **TD-031** (data-integrity): `create_user`'s existence check is a
  check-then-insert (TOCTOU) — a concurrent duplicate-email request can surface
  as 500 instead of 409. Registered against S7-3.

---

## Key takeaways

- I learned that a SELECT used purely for an existence check can often be widened
  (by one or two columns) to also answer a second question — `select(Account.id, Account.currency)`
  instead of a second round trip — but the right discipline is to check what the
  *rest of the function actually uses* before deciding how wide to make it, not to
  default to `select(Model)` "just in case."
- I learned that `ORDER BY` is not just about presentation — without it,
  `LIMIT`/`OFFSET` pagination has no correctness guarantee at all under concurrent
  writes, and a composite `ORDER BY` needs a unique tie-breaker column to be a
  true total order.
- I was surprised by how much TD-024 rippled into existing tests — 7 failures
  across 3 files, all because those tests had quietly relied on
  "account currency and entry currency don't have to match." Writing TD-024 made
  that implicit (and incorrect) assumption visible everywhere it was baked into
  fixtures.
- I was also surprised that the "fix" for `test_get_ledger_currency_filter_returns_only_matching_currency`
  wasn't a tweak — its premise (one account receiving both USD and EUR entries)
  was itself the kind of bug TD-024 exists to prevent, so the test had to be
  redesigned around two account pairs.
- If I did this again, I'd grep for tests that mix a non-default `currency=` on
  entries with the default `currency=` on accounts (or vice versa) *before*
  implementing TD-024, to size the fallout up front instead of discovering it via
  a full test run at the end.
- Worth remembering for future goals: this codebase already distinguishes between
  "the account's currency" and "the transaction's currency_code / converted_amount_usd"
  — TD-024 only closed the gap for the *former*. The latter (functional-currency
  accounts with conversion) is a real, larger feature, documented in
  [multi-currency-account-models.md](concepts/multi-currency-account-models.md),
  and ties directly into TD-030's N+1 fix if it's ever picked up.

---

## Related documents

- `docs/tech-debt.md` — TD-024, TD-025 (resolved), TD-030, TD-031 (registered)
- [sqlalchemy-query-reuse.md](concepts/sqlalchemy-query-reuse.md)
- [multi-currency-account-models.md](concepts/multi-currency-account-models.md)
