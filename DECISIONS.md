# Decisions

## 2026-08-30

## Track selection

Evaluated all five tracks. Rejected Tracks 2 and 3 because their
ground truth requires predicting human behaviour (will this
transaction prove fraudulent, will this customer pay on retry),
which cannot be synthesised without grading your own homework.
Track 4 differs in kind: reconciliation ground truth is a structural
fact you construct, not a human decision you invent. Track 1 was the
most crowded. Track 5 needed a pre-existing project.

## Leg 3 cut

This started as three-way reconciliation including the merchant's own
order ledger. Cut that leg. Real bank statements ground the bank leg.
Test mode fixtures ground the settlement leg. No merchant order data
exists, so that leg's difficulty would have been entirely invented
and its match rate indefensible. Two trust boundaries with evidence
beats three with fiction. The hours saved bought the held-out split,
the three-rung ablation, and the sensitivity sweep.

## Integer paise, no floats

All amounts are integer paise everywhere. No float ever touches
money. Rounding rule declared once in fees.py. This is non-negotiable
because floating point arithmetic produces rounding errors that break
the per-line sum verification, which is the core of the matching
engine.

## Verifier never reads the fee schedule

The fee schedule lives in the generator only. The verifier checks
that the books tie using the fee and tax fields on each recon line.
It never recomputes from a rate. This means it works against any
pricing, including Razorpay's real one.

## Evidence-based routing, not confidence

Routing is a pure function of verifiable facts: exactly one candidate
survives arithmetic verification means auto-match, multiple means
propose, zero means refuse. Self-reported confidence scores from
models are poorly calibrated and indefensible in a panel. This
tolerance tried to enter matching three times and was rejected three
times.

## 2026-09-4

## Fuzzy stage ordering

Fuzzy was originally specced to run after amount+date matching. Realized
that PROPOSE is terminal: a credit whose amount ties two settlements
exits at amount+date as PROPOSE, and fuzzy (which could read the narration
fragment and disambiguate to exactly one) never runs. Reordered by evidence
strength before writing code. The stage with more evidence must run first.
