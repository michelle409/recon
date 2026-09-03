from __future__ import annotations

"""Pydantic models and mutable World container for the synthetic generator."""

from dataclasses import dataclass, field
from pydantic import BaseModel


class Settlement(BaseModel):
    settlement_id: str
    utr: str
    amount_paise: int
    fees_paise: int
    tax_paise: int
    status: str
    created_at: str


class ReconLine(BaseModel):
    entity_id: str
    settlement_id: str
    settlement_utr: str
    type: str            # "payment" | "refund" | "adjustment"
    debit_paise: int
    credit_paise: int
    amount_paise: int
    fee_paise: int
    tax_paise: int
    method: str          # "upi" | "card" | "netbanking" | "na"
    order_id: str
    created_at: str
    settled_at: str


class BankCredit(BaseModel):
    credit_id: str
    value_date: str
    txn_date: str
    amount_paise: int
    narration_raw: str


class GroundTruth(BaseModel):
    seed: int
    corruption_set: str
    credit_to_settlements: dict[str, list[str]]
    settlement_to_entities: dict[str, list[str]]
    duplicate_credit_ids: list[str]
    expected_arithmetic_fail_settlements: list[str]
    corruptions: list[dict]


@dataclass
class World:
    """Mutable working state threaded through the generator pipeline."""
    settlements: list[Settlement] = field(default_factory=list)
    lines: list[ReconLine] = field(default_factory=list)
    credits: list[BankCredit] = field(default_factory=list)
    # credit_id -> UTR string currently embedded in narration_raw
    credit_utr: dict[str, str] = field(default_factory=dict)
    # credit_id -> list of settlement_ids (1 normally, 2 after H01)
    credit_to_settlements: dict[str, list[str]] = field(default_factory=dict)
    duplicate_credit_ids: list[str] = field(default_factory=list)
    expected_arithmetic_fail_settlements: list[str] = field(default_factory=list)
    corruption_records: list[dict] = field(default_factory=list)
    _credit_seq: int = field(default=0, repr=False)

    def next_credit_id(self) -> str:
        self._credit_seq += 1
        return f"bc_{self._credit_seq:03d}"

    def settlement_by_id(self, sid: str) -> Settlement:
        return next(s for s in self.settlements if s.settlement_id == sid)

    def lines_for(self, settlement_id: str) -> list[ReconLine]:
        return [l for l in self.lines if l.settlement_id == settlement_id]

    def credit_by_id(self, cid: str) -> BankCredit:
        return next(c for c in self.credits if c.credit_id == cid)
