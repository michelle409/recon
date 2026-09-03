from __future__ import annotations

from recon import metrics


def test_metric_definitions():
    """Verify all metric definitions across all routing outcomes."""
    # Settlement line counts:
    #   setl_A → 2 lines (correctly AUTO_MATCHed)
    #   setl_B → 1 line  (wrong AUTO_MATCH → false match)
    #   setl_C → 3 lines (PROPOSE → exception)
    #   setl_D → 1 line  (REFUSE  → exception)
    # Total non-dup credits: 4   Total AUTO_MATCH: 2
    # bc_005 DUPLICATE, bc_006 DUPLICATE_SUSPECTED → not counted as non-dup
    gt = {
        "credit_to_settlements": {
            "bc_001": ["setl_A"],
            "bc_002": ["setl_B"],
            "bc_003": ["setl_C"],
            "bc_004": ["setl_D"],
        },
        "duplicate_credit_ids": ["bc_005", "bc_006"],
        "settlement_to_entities": {
            "setl_A": ["pay_A1", "pay_A2"],
            "setl_B": ["pay_B1"],
            "setl_C": ["pay_C1", "pay_C2", "pay_C3"],
            "setl_D": ["pay_D1"],
        },
        "expected_arithmetic_fail_settlements": [],
    }

    matches = {
        "credits": [
            {"credit_id": "bc_001", "route": "AUTO_MATCH",
             "settlement_ids": ["setl_A"], "stage": "exact_utr",
             "detail": "", "verification": "EXACT"},
            {"credit_id": "bc_002", "route": "AUTO_MATCH",
             "settlement_ids": ["setl_WRONG"], "stage": "amount_date",
             "detail": "", "verification": "UNVERIFIED"},
            {"credit_id": "bc_003", "route": "PROPOSE",
             "settlement_ids": ["setl_C"], "stage": "partial_utr",
             "detail": "", "verification": "EXACT"},
            {"credit_id": "bc_004", "route": "REFUSE",
             "settlement_ids": [], "stage": "refuse",
             "detail": "", "verification": "UNVERIFIED"},
            {"credit_id": "bc_005", "route": "DUPLICATE",
             "settlement_ids": [], "stage": "dedupe",
             "detail": "exact duplicate of bc_001", "verification": "UNVERIFIED"},
            {"credit_id": "bc_006", "route": "DUPLICATE_SUSPECTED",
             "settlement_ids": [], "stage": "dedupe",
             "detail": "suspected duplicate", "verification": "UNVERIFIED"},
        ],
        "summary": {},
    }

    s = metrics.score(matches, gt)

    # match_rate: 1 correct AUTO_MATCH out of 4 non-dup credits
    assert s["match_rate"] == 0.25, s["match_rate"]

    # false_match_rate: 1 wrong out of 2 AUTO_MATCH
    assert s["false_match_rate"] == 0.5, s["false_match_rate"]

    # exception_rate: 2 exceptions (bc_003 PROPOSE, bc_004 REFUSE) out of 4
    assert s["exception_rate"] == 0.5, s["exception_rate"]

    # settlement_level_match: only setl_A correctly matched → 1/4
    assert s["settlement_level_match"] == 0.25, s["settlement_level_match"]

    # line_weighted_match_rate: setl_A has 2 lines; total = 2+1+3+1 = 7
    expected_lw = 2 / 7
    assert abs(s["line_weighted_match_rate"] - expected_lw) < 1e-9, (
        s["line_weighted_match_rate"]
    )

    # Counts
    c = s["counts"]
    assert c["total_credits"] == 6
    assert c["non_duplicate_credits"] == 4
    assert c["auto_match"] == 2
    assert c["correct_auto_match"] == 1
    assert c["wrong_auto_match"] == 1
    assert c["exceptions"] == 2
    assert c["duplicate_credits"] == 2
    assert c["settlements_total"] == 4
    assert c["settlements_correctly_matched"] == 1
