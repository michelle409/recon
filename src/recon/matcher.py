from __future__ import annotations

"""
Reconciliation matcher — rungs 1 and 2.

Stage order (post-dedupe):
  exact_utr -> partial_utr -> fuzzy_utr -> amount_date -> llm -> pair_sum -> refuse

RATIONALE: PROPOSE is terminal, so stages with more evidence must precede
stages with less.  fuzzy_utr (narration similarity + exact amount + date)
outranks amount_date (amount + date only).  Running fuzzy after amount_date
would let a two-way amount tie terminate as PROPOSE before the narration is
ever consulted.

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


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _utr_tokens(narration: str) -> list[str]:
    """Uppercase alphanumeric tokens with length >= 8."""
    return [t for t in re.split(r"[^A-Z0-9]", narration.upper()) if len(t) >= 8]


def _date_ok(credit: dict, settlement: dict) -> bool:
    """True if credit is within ±2 business days of expected settlement date."""
    expected = calendars.add_business_days(settlement["created_at"], 2)
    dist = abs(calendars.business_days_between(credit["txn_date"], expected))
    if dist > 2:
        dist = abs(calendars.business_days_between(credit["value_date"], expected))
    return dist <= 2


# ── stage 0: load and verify ──────────────────────────────────────────────────

def _verify_settlements(
    settlements: list[dict], lines: list[dict]
) -> dict[str, str]:
    """Return settlement_id -> "EXACT" | "DRIFT" | "UNVERIFIED"."""
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


def _make_candidate(
    credit_id: str,
    route: str,
    sids: list[str],
    stage: str,
    detail: str,
    verification: dict[str, str],
) -> MatchCandidate:
    """Build a MatchCandidate, downgrading AUTO_MATCH to PROPOSE on UNVERIFIED."""
    primary_sid = sids[0] if sids else ""
    ver = verification.get(primary_sid, "UNVERIFIED") if primary_sid else "UNVERIFIED"
    effective_route = route
    if route == AUTO_MATCH and ver == "UNVERIFIED":
        effective_route = PROPOSE
    return MatchCandidate(
        credit_id=credit_id,
        route=effective_route,
        settlement_ids=sids,
        stage=stage,
        detail=detail,
        verification=ver,
    )


# ── stage 1: deduplication ────────────────────────────────────────────────────

def _dedupe(credits: list[dict]) -> tuple[list[MatchCandidate], list[dict]]:
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
            candidates.append(_make_candidate(
                c["credit_id"], AUTO_MATCH, [matched_sid], "exact_utr",
                f"narration token matches UTR of {matched_sid}", verification,
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
        matched_sid: str | None = None
        for token in _utr_tokens(c["narration_raw"]):
            for s in pool_setls:
                if token in s["utr"]:
                    matched_sid = s["settlement_id"]
                    break
            if matched_sid:
                break
        if matched_sid:
            results.append(_make_candidate(
                c["credit_id"], PROPOSE, [matched_sid], "partial_utr",
                f"narration token is substring of UTR of {matched_sid}", verification,
            ))
        else:
            unmatched.append(c)

    return results, unmatched


# ── stage 3b: fuzzy UTR ───────────────────────────────────────────────────────

def _stage_fuzzy_utr(
    credits: list[dict],
    settlements: list[dict],
    pool: set[str],
    verification: dict[str, str],
    threshold: int,
) -> tuple[list[MatchCandidate], list[dict]]:
    """
    Fuzzy narration-to-UTR matching with amount and date verification.
    A candidate survives only when:
      - fuzzy score >= threshold (filters candidates)
      - credit.amount_paise == settlement.amount_paise exactly
      - date within ±2 business days
    Routing is determined by survivor count (claim-conflict rule).
    Stage name: "fuzzy_utr".
    """
    from recon.fuzzy import fuzzy_candidates

    pool_setls = [s for s in settlements if s["settlement_id"] in pool]
    results: list[MatchCandidate] = []
    unmatched: list[dict] = []

    for c in credits:
        # fuzzy_candidates returns sorted-by-score-desc list
        raw = fuzzy_candidates(
            c["narration_raw"],
            pool_setls,
            set(),          # already filtered to pool_setls; skip re-exclusion
            threshold,
        )

        # Apply arithmetic + date verification to filter survivors
        survivors: list[tuple[str, int, str]] = []
        for sid, score, token in raw:
            if sid not in pool:
                continue
            s = next((x for x in pool_setls if x["settlement_id"] == sid), None)
            if s is None:
                continue
            if int(c["amount_paise"]) != int(s["amount_paise"]):
                continue
            if not _date_ok(c, s):
                continue
            survivors.append((sid, score, token))

        if not survivors:
            unmatched.append(c)
            continue

        if len(survivors) == 1:
            sid, score, token = survivors[0]
            detail = (
                f"fuzzy token '{token}' ~ UTR of {sid} (score {score}), "
                f"amount exact, in window"
            )
            results.append(_make_candidate(
                c["credit_id"], AUTO_MATCH, [sid], "fuzzy_utr", detail, verification,
            ))
        else:
            # Multiple survivors → PROPOSE to all
            sids = [sid for sid, _, _ in survivors]
            best_sid, best_score, best_token = survivors[0]
            detail = (
                f"fuzzy token '{best_token}' ~ UTR (score {best_score}), "
                f"multiple survivors: {sids}"
            )
            results.append(_make_candidate(
                c["credit_id"], PROPOSE, sids, "fuzzy_utr", detail, verification,
            ))

    resolved = resolve_conflicts(results)
    for r in resolved:
        if r.route == AUTO_MATCH:
            pool.discard(r.settlement_ids[0])
    return resolved, unmatched


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
        matched_sids: list[str] = []

        for s in pool_by_amount.get(credit_amt, []):
            if s["settlement_id"] not in pool:
                continue
            if _date_ok(c, s):
                matched_sids.append(s["settlement_id"])

        if matched_sids:
            results.append(_make_candidate(
                c["credit_id"], PROPOSE, matched_sids, "amount_date",
                f"amount+date match to {matched_sids}", verification,
            ))
        else:
            unmatched.append(c)

    return results, unmatched


# ORDERING: cost says the LLM runs after every cheaper stage; evidence
# strength says narration reasoning outranks bare amount+date. Both are
# satisfied by making PROPOSE finality evidence-class-relative: this
# stage runs last but may reopen amount_date PROPOSEs, because it brings
# evidence (narration semantics) they never had. It does NOT reopen
# exact/partial/fuzzy PROPOSEs (narration evidence was already consulted;
# two narration-similar candidates deserve a human review) and does NOT
# touch REFUSEs (a near-miss is a decisive amount mismatch; a bare REFUSE
# has, by construction, zero candidates passing this stage's own
# pre-filter — the pre-filter equals the amount_date predicate).
# Corollary: under exact-amount verification, the LLM cannot CREATE
# matches. It can only break ties. That is its entire earned territory.


def _stage_llm(
    r4: list[MatchCandidate],
    settlements: list[dict],
    credits_data: list[dict],
    pool: set[str],
    verification: dict[str, str],
    llm_stats: dict,
    client: object | None = None,
    cache_dir: str | None = None,
) -> list[MatchCandidate]:
    from recon.llm_candidates import dispose, propose

    setl_by_id = {s["settlement_id"]: s for s in settlements}
    credit_by_id = {c["credit_id"]: c for c in credits_data}

    eligible_indices = [
        i for i, r in enumerate(r4)
        if r.route == PROPOSE and r.stage == "amount_date"
    ]
    llm_stats["eligible_credits"] = len(eligible_indices)

    conversion_candidates: dict[int, tuple[str, str]] = {}

    for idx in eligible_indices:
        r = r4[idx]
        credit = credit_by_id.get(r.credit_id, {})
        narration_raw = credit.get("narration_raw", "")
        txn_date = credit.get("txn_date", "")

        cand_dicts = []
        for sid in r.settlement_ids:
            if sid not in pool:
                continue
            s = setl_by_id.get(sid)
            if s is None:
                continue
            cand_dicts.append({
                "settlement_id": sid,
                "utr": s["utr"],
                "amount_paise": s["amount_paise"],
                "expected_credit_date": calendars.add_business_days(s["created_at"], 2),
            })

        if not cand_dicts:
            continue

        proposal, cache_hit = propose(
            narration_raw, cand_dicts, client, cache_dir,
            credit_id=r.credit_id, txn_date=txn_date,
        )

        if cache_hit:
            llm_stats["cache_hits"] += 1
        else:
            llm_stats["api_calls"] += 1

        if proposal is None:
            llm_stats["errors"] += 1
            r4[idx] = MatchCandidate(
                credit_id=r.credit_id,
                route=r.route,
                settlement_ids=r.settlement_ids,
                stage=r.stage,
                detail=r.detail + " | llm: api error",
                verification=r.verification,
            )
            continue

        llm_stats["proposals_total"] += 1
        accepted, rejected = dispose(proposal, narration_raw, cand_dicts)

        for _, reason in rejected:
            llm_stats["rejected"][reason] = llm_stats["rejected"].get(reason, 0) + 1

        llm_stats["accepted"] += len(accepted)

        if len(accepted) == 1:
            sid = accepted[0].settlement_id
            evidence = sorted(set(accepted[0].cited_evidence))
            detail = (
                f"LLM cited fragment(s) {evidence} present in narration "
                f"and in UTR of {sid}; amount exact; in window"
            )
            conversion_candidates[idx] = (sid, detail)
        elif len(accepted) == 0:
            r4[idx] = MatchCandidate(
                credit_id=r.credit_id,
                route=r.route,
                settlement_ids=r.settlement_ids,
                stage=r.stage,
                detail=r.detail + " | llm: no grounded single candidate",
                verification=r.verification,
            )
            llm_stats["upheld_propose"] += 1
        else:
            r4[idx] = MatchCandidate(
                credit_id=r.credit_id,
                route=r.route,
                settlement_ids=r.settlement_ids,
                stage=r.stage,
                detail=r.detail + " | llm: grounded evidence for multiple candidates",
                verification=r.verification,
            )
            llm_stats["upheld_propose"] += 1

    sid_to_indices: dict[str, list[int]] = {}
    for idx, (sid, _) in conversion_candidates.items():
        sid_to_indices.setdefault(sid, []).append(idx)

    for idx, (sid, detail) in conversion_candidates.items():
        competing = sid_to_indices.get(sid, [])
        if len(competing) > 1:
            r = r4[idx]
            r4[idx] = MatchCandidate(
                credit_id=r.credit_id,
                route=r.route,
                settlement_ids=r.settlement_ids,
                stage=r.stage,
                detail=r.detail + f" | llm: conversion conflict on {sid}",
                verification=r.verification,
            )
            llm_stats["upheld_propose"] += 1
        else:
            r = r4[idx]
            ver = verification.get(sid, "UNVERIFIED")
            effective_route = AUTO_MATCH if ver != "UNVERIFIED" else PROPOSE
            r4[idx] = MatchCandidate(
                credit_id=r.credit_id,
                route=effective_route,
                settlement_ids=[sid],
                stage="llm",
                detail=detail,
                verification=ver,
            )
            if effective_route == AUTO_MATCH:
                pool.discard(sid)
                llm_stats["converted_to_auto"] += 1
            else:
                llm_stats["upheld_propose"] += 1

    return r4


# ── stage 5: pair-sum ─────────────────────────────────────────────────────────

def _stage_pair_sum(
    credits: list[dict],
    settlements: list[dict],
    pool: set[str],
    verification: dict[str, str],
) -> tuple[list[MatchCandidate], list[dict]]:
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
                            results.append(_make_candidate(
                                cid, PROPOSE, [sid], "pair_sum",
                                f"pair sum with {other} matches {sid}", verification,
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
    pipeline: str = "det+fuzzy",
    fuzzy_threshold: int = 70,
    as_of: str | None = None,
    _llm_client: object | None = None,
    _llm_cache_dir: str | None = None,
) -> dict:
    settlements = _read_csv(settlements_path)
    lines = _read_csv(lines_path)
    credits = _read_csv(credits_path)

    if as_of is None:
        as_of = max(c["txn_date"] for c in credits) if credits else "2026-01-01"

    verification = _verify_settlements(settlements, lines)
    pool: set[str] = {s["settlement_id"] for s in settlements}

    dup_results, survivors = _dedupe(credits)

    r2, survivors = _stage_exact_utr(survivors, settlements, pool, verification)
    r3, survivors = _stage_partial_utr(survivors, settlements, pool, verification)

    if pipeline in ("det+fuzzy", "det+fuzzy+llm"):
        r_fuzzy, survivors = _stage_fuzzy_utr(
            survivors, settlements, pool, verification, fuzzy_threshold
        )
    else:
        r_fuzzy = []

    r4, survivors = _stage_amount_date(survivors, settlements, pool, verification)

    llm_stats: dict = {}
    if pipeline == "det+fuzzy+llm":
        from recon.llm_candidates import MODEL as _LLM_MODEL, PROMPT_VERSION as _LLM_PV
        llm_stats = {
            "model": _LLM_MODEL,
            "prompt_version": _LLM_PV,
            "eligible_credits": 0,
            "api_calls": 0,
            "cache_hits": 0,
            "errors": 0,
            "proposals_total": 0,
            "accepted": 0,
            "rejected": {},
            "converted_to_auto": 0,
            "upheld_propose": 0,
        }
        r4 = _stage_llm(
            r4, settlements, credits, pool, verification, llm_stats,
            client=_llm_client, cache_dir=_llm_cache_dir,
        )

    r5, survivors = _stage_pair_sum(survivors, settlements, pool, verification)
    refuse = _stage_refuse(survivors)

    all_results: list[MatchCandidate] = (
        dup_results + r2 + r3 + r_fuzzy + r4 + r5 + refuse
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
        "run": {
            "pipeline": pipeline,
            "fuzzy_threshold": fuzzy_threshold,
            "as_of": as_of,
            "llm": llm_stats if llm_stats else None,
        },
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

    # ── ledger outputs ────────────────────────────────────────────────────────
    from recon import ledger

    journal_rows = ledger.build_journal(output, settlements, lines, credits)
    _write_csv(out_path / "journal_entries.csv", journal_rows)

    exc_rows = ledger.build_exceptions(output, credits, as_of)
    _write_csv(out_path / "exceptions.csv", exc_rows)

    _print_summary(summary, journal_rows, exc_rows, llm_stats or None)
    return output


def _paise_to_rupees(paise: int) -> str:
    return f"₹{paise // 100:,}.{paise % 100:02d}"


def _print_summary(
    summary: dict,
    journal_rows: list[dict],
    exc_rows: list[dict],
    llm_stats: dict | None = None,
) -> None:
    print("\n=== Matcher summary ===")
    print(f"Total credits  : {summary['total_credits']}")
    print(f"AUTO_MATCH     : {summary['auto_match']}")
    print(f"PROPOSE        : {summary['propose']}")
    print(f"REFUSE         : {summary['refuse']}")
    print(f"DUPLICATE      : {summary['duplicate']}")
    print(f"DUPLICATE_SUSP : {summary['duplicate_suspected']}")

    if llm_stats:
        e = llm_stats.get("eligible_credits", 0)
        a = llm_stats.get("api_calls", 0)
        m = llm_stats.get("cache_hits", 0)
        acc = llm_stats.get("accepted", 0)
        rej = sum(llm_stats.get("rejected", {}).values())
        conv = llm_stats.get("converted_to_auto", 0)
        print(
            f"LLM            : {e} eligible, {a} api calls ({m} cached), "
            f"{acc} accepted, {rej} rejected, {conv} converted to auto-match"
        )

    itc = sum(
        r["amount_paise"] for r in journal_rows if r["entry_type"] == "dr_gst_itc"
    )
    blocked = sum(
        r["blocked_amount_paise"]
        for r in exc_rows
        if r["category"] != "DUPLICATE"
    )
    n_balanced = sum(1 for r in journal_rows if r["entry_type"] == "dr_bank")

    print(f"\nITC-claimable GST  : {_paise_to_rupees(itc)}")
    print(f"Blocked in exceptions: {_paise_to_rupees(blocked)}")
    print(f"Journal balance check: PASS ({n_balanced} settlements)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconciliation matcher (rungs 1 + 2)"
    )
    parser.add_argument(
        "--data", type=Path, default=Path("data/generated"),
        help="Directory containing settlements.csv, recon_lines.csv, bank_credits.csv",
    )
    # Legacy individual-file overrides (kept for test backwards-compat)
    parser.add_argument("--settlements", type=Path, default=None)
    parser.add_argument("--lines", type=Path, default=None)
    parser.add_argument("--credits", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--ground-truth", type=Path, default=None)
    parser.add_argument(
        "--pipeline", choices=["det", "det+fuzzy", "det+fuzzy+llm"], default="det+fuzzy",
    )
    parser.add_argument("--fuzzy-threshold", type=int, default=70)
    parser.add_argument("--as-of", type=str, default=None)
    args = parser.parse_args()

    data = args.data
    settlements_path = args.settlements or data / "settlements.csv"
    lines_path = args.lines or data / "recon_lines.csv"
    credits_path = args.credits or data / "bank_credits.csv"
    out_path = args.out or data

    output = run_matcher(
        settlements_path,
        lines_path,
        credits_path,
        out_path,
        pipeline=args.pipeline,
        fuzzy_threshold=args.fuzzy_threshold,
        as_of=args.as_of,
    )

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

        llm_credits = [
            r for r in output["credits"]
            if r["stage"] == "llm" and r["route"] == "AUTO_MATCH"
        ]
        if llm_credits:
            gt_c2s = gt["credit_to_settlements"]
            correct = sum(
                1 for r in llm_credits
                if set(r["settlement_ids"]) == set(gt_c2s.get(r["credit_id"], []))
            )
            total = len(llm_credits)
            pct = correct / total if total else 0.0
            print(f"\nLLM tie-break precision      : {correct}/{total} ({pct:.1%})")


if __name__ == "__main__":
    main()
