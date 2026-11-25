from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from weather_risk.data.errors import InvalidRequestError
from weather_risk.data.http import SourceRequest
from weather_risk.data.periods import (
    canonical_year_chunk,
    days_in_range,
    iter_dates,
    last_completed_year,
    validate_range,
    year_chunks,
)

REQ = SourceRequest(source_id="test", url="https://example.test", params={"q": "1"})
NOW = datetime(2026, 11, 25, tzinfo=UTC)


def test_cache_miss_put_hit(cache):
    assert cache.get(REQ) is None
    cache.put(REQ, b'{"a":1}', ttl_seconds=60, dataset_version="v1", now=NOW)
    entry = cache.get(REQ)
    assert entry.body == b'{"a":1}' and entry.dataset_version == "v1"
    assert entry.is_fresh(NOW + timedelta(seconds=59))
    assert not entry.is_fresh(NOW + timedelta(seconds=61))


def test_expired_entries_are_still_returned_for_stale_fallback(cache):
    cache.put(REQ, b"x", ttl_seconds=1, now=NOW - timedelta(days=10))
    entry = cache.get(REQ)
    assert entry is not None and not entry.is_fresh(NOW)


def test_corrupt_entry_is_evicted(cache):
    cache.put(REQ, b"good", ttl_seconds=60, now=NOW)
    cache._corrupt(REQ)
    assert cache.get(REQ) is None
    assert cache.count() == 0


def test_put_replaces_existing(cache):
    cache.put(REQ, b"one", ttl_seconds=60, now=NOW)
    cache.put(REQ, b"two", ttl_seconds=60, now=NOW)
    assert cache.get(REQ).body == b"two" and cache.count() == 1


# ----------------------------------------------------------------- periods


def test_leap_years():
    assert days_in_range(date(2024, 1, 1), date(2024, 12, 31)) == 366
    assert days_in_range(date(2025, 1, 1), date(2025, 12, 31)) == 365
    assert date(2024, 2, 29) in list(iter_dates(date(2024, 2, 28), date(2024, 3, 1)))


def test_year_chunks_split_on_calendar_years():
    assert year_chunks(date(2024, 11, 1), date(2026, 2, 1)) == [
        (date(2024, 11, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 2, 1)),
    ]


def test_canonical_chunk_for_current_year_stops_yesterday():
    today = date(2026, 11, 25)
    assert canonical_year_chunk(2025, today=today) == (date(2025, 1, 1), date(2025, 12, 31))
    assert canonical_year_chunk(2026, today=today) == (date(2026, 1, 1), date(2026, 11, 24))
    with pytest.raises(InvalidRequestError):
        canonical_year_chunk(2027, today=today)


def test_last_completed_year():
    assert last_completed_year(date(2026, 11, 25)) == 2025
    assert last_completed_year(date(2026, 1, 1)) == 2025


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2025, 2, 1), date(2025, 1, 1)),  # inverted
        (date(2026, 11, 1), date(2026, 11, 25)),  # includes today
        (date(2026, 12, 1), date(2026, 12, 31)),  # future
        (date(1800, 1, 1), date(1800, 12, 31)),  # before earliest
    ],
)
def test_validate_range_rejects(start, end):
    with pytest.raises(InvalidRequestError):
        validate_range(start, end, today=date(2026, 11, 25), earliest=date(1900, 1, 1))
