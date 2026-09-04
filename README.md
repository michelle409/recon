# recon

Multi-source reconciliation of payment gateway settlements against
bank credits.

## The problem

Razorpay processes over fifteen billion dollars a month. Every
settlement lands in a merchant's bank account as one lump NEFT credit
covering hundreds of orders, net of MDR, 18% GST on that MDR, and
refunds deducted from the same batch.

The bank statement shows a single line. The merchant's system shows
hundreds of orders. Neither view explains the other, and until they
are matched the merchant cannot post revenue correctly or claim input
credit on the GST.

Most Indian SMBs do this by hand. It breaks down constantly: reference
IDs missing or truncated in bank narrations, refunds netting against a
batch they did not originate in, two customers paying identical amounts
on the same day, and adjustments appearing with no obvious counterpart.

## What this builds

A three-rung matching engine measured honestly against synthetic data
with known ground truth.

**Rung 1 (deterministic):** exact UTR, partial UTR, amount plus date
window, pair-sum detection for clubbed credits.

**Rung 2 (fuzzy):** rapidfuzz token matching on garbled narrations, for
fragments too damaged for substring matching.

**Rung 3 (LLM):** Claude via Anthropic API, confined to unstructured
narration text only. Proposes candidate settlements with cited
evidence. Every proposal is verified arithmetically before acceptance.
The model proposes, the deterministic layer disposes.

A wrong match is more expensive than no match. The system refuses when
uncertain and reports exactly what it could not resolve.

## Results

Seed 42, 20 settlements.

### Seen corruptions (C01-C06)

| metric | det | det+fuzzy | det+fuzzy+llm |
|---|---|---|---|
| match_rate | 0.50 | 0.50 | 0.50 |
| false_match_rate | 0.00 | 0.00 | 0.00 |
| exception_rate | 0.50 | 0.50 | 0.50 |

### Held-out corruptions (C01-C06 + H01-H04)

| metric | det | det+fuzzy | det+fuzzy+llm |
|---|---|---|---|
| match_rate | 0.45 | 0.45 | 0.45 |
| false_match_rate | 0.00 | 0.00 | 0.00 |
| exception_rate | 0.55 | 0.55 | 0.55 |

Zero false matches across all configurations. The system degrades by
refusing, not by lying.

Fuzzy and LLM rungs add nothing on this seed. The deterministic matcher
handles everything resolvable under exact amount verification. The
remaining exceptions are structurally unmatchable by any single-settlement
strategy: clubbed credits, absent UTRs with amount ties, and split
settlements. Under a rubric that rewards knowing where not to use a
model, this is reported straight.

## What a run produces

**journal_entries.csv:** four double-entry rows per matched settlement
(Dr Bank, Dr Payment Gateway Fees, Dr GST Input Credit, Cr Receivables).
Balances to the paise, with a rounding-difference account for C06 drift.

**exceptions.csv:** every unresolved credit with category, age, blocked
amount, and a suggested next action.

**ITC-claimable GST total:** the number a merchant needs to file input
credit. On the seen set: Rs 11,304.36.

## Evaluation methodology

Synthetic data with known ground truth. Clean records generated with
their true mapping, then deliberately degraded using a taxonomy of
ten realistic corruptions. The engine reconstructs the mapping without
access to it.

Corruption types are held out: the engine was developed against six
seen types and evaluated against four types it had never encountered.
The first held-out run numbers are the reported numbers. Fixes found
afterwards are documented with their improved numbers labelled
non-held-out.

## Data provenance

No real transaction data is used or committed. Bank narration formats
are calibrated against 363 anonymised rows from real HDFC bank
statements, held locally and excluded via .gitignore. Settlement
structure is validated against Razorpay test mode fixtures committed
in fixtures/testmode/. Every corruption type is classified OBSERVED,
DOCUMENTED, or CONJECTURED in PROVENANCE.md, with evidence cited.

## Residual weakness

These numbers measure the engine against a declared threat model. Bank
leg corruption frequencies are estimated from three months of real
statements, a real sample rather than a representative one. What
remains assumed is the batch size distribution and how corruptions
co-occur. No synthetic dataset yields a production point estimate.

## Where the AI is not

The fee schedule lives in the generator only. The verifier checks that
the books tie using the fee and tax fields on each recon line. It never
recomputes from a rate. It works against any pricing, including
Razorpay's real one.

Routing is a pure function of verifiable arithmetic: one survivor means
auto-match, multiple means propose, zero means refuse. No model
self-reported confidence score enters any routing decision.

The three-rung ablation measures where each layer adds value. On this
data, the answer is: the deterministic layer handles everything. That
finding is the evidence for AI judgment, not an argument against it.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then fill in your API keys in .env.

## Run

```bash
# generate data
PYTHONPATH=src python -m recon.generator --seed 42 --settlements 20 --corruption-set seen

# match
PYTHONPATH=src python -m recon.matcher --data data/generated --pipeline det+fuzzy --ground-truth data/generated/ground_truth.json
```
