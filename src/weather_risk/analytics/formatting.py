"""Deterministic display formatting for critical numbers (single source of truth).

Rounding policy for 0–100 scores (D-026):
  - Bands are always determined from the UNROUNDED score.
  - Scores are displayed with 1 decimal, unless rounding to 1 decimal would move the value across
    a band boundary (e.g. 39.975 -> "40.0" while the band is Low); then 2 decimals are shown
    ("39.98"), so the displayed number never contradicts its band.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

_BAND_MINS: tuple[float, ...] | None = None


def configure_bands(band_mins: Sequence[float]) -> None:
    """Register band lower bounds from the scoring config (single source of truth, D-039)."""
    global _BAND_MINS
    _BAND_MINS = tuple(float(m) for m in band_mins)


def band_mins() -> tuple[float, ...]:
    if _BAND_MINS is None:  # not yet configured: read the same config file the engine uses
        from weather_risk.analytics.config import load_scoring_config
        from weather_risk.config import PROJECT_ROOT

        load_scoring_config(PROJECT_ROOT / "config" / "scoring.yaml")
    assert _BAND_MINS is not None
    return _BAND_MINS


def format_score(score: float | None, band_mins_override: Sequence[float] | None = None) -> str:
    if score is None:
        return "n/a"
    mins = band_mins_override if band_mins_override is not None else band_mins()

    def band(x: float) -> int:
        return sum(1 for m in mins if x >= m)

    for decimals in (1, 2, 3):
        shown = round(score, decimals)
        if band(shown) == band(score):
            return f"{shown:.{decimals}f}"
    # Still crossing at 3 decimals (e.g. 39.9999): truncate downward, which keeps the band.
    return f"{math.floor(score * 1000) / 1000:.3f}"


def format_value(value: float | int | str | None, unit: str | None, kind: str) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, str):
        return value
    if kind == "rank":
        return f"#{int(value)}"
    if kind in ("score", "percentile") or unit == "index 0–100":
        return format_score(float(value))
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "days" or kind == "count":
        return str(int(value))  # bare: the narrative supplies the noun ("26 of 364 days")
    if unit in ("days/yr", "points"):
        return f"{value:.1f}"
    if kind == "frequency":
        return f"{value:.3g} per year"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
