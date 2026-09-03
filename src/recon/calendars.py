from __future__ import annotations

"""
Shared world knowledge. Unlike fees.py, the matching engine MAY import this.
"""

import datetime

# Subset sufficient for the generated window; source: RBI holiday calendar.
# Extend if the window extends.
RBI_HOLIDAYS_2026: list[str] = [
    "2026-01-01",
    "2026-01-14",
    "2026-01-26",
    "2026-02-16",
    "2026-03-03",
    "2026-03-21",
    "2026-03-25",
]

_HOLIDAY_SET: frozenset[str] = frozenset(RBI_HOLIDAYS_2026)


def is_business_day(iso_date: str) -> bool:
    d = datetime.date.fromisoformat(iso_date)
    return d.weekday() < 5 and iso_date not in _HOLIDAY_SET


def add_business_days(iso_date: str, n: int) -> str:
    d = datetime.date.fromisoformat(iso_date)
    added = 0
    while added < n:
        d += datetime.timedelta(days=1)
        if is_business_day(d.isoformat()):
            added += 1
    return d.isoformat()


def business_days_distance(date_a: str, date_b: str) -> int:
    """Number of add_business_days steps from the earlier date to the later."""
    d_a = datetime.date.fromisoformat(date_a)
    d_b = datetime.date.fromisoformat(date_b)
    if d_a > d_b:
        d_a, d_b = d_b, d_a
    count = 0
    d = d_a
    while d < d_b:
        d += datetime.timedelta(days=1)
        if is_business_day(d.isoformat()):
            count += 1
    return count
