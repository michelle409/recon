from __future__ import annotations

"""Inspect what pdfplumber extracts from the first few pages of a PDF."""

import argparse

import pdfplumber


def debug_page(page, page_num: int) -> None:
    print(f"\n{'=' * 60}")
    print(f"PAGE {page_num}")
    print("=" * 60)

    print("\n--- extract_text() (first 500 chars) ---")
    text = page.extract_text() or ""
    print(repr(text[:500]))

    print("\n--- extract_table() ---")
    table = page.extract_table()
    if table is not None:
        print(f"Returned {len(table)} rows:")
        for i, row in enumerate(table):
            print(f"  [{i}] {row}")
    else:
        print("None — trying extract_tables() instead...")
        tables = page.extract_tables()
        if tables:
            print(f"extract_tables() found {len(tables)} table(s):")
            for t_idx, t in enumerate(tables):
                print(f"\n  Table {t_idx} ({len(t)} rows):")
                for i, row in enumerate(t):
                    print(f"    [{i}] {row}")
        else:
            print("extract_tables() also returned nothing.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug pdfplumber extraction on pages 1-3")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--password", default=None, help="PDF password if protected")
    args = parser.parse_args()

    open_kwargs = {"password": args.password} if args.password else {}

    with pdfplumber.open(args.pdf_path, **open_kwargs) as pdf:
        print(f"Total pages: {len(pdf.pages)}")
        for i in range(min(3, len(pdf.pages))):
            debug_page(pdf.pages[i], i + 1)


if __name__ == "__main__":
    main()
