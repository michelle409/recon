from __future__ import annotations

"""
Deterministic reconciliation matcher — rung 1.

Pipeline stages:
  0  load + verify internal arithmetic per settlement
  1  deduplication  (exact duplicate / suspected duplicate)
  2  exact UTR      (narration token ≥8 chars matches settlement UTR)
  3  partial UTR    (token is substring of settlement UTR)
  4  amount + date  (exact paise, ±2 business days)
  5  pair-sum       (two credits on same date sum to one settlement)
  6  refuse         (anything remaining)

NEVER imports recon.fees — knows nothing about fee schedules.
"""

import argparse
import csv
import json
import re
from pathlib import Path

from recon import calendars
from recon.routing import (
    AUTO_MATCH,
    DUPLICATE,
    DUPLICATE_SUSPECTED,
    PROPOSE,
    REFUSE,
    MatchCandidate,
    resolve_conflicts,
)


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _utr_tokens(narration: str) -> list[str]:
    """Extract uppercase alphanumeric tokens with length ≥ 8."""
    return [t for t in re.split(r"[^A-Z0-9]", narration.upper()) if len(t) >= 8]


# ── stage 0: load and verify ──────────────────────────────────────────────────

def _verify_settlements(
    settlements: list[dict], lines: list[dict]
) -> dict[str, str]:
    """Return settlement_id → "EXACT" | "DRIFT" | "UNVERIFIED"."""
    by_setl: dict[str, list[dict]] = {}
    for ln in lines:
        by_setl.setdefault(ln["settlement_id"], []).append(ln)

    result: dict[str, str] = {}
    for s in settlements:
        sid = s["settlement_id"]
        ls = by_setl.get(sid, [])
        if not ls:
            result[sid] = "UNVERIFIED"
            continue
        actual = (
            sum(int(ln["credit_paise"]) for ln in ls)
            - sum(int(ln["debit_paise"]) for ln in ls)
        )
        expected = int(s["amount_paise"])
        if actual == expected:
            result[sid] = "EXACT"
        elif 1 <= abs(actual - expected) <= 10:
            result[sid] = "DRIFT"
        else:
            result[sid] = "UNVERIFIED"
    return result


# ── stage 1: deduplication ────────────────────────────────────────────────────

def _dedupe(
    credits: list[dict],
) -> tuple[list[MatchCandidate], list[dict]]:
    """
    Exact duplicates (same txn_date + amount_paise + narration_raw) → DUPLICATE.
    Same (txn_date + amount_paise) but different narrations → DUPLICATE_SUSPECTED.
    The alphabetically-first credit_id in each group is kept as the survivor.
    """
    exact_groups: dict[tuple, list[dict]] = {}
    for c in credits:
        key = (c["txn_date"], c["amount_paise"], c["narration_raw"])
        exact_groups.setdefault(key, []).append(c)

    amount_date_groups: dict[tuple, list[dict]] = {}
    for c in credits:
        key = (c["txn_date"], c["amount_paise"])
        amount_date_groups.setdefault(key, []).append(c)

    dup_results: list[MatchCandidate] = []
    dup_ids: set[str] = set()

    for group in exact_groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda c: c["credit_id"])
        original = group[0]
        for dup in group[1:]:
            dup_ids.add(dup["credit_id"])
            dup_results.append(MatchCandidate(
                credit_id=dup["credit_id"],
                route=DUPLICATE,
                settlement_ids=[],
                stage="dedupe",
                detail=f"exact duplicate of {original['credit_id']}",
            ))

    for group in amount_date_groups.values():
        non_dup = [c for c in group if c["credit_id"] not in dup_ids]
        if len(non_dup) < 2:
            continue
        narrations = {c["narration_raw"] for c in non_dup}
        if len(narrations) <= 1:
            continue
        non_dup.sort(key=lambda c: c["credit_id"])
        original = non_dup[0]
        for suspected in non_dup[1:]:
            if suspected["credit_id"] not in dup_ids:
                dup_ids.add(suspected["credit_id"])
                dup_results.append(MatchCandidate(
                    credit_id=suspected["credit_id"],
                    route=DUPLICATE_SUSPECTED,
                    settlement_ids=[],
                    stage="dedupe",
                    detail=(
                        f"suspected duplicate of {original['credit_id']}"
                        " (same date+amount, different narration)"
                    ),
                ))

    survivors = [c for c in credits if c["credit_id"] not in dup_ids]
    return dup_results, survivors


# ── stage 2: exact UTR ────────────────────────────────────────────────────────

def _stage_exact_utr(
    credits: list[dict],
    settlements: list[dict],
    pool: set[str],
    verification: dict[str, str],
) -> tuple[list[MatchCandidate], list[dict]]:
    utr_to_sid = {
        s["utr"]: s["settlement_id"]
        for s in settlements
        if s["settlement_id"] in pool
    }

    candidates: list[MatchCandidate] = []
    unmatched: list[dict] = []

    for c in credits:
        matched_sid: str | None = None
        for token in _utr_tokens(c["narration_raw"]):
            sid = utr_to_sid.get(token)
            if sid and sid in pool:
                matched_sid = sid
                break
        if matched_sid:
            candidates.append(MatchCandidate(
                credit_id=c["credit_id"],
                route=AUTO_MATCH,
                settlement_ids=[matched_sid],
                stage="exact_utr",
                detail=f"narration token matches UTR of {matched_sid}",
                verification=verification.get(matched_sid, "UNVERIFIED"),
            ))
        else:
            unmatched.append(c)

    resolved = resolve_conflicts(candidates)
    for r in resolved:
        if r.route == AUTO_MATCH:
            pool.discard(r.settlement_ids[0])

    return resolved, unmatched


# ── stage 3: partial UTR ──────────────────────────────────────────────────────

def _stage_partial_utr(
    credits: list[dict],
    settlements: list[dict],
    pool: set[str],
    verification: dict[str, str],
) -> tuple[list[MatchCandidate], list[dict]]:
    pool_setls = [s for s in settlements if s["settlement_id"] in pool]

    results: list[MatchCandidate] = []
    unmatched: list[dict] = []

    for c in credits:
        tokens = _utr_tokens(c["narration_raw"])
        matched_sid: str | None = None
        for token in tokens:
            for s in pool_setls:
                if token in s["utr"]:
                    matched_sid = s["settlement_id"]
                    break
            if matched_sid:
                break
        if matched_sid:
            results.append(MatchCandidate(
                credit_id=c["credit_id"],
                route=PROPOSE,
                settlement_ids=[matched_sid],
                stage="partial_utr",
                detail=f"narration token is substring of UTR of {matched_sid}",
                verification=verification.get(matched_sid, "UNVERIFIED"),
            ))
        else:
            unmatched.append(c)

    return results, unmatched


# ── stage 4: amount + date window ────────────────────────────────────────────

def _stage_amount_date(
    credits: list[dict],
    settlements: list[dict],
    pool: set[str],
    verification: dict[str, str],
) -> tuple[list[MatchCandidate], list[dict]]:
    pool_by_amount: dict[int, list[dict]] = {}
    for s in settlements:
        if s["settlement_id"] not in pool:
            continue
        pool_by_amount.setdefault(int(s["amount_paise"]), []).append(s)

    results: list[MatchCandidate] = []
    unmatched: list[dict] = []

    for c in credits:
        credit_amt = int(c["amount_paise"])
        matched_sid: str | None = None

        for s in pool_by_amount.get(credit_amt, []):
            if s["settlement_id"] not in pool:
                continue
            expected = calendars.add_business_days(s["created_at"], 2)
            # Try txn_date; fall back to value_date
            dist = abs(calendars.business_days_between(c["txn_date"], expected))
            if dist > 2:
                dist = abs(calendars.business_days_between(c["value_date"], expected))
            if dist <= 2:
                matched_sid = s["settlement_id"]
                break

        if matched_sid:
            results.append(MatchCandidate(
                credit_id=c["credit_id"],
                route=PROPOSE,
                settlement_ids=[matched_sid],
                stage="amount_date",
                detail=f"amount+date match to {matched_sid}",
                verification=verification.get(matched_sid, "UNVERIFIED"),
            ))
        else:
            unmatched.append(c)

    return results, unmatched


# ── stage 5: pair-sum ─────────────────────────────────────────────────────────

def _stage_pair_sum(
    credits: list[dict],
    settlements: list[dict],
    pool: set[str],
    verification: dict[str, str],
) -> tuple[list[MatchCandidate], list[dict]]:
    """
    Detect clubbed credits: two credits on the same txn_date whose amounts
    sum exactly to an unmatched settlement.  Both are PROPOSE to that settlement.
    """
    by_date: dict[str, list[dict]] = {}
    for c in credits:
        by_date.setdefault(c["txn_date"], []).append(c)

    pool_setls = [s for s in settlements if s["settlement_id"] in pool]
    matched_cids: set[str] = set()
    results: list[MatchCandidate] = []

    for s in pool_setls:
        target = int(s["amount_paise"])
        sid = s["settlement_id"]
        found = False
        for day_credits in by_date.values():
            available = [c for c in day_credits if c["credit_id"] not in matched_cids]
            for i in range(len(available)):
                for j in range(i + 1, len(available)):
                    if (
                        int(available[i]["amount_paise"])
                        + int(available[j]["amount_paise"])
                        == target
                    ):
                        cid_a = available[i]["credit_id"]
                        cid_b = available[j]["credit_id"]
                        matched_cids.update([cid_a, cid_b])
                        for cid, other in [(cid_a, cid_b), (cid_b, cid_a)]:
                            results.append(MatchCandidate(
                                credit_id=cid,
                                route=PROPOSE,
                                settlement_ids=[sid],
                                stage="pair_sum",
                                detail=f"pair sum with {other} matches {sid}",
                                verification=verification.get(sid, "UNVERIFIED"),
                            ))
                        found = True
                        break
                if found:
                    break
            if found:
                break

    unmatched = [c for c in credits if c["credit_id"] not in matched_cids]
    return results, unmatched


# ── stage 6: refuse ───────────────────────────────────────────────────────────

def _stage_refuse(credits: list[dict]) -> list[MatchCandidate]:
    return [
        MatchCandidate(
            credit_id=c["credit_id"],
            route=REFUSE,
            settlement_ids=[],
            stage="refuse",
            detail="no matching settlement found",
        )
        for c in credits
    ]


# ── pipeline ──────────────────────────────────────────────────────────────────

def run_matcher(
    settlements_path: Path,
    lines_path: Path,
    credits_path: Path,
    out_path: Path,
) -> dict:
    settlements = _read_csv(settlements_path)
    lines = _read_csv(lines_path)
    credits = _read_csv(credits_path)

    verification = _verify_settlements(settlements, lines)
    pool: set[str] = {s["settlement_id"] for s in settlements}

    dup_results, survivors = _dedupe(credits)

    r2, survivors = _stage_exact_utr(survivors, settlements, pool, verification)
    r3, survivors = _stage_partial_utr(survivors, settlements, pool, verification)
    r4, survivors = _stage_amount_date(survivors, settlements, pool, verification)
    r5, survivors = _stage_pair_sum(survivors, settlements, pool, verification)
    refuse = _stage_refuse(survivors)

    all_results: list[MatchCandidate] = (
        dup_results + r2 + r3 + r4 + r5 + refuse
    )
    all_results.sort(key=lambda r: r.credit_id)

    summary = {
        "total_credits": len(credits),
        "auto_match": sum(1 for r in all_results if r.route == AUTO_MATCH),
        "propose": sum(1 for r in all_results if r.route == PROPOSE),
        "refuse": sum(1 for r in all_results if r.route == REFUSE),
        "duplicate": sum(1 for r in all_results if r.route == DUPLICATE),
        "duplicate_suspected": sum(
            1 for r in all_results if r.route == DUPLICATE_SUSPECTED
        ),
    }

    output = {
        "credits": [
            {
                "credit_id": r.credit_id,
                "route": r.route,
                "settlement_ids": r.settlement_ids,
                "stage": r.stage,
                "detail": r.detail,
                "verification": r.verification,
            }
            for r in all_results
        ],
        "summary": summary,
    }

    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "matches.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )

    _print_summary(summary)
    return output


def _print_summary(summary: dict) -> None:
    print("\n=== Matcher summary ===")
    print(f"Total credits  : {summary['total_credits']}")
    print(f"AUTO_MATCH     : {summary['auto_match']}")
    print(f"PROPOSE        : {summary['propose']}")
    print(f"REFUSE         : {summary['refuse']}")
    print(f"DUPLICATE      : {summary['duplicate']}")
    print(f"DUPLICATE_SUSP : {summary['duplicate_suspected']}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic reconciliation matcher"
    )
    parser.add_argument(
        "--settlements", type=Path, default=Path("data/generated/settlements.csv")
    )
    parser.add_argument(
        "--lines", type=Path, default=Path("data/generated/recon_lines.csv")
    )
    parser.add_argument(
        "--credits", type=Path, default=Path("data/generated/bank_credits.csv")
    )
    parser.add_argument("--out", type=Path, default=Path("data/generated"))
    parser.add_argument("--ground-truth", type=Path, default=None)
    args = parser.parse_args()

    output = run_matcher(args.settlements, args.lines, args.credits, args.out)

    if args.ground_truth and args.ground_truth.exists():
        from recon import metrics
        gt = json.loads(args.ground_truth.read_text(encoding="utf-8"))
        scores = metrics.score(output, gt)
        print("\n=== Metrics ===")
        for k, v in scores.items():
            if isinstance(v, float):
                print(f"{k:35s}: {v:.4f}")
            elif isinstance(v, dict):
                print(f"{k}:")
                for kk, vv in v.items():
                    print(f"  {kk:33s}: {vv}")
            else:
                print(f"{k:35s}: {v}")


if __name__ == "__main__":
    main()
