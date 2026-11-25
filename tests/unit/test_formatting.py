from __future__ import annotations

import pytest

from weather_risk.analytics.formatting import format_score, format_value


@pytest.mark.parametrize(
    "score,shown",
    [(39.97549589760598, "39.98"), (39.9999, "39.999"), (40.0, "40.0"), (40.04, "40.0"),
     (69.96, "69.96"), (70.0, "70.0"), (58.6554, "58.7"), (0.0, "0.0"), (100.0, "100.0")],
)  # fmt: skip
def test_displayed_score_never_crosses_its_band(score, shown):
    """Denver 39.975 is Low: it must not be displayed as '40.0' (rounding policy D-026)."""
    assert format_score(score) == shown


@pytest.mark.parametrize(
    "value,unit,kind,shown",
    [(7.142857, "%", "statistic", "7.14%"), (26, "days", "count", "26"), (2, None, "rank", "#2"),
     (0.305, "per year", "frequency", "0.305 per year"), (None, "%", "statistic", "n/a"),
     ("2025", None, "label", "2025")],
)  # fmt: skip
def test_format_value(value, unit, kind, shown):
    assert format_value(value, unit, kind) == shown
