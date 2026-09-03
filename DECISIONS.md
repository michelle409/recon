# Decisions

## 2026-08-30

## Fuzzy stage ordering

Fuzzy was originally specced to run after amount+date matching. Realized
that PROPOSE is terminal: a credit whose amount ties two settlements
exits at amount+date as PROPOSE, and fuzzy (which could read the narration
fragment and disambiguate to exactly one) never runs. Reordered by evidence
strength before writing code. The stage with more evidence must run first.
