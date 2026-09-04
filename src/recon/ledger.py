from __future__ import annotations

"""
Loop-closure outputs: journal entries and exception queue.

Pure functions only — no I/O.  Never imports fees.py, never reads
ground_truth.json.  All arithmetic is integer paise.
"""

import datetime


# ── journal ───────────────────────────────────────────────────────────────────

def build_journal(
    matches: dict,
    settlements: list[dict],
    recon_lines: list[dict],
    credits: list[dict],
) -> list[dict]:
    """
    Build one journal block per AUTO_MATCH credit.

    Entry types per settlement:
      dr_bank          credit.amount_paise
      dr_fees          sum(fee_paise)
      dr_gst_itc       sum(tax_paise)
      cr_receivables   net settlement amount

    A balancing rounding row is appended when |diff| in [1, 10].
    Raises if |diff| > 10 (generator bug).

    Returns list of row dicts matching journal_entries.csv column order.
    """
    setl_by_id: dict[str, dict] = {s["settlement_id"]: s for s in settlements}
    credit_by_id: dict[str, dict] = {c["credit_id"]: c for c in credits}

    lines_by_setl: dict[str, list[dict]] = {}
    for ln in recon_lines:
        lines_by_setl.setdefault(ln["settlement_id"], []).append(ln)

    rows: list[dict] = []

    for result in matches["credits"]:
        if result["route"] != "AUTO_MATCH":
            continue
        cid = result["credit_id"]
        sids = result["settlement_ids"]
        if not sids:
            continue
        sid = sids[0]

        credit = credit_by_id.get(cid)
        setl = setl_by_id.get(sid)
        if not credit or not setl:
            continue

        ls = lines_by_setl.get(sid, [])
        date = credit["txn_date"]
        utr = setl["utr"]

        dr_bank = int(credit["amount_paise"])
        dr_fees = sum(int(ln["fee_paise"]) for ln in ls)
        dr_gst = sum(int(ln["tax_paise"]) for ln in ls)

        # spec: sum(amount_paise over payment lines) - sum(debit_paise over
        # refund lines) + sum(credit_paise over adj) - sum(debit_paise over adj)
        payment_gross = sum(
            int(ln["amount_paise"]) for ln in ls if ln["type"] == "payment"
        )
        refund_debit = sum(
            int(ln["debit_paise"]) for ln in ls if ln["type"] == "refund"
        )
        adj_credit = sum(
            int(ln["credit_paise"]) for ln in ls if ln["type"] == "adjustment"
        )
        adj_debit = sum(
            int(ln["debit_paise"]) for ln in ls if ln["type"] == "adjustment"
        )
        cr_recv = payment_gross - refund_debit + adj_credit - adj_debit

        def _row(entry_type: str, amount: int, desc: str) -> dict:
            return {
                "settlement_id": sid,
                "credit_id": cid,
                "date": date,
                "entry_type": entry_type,
                "amount_paise": amount,
                "description": desc,
            }

        block: list[dict] = [
            _row("dr_bank", dr_bank, f"Bank credit {cid} UTR {utr}"),
            _row("dr_fees", dr_fees, f"Gateway fees for {sid}"),
            _row("dr_gst_itc", dr_gst, f"GST ITC for {sid}"),
            _row("cr_receivables", cr_recv, f"Settlement {sid} receivables cleared"),
        ]

        total_dr = dr_bank + dr_fees + dr_gst
        diff = total_dr - cr_recv
        if diff != 0:
            if abs(diff) > 10:
                raise AssertionError(
                    f"Journal imbalance for {sid}/{cid}: diff={diff} paise "
                    f"(>10 — generator bug)"
                )
            if diff > 0:
                block.append(_row("cr_rounding_diff", diff, "per-line rounding drift"))
            else:
                block.append(_row("dr_rounding_diff", -diff, "per-line rounding drift"))

        # Assert balance
        total_dr_final = sum(
            r["amount_paise"] for r in block if r["entry_type"].startswith("dr_")
        )
        total_cr_final = sum(
            r["amount_paise"] for r in block if r["entry_type"].startswith("cr_")
        )
        assert total_dr_final == total_cr_final, (
            f"Journal block for {sid} does not balance: "
            f"dr={total_dr_final} cr={total_cr_final}"
        )

        rows.extend(block)

    return rows


# ── exceptions ────────────────────────────────────────────────────────────────

def build_exceptions(
    matches: dict,
    credits: list[dict],
    as_of: str,
) -> list[dict]:
    """
    One row per non-AUTO_MATCH credit, sorted by credit_id.
    exception_id = "exc_" + zero-padded sequence.
    age_days = calendar days from credit.txn_date to as_of.
    """
    credit_by_id: dict[str, dict] = {c["credit_id"]: c for c in credits}
    as_of_date = datetime.date.fromisoformat(as_of)

    non_auto = [
        r for r in matches["credits"] if r["route"] != "AUTO_MATCH"
    ]
    non_auto.sort(key=lambda r: r["credit_id"])

    rows: list[dict] = []
    for seq, result in enumerate(non_auto, start=1):
        cid = result["credit_id"]
        route = result["route"]
        stage = result["stage"]
        detail = result["detail"]
        sids = result["settlement_ids"]

        credit = credit_by_id.get(cid, {})
        txn_date_str = credit.get("txn_date", as_of)
        txn_date = datetime.date.fromisoformat(txn_date_str)
        age_days = (as_of_date - txn_date).days
        blocked = int(credit.get("amount_paise", 0))

        category = _derive_category(route, stage, detail)
        action = _suggested_action(category, sids, detail)

        rows.append({
            "exception_id": f"exc_{seq:04d}",
            "credit_id": cid,
            "category": category,
            "age_days": age_days,
            "blocked_amount_paise": blocked,
            "routing_reason": detail,
            "suggested_next_action": action,
        })

    return rows


def _derive_category(route: str, stage: str, detail: str) -> str:
    if route == "DUPLICATE":
        return "DUPLICATE"
    if route == "DUPLICATE_SUSPECTED":
        return "DUPLICATE_SUSPECTED"
    if route == "PROPOSE" and stage == "pair_sum":
        return "CLUBBED_CREDIT_SUSPECTED"
    if route == "PROPOSE":
        return "PROPOSE"
    # REFUSE
    if "near_miss" in detail:
        return "AMOUNT_MISMATCH"
    return "REFUSE"


def _suggested_action(category: str, sids: list[str], detail: str) -> str:
    ids_str = ", ".join(sids) if sids else "unknown"
    if category == "DUPLICATE":
        return "export artifact; verify not a real transaction, then drop"
    if category == "DUPLICATE_SUSPECTED":
        return (
            "identical credit with no reference; confirm with bank whether "
            "artifact or second genuine credit"
        )
    if category == "PROPOSE":
        return f"manually review tied candidates: {ids_str}"
    if category == "CLUBBED_CREDIT_SUSPECTED":
        return f"confirm with bank whether settlements {ids_str} were clubbed into one credit"
    if category == "AMOUNT_MISMATCH":
        # Parse settlement_id and delta from detail if present
        parts = detail.split()
        sid = parts[0] if parts else "unknown"
        return (
            f"UTR matches {sid} but amount differs; pull its recon report "
            "and check for split settlement or hold"
        )
    return "pull recon report for this date range from dashboard"
