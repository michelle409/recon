# recon, build spec

Multi-source reconciliation of payment gateway settlements against bank credits.

This is the working spec. It is not marketing. Where something is uncertain or
deliberately excluded, it says so.

---

## 1. Scope

**Two trust boundaries, three documents:**

- **Bank statement**, one NEFT credit line per settlement. Carries a UTR
  (often mangled), an amount, and a date.
- **Razorpay settlement entity and its recon report line items.** These share a
  trust boundary. A payments engineer counts boundaries, not files.

Present this as **multi-source reconciliation**, which is the brief's own first
example direction. Do not claim "three sources". The count invites the one
cross-examination you would lose.

### The merchant order ledger (leg 3) is cut

**Do the ten minute check before writing the rationale.** Ask whether
M2Studios has any client with gateway-side order exports, and whether the
family jewellery business has any. The leg stays cut either way, but the answer
changes which sentence is true, and the wrong sentence is discoverable by
exactly the people interviewing you.

**If no order data exists anywhere:**

> This started as three-way reconciliation including the merchant's own order
> ledger. I cut that leg. I have real bank statements to ground the bank leg
> and test mode fixtures to ground the settlement leg. I have no merchant order
> data at all, so that leg's difficulty would have been entirely invented and
> its match rate a number I could not defend. I would rather reconcile two
> trust boundaries with evidence than three with fiction.

**If order data does exist:**

> This started as three-way reconciliation including the merchant's own order
> ledger. I have real order exports from one merchant, but grounding that leg
> properly (ingestion, anonymisation, its own provenance table) does not fit
> the timeline, and I do not ship ungrounded legs. It is the named first
> extension.

The second is the stronger answer, because it proves the cut was a standard
rather than a shortage.

**Frame the cut as a purchase.** The ten to twelve fully loaded hours that leg
would have cost are the hours that bought the held-out split, the three rung
ablation, and the sensitivity sweep. Every one of those scores on the rubric.
The leg scores on none of it. Panel sentence: *I traded a leg for measurement.*

---

## 2. The governing principle

Every design decision below follows one rule:

> **No component may depend on a belief the author authored.**

Four applications, all load bearing:

1. The verifier never reads the fee schedule. It checks that the books tie
   using the fee and tax fields present on each recon line, so it works against
   any pricing including Razorpay's real one.
2. Routing is a function of verifiable arithmetic, never of a model's
   self-reported confidence.
3. Conjectured corruption types are quarantined from the headline metric.
4. Assumed parameters are swept, not asserted.

This principle is also the submission's thesis. The Track 2 and 3 rejection,
the leg 3 cut, and the conjecture quarantine are the same decision made three
times: no claim without evidence to ground it. Three consistent applications is
a principle. One is an excuse.

When a decision comes up mid build that this spec does not cover, apply this
rule and record the reasoning in `DECISIONS.md`.

---

## 3. Data model

Amounts are **integer paise** everywhere. No floats touch money. Declare the
rounding rule once, in `fees.py`, and never redeclare it.

### BankCredit
```
credit_id, value_date, txn_date, amount_paise, narration_raw, source_file
```

### Settlement
```
settlement_id, utr, amount_paise, fees_paise, tax_paise, status, created_at
```

### ReconLine
```
entity_id, settlement_id, settlement_utr, type, debit_paise, credit_paise,
amount_paise, fee_paise, tax_paise, method, order_id, order_receipt,
created_at, settled_at, dispute_id
```

`type` is one of payment, refund, adjustment. `method` is one of upi, card,
netbanking, and it drives the fee rule so it stays. Card network, issuer and
type are cut: columns, not evidence.

### Ground truth
```
credit_id to settlement_id      (one to one, except clubbed credits)
settlement_id to [entity_id]    (one to many)
```

Written by the generator, never read by the engine.

---

## 4. Fee arithmetic

**Generator side only** (`fees.py`):

- Per method fee rate, applied per line, in integer paise
- 18% GST on the fee, computed per line, in integer paise
- One declared rounding rule

**Verifier side:**

```
sum(payment credit - fee - tax) - sum(refund debit) == settlement.amount_paise
```

Reading `fee_paise` and `tax_paise` off each line. Never recomputing them from
a rate.

**Two tests:**

- `test_per_line_sums_tie_exactly`
- `test_batch_percentage_does_not_tie`, which asserts the naive approach fails.
  Keep it passing. It makes your reasoning inspectable in the test file.

**The framing line, used once in the video at the books-tie moment:**

> My verifier never assumes Razorpay's pricing. It checks that the books tie
> from the fields on each line. If a merchant were ever mischarged, this is the
> system that would notice.

Deliver that as a property of the design, not as a challenge to the room. It is
the strongest honest thing this project says about itself. Said with any edge,
it lands wrong.

---

## 5. Corruption taxonomy

Ten types. Six seen, four held out. The held-out four are structurally
different from the seen six, not more of the same. That is the point of the
split.

`class` is one of OBSERVED, DOCUMENTED, CONJECTURED, filled in once you have
the real statements. Fill honestly.

### Seen (develop against these)

| id | name | leg | description |
|---|---|---|---|
| C01 | utr_truncation | bank | UTR cut to n chars in narration |
| C02 | narration_format_variance | bank | Different bank formats for the same event |
| C03 | duplicate_export | bank | Overlapping statement slice exported twice |
| C04 | refund_cross_batch | settlement | Refund nets against a batch it did not originate in |
| C05 | value_date_skew | bank | Value date differs from txn date |
| C06 | per_line_rounding_drift | settlement | Paise rounding accumulates across lines |

### Held out (never seen during development)

| id | name | leg | description |
|---|---|---|---|
| H01 | clubbed_credit | bank | Two same day settlements land as one bank line |
| H02 | utr_absent | bank | Narration carries no UTR at all |
| H03 | orphan_adjustment | settlement | Adjustment line with no counterpart |
| H04 | split_settlement | settlement | One payment's value spread across two settlements |

**Discipline:** do not look at held-out performance until the engine is
finished. Looking and then tuning converts held-out into seen and destroys the
only clean signal you have. Write the harness so held-out runs require an
explicit flag.

**Cap the taxonomy at ten.** Depth of measurement over breadth of imagination.

---

## 6. Engine

Three rungs, each independently runnable via
`--pipeline det|det+fuzzy|det+fuzzy+llm`.

### Rung 1, deterministic (`matcher.py`)

- Exact UTR match
- Amount plus business day window match
- Per line sum verification against settlement amount
- Dedupe pass on `(date, amount, narration_hash)`, handles C03, table stakes
- Pair sum check against unmatched settlements in window, **detects** H01,
  does not resolve it

**No general subset-sum solver.** Capped at exact line sum verification plus
the pair check. This kills a two day algorithm rabbit hole that produces no
rubric evidence.

### Rung 2, fuzzy (`fuzzy.py`)

One function. `rapidfuzz` partial ratio, narration against candidate UTRs and
settlement IDs, one threshold. This is the rung a payments engineer reaches for
before an LLM, and its absence is what made a two rung ablation meaningless.

### Rung 3, LLM (`llm_candidates.py`)

Claude via Anthropic SDK, pydantic structured output.

**Scope: unstructured narration text only.** Output is candidate settlement IDs
plus the evidence tokens cited. **No confidence field in the schema.**

Every candidate goes through arithmetic verification before acceptance. The
model proposes, the deterministic layer disposes.

Cache responses on input hash. You will re-run the harness dozens of times.

**Pre-commitment, decided now so the number cannot rattle you later:** the
honest ablation may show the LLM adds close to zero on seen data, because your
narrations are calibrated to real formats and rapidfuzz will eat most of C01
and C02. If that happens, report it straight. Do not pad the LLM's role to feel
more like an AI submission. Criterion 3 explicitly rewards knowing where not to
use the model. A measured delta near zero, with the LLM retained only for the
narration classes where the fuzzy threshold fails, is a stronger answer than a
juiced delta.

### Routing (`routing.py`)

Pure function of verifiable facts:

- Exactly one candidate survives verification, **auto-match**
- Multiple survive, **propose** (exception listing the tied candidates)
- None survive, **refuse**

Every exception row carries `routing_reason`.

A wrong match costs more than no match. Refusal is correct behaviour, not
failure.

---

## 7. Business day settlement windows

`calendars.py`. Hardcoded `RBI_HOLIDAYS_2026` covering only your generated date
range, with a source comment. No library.

Expected credit date is T+2 business days. Match window in business days.

Tests: `test_friday_settlement_lands_tuesday`, one holiday spanning case.

---

## 8. Metrics

`METRICS.md` states these verbatim. `metrics.py::score(pred, truth)` computes
them, tested on tiny hand built fixtures.

**Unit of evaluation: the line level link** (recon line to bank credit
assignment).

- **Precision and recall** at line level
- **Settlement level match**: all lines correctly assigned, no partial credit.
  199 of 200 correct is 1 line level false match and 0 settlement level matches.
- **False match**: line assigned to the wrong credit
- **Exception rate**: refused lines over total
- **Throughput**: lines per second, wall clock, stated with hardware

Undefined metrics are unfalsifiable metrics. A panelist asking what counts as a
false match on a partial batch gets pointed at a file.

---

## 9. Evaluation

`results/ablation.md`: 3 pipelines by {seen, held-out} by {match rate, false
match rate, exception rate}.

**Report held-out twice**, with and without CONJECTURED corruption types. This
makes conjecture structurally unable to inflate the headline number.

**Report LLM proposal precision separately**: of proposals that passed
arithmetic verification, how many were true. Makes propose-and-dispose measured
rather than asserted.

**Two charts only.** Seen versus held-out, and the ablation.

---

## 10. Sensitivity sweep

Runs after step 8. Roughly 3 hours. **First thing cut if step 8 slips.**

Sweep the assumed generator parameters and report metrics as a function of
assumptions, not as a point estimate:

- Corruption injection density at 0.5x, 1x, 2x, 4x
- Refund rate
- Method mix

One chart. Run the full grid on `det+fuzzy` only. Run `det+fuzzy+llm` at the
extremes only, because LLM calls on freshly corrupted narrations cost time you
do not have.

**The hypothesis to test:** as corruption density rises, false match rate stays
flat while exception rate absorbs the degradation, because evidence-based
routing refuses more instead of guessing more.

If true, the line is: **it degrades by refusing, not by lying.** Use it once,
in the video, at the sweep chart.

If false, you have found a genuine engine defect, which is a BREAKAGE entry and
a fix. Also a win.

This converts the frequencies problem from a concession into a position. The
panel exchange inverts: *your match rate predicts nothing about production*
becomes *correct, no point estimate does, which is why I report the response
surface. Give me a merchant's parameters and I will read the number off the
curve.*

---

## 11. PARAMETERS.md

Roughly 1 to 2 hours of desk work in step 9. Zero engine changes.

```
parameter | default | source_class | source | sweep_range
```

`source_class` is one of OBSERVED, PUBLISHED, ASSUMED.

- **OBSERVED**: bank leg corruption rates counted from your real statements
- **PUBLISHED**: method mix and refund rate anchored to RBI payment system
  statistics, NPCI monthly UPI data, or published e-commerce refund ranges,
  each cited
- **ASSUMED**: batch size distribution, corruption co-occurrence

Cite what you anchor. Sweep what you assume.

**State the limit of the published anchors explicitly**, because a panelist
will otherwise state it for you: RBI and NPCI aggregates are economy wide, not
merchant specific. They ground the default as a reasonable central value. They
do not make it correct for any particular merchant. That is precisely why the
same parameters are swept.

**One dead end to skip:** scripting hundreds of test mode payments to
manufacture volume. You would choose the method mix and refund rate yourself,
so it validates format (already done via fixtures) and grounds nothing.

---

## 12. Loop closure

The run emits two artifacts, not a list.

**`journal_entries.csv`**, per matched settlement, four double entry rows: Dr
Bank, Dr Payment Gateway Fees, Dr GST Input Credit, Cr Receivables. Amounts
from verified per line sums.

**`exceptions.csv`**: `exception_id, category, age_days, blocked_amount_paise,
suggested_next_action`. Next action is a fixed mapping per category, for
example "pull recon report for UTR X from dashboard".

No workflow engine, no integrations.

README section "What a run produces", surfacing the **ITC claimable GST
total**. That number is why a merchant does this at all, and it converts
matcher into the brief's own words.

---

## 13. Test mode fixtures

Create a handful of test mode payments and a refund. Pull the settlement entity
and recon report. Commit redacted JSON and CSV to `fixtures/testmode/`.

`test_generator_schema_matches_testmode` asserts column names, dtypes and ID
formats match.

If test mode will not emit settlements, fall back to Razorpay's documented
sample and label the fixture DOCUMENTED rather than OBSERVED. The schema test
works either way.

Doubles as settlement leg provenance. Cheapest credibility available.

---

## 14. PROVENANCE.md

Columns:

```
corruption_id | name | leg | description | class | evidence | rate_real | rate_synth | split
```

**Labelling rule, stated at the top so the classification is itself
falsifiable:**

- **OBSERVED**: at least one instance in the real statements, with the
  anonymised line quoted and a count, for example "41 of 312 NEFT credit lines
  truncate the UTR to 16 chars; sample: NEFT CR-XXXX0000123-RAZORPAY SETTLEME"
- **DOCUMENTED**: derivable from Razorpay docs or a committed file in
  `fixtures/testmode/`, with the path or pointer
- **CONJECTURED**: neither. The evidence cell must state the operational
  mechanism that would produce it, not "seems plausible"

`rate_real` versus `rate_synth` for OBSERVED types only. Showing that injection
frequency was calibrated to observed frequency is the strongest cell in the
table.

`split` is seen or held-out, so the table documents evaluation discipline in
the same place.

**Framing paragraph, top of file:**

> Every corruption in the generator is classified below. OBSERVED types are
> imitations of artifacts found in three months of real, anonymised bank
> statements. DOCUMENTED types come from Razorpay's published schemas or from
> test mode fixtures committed in this repo. CONJECTURED types have no observed
> instance; each is included because a concrete mechanism would produce it, and
> each is quarantined from the headline results: held-out metrics are reported
> twice, with and without conjectured types, so no claim in this repo depends
> on my imagination being right. If a Razorpay engineer tells me a conjectured
> type never occurs in production, deleting it changes the second table and
> nothing else.

---

## 15. BREAKAGE protocol

Start today. Anonymising real statements and fighting the test mode API will
produce friction before the real build does, and that friction counts.

**Entry template, fixed at the top of `BREAKAGE.md`:**

```
symptom
what I believed (wrong)
what I tried (failed)
actual cause
fix commit hash
regression test name
what it changed upstream
```

**Hard rule: no entry closes without a named test**, for example
`test_regression_b03_refund_netting`. An entry without a test is a story. With
one it is a repo artifact, and a panelist can walk the triangle from story to
commit to test.

**Do not squash commits.** Commit broken states with honest messages. The messy
history is the exhibit.

**Pre-register the held-out protocol in `DECISIONS.md` before step 8**, roughly
30 minutes:

> The first held-out run numbers are the reported numbers. Fixes found
> afterwards are documented, and their improved numbers are labelled
> non-held-out, because touching the engine after looking converts held-out
> into seen.

Step 8 is designed to surprise you. That is its function. When it does, the
resulting entry is simultaneously your best breakage story and proof you did
not tune on the test set.

---

## 16. Build sequence

**Walking skeleton first.** Generator, deterministic engine, metrics, one end
to end run. Everything else is added to a working core, never blocking it.

| # | Work |
|---|---|
| 1 | Leg 3 check. Statements anonymised. Corruption guesses written before studying them. Test mode fixtures pulled. BREAKAGE.md live from here. |
| 2 | Data model, `fees.py`, generator emitting clean records plus ground truth |
| 3 | Corruption injection, seen types only. Held-out types written but flag gated. |
| 4 | Deterministic matcher, dedupe, pair sum clubbing detection, `calendars.py` |
| 5 | `metrics.py`, `METRICS.md`, first end to end run. **Walking skeleton complete.** |
| 6 | Fuzzy rung, `routing.py`, exceptions plus journal entries |
| 7 | LLM rung, caching, proposal precision |
| 8 | Pre-registration written. Held-out run (first look). Ablation, charts, `PROVENANCE.md`. |
| 9 | Sensitivity sweep, `PARAMETERS.md`, README, DECISIONS and BREAKAGE final pass, video, form |

If you fall behind, cut corruption types, then the sweep. Never the held-out
split, the ablation, or the tests. Those are the grade.

---

## 17. Video, 5 minutes

| time | content |
|---|---|
| 0:00 to 0:30 | The problem in a merchant's terms. One lump credit, hundreds of orders, GST that cannot be claimed until it is matched. |
| 0:30 to 1:30 | Live run on a batch. Watch the books tie. The fee-schedule-blind verifier line goes here. |
| 1:30 to 2:20 | Metrics. Seen versus held-out side by side. The three rung ablation, reported straight whatever it says. |
| 2:20 to 3:10 | **A live refusal.** Clubbed credit detected, system refuses, explains that resolving it would require information the bank line does not contain. |
| 3:10 to 4:00 | Provenance and the sweep. Formats real, frequencies partly observed and partly published, co-occurrence swept. "It degrades by refusing, not by lying" if the sweep supports it. |
| 4:00 to 5:00 | What broke. What is still weak. |

The refusal is the money shot, not green rows scrolling. Ending on unresolved
problems is stronger than ending on a summary.

Include one sentence in the provenance segment: *this was three-way until I
checked what I could ground.* Pre-empting the question is better than answering
it.

**One instance of each framing line. Do not perfume the README with taglines.**
The repo's plain voice is its credibility, and over-styling reads as marketing.

---

## 18. Residual weakness, state it, do not hide it

The weakness is smaller than the earlier draft conceded. Bank leg corruption
frequencies are observed and counted. Method mix and refund rate are anchored
to published aggregates. What genuinely remains assumed is batch size
distribution and how corruptions co-occur, and both are swept.

README paragraph:

> These numbers measure the engine against a declared threat model. Bank leg
> corruption frequencies are estimated from three months of real statements, a
> real sample rather than a representative one. Method mix and refund rate
> default to published RBI and NPCI aggregates, cited in PARAMETERS.md, which
> are economy wide rather than merchant specific and are swept for that reason.
> What remains assumed is the batch size distribution and how corruptions
> co-occur, also swept. No synthetic dataset yields a production point
> estimate. The sweep is the prediction instrument: a merchant's parameters in,
> a number off the curve out.

Under a rubric where three of four criteria reward honesty about limits, that
paragraph is the closing argument.

---

## 19. Repo artifacts checklist

```
README.md              problem, what a run produces, results, residual weakness
SPEC.md                this file
DECISIONS.md           every non-obvious choice, reasoning, held-out pre-registration
BREAKAGE.md            maintained live, entry template at top. Read first by the panel.
PROVENANCE.md          corruption classification table
PARAMETERS.md          parameter defaults, source class, sweep ranges
METRICS.md             metric definitions, verbatim
src/recon/             fees, generator, corruptions, matcher, fuzzy,
                       llm_candidates, routing, calendars, metrics
fixtures/testmode/     redacted real Razorpay fixtures
tests/                 money path, gates, metric fixtures, regression tests
experiments/           ablation harness, sensitivity sweep
results/               ablation.md, sweep.md, three charts
```

**One command runs everything and regenerates every number in the README.**
That is what "does it run, would you trust it" means to an engineer.

---

## 20. Priority order

Nothing on this list touches the engine. The engine's spec is done.

1. **Walking skeleton on schedule.** Everything else is worthless attached to
   an unfinished repo.
2. **Breakage protocol from today.** It is free.
3. **Held-out pre-registration**, 30 minutes.
4. **Leg 3 truth check**, 10 minutes.
5. **The sweep**, only if step 8 lands on time.
6. **Framing lines**, in step 9.

Go build it.
