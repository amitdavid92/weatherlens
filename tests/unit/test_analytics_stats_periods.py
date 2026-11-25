from __future__ import annotations

from datetime import date

import pytest

from tests.conftest import load_fixture
from tests.unit.analytics_helpers import AT, dataset
from weather_risk.analytics.config import ClimateMetric as M
from weather_risk.analytics.config import Thresholds
from weather_risk.analytics.periods import Period, UnsupportedPeriodError, resolve_period
from weather_risk.analytics.stats import compute_day_count
from weather_risk.data.adapters import noaa_ghcn
from weather_risk.data.models import ClimateElement as E
from weather_risk.data.models import Freshness, SourceId

T = Thresholds(heavy_snow_mm=101.6, freezing_tmin_c=0.0, extreme_heat_tmax_c=35.0)
TODAY = date(2026, 11, 25)
CLIM = (2016, 2025)


def period(start: date, end: date, kind: str = "trailing") -> Period:
    return Period(start=start, end=end, label="test", kind=kind)


# 10 days. SNOW: 5mm, trace, 0, missing, 120mm (heavy), flagged 50mm, 0, 0, trace, 2.5mm
SNOW = [5.0, ("T",), 0.0, None, 120.0, ("Q", 50.0), 0.0, 0.0, ("T",), 2.5]
#   missing = 1, excluded (quality) = 1, valid = 8
#   measurable = {5, 120, 2.5} = 3 -> 37.5 % ; trace-inclusive = 3 + 2 = 5 -> 62.5 % ; heavy = 1
TEN = (date(2025, 1, 1), date(2025, 1, 10))


def stat(metric, ds, p, min_cov=0.75, **kw):
    return compute_day_count(ds, metric, p, T, min_coverage=min_cov, **kw)


def test_snow_statistics_denominators_by_hand():
    ds = dataset(*TEN, {E.SNOWFALL: SNOW})
    p = period(*TEN)
    s = stat(M.SNOW_DAYS_MEASURABLE, ds, p)
    assert (s.expected_days, s.missing_days, s.excluded_days, s.valid_days) == (10, 1, 1, 8)
    assert s.excluded_reasons == {"quality_flag:X": 1}
    assert s.coverage == pytest.approx(0.8)
    assert s.event_days == 3 and s.percent_of_valid_days == pytest.approx(37.5)
    t = stat(M.SNOW_DAYS_TRACE_INCLUSIVE, ds, p)
    assert t.event_days == 5 and t.percent_of_valid_days == pytest.approx(62.5)
    h = stat(M.HEAVY_SNOW_DAYS, ds, p)
    assert h.event_days == 1  # the flagged 50 mm day is excluded, 120 mm counts


def test_quality_flagged_values_can_be_included_when_configured():
    ds = dataset(*TEN, {E.SNOWFALL: SNOW})
    s = stat(M.SNOW_DAYS_MEASURABLE, ds, period(*TEN), exclude_quality_flagged=False)
    assert s.valid_days == 9 and s.event_days == 4 and s.excluded_days == 0


def test_coverage_threshold_withholds_value_but_keeps_counts():
    ds = dataset(*TEN, {E.SNOWFALL: SNOW})
    s = stat(M.SNOW_DAYS_MEASURABLE, ds, period(*TEN), min_cov=0.9)  # 80 % < 90 %
    assert s.status == "insufficient_coverage"
    assert s.event_days is None and s.percent_of_valid_days is None and s.annual_average is None
    assert s.valid_days == 8 and s.missing_days == 1


def test_all_missing_is_insufficient_never_zero():
    ds = dataset(*TEN, {E.SNOWFALL: [None] * 10})
    s = stat(M.SNOW_DAYS_MEASURABLE, ds, period(*TEN))
    assert s.status == "insufficient_coverage" and s.event_days is None and s.valid_days == 0


def test_freezing_includes_zero_and_negative_heat_includes_threshold():
    tmin = [-5.0, 0.0, 0.1, None, -0.1, 3.0, 2.0, 1.0, -20.0, 5.0]  # ≤ 0: -5, 0, -0.1, -20 = 4
    tmax = [35.0, 34.9, 40.0, None, 20.0, 36.0, 10.0, 0.0, -3.0, 35.1]  # ≥ 35: 35, 40, 36, 35.1
    ds = dataset(*TEN, {E.TMIN: tmin, E.TMAX: tmax})
    f = stat(M.FREEZING_DAYS, ds, period(*TEN))
    h = stat(M.EXTREME_HEAT_DAYS, ds, period(*TEN))
    assert f.event_days == 4 and f.valid_days == 9
    assert h.event_days == 4 and h.percent_of_valid_days == pytest.approx(400 / 9)


def test_annual_average_full_leap_year_equals_count():
    days = 366  # 2024
    snow = [10.0 if i % 10 == 0 else 0.0 for i in range(days)]  # 37 snow days
    ds = dataset(date(2024, 1, 1), date(2024, 12, 31), {E.SNOWFALL: snow})
    p = resolve_period("2024", today=TODAY, climatology=CLIM)
    assert p.expected_days == 366 and p.n_years == 1.0
    s = stat(M.SNOW_DAYS_MEASURABLE, ds, p)
    assert s.event_days == 37 and s.annual_average == pytest.approx(37.0)


def test_annual_average_scales_by_observed_rate_over_two_years():
    # 2023 (365) + 2024 (366) = 731 days; 31 missing; 70 events among 700 valid
    n = 731
    snow = [None] * 31 + [5.0] * 70 + [0.0] * (n - 101)
    ds = dataset(date(2023, 1, 1), date(2024, 12, 31), {E.SNOWFALL: snow})
    p = resolve_period("2023-2024", today=TODAY, climatology=CLIM)
    s = stat(M.SNOW_DAYS_MEASURABLE, ds, p, min_cov=0.9)
    expected = (70 / 700) * (731 / 2)  # = 36.55 days/yr, independent of the engine
    assert s.coverage == pytest.approx(700 / 731)
    assert s.annual_average == pytest.approx(expected)


def test_real_denver_fixture_trace_vs_measurable():
    req, body = load_fixture("noaa_denver_2025-01-24_26")
    ds = noaa_ghcn.parse_response(body, req, retrieved_at=AT, freshness=Freshness.LIVE)
    p = period(date(2025, 1, 24), date(2025, 1, 26))
    assert stat(M.SNOW_DAYS_MEASURABLE, ds, p).event_days == 1  # Jan 25: 104 mm
    assert stat(M.SNOW_DAYS_TRACE_INCLUSIVE, ds, p).event_days == 3
    assert stat(M.HEAVY_SNOW_DAYS, ds, p).event_days == 1  # 104 ≥ 101.6


def test_open_meteo_dataset_has_no_trace_and_keeps_source():
    ds = dataset(*TEN, {E.SNOWFALL: [0.0, 1.0] * 5}, source=SourceId.OPEN_METEO_ARCHIVE)
    s = stat(M.SNOW_DAYS_TRACE_INCLUSIVE, ds, period(*TEN))
    assert s.event_days == 5 and s.source_id is SourceId.OPEN_METEO_ARCHIVE


def test_period_outside_dataset_rejected():
    ds = dataset(*TEN, {E.SNOWFALL: [0.0] * 10})
    with pytest.raises(ValueError):
        stat(M.SNOW_DAYS_MEASURABLE, ds, period(date(2025, 1, 1), date(2025, 1, 11)))


# ------------------------------------------------------------------ periods


@pytest.mark.parametrize(
    "spec,today,start,end",
    [
        ("last year", date(2026, 11, 25), date(2025, 1, 1), date(2025, 12, 31)),
        ("last_year", date(2026, 1, 1), date(2025, 1, 1), date(2025, 12, 31)),
        ("2024", TODAY, date(2024, 1, 1), date(2024, 12, 31)),
        ("year:2020", TODAY, date(2020, 1, 1), date(2020, 12, 31)),
        ("last 3 years", TODAY, date(2023, 1, 1), date(2025, 12, 31)),
        ("2016-2025", TODAY, date(2016, 1, 1), date(2025, 12, 31)),
        ("climatology", TODAY, date(2016, 1, 1), date(2025, 12, 31)),
        ("past 12 months", date(2026, 11, 25), date(2025, 11, 25), date(2026, 11, 24)),
        # today = 2024-03-01 -> end = 2024-02-29 (leap day); window has 366 days
        ("trailing_12_months", date(2024, 3, 1), date(2023, 3, 1), date(2024, 2, 29)),
        ("trailing_12_months", date(2025, 3, 1), date(2024, 2, 29), date(2025, 2, 28)),
    ],
)
def test_resolve_period(spec, today, start, end):
    p = resolve_period(spec, today=today, climatology=CLIM)
    assert (p.start, p.end) == (start, end)


def test_leap_year_lengths():
    assert resolve_period("2024", today=TODAY, climatology=CLIM).expected_days == 366
    assert resolve_period("2025", today=TODAY, climatology=CLIM).expected_days == 365
    assert resolve_period("trailing 12 months", today=date(2024, 3, 1),
                          climatology=CLIM).expected_days == 366  # fmt: skip


@pytest.mark.parametrize("spec", ["2026", "2030", "next year", "1800", "last 0 years",
                                  "2025-2020", "yesterday", ""])  # fmt: skip
def test_unsupported_periods(spec):
    with pytest.raises(UnsupportedPeriodError):
        resolve_period(spec, today=TODAY, climatology=CLIM)
