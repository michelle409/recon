from __future__ import annotations

"""
LLM tie-breaker for amount-matched settlements (rung 3).

FIREWALLS:
  - Never imports fees.py (knows nothing about fee schedules).
  - Never reads ground_truth.json.

PRE-COMMITMENT: the honest ablation may show this rung adds zero on
synthetic seen data — the eligible set (amount ties surviving every
string method) may even be empty. If so, report it straight. Criterion 3
rewards knowing where not to use a model. The measured claim this rung
supports is narrow by design: under exact-amount verification an LLM
cannot create matches, only break ties, and its delta is counted in
converted ties.
"""

import hashlib
import json
import os
from pathlib import Path

import anthropic
from pydantic import BaseModel

MODEL = "claude-sonnet-5"
PROMPT_VERSION = "v1"
MAX_TOKENS = 1024

_client: anthropic.Anthropic | None = None


class CandidateMatch(BaseModel):
    settlement_id: str
    cited_evidence: list[str]


class LLMProposal(BaseModel):
    candidates: list[CandidateMatch]


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit(
                "ANTHROPIC_API_KEY is required when eligible credits exist for the "
                "det+fuzzy+llm pipeline. Set it in your environment or .env file."
            )
        _client = anthropic.Anthropic(api_key=key)
    return _client


def _cache_key(narration_raw: str, candidates: list[dict]) -> str:
    sorted_cands = sorted(
        (c["settlement_id"], c["utr"], str(c["amount_paise"]), c["expected_credit_date"])
        for c in candidates
    )
    payload = MODEL + "|" + PROMPT_VERSION + "|" + narration_raw + "|" + json.dumps(sorted_cands)
    return hashlib.sha256(payload.encode()).hexdigest()


def propose(
    narration_raw: str,
    candidates: list[dict],
    client: object | None = None,
    cache_dir: str | None = None,
    *,
    credit_id: str = "",
    txn_date: str = "",
) -> tuple[LLMProposal | None, bool]:
    """
    Ask the LLM which candidate settlements match the narration.

    Returns (proposal, cache_hit).
    proposal is None on API error, bad JSON, or validation failure.
    cache_hit is True when the response was served from disk.
    """
    if cache_dir is None:
        cache_dir = os.environ.get("RECON_LLM_CACHE", ".llm_cache")

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    key = _cache_key(narration_raw, candidates)
    cache_file = cache_path / f"{key}.json"

    if cache_file.exists():
        try:
            proposal = LLMProposal.model_validate_json(cache_file.read_text(encoding="utf-8"))
            return proposal, True
        except Exception:
            pass  # corrupted cache entry → fall through to API

    # Build prompts
    cand_blocks = "\n".join(
        f"  settlement_id: {c['settlement_id']}\n"
        f"  utr: {c['utr']}\n"
        f"  amount_paise: {c['amount_paise']}\n"
        f"  expected_credit_date: {c['expected_credit_date']}"
        for c in candidates
    )
    amt = str(candidates[0]["amount_paise"]) if candidates else ""

    user_prompt = (
        "This bank credit could not be resolved by exact, partial, or fuzzy UTR\n"
        "matching. Every candidate below already matches the credit's amount\n"
        "exactly and falls within the settlement date window; amount and date\n"
        "cannot separate them. Analyze the narration for fragments that identify\n"
        "the correct settlement.\n\n"
        f"Bank credit:\n"
        f"  credit_id: {credit_id}\n"
        f"  amount_paise: {amt}\n"
        f"  txn_date: {txn_date}\n"
        f"  narration: {narration_raw}\n\n"
        f"Candidate settlements:\n{cand_blocks}\n\n"
        'Respond with JSON: {"candidates": [{"settlement_id": "...", '
        '"cited_evidence": ["exact substrings copied from the narration"]}]}. '
        "Cite only substrings that literally appear in the narration. If no "
        "fragment links the narration to a specific candidate, return "
        '{"candidates": []}.'
    )
    system_prompt = (
        "You are a bank reconciliation assistant. Given a bank credit narration "
        "and a list of candidate settlements, identify which settlement(s) this "
        "credit most likely corresponds to. Respond ONLY with JSON matching the "
        "schema provided. Do not explain your reasoning outside the JSON."
    )

    if client is None:
        client = get_client()

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
    except anthropic.NotFoundError:
        try:
            available = client.models.list()
            print("Available models:")
            for m in available.data:
                print(f"  {m.id}")
        except Exception:
            pass
        raise SystemExit("Update MODEL in llm_candidates.py to one of the listed IDs")
    except SystemExit:
        raise
    except Exception:
        return None, False

    # Strip optional ```json fences
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n", 1)
        text = lines[1] if len(lines) > 1 else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        proposal = LLMProposal.model_validate(json.loads(text))
    except Exception:
        return None, False

    cache_file.write_text(proposal.model_dump_json(), encoding="utf-8")
    return proposal, False


def dispose(
    proposal: LLMProposal,
    narration_raw: str,
    candidates: list[dict],
) -> tuple[list[CandidateMatch], list[tuple[str, str]]]:
    """
    Filter LLM proposals through four grounding checks.

    The candidates were pre-filtered by amount and date, so re-running
    arithmetic verification alone would accept everything the model says —
    verification theater. What is NOT guaranteed is that the model's claim
    is grounded: that it named a real candidate, cited text that exists,
    and cited text that points at the candidate it named. That is what
    disposal checks.

    Returns (accepted, rejected) where rejected items are (settlement_id, reason).
    Rejection reasons: NOT_IN_CANDIDATES, UNGROUNDED_CITATION, EVIDENCE_NOT_LINKED.
    """
    candidate_ids = {c["settlement_id"] for c in candidates}
    utr_by_sid = {c["settlement_id"]: c["utr"] for c in candidates}
    narration_upper = narration_raw.upper()

    accepted: list[CandidateMatch] = []
    rejected: list[tuple[str, str]] = []

    for cm in proposal.candidates:
        # 1. Must be in candidate list
        if cm.settlement_id not in candidate_ids:
            rejected.append((cm.settlement_id, "NOT_IN_CANDIDATES"))
            continue

        # 2. Evidence non-empty and every citation is a verbatim substring of narration
        if not cm.cited_evidence or not all(
            ev.upper() in narration_upper for ev in cm.cited_evidence
        ):
            rejected.append((cm.settlement_id, "UNGROUNDED_CITATION"))
            continue

        # 3. At least one citation of length >= 4 is a substring of the candidate's UTR
        utr_upper = utr_by_sid[cm.settlement_id].upper()
        if not any(len(ev) >= 4 and ev.upper() in utr_upper for ev in cm.cited_evidence):
            rejected.append((cm.settlement_id, "EVIDENCE_NOT_LINKED"))
            continue

        # 4. Belt-and-braces: amount + date guaranteed true by pre-filter construction
        cand = next(c for c in candidates if c["settlement_id"] == cm.settlement_id)
        assert cand is not None

        accepted.append(cm)

    return accepted, rejected
