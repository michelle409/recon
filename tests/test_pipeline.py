from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from recon import metrics
from recon.generator import run_pipeline
from recon.matcher import run_matcher


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_clubbed_credit_not_auto_matched(tmp_path: Path):
    """
    B06 regression: a H01 clubbed credit carries settlement_A's UTR in its
    narration but has amount = setl_A.amount + setl_B.amount.  Before the fix,
    exact_utr auto-matched it to setl_A (no amount guard), causing a journal
    imbalance of setl_B.amount paise.  After the fix it must:
      - not auto-match via exact_utr
      - reach pair_sum and be flagged PROPOSE/pair_sum (CLUBBED_CREDIT_SUSPECTED)
    """
    created_at = "2026-01-05"
    txn_date = "2026-01-07"

    settlements = [
        {
            "settlement_id": "setl_A", "utr": "AAAA1111BBBB2222",
            "amount_paise": "100000", "fees_paise": "0", "tax_paise": "0",
            "status": "processed", "created_at": created_at,
        },
        {
            "settlement_id": "setl_B", "utr": "CCCC3333DDDD4444",
            "amount_paise": "200000", "fees_paise": "0", "tax_paise": "0",
            "status": "processed", "created_at": created_at,
        },
    ]
    lines = [
        {
            "entity_id": "pay_A", "settlement_id": "setl_A",
            "settlement_utr": "AAAA1111BBBB2222", "type": "payment",
            "debit_paise": "0", "credit_paise": "100000", "amount_paise": "100000",
            "fee_paise": "0", "tax_paise": "0", "method": "upi", "order_id": "ord_A",
            "created_at": created_at, "settled_at": created_at,
        },
        {
            "entity_id": "pay_B", "settlement_id": "setl_B",
            "settlement_utr": "CCCC3333DDDD4444", "type": "payment",
            "debit_paise": "0", "credit_paise": "200000", "amount_paise": "200000",
            "fee_paise": "0", "tax_paise": "0", "method": "upi", "order_id": "ord_B",
            "created_at": created_at, "settled_at": created_at,
        },
    ]
    # Clubbed credit: amount = 100000 + 200000, narration has setl_A's UTR
    credits = [
        {
            "credit_id": "bc_clubbed", "value_date": txn_date, "txn_date": txn_date,
            "amount_paise": "300000",
            "narration_raw": "NEFT CR-RATN0000088-RAZORPAY-AAAA1111BBBB2222",
        },
    ]

    s_path = tmp_path / "settlements.csv"
    l_path = tmp_path / "recon_lines.csv"
    c_path = tmp_path / "bank_credits.csv"
    _write_csv(s_path, settlements)
    _write_csv(l_path, lines)
    _write_csv(c_path, credits)

    result = run_matcher(s_path, l_path, c_path, tmp_path / "out", pipeline="det")
    r = result["credits"][0]

    assert r["route"] != "AUTO_MATCH", (
        f"clubbed credit must not auto-match; got route={r['route']} stage={r['stage']}"
    )
    assert r["stage"] == "pair_sum", (
        f"expected pair_sum stage (CLUBBED_CREDIT_SUSPECTED), got stage={r['stage']}"
    )
    assert "setl_A" in r["settlement_ids"] and "setl_B" in r["settlement_ids"], (
        f"expected both setl_A and setl_B in candidates, got {r['settlement_ids']}"
    )


def test_fuzzy_disambiguates_amount_tie(tmp_path: Path):
    """
    Two settlements with identical amount_paise; one credit whose narration
    contains a fuzzy fragment of the first settlement's UTR.

    - det pipeline:       credit is PROPOSE (two amount+date candidates,
                          narration never consulted).
    - det+fuzzy pipeline: credit is AUTO_MATCH to the ABCD settlement,
                          stage "fuzzy_utr".

    This is the proof that fuzzy must precede amount_date.
    """
    created_at = "2026-01-05"
    txn_date = "2026-01-07"   # +2 business days from created_at

    settlements = [
        {"settlement_id": "setl_ABCD", "utr": "ABCD1234EFGH5678",
         "amount_paise": "100000", "fees_paise": "0", "tax_paise": "0",
         "status": "processed", "created_at": created_at},
        {"settlement_id": "setl_ZZZZ", "utr": "ZZZZ9999YYYY8888",
         "amount_paise": "100000", "fees_paise": "0", "tax_paise": "0",
         "status": "processed", "created_at": created_at},
    ]
    # "ABCD123" is 7 chars → below >=8 partial_utr cutoff, above >=6 fuzzy cutoff
    credits = [
        {"credit_id": "bc_001", "value_date": txn_date, "txn_date": txn_date,
         "amount_paise": "100000", "narration_raw": "PYMT-ABCD123-RZPSOFT"},
    ]

    s_path = tmp_path / "settlements.csv"
    l_path = tmp_path / "recon_lines.csv"
    c_path = tmp_path / "bank_credits.csv"
    # One payment line per settlement so verification resolves to EXACT.
    # amount_paise == credit.amount_paise (no fees) so journal balances too.
    lines = [
        {"entity_id": "pay_A", "settlement_id": "setl_ABCD",
         "settlement_utr": "ABCD1234EFGH5678", "type": "payment",
         "debit_paise": "0", "credit_paise": "100000", "amount_paise": "100000",
         "fee_paise": "0", "tax_paise": "0", "method": "upi", "order_id": "ord_A",
         "created_at": created_at, "settled_at": created_at},
        {"entity_id": "pay_Z", "settlement_id": "setl_ZZZZ",
         "settlement_utr": "ZZZZ9999YYYY8888", "type": "payment",
         "debit_paise": "0", "credit_paise": "100000", "amount_paise": "100000",
         "fee_paise": "0", "tax_paise": "0", "method": "upi", "order_id": "ord_Z",
         "created_at": created_at, "settled_at": created_at},
    ]
    _write_csv(s_path, settlements)
    _write_csv(l_path, lines)
    _write_csv(c_path, credits)

    # det pipeline: amount_date fires first, two matches → PROPOSE
    det = run_matcher(s_path, l_path, c_path, tmp_path / "det", pipeline="det")
    det_result = det["credits"][0]
    assert det_result["route"] == "PROPOSE", (
        f"det: expected PROPOSE (two-way amount tie), got {det_result['route']}"
    )

    # det+fuzzy: fuzzy stage fires before amount_date, narration resolves to ABCD
    fuzzy = run_matcher(
        s_path, l_path, c_path, tmp_path / "fuzzy", pipeline="det+fuzzy"
    )
    fuzzy_result = fuzzy["credits"][0]
    assert fuzzy_result["route"] == "AUTO_MATCH", (
        f"det+fuzzy: expected AUTO_MATCH, got {fuzzy_result['route']}"
    )
    assert fuzzy_result["stage"] == "fuzzy_utr"
    assert "setl_ABCD" in fuzzy_result["settlement_ids"]


def test_fuzzy_never_increases_exceptions(tmp_path: Path):
    """
    det+fuzzy exceptions <= det exceptions, and false_match_rate == 0 in both.
    Equality is a legitimate ablation result; do not tune threshold to force decrease.
    """
    gen = tmp_path / "gen"
    run_pipeline(42, 20, "seen", gen)
    gt = json.loads((gen / "ground_truth.json").read_text())

    det = run_matcher(
        gen / "settlements.csv",
        gen / "recon_lines.csv",
        gen / "bank_credits.csv",
        tmp_path / "det",
        pipeline="det",
    )
    fuzzy = run_matcher(
        gen / "settlements.csv",
        gen / "recon_lines.csv",
        gen / "bank_credits.csv",
        tmp_path / "fuzzy",
        pipeline="det+fuzzy",
    )

    det_scores = metrics.score(det, gt)
    fuzzy_scores = metrics.score(fuzzy, gt)

    assert fuzzy_scores["counts"]["exceptions"] <= det_scores["counts"]["exceptions"], (
        f"fuzzy exceptions {fuzzy_scores['counts']['exceptions']} > "
        f"det exceptions {det_scores['counts']['exceptions']}"
    )
    assert det_scores["false_match_rate"] == 0.0, det_scores
    assert fuzzy_scores["false_match_rate"] == 0.0, fuzzy_scores


def test_pipeline_flag_respected(tmp_path: Path):
    """With --pipeline det no result should carry stage 'fuzzy_utr'."""
    gen = tmp_path / "gen"
    run_pipeline(42, 20, "seen", gen)

    result = run_matcher(
        gen / "settlements.csv",
        gen / "recon_lines.csv",
        gen / "bank_credits.csv",
        tmp_path / "out",
        pipeline="det",
    )

    fuzzy_stages = [r for r in result["credits"] if r["stage"] == "fuzzy_utr"]
    assert fuzzy_stages == [], f"det pipeline produced fuzzy_utr stages: {fuzzy_stages}"
