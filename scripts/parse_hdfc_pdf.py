from __future__ import annotations

"""Extract the transaction table from an HDFC bank statement PDF."""

import argparse
import csv
import re
import sys
from pathlib import Path

import pdfplumber

HDFC_COLUMNS = [
    "Date",
    "Narration",
    "Chq./Ref.No.",
    "Value Dt",
    "Withdrawal Amt.",
    "Deposit Amt.",
    "Closing Balance",
]

# HDFC transaction dates: DD/MM/YY
_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")

OUTPUT = Path(__file__).parent.parent / "data" / "raw" / "statement_parsed.csv"


def _is_header_row(row: list) -> bool:
    return (row[0] or "").strip().lower() == "date"


def _split_cells(row: list) -> list[list[str]]:
    """Split each cell on newline; pad all lists to the same length."""
    cols = [(c or "").split("\n") for c in row]
    max_len = max((len(c) for c in cols), default=0)
    return [c + [""] * (max_len - len(c)) for c in cols]


def _parse_table_rows(table: list[list]) -> list[dict]:
    """
    Reconstruct individual transactions from a pdfplumber table where each
    cell contains all that column's values joined by newlines.

    The Date column is the anchor: a line whose first column matches DD/MM/YY
    starts a new transaction. Lines with an empty date are narration
    continuations and are appended to the current transaction's narration.
    """
    rows: list[dict] = []

    for raw_row in table:
        if not raw_row:
            continue
        if _is_header_row(raw_row):
            continue

        # Pad/trim to 7 columns then split each on "\n"
        padded = (list(raw_row) + [""] * 7)[:7]
        cols = _split_cells(padded)

        dates, narrations, refs, val_dts, withdrawals, deposits, closings = cols

        current: dict | None = None

        for i, raw_date in enumerate(dates):
            date = raw_date.strip()
            narr = narrations[i].strip()

            if _DATE_RE.match(date):
                # Flush previous transaction
                if current is not None:
                    rows.append(current)
                current = {
                    "Date": date,
                    "Narration": narr,
                    "Chq./Ref.No.": refs[i].strip(),
                    "Value Dt": val_dts[i].strip(),
                    "Withdrawal Amt.": withdrawals[i].strip(),
                    "Deposit Amt.": deposits[i].strip(),
                    "Closing Balance": closings[i].strip(),
                }
            elif current is not None and narr:
                # Continuation line: append narration fragment
                current["Narration"] = (current["Narration"] + " " + narr).strip()

        if current is not None:
            rows.append(current)

    return rows


def extract_rows(pdf_path: str, password: str | None) -> tuple[list[dict], int]:
    open_kwargs = {"password": password} if password else {}
    rows: list[dict] = []
    pages_processed = 0

    with pdfplumber.open(pdf_path, **open_kwargs) as pdf:
        for page in pdf.pages:
            pages_processed += 1
            table = page.extract_table()
            if not table:
                continue
            rows.extend(_parse_table_rows(table))

    return rows, pages_processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse HDFC bank statement PDF to CSV")
    parser.add_argument("pdf_path", help="Path to the HDFC statement PDF")
    parser.add_argument("--password", default=None, help="PDF password if protected")
    args = parser.parse_args()

    rows, pages = extract_rows(args.pdf_path, args.password)

    if not rows:
        print(f"No rows extracted from {pages} pages. "
              "Check the PDF path, password, or table format.")
        sys.exit(1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HDFC_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Pages processed : {pages}")
    print(f"Rows extracted  : {len(rows)}")
    print(f"Output          : {OUTPUT}")


if __name__ == "__main__":
    main()
