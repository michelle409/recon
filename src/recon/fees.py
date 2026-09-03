from __future__ import annotations

"""
Fee and tax calculation for synthetic data generation.

The matching engine must NEVER import this module.
The verifier reads fee_paise/tax_paise from recon lines; it never assumes
a fee schedule.
"""

FEE_SCHEDULE_BPS: dict[str, int] = {
    "upi": 30,
    "card": 200,
    "netbanking": 175,
}
GST_BPS: int = 1800


def fee_paise(amount_paise: int, method: str) -> int:
    """Round-half-up fee: (amount * bps + 5000) // 10000."""
    return (amount_paise * FEE_SCHEDULE_BPS[method] + 5000) // 10000


def gst_paise(fee: int) -> int:
    """Round-half-up GST on fee."""
    return (fee * GST_BPS + 5000) // 10000
