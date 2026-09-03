from __future__ import annotations

import csv
import json
import random
from pathlib import Path

import pytest

from recon.generator import generate_clean, run_pipeline


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _ties(settlements: list[dict], lines: list[dict]) -> list[str]:
    """Return settlement_ids that do NOT tie."""
    by_setl: dict[str, list[dict]] = {}
    for l in lines:
        by_setl.setdefault(l["settlement_id"], []).append(l)
    failing = []
    for s in settlements:
        sid = s["settlement_id"]
        ls = by_setl.get(sid, [])
        actual = sum(int(l["credit_paise"]) for l in ls) - sum(int(l["debit_paise"]) for l in ls)
        if actual != int(s["amount_paise"]):
            failing.append(sid)
    return failing


# ── tests ─────────────────────────────────────────────────────────────────────

def test_clean_generation_ties():
    rng = random.Random(42)
    settlements, lines = generate_clean(rng, 15)

    by_setl: dict[str, list] = {}
    for l in lines:
        by_setl.setdefault(l.settlement_id, []).append(l)

    for s in settlements:
        ls = by_setl.get(s.settlement_id, [])
        actual_amount = sum(l.credit_paise for l in ls) - sum(l.debit_paise for l in ls)
        actual_fees = sum(l.fee_paise for l in ls)
        actual_tax = sum(l.tax_paise for l in ls)
        assert actual_amount == s.amount_paise, f"{s.settlement_id}: amount mismatch"
        assert actual_fees == s.fees_paise, f"{s.settlement_id}: fees mismatch"
        assert actual_tax == s.tax_paise, f"{s.settlement_id}: tax mismatch"


def test_reproducible(tmp_path: Path):
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    run_pipeline(42, 20, "seen", out1)
    run_pipeline(42, 20, "seen", out2)

    for fname in ["settlements.csv", "recon_lines.csv", "bank_credits.csv", "ground_truth.json"]:
        assert (out1 / fname).read_bytes() == (out2 / fname).read_bytes(), (
            f"{fname} differs between identical-seed runs"
        )


def test_ground_truth_complete(tmp_path: Path):
    out = tmp_path / "run"
    run_pipeline(7, 20, "all", out)

    gt = json.loads((out / "ground_truth.json").read_text())
    credits = _read_csv(out / "bank_credits.csv")
    settlements = _read_csv(out / "settlements.csv")

    all_credit_ids = {row["credit_id"] for row in credits}
    dup_ids = set(gt["duplicate_credit_ids"])
    mapped_ids = set(gt["credit_to_settlements"])
    all_setl_ids = {row["settlement_id"] for row in settlements}

    # Every non-duplicate credit must be in the mapping
    for cid in all_credit_ids - dup_ids:
        assert cid in mapped_ids, f"credit {cid} missing from credit_to_settlements"

    # Duplicates must NOT appear in the mapping
    for dup in dup_ids:
        assert dup not in mapped_ids, f"duplicate {dup} should not be in credit_to_settlements"

    # Every settlement must have an entity list
    for sid in all_setl_ids:
        assert sid in gt["settlement_to_entities"], f"settlement {sid} missing from settlement_to_entities"

    # H01 credits must map to exactly 2 settlements
    h01_records = [r for r in gt["corruptions"] if r["id"] == "H01"]
    for rec in h01_records:
        merged_id = rec["target"]
        assert merged_id in mapped_ids, f"H01 merged credit {merged_id} not mapped"
        assert len(gt["credit_to_settlements"][merged_id]) == 2, (
            f"H01 merged credit {merged_id} should map to 2 settlements"
        )

    # H04 pairs: both credits map to same settlement, sums match
    h04_records = [r for r in gt["corruptions"] if r["id"] == "H04"]
    credits_by_id = {row["credit_id"]: int(row["amount_paise"]) for row in credits}
    setl_by_id = {row["settlement_id"]: int(row["amount_paise"]) for row in settlements}

    for rec in h04_records:
        # Find the two credits that map to this settlement
        # The target field holds the original credit_id; find all credits mapping to its settlement
        detail = rec["detail"]
        # Parse split credits from detail: "split into bc_XXX(amt) + bc_YYY(amt) for setl_ZZZ"
        parts = detail.split(" for ")
        sid = parts[-1]
        split_credits = [cid for cid, sids in gt["credit_to_settlements"].items() if sid in sids]
        assert len(split_credits) == 2, f"H04 settlement {sid} should have 2 credits"
        total = sum(credits_by_id[cid] for cid in split_credits)
        assert total == setl_by_id[sid], (
            f"H04 split credits for {sid} sum to {total}, expected {setl_by_id[sid]}"
        )


def test_corrupted_world_ties_except_c06(tmp_path: Path):
    out = tmp_path / "run"
    run_pipeline(42, 20, "seen", out)

    gt = json.loads((out / "ground_truth.json").read_text())
    expected_fails = set(gt["expected_arithmetic_fail_settlements"])

    settlements = _read_csv(out / "settlements.csv")
    lines = _read_csv(out / "recon_lines.csv")

    by_setl: dict[str, list[dict]] = {}
    for l in lines:
        by_setl.setdefault(l["settlement_id"], []).append(l)

    for s in settlements:
        sid = s["settlement_id"]
        ls = by_setl.get(sid, [])
        actual = sum(int(l["credit_paise"]) for l in ls) - sum(int(l["debit_paise"]) for l in ls)
        expected = int(s["amount_paise"])

        if sid in expected_fails:
            drift = abs(actual - expected)
            assert 1 <= drift <= 10, (
                f"C06 settlement {sid}: drift {drift} outside expected [1, 10] paise"
            )
        else:
            assert actual == expected, (
                f"Unexpected arithmetic failure in settlement {sid}: "
                f"actual={actual}, expected={expected}"
            )
