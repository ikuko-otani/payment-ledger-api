# S7-6: Service Review + Integration Tests (Currency Consistency, Pagination)

Date: 2026-06-17
Branch: `feature/s7-6-service-review-integration-tests`
PR: #79

---

## Goal Summary

Review all service layer endpoints against a checklist (input validation / sort order /
currency consistency / audit log), register newly found issues as TD-XXX, and add
integration tests covering multi-currency transactions and pagination boundaries.

---

## Step C Walkthrough

### What was reviewed

Applied a four-point checklist to every service-layer function:

| Checkpoint | What to look for |
|------------|-----------------|
| Input validation | Missing guards, unexpected `None` acceptance |
| Sort order | `SELECT` without `ORDER BY` on paginated or list endpoints |
| Currency consistency | Amount stored in wrong unit, no FK to currencies table |
| Audit log | Mutating operations that do not call `log_action` |

### Findings and actions taken

**TD-033 (Resolved in S7-6)**
`get_currencies` had no `ORDER BY`. Returned rows in PostgreSQL heap-scan order —
non-deterministic under concurrent inserts. Same pattern as TD-025, which fixed
`list_accounts`/`list_transactions` but missed this endpoint.
Fix: `.order_by(Currency.code)` added.

**TD-034 (Resolved in S7-6)**
`get_exchange_rates` also had no `ORDER BY`. Same risk as TD-033.
Fix: `.order_by(ExchangeRate.effective_date.desc(), ExchangeRate.id)` added.

**TD-035 (Registered, deferred to S8+)**
`accounts.currency` and `entries.currency` are plain `String(3)` columns with no
foreign key to `currencies.code`. The DB accepts any three-letter string without a
referential-integrity error. Root cause: both columns predate the `currencies` table
(added in S4); no retroactive FK migration was created at that time.
Application-layer guards partially mitigate the risk, but `create_account` still
accepts non-existent currency codes.
Fix deferred: add `ForeignKey("currencies.code")` + Alembic migration with data-integrity pre-check.

**TD-008 (Deferred to S7-7)**
Repository layer separation was in scope per personal policy, but consensus during
Step A was to keep S7-6 focused on the review checklist. TD-008 becomes an independent
Goal (S7-7).

### ORDER BY tiebreaker improvement

The pre-existing fix for TD-025 used `Transaction.id` (UUID v4) as the secondary sort
key after `transaction_date`. UUID v4 is random — it provides determinism but has no
semantic meaning as a tiebreaker.

Changed to `Transaction.posted_at DESC` (set to `datetime.now(UTC)` at write time)
as the secondary key, retaining `id` only as the final unique guarantee:

```python
# Before
.order_by(Transaction.transaction_date.desc(), Transaction.id)

# After
.order_by(Transaction.transaction_date.desc(), Transaction.posted_at.desc(), Transaction.id)
```

Applied to:
- `app/api/v1/routes/transactions.py` — `list_transactions`
- `app/services/ledger_service.py` — `get_ledger_entries` (uses `Entry.id` as final tiebreaker)

### Integration tests added

**`tests/test_transactions_multi_currency.py`** (new file)

| Test | Fixture | What it verifies |
|------|---------|-----------------|
| `test_eur_transaction_sets_converted_amount_usd` | `db_session` | `converted_amount_usd = amount × rate`, service-layer round-trip |
| `test_jpy_transaction_converted_amount_usd_rounded_half_up` | `db_session` | `5 × 0.5 = 2.5 → ROUND_HALF_UP → 3` |
| `test_list_transactions_pagination_no_duplicates_across_pages` | `async_client` | No duplicate IDs across pages; date DESC confirmed |
| `test_list_transactions_offset_beyond_total_returns_empty` | `async_client` | `offset > total` → `200 + []` |
| `test_currencies_list_returns_stable_ascending_order` | `async_client` | TD-033 fix regression |

**`tests/test_transactions_http.py`** (existing file, one test added)

| Test | What it verifies |
|------|-----------------|
| `test_same_date_transactions_ordered_by_posted_at_desc` | Same-date transactions ordered by `posted_at DESC` (newest first) |

---

## Key Takeaways

### What did I learn?

**ROUND_HALF_UP vs ROUND_HALF_EVEN requires 2.5 as the test value, not 1.5.**
Both rounding modes give 2 for 1.5 (nearest even happens to be up). Only a midpoint
whose nearest even integer is *down* — like 2.5 → ROUND_HALF_EVEN gives 2, ROUND_HALF_UP
gives 3 — makes the two modes distinguishable in a test.

**A tiebreaker that's never triggered is an untested path.**
The pagination ORDER BY test initially used the same date for all transactions, which
meant the `posted_at` tiebreaker was never exercised. Adding a test specifically for
same-date transactions was necessary to prove the secondary sort works.

**Test file placement affects readability.**
I initially added the `posted_at` sort test to `test_transactions_multi_currency.py`
because that was the file I was editing. The better home was `test_transactions_http.py`,
which already contained `test_list_transactions_ordered_by_transaction_date_desc` — the
primary sort test. The tiebreaker test belongs alongside its primary-sort companion.

### What would I do differently?

I would plan the test file assignment as part of Step A, not as an afterthought.
Asking "which existing file does this test belong in?" before writing prevents
unnecessary moves.

I would also check for existing TD entries before registering new ones — TD-033 and
TD-034 were both missed by the TD-025 fix, so they could have been registered earlier.

### What surprised me?

The `posted_at` secondary sort was a meaningful improvement over UUID that I had not
noticed before the Q2 review. UUID provides determinism, but it implies nothing about
insertion order. Using `posted_at` means that within the same transaction date,
records appear newest-first — which is the user expectation for a ledger list.

### What is worth remembering for future goals?

**"If you can change the code without breaking any test, that code path is untested."**
The `posted_at.desc()` change could have been introduced or reverted with no test
failure until the dedicated same-date test was added. When adding a sort key, always
add a test that can only pass if that specific key is applied correctly.

**Non-chronological insertion order is essential for ORDER BY tests.**
Inserting transactions in date order (oldest first) and asserting descending order
could pass even without `ORDER BY` if PostgreSQL happens to return rows in heap order.
Inserting in random order (e.g. 06-02, 06-04, 06-01, 06-03) forces the DB to sort,
making the test meaningful.

---

## Related

- `docs/tech-debt.md` — TD-033 (Resolved), TD-034 (Resolved), TD-035 (Open)
- `docs/adr/` — no new ADR; changes are incremental fixes, not architectural decisions
- Next goal: S7-7 (repository layer separation, TD-008)
