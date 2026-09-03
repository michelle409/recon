from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from recon import metrics
from recon.generator import run_pipeline
from recon.matcher import run_matcher


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _fixture_paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    return (
        tmp_path / "settlements.csv",
        tmp_path / "recon_lines.csv",
        tmp_path / "bank_credits.csv",
        tmp_path / "out",
    )


# ── tests ─────────────────────────────────────────────────────────────────────

def test_perfect_data_full_match(tmp_path: Path):
    """With no corruptions every credit should AUTO_MATCH its settlement."""
    gen = tmp_path / "gen"
    run_pipeline(42, 10, "none", gen)

    result = run_matcher(
        gen / "settlements.csv",
        gen / "recon_lines.csv",
        gen / "bank_credits.csv",
        tmp_path / "out",
    )

    gt = json.loads((gen / "ground_truth.json").read_text())
    scores = metrics.score(result, gt)

    assert scores["match_rate"] == 1.0, scores
    assert scores["false_match_rate"] == 0.0, scores
    assert scores["exception_rate"] == 0.0, scores


def test_deduplication(tmp_path: Path):
    """C03 exact duplicates must be routed DUPLICATE, not matched."""
    gen = tmp_path / "gen"
    run_pipeline(42, 20, "seen", gen)

    gt = json.loads((gen / "ground_truth.json").read_text())
    dup_ids = set(gt["duplicate_credit_ids"])
    assert dup_ids, "C03 must produce duplicates with this seed"

    result = run_matcher(
        gen / "settlements.csv",
        gen / "recon_lines.csv",
        gen / "bank_credits.csv",
        tmp_path / "out",
    )

    by_id = {r["credit_id"]: r for r in result["credits"]}
    for did in dup_ids:
        if did in by_id:
            assert by_id[did]["route"] == "DUPLICATE", (
                f"{did}: expected DUPLICATE, got {by_id[did]['route']}"
            )


def test_refuse_not_false_match(tmp_path: Path):
    """REFUSE must not be counted as a false match in metrics."""
    s_path, l_path, c_path, out = _fixture_paths(tmp_path)

    _write_csv(s_path, [{"settlement_id": "setl_A", "utr": "UTRAAA12345678",
                          "amount_paise": "100000", "fees_paise": "30",
                          "tax_paise": "6", "status": "processed",
                          "created_at": "2026-01-05"}])
    _write_csv(l_path, [{"entity_id": "pay_1", "settlement_id": "setl_A",
                          "settlement_utr": "UTRAAA12345678", "type": "payment",
                          "debit_paise": "0", "credit_paise": "99964",
                          "amount_paise": "100000", "fee_paise": "30",
                          "tax_paise": "6", "method": "upi", "order_id": "ord_1",
                          "created_at": "2026-01-05", "settled_at": "2026-01-05"}])
    # Credit whose amount does not match anything
    _write_csv(c_path, [{"credit_id": "bc_001", "value_date": "2026-01-07",
                          "txn_date": "2026-01-07", "amount_paise": "999999999",
                          "narration_raw": "NEFT CREDIT UNRELATED TRANSFER"}])

    result = run_matcher(s_path, l_path, c_path, out)
    assert result["credits"][0]["route"] == "REFUSE"

    gt = {
        "credit_to_settlements": {"bc_001": ["setl_A"]},
        "duplicate_credit_ids": [],
        "settlement_to_entities": {"setl_A": ["pay_1"]},
        "expected_arithmetic_fail_settlements": [],
    }
    scores = metrics.score(result, gt)
    assert scores["false_match_rate"] == 0.0


def test_amount_tolerance_zero(tmp_path: Path):
    """A credit 1 paise off must not match the settlement."""
    s_path, l_path, c_path, out = _fixture_paths(tmp_path)

    _write_csv(s_path, [{"settlement_id": "setl_B", "utr": "UTRBBB12345678",
                          "amount_paise": "100000", "fees_paise": "30",
                          "tax_paise": "6", "status": "processed",
                          "created_at": "2026-01-05"}])
    _write_csv(l_path, [])
    # Credit with amount 1 paise above settlement, no UTR in narration
    _write_csv(c_path, [{"credit_id": "bc_001", "value_date": "2026-01-07",
                          "txn_date": "2026-01-07", "amount_paise": "100001",
                          "narration_raw": "NEFT CREDIT BY TRANSFER ONLY"}])

    result = run_matcher(s_path, l_path, c_path, out)
    r = result["credits"][0]
    assert r["route"] == "REFUSE", (
        f"Off-by-1-paise credit must be REFUSED, got {r['route']}"
    )


def test_claim_conflict_proposes(tmp_path: Path):
    """Two credits both matching the same settlement via UTR → both PROPOSE."""
    s_path, l_path, c_path, out = _fixture_paths(tmp_path)

    _write_csv(s_path, [{"settlement_id": "setl_C", "utr": "UTRCCC12345678",
                          "amount_paise": "100000", "fees_paise": "0",
                          "tax_paise": "0", "status": "processed",
                          "created_at": "2026-01-05"}])
    _write_csv(l_path, [])
    _write_csv(c_path, [
        {"credit_id": "bc_001", "value_date": "2026-01-07", "txn_date": "2026-01-07",
         "amount_paise": "60000",
         "narration_raw": "NEFT CR-RATN0000088-RAZORPAY-UTRCCC12345678"},
        {"credit_id": "bc_002", "value_date": "2026-01-07", "txn_date": "2026-01-07",
         "amount_paise": "40000",
         "narration_raw": "NEFT CR-RATN0000088-RAZORPAY-UTRCCC12345678"},
    ])

    result = run_matcher(s_path, l_path, c_path, out)
    by_id = {r["credit_id"]: r for r in result["credits"]}

    for cid in ("bc_001", "bc_002"):
        assert by_id[cid]["route"] == "PROPOSE", (
            f"{cid}: expected PROPOSE (claim-conflict), got {by_id[cid]['route']}"
        )


def test_pair_sum_detection(tmp_path: Path):
    """Two credits on the same date summing to a settlement → both PROPOSE via pair_sum."""
    s_path, l_path, c_path, out = _fixture_paths(tmp_path)

    _write_csv(s_path, [{"settlement_id": "setl_D", "utr": "UTRDDD12345678",
                          "amount_paise": "100000", "fees_paise": "0",
                          "tax_paise": "0", "status": "processed",
                          "created_at": "2026-01-05"}])
    _write_csv(l_path, [])
    # No UTR in narrations; individual amounts don't match settlement
    _write_csv(c_path, [
        {"credit_id": "bc_001", "value_date": "2026-01-07", "txn_date": "2026-01-07",
         "amount_paise": "60000", "narration_raw": "NEFT CREDIT"},
        {"credit_id": "bc_002", "value_date": "2026-01-07", "txn_date": "2026-01-07",
         "amount_paise": "40000", "narration_raw": "NEFT CREDIT"},
    ])

    result = run_matcher(s_path, l_path, c_path, out)
    by_id = {r["credit_id"]: r for r in result["credits"]}

    for cid in ("bc_001", "bc_002"):
        assert by_id[cid]["route"] == "PROPOSE", (
            f"{cid}: expected PROPOSE (pair_sum), got {by_id[cid]['route']}"
        )
        assert by_id[cid]["stage"] == "pair_sum"
        assert "setl_D" in by_id[cid]["settlement_ids"]


def test_dedupe_without_reference_suspected(tmp_path: Path):
    """Same txn_date + amount, different narration → second credit is DUPLICATE_SUSPECTED."""
    s_path, l_path, c_path, out = _fixture_paths(tmp_path)

    _write_csv(s_path, [{"settlement_id": "setl_E", "utr": "UTREEE12345678",
                          "amount_paise": "100000", "fees_paise": "0",
                          "tax_paise": "0", "status": "processed",
                          "created_at": "2026-01-05"}])
    _write_csv(l_path, [])
    _write_csv(c_path, [
        {"credit_id": "bc_001", "value_date": "2026-01-07", "txn_date": "2026-01-07",
         "amount_paise": "100000", "narration_raw": "NEFT CR-FIRST-NARRATION"},
        {"credit_id": "bc_002", "value_date": "2026-01-07", "txn_date": "2026-01-07",
         "amount_paise": "100000", "narration_raw": "NEFT CR-DIFFERENT-NARRATION"},
    ])

    result = run_matcher(s_path, l_path, c_path, out)
    by_id = {r["credit_id"]: r for r in result["credits"]}

    assert by_id["bc_002"]["route"] == "DUPLICATE_SUSPECTED", (
        f"Expected DUPLICATE_SUSPECTED, got {by_id['bc_002']['route']}"
    )
