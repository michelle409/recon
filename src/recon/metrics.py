from __future__ import annotations

"""
Score matcher output against ground truth.

Call score() from the CLI or tests — never imported by matcher.py itself.
"""


def score(matches: dict, ground_truth: dict) -> dict:
    """
    Parameters
    ----------
    matches
        Output of run_matcher(): has 'credits' list with route/settlement_ids.
    ground_truth
        Parsed ground_truth.json: has credit_to_settlements, duplicate_credit_ids,
        settlement_to_entities.

    Returns
    -------
    dict with keys:
        match_rate               – correct AUTO_MATCH / total non-duplicate credits
        false_match_rate         – wrong AUTO_MATCH / total AUTO_MATCH
        exception_rate           – REFUSE or PROPOSE / total non-duplicate credits
        settlement_level_match   – correctly-matched settlements / total settlements
        line_weighted_match_rate – lines in correctly-matched settlements / total lines
        counts                   – raw counts dict
    """
    gt_c2s: dict[str, list[str]] = ground_truth["credit_to_settlements"]
    gt_dups: set[str] = set(ground_truth.get("duplicate_credit_ids", []))
    gt_s2e: dict[str, list[str]] = ground_truth.get("settlement_to_entities", {})

    credit_results: list[dict] = matches["credits"]

    non_dup = [r for r in credit_results if r["credit_id"] not in gt_dups]
    auto_matched = [r for r in non_dup if r["route"] == "AUTO_MATCH"]
    exceptions = [r for r in non_dup if r["route"] in ("REFUSE", "PROPOSE")]

    n_non_dup = len(non_dup)
    n_auto = len(auto_matched)

    correct_auto = sum(
        1
        for r in auto_matched
        if set(r["settlement_ids"]) == set(gt_c2s.get(r["credit_id"], []))
    )
    wrong_auto = n_auto - correct_auto

    match_rate = correct_auto / n_non_dup if n_non_dup else 0.0
    false_match_rate = wrong_auto / n_auto if n_auto else 0.0
    exception_rate = len(exceptions) / n_non_dup if n_non_dup else 0.0

    all_sids = set(gt_s2e.keys())
    n_settlements = len(all_sids)

    correctly_matched_sids: set[str] = set()
    for r in auto_matched:
        gt_sids = set(gt_c2s.get(r["credit_id"], []))
        if set(r["settlement_ids"]) == gt_sids:
            correctly_matched_sids.update(gt_sids)

    settlement_level_match = (
        len(correctly_matched_sids) / n_settlements if n_settlements else 0.0
    )

    total_lines = sum(len(v) for v in gt_s2e.values())
    matched_lines = sum(len(gt_s2e.get(sid, [])) for sid in correctly_matched_sids)
    line_weighted_match_rate = matched_lines / total_lines if total_lines else 0.0

    counts = {
        "total_credits": len(credit_results),
        "non_duplicate_credits": n_non_dup,
        "auto_match": n_auto,
        "correct_auto_match": correct_auto,
        "wrong_auto_match": wrong_auto,
        "exceptions": len(exceptions),
        "duplicate_credits": len(credit_results) - n_non_dup,
        "settlements_total": n_settlements,
        "settlements_correctly_matched": len(correctly_matched_sids),
    }

    return {
        "match_rate": match_rate,
        "false_match_rate": false_match_rate,
        "exception_rate": exception_rate,
        "settlement_level_match": settlement_level_match,
        "line_weighted_match_rate": line_weighted_match_rate,
        "counts": counts,
    }
