# Ablation results

## Multi-seed validation (20 settlements, seen corruptions)

| seed | match_rate | false_match_rate | exception_rate |
|---|---|---|---|
| 42 | 0.50 | 0.00 | 0.50 |
| 99 | 0.65 | 0.00 | 0.35 |
| 7 | 0.55 | 0.00 | 0.45 |
| 123 | 0.50 | 0.00 | 0.50 |
| 256 | 0.60 | 0.00 | 0.40 |
| mean | 0.56 | 0.00 | 0.44 |

## Scale test (100 settlements, seed 42, seen corruptions)

| match_rate | false_match_rate | exception_rate |
|---|---|---|
| 0.49 | 0.00 | 0.51 |

2026 recon lines. 103 credits (3 duplicates). 49 correct matches.
Match rate holds at scale. Zero false matches.

## Held-out corruptions (seed 42, 20 settlements)

| match_rate | false_match_rate | exception_rate |
|---|---|---|
| 0.45 | 0.00 | 0.55 |

## Interpretation

Zero false matches across every configuration tested. The system
degrades by refusing, not by lying.
