from __future__ import annotations

from recon.routing import (
    AUTO_MATCH,
    PROPOSE,
    MatchCandidate,
    resolve_conflicts,
)


def test_single_candidate_auto_matches():
    c = MatchCandidate(
        credit_id="bc_001",
        route=AUTO_MATCH,
        settlement_ids=["setl_A"],
        stage="exact_utr",
        detail="",
    )
    result = resolve_conflicts([c])
    assert len(result) == 1
    assert result[0].route == AUTO_MATCH


def test_multiple_candidates_proposes():
    # Two credits both claim setl_A → both downgraded to PROPOSE
    c1 = MatchCandidate("bc_001", AUTO_MATCH, ["setl_A"], "exact_utr", "")
    c2 = MatchCandidate("bc_002", AUTO_MATCH, ["setl_A"], "exact_utr", "")
    result = resolve_conflicts([c1, c2])
    assert all(r.route == PROPOSE for r in result), [r.route for r in result]


def test_zero_candidates_refuses():
    # resolve_conflicts does not produce REFUSE — that is handled by _stage_refuse.
    # With zero candidates the list is simply empty.
    result = resolve_conflicts([])
    assert result == []
