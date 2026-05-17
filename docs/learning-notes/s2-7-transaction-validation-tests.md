# S2-7: pytest 基盤整備 + バリデーションテスト

**Date**: 2026-05-17
**Goal**: Add validation tests to `tests/test_transactions.py` (unbalanced, empty entries, negative amount, etc.)
**Branch**: none — DONE condition already met by tests written in prior goals
**Support level**: balanced

---

## Outcome

No new code was written. On inspecting `tests/test_transactions.py` before starting
implementation, 11 tests were already present and all passed:

```
pytest tests/test_transactions.py -v
# 11 passed
```

The DONE condition ("5件 PASSED") was satisfied without additional work.

### Tests already in place

| Test | Category |
|------|----------|
| `test_create_balanced_transaction_persists_rows` | Success path |
| `test_unbalanced_transaction_raises_http_422` | Service validation |
| `test_transaction_create_requires_at_least_two_entries` | Schema validation |
| `test_transaction_response_shape_like_domain_object` | Success path |
| `test_entry_amount_zero_raises_validation_error` | Schema validation |
| `test_entry_amount_negative_raises_validation_error` | Schema validation |
| `test_description_blank_raises_validation_error` | Schema validation |
| `test_unknown_account_id_raises_http_422` | Service validation |
| `test_all_debit_entries_raises_http_422` | Service validation |
| `test_all_credit_entries_raises_http_422` | Service validation |
| `test_mixed_currency_entries_raises_http_422` | Service validation |

---

## Observations

### "空リスト" vs "最低 2 件" の違い

The Notion Focus mentioned "空リスト" (empty list) as a test case, but the existing
test `test_transaction_create_requires_at_least_two_entries` checks `len(entries) == 1`
(single entry) rather than `entries=[]`.

Both cases are rejected by the same Pydantic `min_length=2` constraint, so one test
effectively covers both. Splitting them into separate tests would increase coverage
granularity but is not necessary to satisfy the DONE condition. Whether to add an
explicit empty-list test is a judgement call — the constraint behaviour is identical.

---

## Key Takeaways

**What did I learn?**

I learned that checking existing tests before starting implementation is worth the
few minutes it takes. The DONE condition was already met, and recognising that early
prevented unnecessary duplicate work.

I also noticed the subtle difference between testing "empty list" and "single entry":
they trigger the same validation path, but represent distinct user mistakes. When
deciding test granularity, it is reasonable to ask whether each separate test would
catch a different bug — if not, one test is enough.

**What would I do differently?**

Before writing any tests for a goal focused on test coverage, I would check what
already exists first. Reading the test file upfront is a low-cost step that reveals
whether the goal is already partially or fully satisfied.

**What surprised me?**

That all 11 tests existed before I even started. The prior goals had accumulated more
coverage than the Notion goal description implied.

**What is worth remembering for future goals?**

- Always read existing test files before adding new tests — duplication is easy to
  introduce and hard to notice when files grow.
- A single Pydantic constraint (e.g., `min_length=2`) covers multiple invalid inputs
  (empty list, single item). Testing one representative case is usually sufficient
  unless the error messages or downstream behaviour differ per input.
