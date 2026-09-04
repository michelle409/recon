from __future__ import annotations

import json
from pathlib import Path

import pytest

from recon.llm_candidates import (
    CandidateMatch,
    LLMProposal,
    dispose,
    propose,
)


# ── fake client helpers ───────────────────────────────────────────────────────

class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, response_text: str) -> None:
        self._text = response_text
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        return _FakeResponse(self._text)


class _FakeClient:
    def __init__(self, response_text: str) -> None:
        self.messages = _FakeMessages(response_text)


class _ErrorMessages:
    def __init__(self) -> None:
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        raise RuntimeError("api failure")


class _ErrorClient:
    def __init__(self) -> None:
        self.messages = _ErrorMessages()


def _json_response(candidates: list[dict]) -> str:
    return json.dumps({"candidates": candidates})


_SETTLEMENTS = [
    {
        "settlement_id": "setl_A",
        "utr": "AB12CD34EF56GH78",
        "amount_paise": "123456700",
        "expected_credit_date": "2026-01-14",
    },
    {
        "settlement_id": "setl_B",
        "utr": "ZZ99YY88XX77WW66",
        "amount_paise": "123456700",
        "expected_credit_date": "2026-01-14",
    },
]

_NARRATION = "PYMT/AB12C/RZP SETTLEMENT"


# ── tests ─────────────────────────────────────────────────────────────────────

def test_llm_no_confidence_in_schema():
    """LLMProposal and CandidateMatch must not expose confidence/score fields."""
    forbidden = {"confidence", "score", "probability", "likelihood"}
    for model_cls in (LLMProposal, CandidateMatch):
        fields = set(model_cls.model_fields.keys())
        overlap = forbidden & fields
        assert not overlap, f"{model_cls.__name__} has forbidden fields: {overlap}"


def test_llm_cache_hit(tmp_path: Path):
    """Second identical propose() call is served from cache; only 1 API call total."""
    client = _FakeClient(_json_response([
        {"settlement_id": "setl_A", "cited_evidence": ["AB12C"]},
    ]))
    cache_dir = str(tmp_path / "cache")

    propose(_NARRATION, _SETTLEMENTS, client=client, cache_dir=cache_dir)
    _, cache_hit = propose(_NARRATION, _SETTLEMENTS, client=client, cache_dir=cache_dir)

    assert cache_hit is True
    assert client.messages.call_count == 1


def test_llm_membership_rejected():
    """LLM naming a settlement not in candidates → NOT_IN_CANDIDATES."""
    proposal = LLMProposal(candidates=[
        CandidateMatch(settlement_id="setl_X", cited_evidence=["AB12C"]),
    ])
    accepted, rejected = dispose(proposal, _NARRATION, _SETTLEMENTS)
    assert accepted == []
    reasons = [r for _, r in rejected]
    assert "NOT_IN_CANDIDATES" in reasons


def test_llm_ungrounded_citation_rejected():
    """Cited text not present verbatim in narration → UNGROUNDED_CITATION."""
    proposal = LLMProposal(candidates=[
        CandidateMatch(settlement_id="setl_A", cited_evidence=["NOTINNARRATION"]),
    ])
    accepted, rejected = dispose(proposal, _NARRATION, _SETTLEMENTS)
    assert accepted == []
    reasons = [r for _, r in rejected]
    assert "UNGROUNDED_CITATION" in reasons


def test_llm_unlinked_evidence_rejected():
    """Citation in narration but not in candidate's UTR → EVIDENCE_NOT_LINKED."""
    proposal = LLMProposal(candidates=[
        CandidateMatch(settlement_id="setl_A", cited_evidence=["PYMT"]),
    ])
    # "PYMT" is in _NARRATION but not in setl_A's UTR "AB12CD34EF56GH78"
    accepted, rejected = dispose(proposal, _NARRATION, _SETTLEMENTS)
    assert accepted == []
    reasons = [r for _, r in rejected]
    assert "EVIDENCE_NOT_LINKED" in reasons


def test_llm_tiebreak_auto_matches(tmp_path: Path):
    """
    Two amount-tied settlements; narration has 'AB12C' which is in setl_A's UTR.
    LLM stage should convert the PROPOSE to AUTO_MATCH with stage='llm'.
    """
    import csv
    from recon.matcher import run_matcher

    created_at = "2026-01-12"
    txn_date = "2026-01-14"

    settlements = [
        {
            "settlement_id": "setl_A", "utr": "AB12CD34EF56GH78",
            "amount_paise": "123456700", "fees_paise": "0", "tax_paise": "0",
            "status": "processed", "created_at": created_at,
        },
        {
            "settlement_id": "setl_B", "utr": "ZZ99YY88XX77WW66",
            "amount_paise": "123456700", "fees_paise": "0", "tax_paise": "0",
            "status": "processed", "created_at": created_at,
        },
    ]
    lines = [
        {
            "entity_id": "pay_A", "settlement_id": "setl_A",
            "settlement_utr": "AB12CD34EF56GH78", "type": "payment",
            "debit_paise": "0", "credit_paise": "123456700",
            "amount_paise": "123456700", "fee_paise": "0", "tax_paise": "0",
            "method": "upi", "order_id": "ord_A",
            "created_at": created_at, "settled_at": created_at,
        },
        {
            "entity_id": "pay_B", "settlement_id": "setl_B",
            "settlement_utr": "ZZ99YY88XX77WW66", "type": "payment",
            "debit_paise": "0", "credit_paise": "123456700",
            "amount_paise": "123456700", "fee_paise": "0", "tax_paise": "0",
            "method": "upi", "order_id": "ord_B",
            "created_at": created_at, "settled_at": created_at,
        },
    ]
    credits = [
        {
            "credit_id": "bc_001", "value_date": txn_date, "txn_date": txn_date,
            "amount_paise": "123456700", "narration_raw": _NARRATION,
        },
    ]

    def _write(path: Path, rows: list[dict]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    s_path = tmp_path / "settlements.csv"
    l_path = tmp_path / "recon_lines.csv"
    c_path = tmp_path / "bank_credits.csv"
    _write(s_path, settlements)
    _write(l_path, lines)
    _write(c_path, credits)

    fake = _FakeClient(_json_response([
        {"settlement_id": "setl_A", "cited_evidence": ["AB12C"]},
    ]))

    result = run_matcher(
        s_path, l_path, c_path, tmp_path / "out",
        pipeline="det+fuzzy+llm",
        _llm_client=fake,
        _llm_cache_dir=str(tmp_path / "cache"),
    )

    credit_result = result["credits"][0]
    assert credit_result["route"] == "AUTO_MATCH", credit_result
    assert credit_result["stage"] == "llm", credit_result
    assert "setl_A" in credit_result["settlement_ids"]

    llm_run = result["run"]["llm"]
    assert llm_run["converted_to_auto"] == 1
    assert llm_run["eligible_credits"] == 1


def test_llm_multi_accept_upholds_propose(tmp_path: Path):
    """LLM returns grounded evidence for BOTH candidates → PROPOSE stands."""
    from recon.matcher import _stage_llm
    from recon.routing import PROPOSE, MatchCandidate

    r4 = [MatchCandidate(
        credit_id="bc_001", route=PROPOSE, settlement_ids=["setl_A", "setl_B"],
        stage="amount_date", detail="amount+date match to ['setl_A', 'setl_B']",
        verification="EXACT",
    )]
    pool = {"setl_A", "setl_B"}
    verification = {"setl_A": "EXACT", "setl_B": "EXACT"}
    credits_data = [{"credit_id": "bc_001", "narration_raw": _NARRATION, "txn_date": "2026-01-14"}]
    settlements_full = [
        {"settlement_id": "setl_A", "utr": "AB12CD34EF56GH78",
         "amount_paise": "123456700", "created_at": "2026-01-12"},
        {"settlement_id": "setl_B", "utr": "ZZ99YY88XX77WW66",
         "amount_paise": "123456700", "created_at": "2026-01-12"},
    ]

    # Both candidates have grounded evidence in the narration and their UTR
    fake = _FakeClient(_json_response([
        {"settlement_id": "setl_A", "cited_evidence": ["AB12C"]},
        {"settlement_id": "setl_B", "cited_evidence": ["ZZ99"]},
    ]))
    # Note: "ZZ99" is 4 chars and in "ZZ99YY88XX77WW66", "AB12C" is 5 chars in "AB12CD34EF56GH78"
    # But "ZZ99" is NOT in _NARRATION "PYMT/AB12C/RZP SETTLEMENT"
    # So setl_B will be UNGROUNDED_CITATION → only setl_A accepted
    # Let me use a different narration with both UTR fragments
    narration_both = "PYMT/AB12C/ZZ99/SETTLEMENT"
    credits_data = [{"credit_id": "bc_001", "narration_raw": narration_both, "txn_date": "2026-01-14"}]
    r4[0] = MatchCandidate(
        credit_id="bc_001", route=PROPOSE, settlement_ids=["setl_A", "setl_B"],
        stage="amount_date", detail="amount+date match to ['setl_A', 'setl_B']",
        verification="EXACT",
    )

    llm_stats: dict = {
        "eligible_credits": 0, "api_calls": 0, "cache_hits": 0,
        "errors": 0, "proposals_total": 0, "accepted": 0,
        "rejected": {}, "converted_to_auto": 0, "upheld_propose": 0,
    }
    result = _stage_llm(
        r4, settlements_full, credits_data, pool, verification, llm_stats,
        client=fake, cache_dir=str(tmp_path / "cache"),
    )

    assert result[0].route == PROPOSE
    assert result[0].stage == "amount_date"
    assert llm_stats["converted_to_auto"] == 0
    assert llm_stats["upheld_propose"] >= 1


def test_llm_error_upholds_propose(tmp_path: Path):
    """API error → PROPOSE unchanged (with error note); errors counter incremented."""
    from recon.matcher import _stage_llm
    from recon.routing import PROPOSE, MatchCandidate

    r4 = [MatchCandidate(
        credit_id="bc_001", route=PROPOSE, settlement_ids=["setl_A", "setl_B"],
        stage="amount_date", detail="amount+date match",
        verification="EXACT",
    )]
    pool = {"setl_A", "setl_B"}
    verification = {"setl_A": "EXACT", "setl_B": "EXACT"}
    credits_data = [{"credit_id": "bc_001", "narration_raw": _NARRATION, "txn_date": "2026-01-14"}]
    settlements_full = [
        {"settlement_id": "setl_A", "utr": "AB12CD34EF56GH78",
         "amount_paise": "123456700", "created_at": "2026-01-12"},
        {"settlement_id": "setl_B", "utr": "ZZ99YY88XX77WW66",
         "amount_paise": "123456700", "created_at": "2026-01-12"},
    ]
    err_client = _ErrorClient()

    llm_stats: dict = {
        "eligible_credits": 0, "api_calls": 0, "cache_hits": 0,
        "errors": 0, "proposals_total": 0, "accepted": 0,
        "rejected": {}, "converted_to_auto": 0, "upheld_propose": 0,
    }
    result = _stage_llm(
        r4, settlements_full, credits_data, pool, verification, llm_stats,
        client=err_client, cache_dir=str(tmp_path / "cache"),
    )

    assert result[0].route == PROPOSE
    assert "llm: api error" in result[0].detail
    assert llm_stats["errors"] == 1
    assert llm_stats["converted_to_auto"] == 0


def test_llm_conversion_conflict(tmp_path: Path):
    """Two credits both want setl_A → neither converts; both note conflict."""
    from recon.matcher import _stage_llm
    from recon.routing import PROPOSE, MatchCandidate

    r4 = [
        MatchCandidate(
            credit_id="bc_001", route=PROPOSE, settlement_ids=["setl_A"],
            stage="amount_date", detail="amount+date match",
            verification="EXACT",
        ),
        MatchCandidate(
            credit_id="bc_002", route=PROPOSE, settlement_ids=["setl_A"],
            stage="amount_date", detail="amount+date match",
            verification="EXACT",
        ),
    ]
    pool = {"setl_A"}
    verification = {"setl_A": "EXACT"}
    settlements_full = [
        {"settlement_id": "setl_A", "utr": "AB12CD34EF56GH78",
         "amount_paise": "123456700", "created_at": "2026-01-12"},
    ]
    credits_data = [
        {"credit_id": "bc_001", "narration_raw": _NARRATION, "txn_date": "2026-01-14"},
        {"credit_id": "bc_002", "narration_raw": _NARRATION, "txn_date": "2026-01-14"},
    ]

    call_count = [0]

    class _ConflictMessages:
        def create(self, **kwargs):
            call_count[0] += 1
            return _FakeResponse(_json_response([
                {"settlement_id": "setl_A", "cited_evidence": ["AB12C"]},
            ]))

    class _ConflictClient:
        messages = _ConflictMessages()

    llm_stats: dict = {
        "eligible_credits": 0, "api_calls": 0, "cache_hits": 0,
        "errors": 0, "proposals_total": 0, "accepted": 0,
        "rejected": {}, "converted_to_auto": 0, "upheld_propose": 0,
    }
    result = _stage_llm(
        r4, settlements_full, credits_data, pool, verification, llm_stats,
        client=_ConflictClient(), cache_dir=str(tmp_path / "cache"),
    )

    assert all(r.route == PROPOSE for r in result)
    assert all("conversion conflict on setl_A" in r.detail for r in result)
    assert llm_stats["converted_to_auto"] == 0


def test_llm_zero_eligible_makes_zero_calls(tmp_path: Path):
    """No amount_date PROPOSEs → LLM is never called."""
    from recon.matcher import _stage_llm
    from recon.routing import REFUSE, MatchCandidate

    class _BombMessages:
        def create(self, **kwargs):
            raise AssertionError("LLM must not be called when no eligible credits")

    class _BombClient:
        messages = _BombMessages()

    r4: list[MatchCandidate] = []  # no amount_date PROPOSEs
    llm_stats: dict = {
        "eligible_credits": 0, "api_calls": 0, "cache_hits": 0,
        "errors": 0, "proposals_total": 0, "accepted": 0,
        "rejected": {}, "converted_to_auto": 0, "upheld_propose": 0,
    }
    result = _stage_llm(
        r4, [], [], set(), {}, llm_stats,
        client=_BombClient(), cache_dir=str(tmp_path / "cache"),
    )

    assert result == []
    assert llm_stats["api_calls"] == 0
    assert llm_stats["eligible_credits"] == 0


def test_llm_stage_skipped_without_flag(tmp_path: Path):
    """det+fuzzy pipeline never produces stage='llm'."""
    import json
    from recon.generator import run_pipeline
    from recon.matcher import run_matcher

    gen = tmp_path / "gen"
    run_pipeline(42, 20, "seen", gen)

    result = run_matcher(
        gen / "settlements.csv",
        gen / "recon_lines.csv",
        gen / "bank_credits.csv",
        tmp_path / "out",
        pipeline="det+fuzzy",
    )

    llm_stages = [r for r in result["credits"] if r["stage"] == "llm"]
    assert llm_stages == [], f"det+fuzzy produced llm stage: {llm_stages}"
    assert result["run"]["llm"] is None
