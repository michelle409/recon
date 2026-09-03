from __future__ import annotations

"""
Synthetic data generator for payment reconciliation evaluation.

Run as:
    PYTHONPATH=src .venv/bin/python -m recon.generator [--seed N] [--settlements N]
        [--corruption-set {seen,all}] [--out PATH]
"""

import argparse
import csv
import json
import random
import string
from pathlib import Path

from recon import calendars, corruptions
from recon.fees import fee_paise, gst_paise
from recon.models import BankCredit, GroundTruth, ReconLine, Settlement, World

# ── ID helpers ────────────────────────────────────────────────────────────────

_ALNUM = string.ascii_letters + string.digits
_UPPER = string.ascii_uppercase + string.digits


def _rand_id(prefix: str, rng: random.Random) -> str:
    return prefix + "".join(rng.choices(_ALNUM, k=14))


def _rand_utr(rng: random.Random) -> str:
    return "".join(rng.choices(_UPPER, k=16))


# ── calendar helpers ──────────────────────────────────────────────────────────

def _business_days_in_range(start: str, end: str) -> list[str]:
    import datetime
    days = []
    d = datetime.date.fromisoformat(start)
    end_d = datetime.date.fromisoformat(end)
    while d <= end_d:
        if calendars.is_business_day(d.isoformat()):
            days.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return days


# ── assertion ─────────────────────────────────────────────────────────────────

def _assert_ties(
    world: World,
    context: str,
    skip_ids: set[str] | None = None,
) -> None:
    skip_ids = skip_ids or set()
    for s in world.settlements:
        if s.settlement_id in skip_ids:
            continue
        ls = world.lines_for(s.settlement_id)
        actual_amount = sum(l.credit_paise for l in ls) - sum(l.debit_paise for l in ls)
        actual_fees = sum(l.fee_paise for l in ls)
        actual_tax = sum(l.tax_paise for l in ls)
        if (
            actual_amount != s.amount_paise
            or actual_fees != s.fees_paise
            or actual_tax != s.tax_paise
        ):
            raise AssertionError(
                f"[{context}] Generator bug — settlement {s.settlement_id} does not tie:\n"
                f"  amount : expected {s.amount_paise}, got {actual_amount}\n"
                f"  fees   : expected {s.fees_paise}, got {actual_fees}\n"
                f"  tax    : expected {s.tax_paise}, got {actual_tax}"
            )


# ── clean-world generation (public for tests) ─────────────────────────────────

def generate_clean(
    rng: random.Random, n: int
) -> tuple[list[Settlement], list[ReconLine]]:
    """Generate n clean settlements. Exposed for unit testing."""
    all_bdays = _business_days_in_range("2026-01-05", "2026-02-20")
    settlements: list[Settlement] = []
    all_lines: list[ReconLine] = []

    for _ in range(n):
        created_at = rng.choice(all_bdays)
        settlement_id = _rand_id("setl_", rng)
        utr = _rand_utr(rng)

        lines: list[ReconLine] = []

        # payment lines
        n_pay = rng.randint(5, 30)
        for _ in range(n_pay):
            entity_id = _rand_id("pay_", rng)
            order_id = _rand_id("order_", rng)
            method = rng.choice(["upi", "card", "netbanking"])
            amount = rng.randint(10000, 5000000)
            fee = fee_paise(amount, method)
            tax = gst_paise(fee)
            credit = amount - fee - tax
            lines.append(ReconLine(
                entity_id=entity_id,
                settlement_id=settlement_id,
                settlement_utr=utr,
                type="payment",
                debit_paise=0,
                credit_paise=credit,
                amount_paise=amount,
                fee_paise=fee,
                tax_paise=tax,
                method=method,
                order_id=order_id,
                created_at=created_at,
                settled_at=created_at,
            ))

        payment_lines = lines[:]
        remaining = sum(l.credit_paise for l in payment_lines)

        # refund lines
        n_ref = rng.randint(0, 3)
        for _ in range(n_ref):
            if remaining < 5000:
                break
            max_ref = min(200000, remaining)
            ref_amt = rng.randint(5000, max_ref)
            parent = rng.choice(payment_lines)
            entity_id = _rand_id("rfnd_", rng)
            lines.append(ReconLine(
                entity_id=entity_id,
                settlement_id=settlement_id,
                settlement_utr=utr,
                type="refund",
                debit_paise=ref_amt,
                credit_paise=0,
                amount_paise=ref_amt,
                fee_paise=0,
                tax_paise=0,
                method="na",
                order_id=parent.order_id,
                created_at=created_at,
                settled_at=created_at,
            ))
            remaining -= ref_amt

        # adjustment line (30% chance)
        if rng.random() < 0.30:
            adj_amt = rng.randint(500, 50000)
            is_credit = rng.random() < 0.5
            entity_id = _rand_id("adj_", rng)
            lines.append(ReconLine(
                entity_id=entity_id,
                settlement_id=settlement_id,
                settlement_utr=utr,
                type="adjustment",
                debit_paise=0 if is_credit else adj_amt,
                credit_paise=adj_amt if is_credit else 0,
                amount_paise=adj_amt,
                fee_paise=0,
                tax_paise=0,
                method="na",
                order_id="",
                created_at=created_at,
                settled_at=created_at,
            ))

        amount_total = (
            sum(l.credit_paise for l in lines)
            - sum(l.debit_paise for l in lines)
        )
        fees_total = sum(l.fee_paise for l in lines)
        tax_total = sum(l.tax_paise for l in lines)

        settlements.append(Settlement(
            settlement_id=settlement_id,
            utr=utr,
            amount_paise=amount_total,
            fees_paise=fees_total,
            tax_paise=tax_total,
            status="processed",
            created_at=created_at,
        ))
        all_lines.extend(lines)

    return settlements, all_lines


# ── emit ──────────────────────────────────────────────────────────────────────

_SETTLEMENT_FIELDS = [
    "settlement_id", "utr", "amount_paise", "fees_paise", "tax_paise",
    "status", "created_at",
]
_LINE_FIELDS = [
    "entity_id", "settlement_id", "settlement_utr", "type",
    "debit_paise", "credit_paise", "amount_paise", "fee_paise", "tax_paise",
    "method", "order_id", "created_at", "settled_at",
]
_CREDIT_FIELDS = [
    "credit_id", "value_date", "txn_date", "amount_paise", "narration_raw",
]


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


# ── full pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(
    seed: int,
    n_settlements: int,
    corruption_set: str,
    out_path: Path,
) -> GroundTruth:
    rng = random.Random(seed)
    do_all = corruption_set == "all"

    # ── STEP 1: clean world ───────────────────────────────────────────────────
    settlements, lines = generate_clean(rng, n_settlements)
    world = World(settlements=settlements, lines=lines)
    _assert_ties(world, "clean world")

    # ── STEP 2: settlement-side structural corruptions ────────────────────────
    recs = corruptions.apply_c04(world, rng)
    world.corruption_records.extend(recs)

    if do_all:
        recs = corruptions.apply_h03(world, rng)
        world.corruption_records.extend(recs)

    _assert_ties(world, "post step-2")

    # ── STEP 3: bank credits ──────────────────────────────────────────────────
    for s in world.settlements:
        txn_date = calendars.add_business_days(s.created_at, 2)
        utr = s.utr  # use the settlement's UTR
        narration = corruptions._build_narration(utr, rng)
        cid = world.next_credit_id()
        credit = BankCredit(
            credit_id=cid,
            value_date=txn_date,
            txn_date=txn_date,
            amount_paise=s.amount_paise,
            narration_raw=narration,
        )
        world.credits.append(credit)
        world.credit_utr[cid] = utr
        world.credit_to_settlements[cid] = [s.settlement_id]

    # ── STEP 4: C06 per_line_rounding_drift ───────────────────────────────────
    recs = corruptions.apply_c06(world, rng)
    world.corruption_records.extend(recs)

    # ── STEP 5: bank-side structural ─────────────────────────────────────────
    h01_used_sids: set[str] = set()
    if do_all:
        used_pairs = corruptions.apply_h01(world, rng)
        for c1_id, c2_id in used_pairs:
            # used_pairs are original credit IDs; we need the settlement IDs
            # they're already gone from credit_to_settlements, so track from records
            pass
        # Collect settlement IDs used by H01 from the corruption record
        for rec in world.corruption_records:
            if rec["id"] == "H01":
                merged_id = rec["target"]
                h01_used_sids.update(world.credit_to_settlements.get(merged_id, []))

        corruptions.apply_h04(world, rng, h01_used_sids)

    # ── STEP 6: bank-side information-destroying ──────────────────────────────
    modified: set[str] = set()
    recs = corruptions.apply_c01(world, rng, modified)
    world.corruption_records.extend(recs)
    recs = corruptions.apply_c02(world, rng, modified)
    world.corruption_records.extend(recs)

    if do_all:
        recs = corruptions.apply_h02(world, rng, modified)
        world.corruption_records.extend(recs)

    recs = corruptions.apply_c05(world, rng)
    world.corruption_records.extend(recs)

    # ── STEP 7: C03 duplicate_export ─────────────────────────────────────────
    recs = corruptions.apply_c03(world, rng)
    world.corruption_records.extend(recs)

    # ── STEP 8: emit ─────────────────────────────────────────────────────────
    out_path.mkdir(parents=True, exist_ok=True)

    # Build settlement_to_entities from final line state
    settlement_to_entities: dict[str, list[str]] = {
        s.settlement_id: [l.entity_id for l in world.lines_for(s.settlement_id)]
        for s in world.settlements
    }

    gt = GroundTruth(
        seed=seed,
        corruption_set=corruption_set,
        credit_to_settlements={
            cid: sids
            for cid, sids in world.credit_to_settlements.items()
        },
        settlement_to_entities=settlement_to_entities,
        duplicate_credit_ids=world.duplicate_credit_ids,
        expected_arithmetic_fail_settlements=world.expected_arithmetic_fail_settlements,
        corruptions=world.corruption_records,
    )

    _write_csv(
        out_path / "settlements.csv",
        _SETTLEMENT_FIELDS,
        [s.model_dump() for s in world.settlements],
    )
    _write_csv(
        out_path / "recon_lines.csv",
        _LINE_FIELDS,
        [l.model_dump() for l in world.lines],
    )
    _write_csv(
        out_path / "bank_credits.csv",
        _CREDIT_FIELDS,
        [c.model_dump() for c in world.credits],
    )
    (out_path / "ground_truth.json").write_text(
        gt.model_dump_json(indent=2), encoding="utf-8"
    )

    # ── STEP 9: verify & summarise ────────────────────────────────────────────
    fail_set = set(world.expected_arithmetic_fail_settlements)
    _assert_ties(world, "final (excluding C06)", skip_ids=fail_set)

    # Verify C06 settlements drift by 1-10 paise (generator self-check)
    for sid in fail_set:
        s = world.settlement_by_id(sid)
        ls = world.lines_for(sid)
        actual = sum(l.credit_paise for l in ls) - sum(l.debit_paise for l in ls)
        drift = abs(actual - s.amount_paise)
        if drift == 0 or drift > 10:
            raise AssertionError(
                f"Generator bug — C06 settlement {sid} drift={drift} outside [1,10]"
            )

    _print_summary(world, gt)
    return gt


def _print_summary(world: World, gt: GroundTruth) -> None:
    line_counts = {}
    for l in world.lines:
        line_counts[l.type] = line_counts.get(l.type, 0) + 1

    total_credits = len(world.credits)
    dup_count = len(world.duplicate_credit_ids)

    print(f"\n=== Generator summary ===")
    print(f"Settlements : {len(world.settlements)}")
    print(f"Lines       : {sum(line_counts.values())} "
          f"(payment={line_counts.get('payment', 0)}, "
          f"refund={line_counts.get('refund', 0)}, "
          f"adjustment={line_counts.get('adjustment', 0)})")
    print(f"Credits     : {total_credits} total ({dup_count} duplicates)")

    print(f"\nCorruptions applied:")
    by_id: dict[str, list[str]] = {}
    for rec in gt.corruptions:
        by_id.setdefault(rec["id"], []).append(rec["target"])
    for cid, targets in sorted(by_id.items()):
        print(f"  {cid}: {targets}")

    n_pass = len(world.settlements) - len(gt.expected_arithmetic_fail_settlements)
    fail_ids = gt.expected_arithmetic_fail_settlements
    print(
        f"\nArithmetic : PASS ({n_pass} settlements tie; "
        f"{len(fail_ids)} expected fails from C06: {fail_ids})"
    )


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic Razorpay settlement fixtures"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--settlements", type=int, default=20)
    parser.add_argument(
        "--corruption-set", choices=["seen", "all"], default="seen"
    )
    parser.add_argument("--out", type=Path, default=Path("data/generated"))
    args = parser.parse_args()

    run_pipeline(args.seed, args.settlements, args.corruption_set, args.out)


if __name__ == "__main__":
    main()
