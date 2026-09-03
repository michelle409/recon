from __future__ import annotations

"""
One function per corruption id. Each takes (world, rng) and mutates world
in-place, returning a list of corruption record dicts.

The floor-division fee variant used by C06 lives here, not in fees.py.
"""

import random
import string

from recon import calendars
from recon.models import BankCredit, ReconLine, World

# ── fee helpers (floor division, for C06 only) ───────────────────────────────

_FEE_BPS: dict[str, int] = {"upi": 30, "card": 200, "netbanking": 175}
_GST_BPS = 1800


def _floor_fee(amount_paise: int, method: str) -> int:
    return (amount_paise * _FEE_BPS[method]) // 10000


def _floor_gst(fee: int) -> int:
    return (fee * _GST_BPS) // 10000


# ── internal helpers ──────────────────────────────────────────────────────────

def _recompute(world: World, settlement_id: str) -> None:
    s = world.settlement_by_id(settlement_id)
    ls = world.lines_for(settlement_id)
    s.amount_paise = sum(l.credit_paise for l in ls) - sum(l.debit_paise for l in ls)
    s.fees_paise = sum(l.fee_paise for l in ls)
    s.tax_paise = sum(l.tax_paise for l in ls)


_UPPER = string.ascii_uppercase + string.digits
_ALNUM = string.ascii_letters + string.digits

_IFSC_LIST = ["RATN0000088", "YESB0000001", "ICIC0000104", "HDFC0000060"]
_BANK_LIST = ["RBL", "YES", "ICICI", "HDFC"]
_CPTY_LIST = [
    "RAZORPAY SOFTWARE PVT LTD",
    "RAZORPAYSOFTWARE",
    "RAZORPAY SOFTWARE PRIVATE LTD",
]
_NARRATION_WEIGHTS = [40, 25, 20, 15]


def _build_narration(utr: str, rng: random.Random) -> str:
    choice = rng.choices(range(4), weights=_NARRATION_WEIGHTS, k=1)[0]
    cpty = rng.choice(_CPTY_LIST)
    if choice == 0:
        ifsc = rng.choice(_IFSC_LIST)
        return f"NEFT CR-{ifsc}-{cpty}-{utr}"
    if choice == 1:
        bank = rng.choice(_BANK_LIST)
        return f"NEFTCR-{bank}-{cpty}-{utr}"
    if choice == 2:
        ifsc = rng.choice(_IFSC_LIST)
        return f"RTGSCR-{ifsc}-{cpty}-{utr}"
    return f"{cpty}-{utr}"


# ── corruption: C04 refund_cross_batch ───────────────────────────────────────

def apply_c04(world: World, rng: random.Random) -> list[dict]:
    records: list[dict] = []
    refund_lines = [l for l in world.lines if l.type == "refund"]
    if not refund_lines:
        return records

    n = min(rng.randint(1, 2), len(refund_lines))
    targets = rng.sample(refund_lines, n)

    for line in targets:
        src_id = line.settlement_id
        src = world.settlement_by_id(src_id)

        candidates = [
            s for s in world.settlements
            if s.settlement_id != src_id
            and calendars.business_days_distance(src.created_at, s.created_at) <= 3
        ]
        if not candidates:
            continue

        dst = rng.choice(candidates)
        line.settlement_id = dst.settlement_id
        line.settlement_utr = dst.utr

        _recompute(world, src_id)
        _recompute(world, dst.settlement_id)

        records.append({
            "id": "C04",
            "target": line.entity_id,
            "detail": f"moved {src_id} -> {dst.settlement_id}",
        })

    return records


# ── corruption: H03 orphan_adjustment (all only) ─────────────────────────────

def apply_h03(world: World, rng: random.Random) -> list[dict]:
    # Pick a settlement that currently has no adjustment lines
    adj_setl_ids = {l.settlement_id for l in world.lines if l.type == "adjustment"}
    eligible = [s for s in world.settlements if s.settlement_id not in adj_setl_ids]
    if not eligible:
        return []

    setl = rng.choice(eligible)
    adj_amt = rng.randint(500, 50000)
    is_credit = rng.random() < 0.5
    entity_id = "adj_" + "".join(rng.choices(_ALNUM, k=14))

    line = ReconLine(
        entity_id=entity_id,
        settlement_id=setl.settlement_id,
        settlement_utr=setl.utr,
        type="adjustment",
        debit_paise=0 if is_credit else adj_amt,
        credit_paise=adj_amt if is_credit else 0,
        amount_paise=adj_amt,
        fee_paise=0,
        tax_paise=0,
        method="na",
        order_id="",
        created_at=setl.created_at,
        settled_at=setl.created_at,
    )
    world.lines.append(line)
    _recompute(world, setl.settlement_id)

    return [{"id": "H03", "target": setl.settlement_id, "detail": f"orphan adj {entity_id} added"}]


# ── corruption: C06 per_line_rounding_drift ───────────────────────────────────

def apply_c06(world: World, rng: random.Random) -> list[dict]:
    """
    Apply floor-division fee recomputation to a small number of payment lines
    in 1-2 settlements. Only lines where floor differs from round-half-up are
    selected, guaranteeing drift >= 1 paise. At most 5 lines per settlement
    are touched, keeping total drift <= 10 paise (each line contributes 1-2).
    Settlement totals are NOT updated — the arithmetic gap is the corruption.
    """
    payment_setl_ids = list({
        l.settlement_id for l in world.lines if l.type == "payment"
    })
    if not payment_setl_ids:
        return []

    n_setl = min(rng.randint(1, 2), len(payment_setl_ids))
    target_sids = rng.sample(payment_setl_ids, n_setl)
    records: list[dict] = []

    for sid in target_sids:
        payment_lines = [
            l for l in world.lines
            if l.settlement_id == sid and l.type == "payment"
        ]
        # Lines where floor division gives a different fee than round-half-up
        driftable = [
            l for l in payment_lines
            if _floor_fee(l.amount_paise, l.method) != l.fee_paise
        ]
        if not driftable:
            continue  # no rounding gap possible for this settlement

        n_lines = min(rng.randint(1, 5), len(driftable))
        chosen = rng.sample(driftable, n_lines)

        for line in chosen:
            new_fee = _floor_fee(line.amount_paise, line.method)
            new_tax = _floor_gst(new_fee)
            line.fee_paise = new_fee
            line.tax_paise = new_tax
            line.credit_paise = line.amount_paise - new_fee - new_tax

        world.expected_arithmetic_fail_settlements.append(sid)
        records.append({
            "id": "C06",
            "target": sid,
            "detail": f"floor-division fee drift on {n_lines} line(s)",
        })

    return records


# ── corruption: H01 clubbed_credit (all only) ────────────────────────────────

def apply_h01(world: World, rng: random.Random) -> list[tuple[str, str]]:
    """
    Returns list of (credit_id_a, credit_id_b) pairs that were clubbed.
    The merged credit is already added to world.credits by this function.
    """
    # eligible credits are those that map to exactly one settlement (not already merged)
    eligible = [c for c in world.credits if len(world.credit_to_settlements.get(c.credit_id, [])) == 1]

    by_txn: dict[str, list[BankCredit]] = {}
    for c in eligible:
        by_txn.setdefault(c.txn_date, []).append(c)

    shared_dates = [d for d, cs in by_txn.items() if len(cs) >= 2]

    if shared_dates:
        date = rng.choice(shared_dates)
        pair = rng.sample(by_txn[date], 2)
        c1, c2 = pair
    else:
        # Force-align: pick two credits, set c2.txn_date = c1.txn_date
        c1, c2 = rng.sample(eligible, 2)
        # Adjust c2 and its settlement's created_at
        c2.txn_date = c1.txn_date
        c2.value_date = c1.txn_date
        sid2 = world.credit_to_settlements[c2.credit_id][0]
        world.settlement_by_id(sid2).created_at = world.settlement_by_id(
            world.credit_to_settlements[c1.credit_id][0]
        ).created_at

    sid1 = world.credit_to_settlements[c1.credit_id][0]
    sid2 = world.credit_to_settlements[c2.credit_id][0]

    merged_id = world.next_credit_id()
    merged = BankCredit(
        credit_id=merged_id,
        value_date=c1.txn_date,
        txn_date=c1.txn_date,
        amount_paise=c1.amount_paise + c2.amount_paise,
        narration_raw=c1.narration_raw,  # only first settlement's narration
    )

    world.credits.remove(c1)
    world.credits.remove(c2)
    world.credits.append(merged)

    utr1 = world.credit_utr.pop(c1.credit_id, "")
    world.credit_utr.pop(c2.credit_id, None)
    world.credit_utr[merged_id] = utr1

    del world.credit_to_settlements[c1.credit_id]
    del world.credit_to_settlements[c2.credit_id]
    world.credit_to_settlements[merged_id] = [sid1, sid2]

    world.corruption_records.append({
        "id": "H01",
        "target": merged_id,
        "detail": f"clubbed {c1.credit_id}({sid1}) + {c2.credit_id}({sid2})",
    })
    return [(c1.credit_id, c2.credit_id)]


# ── corruption: H04 split_settlement (all only) ──────────────────────────────

def apply_h04(world: World, rng: random.Random, h01_used_sids: set[str]) -> None:
    eligible = [
        c for c in world.credits
        if len(world.credit_to_settlements.get(c.credit_id, [])) == 1
        and world.credit_to_settlements[c.credit_id][0] not in h01_used_sids
    ]
    if not eligible:
        return

    c = rng.choice(eligible)
    sid = world.credit_to_settlements[c.credit_id][0]
    total = c.amount_paise

    # split point uniform in [30%, 70%]
    split_pct = rng.randint(300, 700)
    amt1 = total * split_pct // 1000
    amt2 = total - amt1

    utr = world.credit_utr.get(c.credit_id, "")

    id1 = world.next_credit_id()
    id2 = world.next_credit_id()

    credit1 = BankCredit(
        credit_id=id1,
        value_date=c.value_date,
        txn_date=c.txn_date,
        amount_paise=amt1,
        narration_raw=c.narration_raw,
    )
    credit2 = BankCredit(
        credit_id=id2,
        value_date=c.value_date,
        txn_date=c.txn_date,
        amount_paise=amt2,
        narration_raw=c.narration_raw,
    )

    world.credits.remove(c)
    world.credits.extend([credit1, credit2])

    world.credit_utr.pop(c.credit_id, None)
    world.credit_utr[id1] = utr
    world.credit_utr[id2] = utr

    del world.credit_to_settlements[c.credit_id]
    world.credit_to_settlements[id1] = [sid]
    world.credit_to_settlements[id2] = [sid]

    world.corruption_records.append({
        "id": "H04",
        "target": c.credit_id,
        "detail": f"split into {id1}({amt1}) + {id2}({amt2}) for {sid}",
    })


# ── corruption: C01 utr_truncation ───────────────────────────────────────────

def apply_c01(world: World, rng: random.Random, modified: set[str]) -> list[dict]:
    records: list[dict] = []
    for c in world.credits:
        if c.credit_id in modified:
            continue
        if rng.random() >= 0.30:
            continue
        utr = world.credit_utr.get(c.credit_id, "")
        if not utr:
            continue
        n = rng.randint(8, 14)
        truncated = utr[:n]
        c.narration_raw = c.narration_raw.replace(utr, truncated, 1)
        world.credit_utr[c.credit_id] = truncated
        modified.add(c.credit_id)
        records.append({
            "id": "C01",
            "target": c.credit_id,
            "detail": f"utr truncated to {n} chars",
        })
    return records


# ── corruption: C02 narration_format_variance ─────────────────────────────────

def apply_c02(world: World, rng: random.Random, modified: set[str]) -> list[dict]:
    records: list[dict] = []
    for c in world.credits:
        if c.credit_id in modified:
            continue
        if rng.random() >= 0.20:
            continue
        utr = world.credit_utr.get(c.credit_id, "")
        utr_frag = utr[:rng.randint(8, 12)] if utr else ""
        cpty = rng.choice(_CPTY_LIST)
        # Pick from alternative templates (not the original format categories)
        alt_choice = rng.randint(0, 1)
        if alt_choice == 0:
            new_narration = f"{utr_frag}-{cpty}" if utr_frag else f"TRANSFER-{cpty}"
        else:
            digits12 = "".join(rng.choices(string.digits, k=12))
            new_narration = f"IMPS-{digits12}-{cpty}"
        c.narration_raw = new_narration
        world.credit_utr[c.credit_id] = utr_frag
        modified.add(c.credit_id)
        records.append({
            "id": "C02",
            "target": c.credit_id,
            "detail": "narration format rewritten",
        })
    return records


# ── corruption: C05 value_date_skew ─────────────────────────────────────────

def apply_c05(world: World, rng: random.Random) -> list[dict]:
    import datetime
    records: list[dict] = []
    for c in world.credits:
        if rng.random() >= 0.15:
            continue
        skew = rng.randint(1, 2)
        d = datetime.date.fromisoformat(c.value_date) + datetime.timedelta(days=skew)
        c.value_date = d.isoformat()
        records.append({
            "id": "C05",
            "target": c.credit_id,
            "detail": f"value_date skewed +{skew} days",
        })
    return records


# ── corruption: H02 utr_absent (all only) ────────────────────────────────────

def apply_h02(world: World, rng: random.Random, modified: set[str]) -> list[dict]:
    eligible = [c for c in world.credits if c.credit_id not in modified]
    if not eligible:
        return []
    n = min(rng.randint(1, 2), len(eligible))
    targets = rng.sample(eligible, n)
    records: list[dict] = []
    replacements = ["NEFT CREDIT", "BY TRANSFER"]
    for c in targets:
        narr = rng.choice(replacements)
        c.narration_raw = narr
        world.credit_utr[c.credit_id] = ""
        modified.add(c.credit_id)
        records.append({
            "id": "H02",
            "target": c.credit_id,
            "detail": f"narration replaced with '{narr}'",
        })
    return records


# ── corruption: C03 duplicate_export ─────────────────────────────────────────

def apply_c03(world: World, rng: random.Random) -> list[dict]:
    n = rng.randint(2, 3)
    targets = rng.sample(world.credits, min(n, len(world.credits)))
    records: list[dict] = []
    for c in targets:
        dup_id = f"{c.credit_id}_d1"
        dup = BankCredit(
            credit_id=dup_id,
            value_date=c.value_date,
            txn_date=c.txn_date,
            amount_paise=c.amount_paise,
            narration_raw=c.narration_raw,
        )
        world.credits.append(dup)
        world.duplicate_credit_ids.append(dup_id)
        records.append({
            "id": "C03",
            "target": c.credit_id,
            "detail": f"duplicated as {dup_id}",
        })
    return records
