# recon

Multi-source reconciliation of payment gateway settlements against
bank credits.

## The problem

A Razorpay settlement lands in a merchant's bank account as one lump
NEFT credit covering hundreds of orders, net of MDR, 18% GST on that
MDR, and refunds deducted from the same batch.

The bank statement shows a single line. The merchant's system shows
hundreds of orders. Neither view explains the other, and until they
are matched the merchant cannot post revenue correctly or claim input
credit on the GST.

Most Indian SMBs do this by hand. It breaks down constantly:

- reference IDs missing or truncated in bank narrations
- one payment split across two settlements
- refunds netting against a batch they did not originate in
- two customers paying identical amounts on the same day
- adjustments and disputes appearing with no obvious counterpart

## What this builds

A matching engine for that loop, measured honestly. Match rate, false
match rate, throughput, and a full list of the exceptions it could not
resolve.

A wrong match is more expensive than no match. A system that
confidently matches everything is worse than one that matches most
things and tells you exactly what it could not.

## Evaluation

Synthetic data with known ground truth. Clean records are generated
with their true mapping, then deliberately degraded using a taxonomy
of realistic corruptions. The engine reconstructs the mapping without
access to it.

Corruption types are held out: the engine is developed against one
subset and evaluated against patterns it has never seen.

## Data provenance

No real transaction data is used or committed. Bank narration formats
are calibrated against real statements from two businesses, held
locally and excluded via .gitignore. Settlement structure is validated
against Razorpay test mode fixtures committed in fixtures/testmode/.
Only the shape of the data informs the generator, never its contents.

## Residual weakness

These numbers measure the engine against a declared threat model. Bank
leg corruption frequencies are estimated from three months of real
statements, a real sample rather than a representative one. Method mix
and refund rate default to published RBI and NPCI aggregates, cited in
PARAMETERS.md, which are economy wide rather than merchant specific
and are swept for that reason. What remains assumed is the batch size
distribution and how corruptions co-occur, also swept. No synthetic
dataset yields a production point estimate. The sweep is the
prediction instrument: a merchant's parameters in, a number off the
curve out.

## Status

Early. Scaffold only.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then fill in your API keys in .env.
