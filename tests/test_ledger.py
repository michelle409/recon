from __future__ import annotations

import pytest

from recon.ledger import build_exceptions, build_journal


# ── helpers ───────────────────────────────────────────────────────────────────

def _matches(credits_list: list[dict]) -> dict:
    return {"credits": credits_list, "summary": {}}


def _auto(cid: str, sid: str) -> dict:
    return {
        "credit_id": cid,
        "route": "AUTO_MATCH",
        "settlement_ids": [sid],
        "stage": "exact_utr",
        "detail": "test",
        "verification": "EXACT",
    }


def _refuse(cid: str) -> dict:
    return {
        "credit_id": cid,
        "route": "REFUSE",
        "settlement_ids": [],
        "stage": "refuse",
        "detail": "no match",
        "verification": "UNVERIFIED",
    }


# ── test data ─────────────────────────────────────────────────────────────────
# Balance identity:
#   cr_recv = sum(payment.amount_paise) - refund_debits = 60650 + 40432 - 5000 = 96082
#   dr_fees = 200 + 100 = 300
#   dr_gst  = 36  +  18 = 54
#   dr_bank = cr_recv - dr_fees - dr_gst = 96082 - 300 - 54 = 95728
#   => credit.amount_paise = settlement.amount_paise = 95728

_SETTLEMENT = {
    "settlement_id": "setl_T",
    "utr": "UTRTTTTTTTTTTTTT",
    "amount_paise": "95728",
    "fees_paise": "300",
    "tax_paise": "54",
    "status": "processed",
    "created_at": "2026-01-05",
}

_PAYMENT_1 = {
    "entity_id": "pay_1", "settlement_id": "setl_T",
    "settlement_utr": "UTRTTTTTTTTTTTTT", "type": "payment",
    "debit_paise": "0", "credit_paise": "60414", "amount_paise": "60650",
    "fee_paise": "200", "tax_paise": "36", "method": "card",
    "order_id": "ord_1", "created_at": "2026-01-05", "settled_at": "2026-01-05",
}
_PAYMENT_2 = {
    "entity_id": "pay_2", "settlement_id": "setl_T",
    "settlement_utr": "UTRTTTTTTTTTTTTT", "type": "payment",
    "debit_paise": "0", "credit_paise": "40314", "amount_paise": "40432",
    "fee_paise": "100", "tax_paise": "18", "method": "upi",
    "order_id": "ord_2", "created_at": "2026-01-05", "settled_at": "2026-01-05",
}
_REFUND_1 = {
    "entity_id": "rfnd_1", "settlement_id": "setl_T",
    "settlement_utr": "UTRTTTTTTTTTTTTT", "type": "refund",
    "debit_paise": "5000", "credit_paise": "0", "amount_paise": "5000",
    "fee_paise": "0", "tax_paise": "0", "method": "na",
    "order_id": "ord_1", "created_at": "2026-01-05", "settled_at": "2026-01-05",
}

_CREDIT = {
    "credit_id": "bc_001",
    "value_date": "2026-01-07",
    "txn_date": "2026-01-07",
    "amount_paise": "95728",
    "narration_raw": "NEFT CR-UTR-UTRTTTTTTTTTTTTT",
}

_LINES = [_PAYMENT_1, _PAYMENT_2, _REFUND_1]


# ── tests ─────────────────────────────────────────────────────────────────────

def test_journal_balances_per_settlement():
    """2 payments + 1 refund → 4 rows exactly, debits == credits."""
    matches = _matches([_auto("bc_001", "setl_T")])
    rows = build_journal(matches, [_SETTLEMENT], _LINES, [_CREDIT])

    assert len(rows) == 4, f"Expected 4 rows (no drift), got {len(rows)}: {rows}"

    dr = sum(r["amount_paise"] for r in rows if r["entry_type"].startswith("dr_"))
    cr = sum(r["amount_paise"] for r in rows if r["entry_type"].startswith("cr_"))
    assert dr == cr, f"Journal imbalance: dr={dr} cr={cr}"


def test_rounding_diff_row_on_drift():
    """A 3-paise drift produces a rounding_diff row; 25 paise raises."""
    # credit amount = base + 3 → diff = 3, in [1, 10]
    credit_3 = dict(_CREDIT, amount_paise="95731")
    matches = _matches([_auto("bc_001", "setl_T")])

    rows = build_journal(matches, [_SETTLEMENT], _LINES, [credit_3])
    rounding = [r for r in rows if "rounding_diff" in r["entry_type"]]
    assert len(rounding) == 1, f"Expected 1 rounding row, got {rounding}"
    assert rounding[0]["amount_paise"] == 3

    dr = sum(r["amount_paise"] for r in rows if r["entry_type"].startswith("dr_"))
    cr = sum(r["amount_paise"] for r in rows if r["entry_type"].startswith("cr_"))
    assert dr == cr

    # 25-paise diff must raise
    credit_25 = dict(_CREDIT, amount_paise="95753")
    with pytest.raises(AssertionError, match="generator bug"):
        build_journal(matches, [_SETTLEMENT], _LINES, [credit_25])


def test_no_journal_for_exceptions():
    """Refused credit → 0 journal rows, 1 exceptions row with REFUSE category."""
    credit_row = {
        "credit_id": "bc_999",
        "value_date": "2026-01-07",
        "txn_date": "2026-01-07",
        "amount_paise": "50000",
        "narration_raw": "NEFT CREDIT",
    }
    matches = _matches([_refuse("bc_999")])

    journal = build_journal(matches, [_SETTLEMENT], _LINES, [credit_row])
    assert journal == [], f"Expected empty journal for refused credit, got {journal}"

    exc = build_exceptions(matches, [credit_row], "2026-01-10")
    assert len(exc) == 1
    assert exc[0]["category"] == "REFUSE"
    assert exc[0]["credit_id"] == "bc_999"


def test_itc_total():
    """ITC total equals sum of tax_paise over matched settlements' lines only."""
    credit2 = dict(_CREDIT, credit_id="bc_002", amount_paise="999999")
    matches = _matches([
        _auto("bc_001", "setl_T"),
        _refuse("bc_002"),
    ])

    rows = build_journal(matches, [_SETTLEMENT], _LINES, [_CREDIT, credit2])
    itc = sum(r["amount_paise"] for r in rows if r["entry_type"] == "dr_gst_itc")

    expected = sum(int(ln["tax_paise"]) for ln in _LINES)
    assert itc == expected, f"ITC {itc} != expected {expected}"
