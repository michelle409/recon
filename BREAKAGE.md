# Breakage log

Entry template (copy this for each new entry):

---
**symptom:**
**what I believed (wrong):**
**what I tried (failed):**
**actual cause:**
**fix commit hash:**
**regression test name:**
**what it changed upstream:**
---

## 2026-08-31

### B01: type hint syntax crash

**symptom:** parse script crashed on launch with TypeError on `str | None`
**what I believed (wrong):** modern type hint syntax works on any Python 3
**what I tried (failed):** nothing, identified the cause immediately
**actual cause:** Python version is below 3.10, which does not support the union pipe syntax
**fix commit hash:** XXXXXX
**regression test name:** (none needed, import-time failure)
**what it changed upstream:** added `from __future__ import annotations` to all scripts as a standard first line

### B02: PDF parser extracted 0 rows from 55 pages

**symptom:** parser ran without errors but printed "No rows extracted"
**what I believed (wrong):** pdfplumber extract_table() returns one row per transaction
**what I tried (failed):** ran the parser as-is, got nothing
**actual cause:** HDFC PDFs pack all values per column into a single cell separated by newlines. Each page returns 1 row, not N rows. The real transactions are inside the cells.
**fix commit hash:** XXXXXX
**regression test name:** (pending)
**what it changed upstream:** rewrote parser to split cells by newline and use date column as the row anchor for multi-line narrations

### B03: anonymiser leaking real business names

**symptom:** output narrations still contained real business names like VIJAYAGOLDPALACE and GOLDJEWELLERYPUR
**what I believed (wrong):** matching counterparty names as whole strings would catch them in narrations
**what I tried (failed):** ran anonymiser, checked samples, names visible
**actual cause:** business names are embedded inside narration strings without clean delimiters. Whole-string matching misses substrings. Some narrations were also flattened to just a label, losing all structure.
**fix commit hash:** XXXXXX
**regression test name:** (pending)
**what it changed upstream:** (pending, fixing anonymiser now)

### B04: parser merging multiple transactions into single rows

**symptom:** 233 of 596 rows had multiple transactions jammed into one row, narrations 500+ characters
**what I believed (wrong):** using date as row anchor would cleanly separate transactions
**what I tried (failed):** initial parser with date-anchored splitting
**actual cause:** HDFC PDF packs all column values into single cells per page. Multi-line narrations and adjacent transactions are indistinguishable when split by newline alone. No reliable delimiter exists between transactions within a cell.
**fix commit hash:** (filtered instead of fixed, kept 363 clean rows)
**regression test name:** (not applicable, workaround not fix)
**what it changed upstream:** added filter script to isolate clean rows for format reference. Accepted 363 of 596 as sufficient for provenance calibration. Full parser fix is not worth the hours given that these rows serve as format reference only, not as input data.

### B05: fuzzy stage ordering caught before code

**symptom:** caught in spec review, not in running code
**what I believed (wrong):** fuzzy should run after amount+date as a fallback
**what I tried (failed):** n/a, caught before implementation
**actual cause:** PROPOSE is terminal. A two-way amount tie exits as PROPOSE before narration is ever consulted. Fuzzy (narration similarity + exact amount + date) has strictly more evidence than amount+date alone and must run first.
**fix commit hash:** (next commit)
**regression test name:** test_fuzzy_disambiguates_amount_tie
**what it changed upstream:** stage order in matcher pipeline
