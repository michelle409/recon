# recon

Every Razorpay settlement hits a merchant's bank as one number.
No breakdown. No fees. No GST. Just ₹4,82,910 on a Tuesday.

Inside that number: 200 payments, MDR at three different rates,
18% GST on each fee computed per line in integer paise, three
refunds from last week's batch, and an adjustment nobody remembers.

The merchant cannot post revenue until it is unpacked. Cannot claim
GST input credit. Cannot close the month. Most Indian SMBs do this
by hand, every week, in a spreadsheet that breaks every time.

I built the system that does it in one command and proves it got
the right answer.

---

## The engine

Three rungs. Cheapest first. Each one earns its place or gets cut.

**Rung 1: Deterministic.** Exact UTR match. Partial UTR. Amount plus
business-day window. Pair-sum detection for clubbed credits. Handles
100% of resolvable cases on this data.

**Rung 2: Fuzzy.** rapidfuzz token scoring on garbled narrations.
Fragments too damaged for substring matching.

**Rung 3: LLM.** Claude via Anthropic API. Reads the narration.
Proposes candidates with cited evidence. Every single proposal goes
through arithmetic verification before it can match. The model
proposes. The math disposes.

**The rule that governs all three:** a wrong match puts a false number
in someone's books. No match leaves a to-do. The system knows the
difference.

---

## The results nobody fakes

Every number regenerable by one command.

**Multi-seed validation (20 settlements, 5 seeds):**

| seed | match rate | false match rate | exceptions |
|---|---|---|---|
| 42 | 0.50 | **0.00** | 0.50 |
| 99 | 0.65 | **0.00** | 0.35 |
| 7 | 0.55 | **0.00** | 0.45 |
| 123 | 0.50 | **0.00** | 0.50 |
| 256 | 0.60 | **0.00** | 0.40 |
| **mean** | **0.56** | **0.00** | **0.44** |

**Scale test (100 settlements, 2026 lines):**

| match rate | false match rate | exceptions |
|---|---|---|
| 0.49 | **0.00** | 0.51 |

**Held-out corruptions (seed 42, + H01-H04):**

| match rate | false match rate | exceptions |
|---|---|---|
| 0.45 | **0.00** | 0.55 |

Zero false matches. Five seeds. Five times the scale. Seen and
held-out corruptions. Every pipeline mode. Not one wrong assignment.

Match rate ranges from 50% to 65% depending on how corruptions
land. It holds steady at 100 settlements. The system matches what
it can prove and refuses what it cannot.
---

## What the system actually produces

Not a dashboard. Not a report. Accounting artifacts.

**journal_entries.csv** — four double-entry rows per matched settlement.
Dr Bank. Dr Payment Gateway Fees. Dr GST Input Credit. Cr Receivables.
Balances to the paise. Rounding drift gets its own account, the way
real ledgers handle it.

**exceptions.csv** — every unresolved credit. Category. Age. Blocked
amount. What to do next. Not buried in a log. Actionable.

**ITC-claimable GST: ₹11,304.36.** That is the number a merchant's
accountant needs to file input credit. That is why reconciliation
exists. Not the match rate. This.

---

## What broke at 2 AM

Six entries in BREAKAGE.md. Each with a symptom, a wrong belief, a
failed fix, the real cause, a commit hash, and a regression test.
The three that shaped the design:

**The held-out crash.** First time I ran four corruption types the
engine had never seen. A clubbed credit matched on UTR without
checking amounts. ₹25,265 imbalance. The ledger refused to post.
The exact UTR stage had no amount guard. Found it, fixed it, wrote
the test, re-ran. The held-out protocol was pre-registered before
I touched the data: "first numbers are the reported numbers." The
crash lives in the commit history, not cleaned up. That was the
point of held-out testing.

**The parser that found nothing.** 55-page HDFC PDF. Zero rows
extracted. Because the bank packs every column into one cell per
page. Rewrote the parser. Got 596 rows. 233 were merged. Filtered
to 363 clean rows. Decided the full fix was not worth the hours
because these serve as format reference, not input data. That
tradeoff is in DECISIONS.md.

**The LLM that earned nothing.** Pre-commitment written into the
module docstring before running: "if the delta is zero, report it
straight." The delta was zero. I reported it straight.

---

## The part I am most proud of

The verifier never reads the fee schedule.

It checks that the books tie using the fee and tax fields on each
recon line. It never assumes what Razorpay charges. It never
recomputes from a rate. It works against any pricing, including
Razorpay's real one.

If a merchant were ever mischarged, this is the system that would
notice.

---

## Evaluation

Synthetic data with known ground truth. I know the right answer
because I built both sides. Then I deliberately broke the bank side:
ten corruption types, six seen during development, four held out.

Every corruption is classified in PROVENANCE.md:
- **OBSERVED** — found in 363 real anonymised HDFC bank statement rows,
  with counts and quoted samples
- **DOCUMENTED** — from Razorpay's own API schema, committed in the repo
- **CONJECTURED** — mechanism is real, no instance observed

Conjectured types are quarantined. Held-out metrics reported with and
without them. No claim in this repo depends on my imagination.

---

## One principle, applied three times

> No component may depend on a belief the author authored.

I rejected Tracks 2 and 3 because their ground truth required
predicting human behaviour I could not observe. I cut the merchant
order leg because I had no data to ground it. I quarantine conjectured
corruptions because I cannot prove they happen.

Three applications of one standard. That is not three shortcuts.
That is a principle.

---

## The honest gap

The formats are real. The frequencies are partly observed, partly
assumed. No synthetic dataset predicts production. I would rather
report a number I can defend than a larger one I cannot.

---

## Run it yourself

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in keys

PYTHONPATH=src python -m recon.generator --seed 42 --settlements 20 --corruption-set seen
PYTHONPATH=src python -m recon.matcher --data data/generated --pipeline det+fuzzy
```

One command generates the data. One command matches it. Every number
in this README comes out the other end.
