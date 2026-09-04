from __future__ import annotations

"""
LLM rung smoke test: hardcoded 2-settlement scenario.

Fragment "AB12C" is 5 chars — below fuzzy's >=6 token floor, so it is
genuinely LLM territory and cannot be resolved by any cheaper stage.

Exit 0 on clean run; nonzero on API failure.
"""

import sys
from pathlib import Path

# Allow running from project root without install
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from recon.llm_candidates import dispose, get_client, propose

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
_CREDIT_ID = "bc_smoke_001"
_TXN_DATE = "2026-01-14"


def main() -> int:
    print("=== LLM rung smoke test ===")
    print(f"Narration : {_NARRATION}")
    print(f"Fragment  : 'AB12C' (5 chars — below fuzzy >=6 floor)")
    print(f"Expected  : LLM cites AB12C → resolves to setl_A")
    print()

    try:
        client = get_client()
    except SystemExit as e:
        print(f"ERROR: {e}")
        return 1

    proposal, cache_hit = propose(
        _NARRATION,
        _SETTLEMENTS,
        client=client,
        credit_id=_CREDIT_ID,
        txn_date=_TXN_DATE,
    )

    print(f"Cache hit : {cache_hit}")

    if proposal is None:
        print("ERROR: propose() returned None (API error or validation failure)")
        return 1

    print(f"Raw proposal: {proposal.model_dump_json(indent=2)}")
    print()

    accepted, rejected = dispose(proposal, _NARRATION, _SETTLEMENTS)

    if rejected:
        print("Rejected:")
        for sid, reason in rejected:
            print(f"  {sid}: {reason}")

    if accepted:
        print("Accepted:")
        for cm in accepted:
            print(f"  {cm.settlement_id}: evidence={cm.cited_evidence}")
        if len(accepted) == 1:
            print(f"\nFinal routing: AUTO_MATCH → {accepted[0].settlement_id}")
        else:
            print(f"\nFinal routing: PROPOSE (multiple accepted — human review needed)")
    else:
        print("Final routing: PROPOSE (no grounded single candidate)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
