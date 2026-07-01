"""Unit tests for _convert_amount_usd — pure-function, no DB, no Hypothesis.

These tests document concrete rounding behavior of the FX conversion function.
For the property-based upper-bound test (error <= N), see
test_balance_invariant_hypothesis.py.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.transaction_service import _convert_amount_usd


def test_fx_rounding_concrete_positive_error() -> None:
    """ROUND_HALF_UP-specific: 0.5 rounds up, causing per-entry sum to exceed aggregate.

    Two debits of 1 EUR cent at rate 0.5 each round up to 1 USD cent (0.5 → 1).
    The aggregate credit of 2 EUR cents converts exactly to 1 USD cent (1.0 → 1).
    Per-entry sum (2) exceeds aggregate (1) by +1.

    This test is intentionally coupled to ROUND_HALF_UP behavior.
    If the rounding strategy changes (e.g. to ROUND_HALF_EVEN where 0.5 → 0),
    this test will fail — update the expected value to match the new strategy.
    """
    rate = Decimal("0.5")
    per_entry_sum = _convert_amount_usd(1, rate) + _convert_amount_usd(1, rate)
    # 0.5 → 1,  0.5 → 1  →  sum = 2
    aggregate = _convert_amount_usd(2, rate)
    # 1.0 → 1
    assert per_entry_sum - aggregate == 1


def test_fx_rounding_concrete_negative_error() -> None:
    """Per-entry rounding down can cause per-entry sum to fall below aggregate (-1 cent).

    Two debits of 1 EUR cent at rate 0.4 each round down to 0 USD cent (0.4 → 0).
    The aggregate credit of 2 EUR cents rounds up to 1 USD cent (0.8 → 1).
    Per-entry sum (0) is less than aggregate (1) by -1.

    Unlike the positive-error case, this behavior is the same for both ROUND_HALF_UP
    and ROUND_HALF_EVEN (neither rounds 0.4 up or 0.8 down).
    """
    rate = Decimal("0.4")
    per_entry_sum = _convert_amount_usd(1, rate) + _convert_amount_usd(1, rate)
    # 0.4 → 0,  0.4 → 0  →  sum = 0
    aggregate = _convert_amount_usd(2, rate)
    # 0.8 → 1
    assert per_entry_sum - aggregate == -1
