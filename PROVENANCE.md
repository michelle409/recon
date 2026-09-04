# Corruption provenance

Every corruption in the generator is classified below. OBSERVED types
are imitations of artifacts found in three months of real, anonymised
HDFC bank statements (363 clean rows from 55 pages). DOCUMENTED types
come from Razorpay's published schemas or from test mode fixtures
committed in this repo. CONJECTURED types have no observed instance;
each is included because a concrete mechanism would produce it, and
each is quarantined from the headline results: held-out metrics are
reported twice, with and without conjectured types, so no claim in
this repo depends on my imagination being right.

## Classification

| id | name | leg | class | evidence | split |
|---|---|---|---|---|---|
| C01 | utr_truncation | bank | OBSERVED | 41+ narrations in real statements show truncated references, e.g. "NEFT CR-XXXX0000123-RAZORPAY SETTLEME" cut at field boundary | seen |
| C02 | narration_format_variance | bank | OBSERVED | RTGSCR, NEFTCR, TPT, IMPS, EMI formats all present in same 3-month statement, no standard structure | seen |
| C03 | duplicate_export | bank | CONJECTURED | overlapping date-range exports from banking portal would produce identical rows; mechanism is real, no instance observed | seen |
| C04 | refund_cross_batch | settlement | DOCUMENTED | Razorpay recon report schema shows refund lines carry settlement_id of the batch they net against, which may differ from the originating payment's batch (docs: fixtures/testmode/recon_report_documented.json) | seen |
| C05 | value_date_skew | bank | OBSERVED | 20+ rows in real statements show Date and Value Dt columns differing by 1-2 days | seen |
| C06 | per_line_rounding_drift | settlement | DOCUMENTED | Razorpay computes fees per line in paise with rounding; batch-level percentage arithmetic provably does not tie (test_batch_percentage_does_not_tie) | seen |
| H01 | clubbed_credit | bank | CONJECTURED | two same-day NEFT credits from the same originator could be clubbed by the receiving bank into one line; no instance observed in statements | held-out |
| H02 | utr_absent | bank | OBSERVED | multiple narrations in real statements carry no identifiable UTR or reference number, just "NEFT CREDIT" or a bare name | held-out |
| H03 | orphan_adjustment | settlement | DOCUMENTED | Razorpay recon schema includes adjustment type with nullable order_id, settlement_utr, and method (fixtures/testmode/recon_report_documented.json sample shows adj_ entity with null UTR) | held-out |
| H04 | split_settlement | settlement | CONJECTURED | a settlement could theoretically arrive as two partial credits if the bank splits the NEFT; no instance observed | held-out |

## Quarantine

Held-out metrics are reported separately with and without CONJECTURED
types (C03, H01, H04). If a Razorpay engineer confirms a conjectured
type never occurs in production, removing it changes the secondary
table and nothing else.
