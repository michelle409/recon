from __future__ import annotations

"""Anonymise a parsed HDFC statement CSV for safe use in development."""

import argparse
import csv
import json
import re
import string
from pathlib import Path

INPUT = Path(__file__).parent.parent / "data" / "raw" / "statement_parsed.csv"
OUTPUT = Path(__file__).parent.parent / "data" / "raw" / "statement_anonymised.csv"
MAP_OUTPUT = Path(__file__).parent.parent / "data" / "raw" / "pseudonym_map.json"

# --- Patterns ---
ACCT_NO_RE = re.compile(r"\b(\d{10,})\b")
PHONE_RE = re.compile(r"\b([6-9]\d{9})\b")
VPA_RE = re.compile(r"\b([\w.\-+]+)@([\w.\-]+)\b")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
# Extracts maximal runs of uppercase letters and digits for name scanning
_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9]*")

# Banking keywords, IFSC prefixes, and abbreviations that are never names
BANKING_KEYWORDS: frozenset[str] = frozenset({
    # Transaction type prefixes and their CR/DR composites
    "NEFT", "RTGS", "IMPS", "UPI", "MMT", "ACH", "INF", "BIL", "ATM",
    "NFS", "CLG", "ECS", "SIL", "NACH", "BBPS",
    "RTGSCR", "RTGSDR", "NEFTCR", "NEFTDR", "IMPSCR", "IMPSDR",
    # Bank IFSC prefixes / common bank name fragments
    "HDFC", "ICICI", "SBIN", "AXIS", "KOTK", "YESB", "IOBA", "PUNB",
    "CNRB", "BARB", "UTIB", "KKBK", "UBIN", "INDB", "FDRL", "BDBL",
    "IDIB", "UCBA", "MAHB", "HSBC", "CITI", "DEUT", "STAN", "SCBL",
    "LAVB", "JAKA", "RATN", "BKID", "VIJB", "SIBL", "KVBL", "DCBL",
    "SRCB", "NESF", "PAYTM", "AIRTEL", "JIOSP", "FINO", "EQUI",
    # Generic banking and legal terms
    "BANK", "CREDIT", "DEBIT", "TRANSFER", "PAYMENT", "SALARY",
    "CHARGES", "CHARGE", "GST", "SGST", "CGST", "IGST", "EMI",
    "LOAN", "CARD", "CASH", "FUND", "BALANCE", "ACCOUNT", "SAVINGS",
    "CURRENT", "FIXED", "DEPOSIT", "WITHDRAWAL", "INTEREST",
    "DIVIDEND", "REFUND", "REVERSAL", "OPENING", "CLOSING",
    "STATEMENT", "SUMMARY", "INDIA", "INDIAN", "LIMITED", "PRIVATE",
    "PUBLIC", "SERVICE", "SERVICES", "ACCT", "IFSC", "MICR", "SWIFT",
    "CORP", "CORPORATION", "COOPERATIVE", "URBAN",
})

_LETTERS = list(string.ascii_uppercase)


def _label(n: int) -> str:
    """0→A, 25→Z, 26→AA … (spreadsheet-style)."""
    result = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        result = _LETTERS[r] + result
    return result


class PseudonymRegistry:
    def __init__(self) -> None:
        self._names: dict[str, str] = {}
        self._vpas: dict[str, str] = {}

    def name(self, token: str) -> str:
        if token not in self._names:
            self._names[token] = f"COUNTERPARTY_{_label(len(self._names))}"
        return self._names[token]

    def vpa(self, handle: str, bank: str) -> str:
        key = f"{handle}@{bank}"
        if key not in self._vpas:
            self._vpas[key] = f"VPA_{len(self._vpas) + 1:03d}@{bank}"
        return self._vpas[key]

    def as_dict(self) -> dict:
        return {"counterparties": self._names, "vpas": self._vpas}


def _is_name_token(token: str) -> bool:
    """True when a token looks like a person or business name."""
    alpha_count = sum(1 for c in token if c.isalpha())
    if alpha_count < 5:
        return False
    if token in BANKING_KEYWORDS:
        return False
    if IFSC_RE.match(token):
        return False
    # Mostly digits → reference number, not a name
    if sum(1 for c in token if c.isdigit()) >= alpha_count:
        return False
    return True


def collect_name_tokens(narrations: list[str]) -> list[str]:
    """
    First pass: scan every narration and return unique name-like tokens,
    longest first (so longer names are replaced before any shorter substring).
    """
    seen: set[str] = set()
    for narration in narrations:
        for token in _TOKEN_RE.findall(narration):
            if _is_name_token(token):
                seen.add(token)
    return sorted(seen, key=len, reverse=True)


def _name_pattern(token: str) -> re.Pattern:
    """Match token only when not flanked by another alphanumeric character."""
    return re.compile(r"(?<![A-Z0-9])" + re.escape(token) + r"(?![A-Z0-9])")


def anonymise_narration(
    narration: str,
    name_subs: list[tuple[re.Pattern, str]],
    reg: PseudonymRegistry,
    account_holder_re: re.Pattern | None,
) -> str:
    if not narration:
        return narration

    result = narration

    # 1. Replace UPI VPAs first — before digit masking corrupts them
    def _replace_vpa(mo: re.Match) -> str:
        return reg.vpa(mo.group(1), mo.group(2))

    result = VPA_RE.sub(_replace_vpa, result)

    # 2. Mask account numbers (10+ digits)
    result = ACCT_NO_RE.sub("ACCT_XXXXX", result)

    # 3. Strip phone numbers not already masked
    result = PHONE_RE.sub("", result)

    # 4. Replace account holder name if provided
    if account_holder_re:
        result = account_holder_re.sub("ACCOUNT_HOLDER", result)

    # 5. Replace each name token in-place; all surrounding structure is kept
    for pattern, pseudo in name_subs:
        result = pattern.sub(pseudo, result)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Anonymise parsed HDFC statement CSV")
    parser.add_argument(
        "--account-holder-name",
        default=None,
        help="Exact name to replace with ACCOUNT_HOLDER (case-insensitive)",
    )
    args = parser.parse_args()

    account_holder_re: re.Pattern | None = None
    if args.account_holder_name:
        account_holder_re = re.compile(
            re.escape(args.account_holder_name), re.IGNORECASE
        )

    if not INPUT.exists():
        raise FileNotFoundError(
            f"Input not found: {INPUT}\nRun parse_hdfc_pdf.py first."
        )

    with open(INPUT, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    all_narrations = [r.get("Narration", "") for r in rows]

    # First pass: build the name→pseudonym map from all narrations at once
    reg = PseudonymRegistry()
    name_tokens = collect_name_tokens(all_narrations)
    # Pre-compile patterns and assign pseudonyms in one shot
    name_subs: list[tuple[re.Pattern, str]] = [
        (_name_pattern(tok), reg.name(tok)) for tok in name_tokens
    ]

    sample_before = all_narrations[:10]

    # Second pass: anonymise each row
    anonymised = []
    for row in rows:
        new_row = dict(row)
        new_row["Narration"] = anonymise_narration(
            row.get("Narration", ""), name_subs, reg, account_holder_re
        )
        anonymised.append(new_row)

    sample_after = [r["Narration"] for r in anonymised[:10]]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(anonymised)

    with open(MAP_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(reg.as_dict(), f, indent=2, ensure_ascii=False)

    print(f"Anonymised {len(anonymised)} rows  →  {OUTPUT}")
    print(f"Name tokens found : {len(name_tokens)}")
    print(f"Pseudonym map     →  {MAP_OUTPUT}")
    print()
    print("Sample narrations (before → after):")
    for b, a in zip(sample_before, sample_after):
        print(f"  BEFORE: {b}")
        print(f"  AFTER:  {a}")
        print()


if __name__ == "__main__":
    main()
