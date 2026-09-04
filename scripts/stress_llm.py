from __future__ import annotations

"""
Stress diagnostic for rung 3 (LLM tie-breaker).

Run as:
    PYTHONPATH=src .venv/bin/python scripts/stress_llm.py
"""

import csv
import json
import sys
from pathlib import Path

# ── import generation-side tooling ────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from recon import calendars
from recon.fees import fee_paise, gst_paise

# ── output directory ──────────────────────────────────────────────────────────

OUT = Path("data/generated_stress")

# ── column orders (mirrors generator.py _SETTLEMENT_FIELDS etc.) ──────────────

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

# ── fixed UTRs ────────────────────────────────────────────────────────────────
# P1
UTR_S01 = "AKQJ7T2M9XWBZ4YH"
UTR_S02 = "RNPD5G8VE3CULF6S"
# P2
UTR_S03 = "MHXE94TQZKP2WV7B"
UTR_S04 = "GDYC63JNRLA8UF5T"
# P3
UTR_S05 = "TPWKQ82ZMEJX4NCY"
UTR_S06 = "VBSLH37GRDAF9UOI"
# P4
UTR_S07 = "ZQFN81MYTKDW5RVJ"
UTR_S08 = "CXHU29PSLBGE7KAD"
# Easy
UTR_S09 = "PFXM3BNKZ7QRVCWT"
UTR_S10 = "EJWG45LHUD82YNOS"
UTR_S11 = "CTVRK9ISZQ6XPAMB"   # never appears in narration
UTR_S12 = "WHMQ71DJAEFK3BTL"

# ── fixed settlement ids ──────────────────────────────────────────────────────

SID = {
    "S01": "setl_S01stress0000001",
    "S02": "setl_S02stress0000002",
    "S03": "setl_S03stress0000003",
    "S04": "setl_S04stress0000004",
    "S05": "setl_S05stress0000005",
    "S06": "setl_S06stress0000006",
    "S07": "setl_S07stress0000007",
    "S08": "setl_S08stress0000008",
    "S09": "setl_S09stress0000009",
    "S10": "setl_S10stress0000010",
    "S11": "setl_S11stress0000011",
    "S12": "setl_S12stress0000012",
}

# ── fixed entity/order ids (deterministic) ────────────────────────────────────

def _eid(tag: str) -> str:
    """Fixed entity id for a given short tag."""
    return f"pay_{tag}stress00000001"

def _oid(tag: str) -> str:
    return f"order_{tag}stress0000001"

# ── line-structure specs (method, gross_amount_paise) ─────────────────────────
# Each entry becomes one payment ReconLine. fee/tax computed via fees.py.

PAIR_LINES: dict[str, list[tuple[str, int]]] = {
    "P1": [("upi", 1_500_000), ("card", 2_350_000)],
    "P2": [("netbanking", 4_200_000), ("upi", 800_000), ("card", 999_000)],
    "P3": [("card", 3_100_000), ("card", 3_100_000)],
    "P4": [("upi", 2_750_000), ("netbanking", 1_250_000)],
}

EASY_SPECS: dict[str, dict] = {
    "S09": {
        "created_at": "2026-01-19",
        "utr": UTR_S09,
        "lines": [("upi", 1_111_100)],
    },
    "S10": {
        "created_at": "2026-01-20",
        "utr": UTR_S10,
        "lines": [("card", 2_222_200), ("upi", 505_000)],
    },
    "S11": {
        "created_at": "2026-01-21",
        "utr": UTR_S11,
        "lines": [("netbanking", 3_333_300)],
    },
    "S12": {
        "created_at": "2026-01-22",
        "utr": UTR_S12,
        "lines": [("upi", 4_444_400), ("card", 1_200_000)],
    },
}

PAIR_DATES: dict[str, str] = {
    "P1": "2026-01-12",
    "P2": "2026-01-13",
    "P3": "2026-01-14",
    "P4": "2026-01-15",
}

PAIR_UTRS: dict[str, tuple[str, str]] = {
    "P1": (UTR_S01, UTR_S02),
    "P2": (UTR_S03, UTR_S04),
    "P3": (UTR_S05, UTR_S06),
    "P4": (UTR_S07, UTR_S08),
}

PAIR_SIDS: dict[str, tuple[str, str]] = {
    "P1": (SID["S01"], SID["S02"]),
    "P2": (SID["S03"], SID["S04"]),
    "P3": (SID["S05"], SID["S06"]),
    "P4": (SID["S07"], SID["S08"]),
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_lines(
    sid: str, utr: str, created_at: str, line_specs: list[tuple[str, int]]
) -> list[dict]:
    rows = []
    for i, (method, gross) in enumerate(line_specs):
        fee = fee_paise(gross, method)
        tax = gst_paise(fee)
        net = gross - fee - tax
        tag = f"{sid[-3:]}{method[:2]}{i}"
        rows.append({
            "entity_id": _eid(tag),
            "settlement_id": sid,
            "settlement_utr": utr,
            "type": "payment",
            "debit_paise": 0,
            "credit_paise": net,
            "amount_paise": gross,
            "fee_paise": fee,
            "tax_paise": tax,
            "method": method,
            "order_id": _oid(tag),
            "created_at": created_at,
            "settled_at": created_at,
        })
    return rows


def _settlement_from_lines(
    sid: str, utr: str, created_at: str, lines: list[dict]
) -> dict:
    amount = sum(r["credit_paise"] for r in lines) - sum(r["debit_paise"] for r in lines)
    fees   = sum(r["fee_paise"]    for r in lines)
    tax    = sum(r["tax_paise"]    for r in lines)
    return {
        "settlement_id": sid,
        "utr": utr,
        "amount_paise": amount,
        "fees_paise": fees,
        "tax_paise": tax,
        "status": "processed",
        "created_at": created_at,
    }


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


# ── build dataset ─────────────────────────────────────────────────────────────

def build_dataset() -> tuple[list[dict], list[dict], list[dict], dict]:
    """Return (settlements, lines, credits, ground_truth)."""
    all_settlements: list[dict] = []
    all_lines:       list[dict] = []
    all_credits:     list[dict] = []
    credit_to_settlements: dict[str, list[str]] = {}
    settlement_to_entities: dict[str, list[str]] = {}

    credit_seq = 0

    def next_credit_id() -> str:
        nonlocal credit_seq
        credit_seq += 1
        return f"stress_cred_{credit_seq:03d}"

    # ── pairs P1–P4 ───────────────────────────────────────────────────────────
    for pair, (sid_a, sid_b) in PAIR_SIDS.items():
        date    = PAIR_DATES[pair]
        utr_a, utr_b = PAIR_UTRS[pair]
        specs   = PAIR_LINES[pair]

        lines_a = _make_lines(sid_a, utr_a, date, specs)
        lines_b = _make_lines(sid_b, utr_b, date, specs)

        setl_a = _settlement_from_lines(sid_a, utr_a, date, lines_a)
        setl_b = _settlement_from_lines(sid_b, utr_b, date, lines_b)

        all_settlements += [setl_a, setl_b]
        all_lines       += lines_a + lines_b

        settlement_to_entities[sid_a] = [r["entity_id"] for r in lines_a]
        settlement_to_entities[sid_b] = [r["entity_id"] for r in lines_b]

        txn_date = calendars.add_business_days(date, 2)

        if pair == "P1":
            cid = next_credit_id()
            all_credits.append({
                "credit_id": cid,
                "value_date": txn_date,
                "txn_date": txn_date,
                "amount_paise": setl_a["amount_paise"],
                "narration_raw": "NEFT CR-RATN0000088-RZPSOFTWARE-AKQJ",
            })
            credit_to_settlements[cid] = [sid_a]

        elif pair == "P2":
            cid = next_credit_id()
            all_credits.append({
                "credit_id": cid,
                "value_date": txn_date,
                "txn_date": txn_date,
                "amount_paise": setl_a["amount_paise"],
                "narration_raw": "NEFTCR-YES-RAZORPAYSOFTWARE-MHXE9",
            })
            credit_to_settlements[cid] = [sid_a]

        elif pair == "P3":
            cid_a = next_credit_id()
            all_credits.append({
                "credit_id": cid_a,
                "value_date": txn_date,
                "txn_date": txn_date,
                "amount_paise": setl_a["amount_paise"],
                "narration_raw": "NEFT CR-HDFC0000060-RZP-TPWKQ",
            })
            credit_to_settlements[cid_a] = [sid_a]

            cid_b = next_credit_id()
            all_credits.append({
                "credit_id": cid_b,
                "value_date": txn_date,
                "txn_date": txn_date,
                "amount_paise": setl_b["amount_paise"],
                "narration_raw": "NEFT CR-HDFC0000060-RZP-VBSLH",
            })
            credit_to_settlements[cid_b] = [sid_b]

        elif pair == "P4":
            cid = next_credit_id()
            all_credits.append({
                "credit_id": cid,
                "value_date": txn_date,
                "txn_date": txn_date,
                "amount_paise": setl_a["amount_paise"],
                "narration_raw": "NEFT CR-ICIC0000104-RAZORPAY SOFTWARE PVT LTD-ZQFN81",
            })
            credit_to_settlements[cid] = [sid_a]
        # S02 and S04 intentionally have no credit

    # ── easy settlements S09–S12 ──────────────────────────────────────────────
    for key, spec in EASY_SPECS.items():
        sid        = SID[key]
        utr        = spec["utr"]
        created_at = spec["created_at"]
        specs      = spec["lines"]

        lines = _make_lines(sid, utr, created_at, specs)
        setl  = _settlement_from_lines(sid, utr, created_at, lines)

        all_settlements.append(setl)
        all_lines += lines
        settlement_to_entities[sid] = [r["entity_id"] for r in lines]

        txn_date = calendars.add_business_days(created_at, 2)
        amt      = setl["amount_paise"]

        if key == "S09":
            narration = f"NEFT CR-HDFC0000001-RAZORPAY-{utr}"
        elif key == "S10":
            narration = f"NEFT CR-ICIC0000104-RAZORPAY-{utr[:10]}"
        elif key == "S11":
            narration = "RAZORPAYSOFTWARE-REF778812"
        elif key == "S12":
            narration = f"RTGSCR-ICIC0000104-RAZORPAY SOFTWARE PRIVATE LTD-{utr}"

        cid = next_credit_id()
        all_credits.append({
            "credit_id": cid,
            "value_date": txn_date,
            "txn_date": txn_date,
            "amount_paise": amt,
            "narration_raw": narration,
        })
        credit_to_settlements[cid] = [sid]

    ground_truth = {
        "seed": 0,
        "corruption_set": "stress",
        "credit_to_settlements": credit_to_settlements,
        "settlement_to_entities": settlement_to_entities,
        "duplicate_credit_ids": [],
        "expected_arithmetic_fail_settlements": [],
        "corruptions": [],
    }

    return all_settlements, all_lines, all_credits, ground_truth


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(
        "STRESS DIAGNOSTIC: engineered conditions. This dataset manufactures\n"
        "amount-tie collisions to verify the LLM rung functions when its territory\n"
        "exists, and to demonstrate the fuzzy/LLM boundary at the 6-char token\n"
        "floor. Results are a capability check of rung 3. They are NOT ablation\n"
        "evidence and must never be merged into results/ablation.md."
    )

    settlements, lines, credits, ground_truth = build_dataset()

    OUT.mkdir(parents=True, exist_ok=True)
    _write_csv(OUT / "settlements.csv",  _SETTLEMENT_FIELDS, settlements)
    _write_csv(OUT / "recon_lines.csv",  _LINE_FIELDS,       lines)
    _write_csv(OUT / "bank_credits.csv", _CREDIT_FIELDS,     credits)
    (OUT / "ground_truth.json").write_text(
        json.dumps(ground_truth, indent=2), encoding="utf-8"
    )

    print(f"\nWrote {len(settlements)} settlements, {len(lines)} lines, "
          f"{len(credits)} credits → {OUT}/")

    sid_no_credit = [SID["S02"], SID["S04"]]
    print(f"Intentionally unsettled (no credit): {sid_no_credit}")


if __name__ == "__main__":
    main()
