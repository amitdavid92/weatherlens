"""Resolve user-facing period expressions into concrete, validated date ranges.

Supported specs (strings, case-insensitive):
  "last_year" | "last year" | "previous year"   -> previous completed calendar year
  "YYYY"  | "year:YYYY"                          -> that calendar year (must be completed)
  "last_N_years" | "last N years"                -> the N most recent completed calendar years
  "trailing_12_months" | "past 12 months"        -> the 365/366 days ending yesterday
  "YYYY-YYYY" | "YYYY..YYYY"                     -> inclusive range of completed calendar years
  "climatology"                                  -> configured climatology window
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict

from weather_risk.data.errors import InvalidRequestError
from weather_risk.data.periods import days_in_range


class UnsupportedPeriodError(InvalidRequestError):
    """The period expression is unknown, in the future, or outside supported bounds."""


class Period(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: date
    end: date
    label: str
    kind: str  # calendar_year | calendar_years | trailing | climatology

    @property
    def expected_days(self) -> int:
        return days_in_range(self.start, self.end)

    @property
    def n_years(self) -> float:
        """Length in (fractional) years, leap-aware: expected days / mean days per year."""
        if self.kind in ("calendar_year", "calendar_years", "climatology"):
            return float(self.end.year - self.start.year + 1)
        return self.expected_days / 365.2425

    @property
    def key(self) -> str:
        return f"{self.start.isoformat()}_{self.end.isoformat()}"


EARLIEST_YEAR = 1950


def _year_period(y0: int, y1: int, today: date, label: str, kind: str) -> Period:
    if y0 > y1:
        raise UnsupportedPeriodError(f"start year {y0} is after end year {y1}")
    if y0 < EARLIEST_YEAR:
        raise UnsupportedPeriodError(f"years before {EARLIEST_YEAR} are not supported")
    if y1 >= today.year:
        raise UnsupportedPeriodError(
            f"{y1} is not a completed calendar year (today is {today.isoformat()})"
        )
    return Period(start=date(y0, 1, 1), end=date(y1, 12, 31), label=label, kind=kind)


def resolve_period(spec: str, *, today: date, climatology: tuple[int, int]) -> Period:
    s = spec.strip().lower().replace("-", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s)
    raw = spec.strip()

    if s in ("last year", "previous year", "last calendar year"):
        y = today.year - 1
        return _year_period(
            y, y, today, f"calendar year {y} (last completed year)", "calendar_year"
        )
    if s == "climatology":
        y0, y1 = climatology
        return _year_period(y0, y1, today, f"{y0}–{y1} climatology", "climatology")
    if s in ("trailing 12 months", "past 12 months", "last 12 months"):
        end = today - timedelta(days=1)
        try:
            one_year_before = date(end.year - 1, end.month, end.day)
        except ValueError:  # end is Feb 29 -> previous year has no Feb 29
            one_year_before = date(end.year - 1, 2, 28)
        start = one_year_before + timedelta(days=1)
        return Period(
            start=start, end=end, label=f"{start} to {end} (trailing 12 months)", kind="trailing"
        )
    if m := re.fullmatch(r"(?:year:)?(\d{4})", raw.lower()):
        y = int(m.group(1))
        return _year_period(y, y, today, f"calendar year {y}", "calendar_year")
    if m := re.fullmatch(r"last (\d{1,2}) years?", s):
        n = int(m.group(1))
        if n < 1:
            raise UnsupportedPeriodError("N must be ≥ 1")
        y1 = today.year - 1
        return _year_period(y1 - n + 1, y1, today, f"{y1 - n + 1}–{y1} (last {n} completed years)",
                            "calendar_years")  # fmt: skip
    if m := re.fullmatch(r"(\d{4})\s*(?:-|–|\.\.)\s*(\d{4})", raw):
        y0, y1 = int(m.group(1)), int(m.group(2))
        return _year_period(y0, y1, today, f"{y0}–{y1}", "calendar_years")
    raise UnsupportedPeriodError(f"unsupported period expression: {spec!r}")
