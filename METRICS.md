# Matcher Metrics

Scoring is done by `recon.metrics.score(matches, ground_truth)`.  The matcher
never reads `ground_truth.json`; scoring happens only in the CLI (`--ground-truth`)
or in test code.

---

## Definitions

### Populations

| Symbol | Meaning |
|--------|---------|
| C | All credits in `bank_credits.csv` |
| D | Credits listed in `ground_truth.duplicate_credit_ids` (C03 exact copies) |
| C\D | Non-duplicate credits — the scoreable population |
| A | Credits in C\D routed **AUTO_MATCH** |
| A✓ | Credits in A where the match is *correct* (set-equality rule below) |
| A✗ | Credits in A where the match is *wrong* (= A − A✓) |
| E | Credits in C\D routed **PROPOSE** or **REFUSE** |

### Set-equality rule

A match is *correct* if:

```
set(result.settlement_ids) == set(ground_truth.credit_to_settlements[credit_id])
```

Order is irrelevant; size must match exactly.  A single AUTO_MATCH to `[setl_A]`
when ground truth is `[setl_A, setl_B]` is *wrong* (e.g. H01 clubbed credit).

### Duplicate credits

Credits in D are excluded from all five rate metrics.  They should be routed
`DUPLICATE` (exact same narration) or `DUPLICATE_SUSPECTED` (same date+amount,
different narration).  Routing them to a settlement does not affect any metric.

---

## Metrics

### match_rate

```
|A✓| / |C\D|
```

Fraction of scoreable credits the matcher correctly AUTO_MATCHed.  The ideal
value is 1.0 for a perfect clean dataset.

### false_match_rate

```
|A✗| / |A|   (0.0 if |A| = 0)
```

Fraction of AUTO_MATCH decisions that were wrong.  REFUSE and PROPOSE are *not*
false matches — they are exceptions (see exception_rate).

### exception_rate

```
|E| / |C\D|
```

Fraction of scoreable credits the matcher could not AUTO_MATCH.  Includes both
PROPOSE (partial evidence) and REFUSE (no evidence).

### settlement_level_match

```
|correctly-matched settlements| / |all settlements|
```

A settlement is *correctly matched* if at least one AUTO_MATCH credit maps to it
and that credit's match is correct (set-equality).  This counts settlements, not
credits, so a large settlement with many lines counts the same as a small one.

### line_weighted_match_rate

```
Σ lines(sid) for sid in correctly-matched settlements
─────────────────────────────────────────────────────
Σ lines(sid) for all settlements
```

Line count = `len(ground_truth.settlement_to_entities[settlement_id])`.  This is
the primary headline metric: a matcher that correctly resolves high-volume
settlements scores higher than one that only gets trivial single-line ones right.

---

## Worked example — clubbed credit (H01)

Setup:
- `setl_X` (amount 500 000 p) and `setl_Y` (amount 700 000 p) are both processed.
- H01 clubs the two bank credits into one: `bc_merged` (amount 1 200 000 p,
  narration contains only `setl_X`'s UTR).

Ground truth: `credit_to_settlements["bc_merged"] = ["setl_X", "setl_Y"]`

Matcher behaviour (rung 1):
- Stage 2 (exact UTR): `bc_merged` matches `setl_X` → `AUTO_MATCH` to `["setl_X"]`.
- Set-equality check: `{"setl_X"} ≠ {"setl_X", "setl_Y"}` → **wrong AUTO_MATCH**.
- `bc_merged` lands in A✗ → contributes to `false_match_rate`.
- Neither `setl_X` nor `setl_Y` is in `correctly-matched settlements`.

This is expected rung-1 behaviour.  Rung 2 (ML) is expected to detect clubbed
credits by looking at unsettled settlements and credit amounts.
