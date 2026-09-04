# Ablation results

Seed 42, 20 settlements.

## Seen corruptions (C01-C06)

| metric | det | det+fuzzy | det+fuzzy+llm |
|---|---|---|---|
| match_rate | 0.50 | 0.50 | 0.50 |
| false_match_rate | 0.00 | 0.00 | 0.00 |
| exception_rate | 0.50 | 0.50 | 0.50 |

## Held-out corruptions (C01-C06 + H01-H04)

| metric | det | det+fuzzy | det+fuzzy+llm |
|---|---|---|---|
| match_rate | 0.45 | 0.45 | 0.45 |
| false_match_rate | 0.00 | 0.00 | 0.00 |
| exception_rate | 0.55 | 0.55 | 0.55 |

## Interpretation

Zero false matches across all configurations. The system degrades by
refusing, not by lying.
