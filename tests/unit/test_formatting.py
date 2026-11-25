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


def test_bands_come_from_scoring_config_single_source():
    import yaml

    from weather_risk.analytics import formatting
    from weather_risk.analytics.config import load_scoring_config
    from weather_risk.config import PROJECT_ROOT

    cfg = load_scoring_config(PROJECT_ROOT / "config" / "scoring.yaml")
    file_mins = [
        b["min"]
        for b in yaml.safe_load((PROJECT_ROOT / "config" / "scoring.yaml").read_text())["bands"]
    ]
    assert (
        list(formatting.band_mins()) == [float(m) for m in file_mins] == [b.min for b in cfg.bands]
    )
    # Denver regression: 39.975 is Low by config bands and is never displayed as "40.0"
    assert cfg.band_for(39.97549589760598) == "Low" and format_score(39.97549589760598) == "39.98"


def test_display_follows_reconfigured_bands():
    from weather_risk.analytics import formatting

    saved = formatting.band_mins()
    try:
        formatting.configure_bands([0, 50, 80])
        assert format_score(49.96) == "49.96"  # would round across the new 50 boundary
        assert format_score(39.975) == "40.0"  # 40 is no longer a boundary
    finally:
        formatting.configure_bands(saved)


@pytest.mark.parametrize(
    "score,shown", [(69.951, "69.95"), (70.0, "70.0"), (39.95, "39.95"), (40.04, "40.0")]
)
def test_boundary_regressions(score, shown):
    assert format_score(score) == shown
