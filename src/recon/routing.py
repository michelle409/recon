from __future__ import annotations

"""
Routing constants and conflict resolution for the deterministic matcher.

Rule: collect all AUTO_MATCH claims first, then downgrade conflicts — no
first-come-first-served.  Pool rule: AUTO_MATCH removes a settlement from the
available pool; PROPOSE does not.
"""

from dataclasses import dataclass, field

AUTO_MATCH = "AUTO_MATCH"
PROPOSE = "PROPOSE"
REFUSE = "REFUSE"
DUPLICATE = "DUPLICATE"
DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"


@dataclass
class MatchCandidate:
    credit_id: str
    route: str
    settlement_ids: list[str]
    stage: str
    detail: str
    verification: str = "UNVERIFIED"


def resolve_conflicts(candidates: list[MatchCandidate]) -> list[MatchCandidate]:
    """
    Within a batch of candidates, if two AUTO_MATCH entries claim the same
    settlement, downgrade both to PROPOSE.  Returns the same list, possibly
    with routes mutated.
    """
    claim_count: dict[str, int] = {}
    for c in candidates:
        if c.route == AUTO_MATCH:
            for sid in c.settlement_ids:
                claim_count[sid] = claim_count.get(sid, 0) + 1

    result: list[MatchCandidate] = []
    for c in candidates:
        if c.route == AUTO_MATCH and any(
            claim_count.get(sid, 0) > 1 for sid in c.settlement_ids
        ):
            result.append(MatchCandidate(
                credit_id=c.credit_id,
                route=PROPOSE,
                settlement_ids=c.settlement_ids,
                stage=c.stage,
                detail=c.detail + " [claim-conflict→PROPOSE]",
                verification=c.verification,
            ))
        else:
            result.append(c)

    return result
