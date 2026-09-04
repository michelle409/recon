from __future__ import annotations

"""
Fuzzy UTR matching helpers.

The score FILTERS candidates; it never routes.  Routing is decided by
survivor count under arithmetic and date verification.  Scoring direction
is token-vs-UTR: partial_ratio(token, utr) scores an exact truncated
fragment 100; scoring the whole narration against the UTR would score a
10-char fragment ~62 and break the threshold semantics.
"""

import re

from rapidfuzz import fuzz


def _fuzzy_tokens(narration: str) -> list[str]:
    """Unique uppercase tokens with len >= 6 from narration."""
    seen: set[str] = set()
    result: list[str] = []
    for t in re.split(r"[^A-Z0-9]", narration.upper()):
        if len(t) >= 6 and t not in seen:
            seen.add(t)
            result.append(t)
    return result


def fuzzy_candidates(
    narration_raw: str,
    settlements_df: list[dict],
    matched_settlement_ids: set[str],
    threshold: int = 70,
) -> list[tuple[str, int, str]]:
    """
    Return [(settlement_id, score, best_token)] for every settlement whose
    best partial_ratio(token, utr) score meets the threshold, sorted by
    score desc then settlement_id asc for determinism.

    settlements_df is the list[dict] read from settlements.csv.
    matched_settlement_ids are excluded from consideration.
    """
    tokens = _fuzzy_tokens(narration_raw)
    results: list[tuple[str, int, str]] = []

    for s in settlements_df:
        sid = s["settlement_id"]
        if sid in matched_settlement_ids:
            continue
        utr = s["utr"]
        if not tokens:
            continue
        best_score = 0
        best_token = ""
        for token in tokens:
            sc = fuzz.partial_ratio(token, utr)
            if sc > best_score:
                best_score = sc
                best_token = token
        if best_score >= threshold:
            results.append((sid, int(best_score), best_token))

    results.sort(key=lambda x: (-x[1], x[0]))
    return results
