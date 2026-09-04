from __future__ import annotations

from recon.fuzzy import fuzzy_candidates

_SETTLEMENTS = [
    {"settlement_id": "setl_A", "utr": "ABCD1234EFGH5678"},
    {"settlement_id": "setl_B", "utr": "ZZZZ9999YYYY8888"},
]


def test_fuzzy_finds_truncated_utr():
    # "ABCD1234EF" is a 10-char prefix of "ABCD1234EFGH5678"
    # partial_ratio("ABCD1234EF", "ABCD1234EFGH5678") == 100
    narration = "NEFT CR-RATN0000088-RAZORPAY-ABCD1234EF"
    results = fuzzy_candidates(narration, _SETTLEMENTS, set())
    sids = [r[0] for r in results]
    assert "setl_A" in sids, f"setl_A not found in {results}"
    score = next(r[1] for r in results if r[0] == "setl_A")
    assert score >= 70, f"score {score} below threshold"


def test_fuzzy_excludes_already_matched():
    narration = "NEFT CR-RATN0000088-RAZORPAY-ABCD1234EF"
    results = fuzzy_candidates(narration, _SETTLEMENTS, {"setl_A"})
    sids = [r[0] for r in results]
    assert "setl_A" not in sids, f"setl_A should be excluded: {results}"


def test_fuzzy_threshold_respected():
    # Narration with no tokens resembling either UTR
    narration = "NEFT CREDIT BY TRANSFER ONLY"
    results = fuzzy_candidates(narration, _SETTLEMENTS, set(), threshold=70)
    assert results == [], f"Expected empty, got {results}"
