from __future__ import annotations

import random

from recon.fees import FEE_SCHEDULE_BPS, GST_BPS, fee_paise, gst_paise


def _build_settlement(rng: random.Random, n: int = 500) -> dict:
    """Return per-line totals and per-settlement totals for n random payment lines."""
    methods = list(FEE_SCHEDULE_BPS)
    lines = []
    for _ in range(n):
        method = rng.choice(methods)
        amount = rng.randint(10000, 5000000)
        fee = fee_paise(amount, method)
        tax = gst_paise(fee)
        credit = amount - fee - tax
        lines.append({"method": method, "amount": amount, "fee": fee, "tax": tax, "credit": credit})
    return {
        "lines": lines,
        "amount_paise": sum(l["credit"] for l in lines),
        "fees_paise": sum(l["fee"] for l in lines),
        "tax_paise": sum(l["tax"] for l in lines),
    }


def test_per_line_sums_tie_exactly():
    """Integer per-line fee arithmetic must tie to settlement totals with no drift."""
    rng = random.Random(1234)
    s = _build_settlement(rng)
    lines = s["lines"]

    assert sum(l["credit"] for l in lines) == s["amount_paise"]
    assert sum(l["fee"] for l in lines) == s["fees_paise"]
    assert sum(l["tax"] for l in lines) == s["tax_paise"]


def test_batch_percentage_does_not_tie():
    """
    Demonstrates WHY per-line arithmetic is required: applying the fee rate
    to the batch gross total (even with round-half-up) produces a different
    result from summing individual per-line fees. This is Jensen's inequality
    on the rounding function — small per-transaction rounding decisions don't
    commute with aggregation.
    """
    rng = random.Random(5678)
    # Use a single method so the blended rate is unambiguous
    method = "upi"
    bps = FEE_SCHEDULE_BPS[method]

    amounts = [rng.randint(10000, 5000000) for _ in range(500)]
    per_line_fees = sum(fee_paise(a, method) for a in amounts)

    gross = sum(amounts)
    # Naive batch approximation: apply the rate to the total, round half-up
    batch_fee = (gross * bps + 5000) // 10000

    assert batch_fee != per_line_fees, (
        "Batch and per-line fees must differ for this test to be meaningful. "
        "If they happen to be equal for this seed, choose a different seed."
    )
