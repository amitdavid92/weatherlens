"""Date-range helpers. Pure functions; leap years handled by `datetime.date` arithmetic."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

from weather_risk.data.errors import InvalidRequestError


def iter_dates(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def days_in_range(start: date, end: date) -> int:
    return (end - start).days + 1


def validate_range(start: date, end: date, *, today: date, earliest: date | None = None) -> None:
    if start > end:
        raise InvalidRequestError(f"start {start} is after end {end}")
    if end >= today:
        raise InvalidRequestError(
            f"end {end} must be before today ({today}); no future/partial-day data"
        )
    if earliest and start < earliest:
        raise InvalidRequestError(f"start {start} is before the earliest supported date {earliest}")


def year_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] into calendar-year chunks (used as canonical cache/snapshot units)."""
    if start > end:
        raise InvalidRequestError(f"start {start} is after end {end}")
    chunks = []
    for y in range(start.year, end.year + 1):
        cs = max(start, date(y, 1, 1))
        ce = min(end, date(y, 12, 31))
        chunks.append((cs, ce))
    return chunks


def canonical_year_chunk(year: int, *, today: date) -> tuple[date, date]:
    """The canonical request window for a calendar year: Jan 1 .. min(Dec 31, yesterday)."""
    start = date(year, 1, 1)
    end = min(date(year, 12, 31), today - timedelta(days=1))
    if end < start:
        raise InvalidRequestError(f"year {year} has no completed days before {today}")
    return start, end


def last_completed_year(today: date) -> int:
    return today.year - 1
