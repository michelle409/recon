from __future__ import annotations

"""Filter anonymised statement rows down to clean, well-formed transactions."""

import csv
import re
from pathlib import Path

INPUT = Path(__file__).parent.parent / "data" / "raw" / "statement_anonymised.csv"
OUTPUT = Path(__file__).parent.parent / "data" / "raw" / "statement_clean.csv"

_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")


def is_clean(row: dict) -> bool:
    if not _DATE_RE.match(row.get("Date", "")):
        return False
    if len(row.get("Narration", "")) >= 200:
        return False
    if not row.get("Withdrawal Amt.", "").strip() and not row.get("Deposit Amt.", "").strip():
        return False
    return True


def main() -> None:
    if not INPUT.exists():
        raise FileNotFoundError(f"Input not found: {INPUT}\nRun anonymise.py first.")

    with open(INPUT, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    kept = [r for r in rows if is_clean(r)]
    dropped = len(rows) - len(kept)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    print(f"Input rows  : {len(rows)}")
    print(f"Kept        : {len(kept)}")
    print(f"Dropped     : {dropped}")
    print(f"Output      : {OUTPUT}")


if __name__ == "__main__":
    main()
