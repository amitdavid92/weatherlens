"""Record small, real API responses as offline test fixtures (run manually; needs network).

    uv run python scripts/record_fixtures.py

Fixtures are raw response bodies exactly as returned by the sources, so the offline tests run
the real parsers against real data. Each fixture is small (a few days / a few counties).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from weather_risk.data.adapters import fema_nri, noaa_ghcn, open_meteo
from weather_risk.data.http import USER_AGENT, SourceRequest

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def fetch(req: SourceRequest) -> bytes:
    r = httpx.get(req.url, params=req.params, timeout=60, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.content


def save(name: str, req: SourceRequest, body: bytes) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.body").write_bytes(body)
    (OUT / f"{name}.request.json").write_text(
        json.dumps({"source_id": req.source_id, "url": req.url, "params": req.params,
                    "location_id": req.location_id}, indent=2) + "\n"
    )  # fmt: skip
    print(f"saved {name} ({len(body)} bytes)")


def main() -> None:
    # NOAA: Denver trace days (Jan 24, 26) + 104 mm snow (Jan 25)
    req = noaa_ghcn.build_request("USW00003017", date(2025, 1, 24), date(2025, 1, 26))
    save("noaa_denver_2025-01-24_26", req, fetch(req))
    # NOAA: Denver 2025-05-21 has no SNOW value (missing)
    req = noaa_ghcn.build_request("USW00003017", date(2025, 5, 20), date(2025, 5, 22))
    save("noaa_denver_2025-05-20_22", req, fetch(req))
    # NOAA: Minneapolis across Feb 29 2024 (leap day, sub-zero temperatures)
    req = noaa_ghcn.build_request("USW00014922", date(2024, 2, 27), date(2024, 3, 2))
    save("noaa_msp_2024-02-27_03-02", req, fetch(req))
    # NOAA: Miami, a month where SNOW is often unreported
    req = noaa_ghcn.build_request("USW00012839", date(2019, 1, 1), date(2019, 1, 10))
    save("noaa_miami_2019-01-01_10", req, fetch(req))
    # Open-Meteo ERA5: Denver Jan 1-5 2025
    req = open_meteo.build_request(39.73915, -104.9847, date(2025, 1, 1), date(2025, 1, 5),
                                   "America/Denver")  # fmt: skip
    save("openmeteo_denver_2025-01-01_05", req, fetch(req))
    # NRI: hub counties for the four scenarios
    for fips in ["12086", "48201", "08031", "48113", "17031"]:
        req = fema_nri.build_county_request(fips)
        save(f"nri_county_{fips}", req, fetch(req))
    # NRI: count + a tiny 2-page pagination sample (page size 3) for pagination tests
    req = fema_nri.build_count_request()
    save("nri_count", req, fetch(req))
    for offset in (0, 3):
        req = fema_nri.build_page_request(offset, page_size=3)
        save(f"nri_page_size3_offset{offset}", req, fetch(req))
    # NRI: real edge-state records — a territory (Insufficient Data) and an HRCN observed-zero
    for name, where in [
        ("nri_edge_territory", "STATEABBRV='GU' AND TRND_EALR='Insufficient Data'"),
        ("nri_edge_alaska_hwav", "STATEABBRV='AK' AND HWAV_EALR='Insufficient Data'"),
        ("nri_edge_hrcn_zero", "HRCN_AFREQ = 0"),
    ]:
        req = SourceRequest(
            source_id=fema_nri.SOURCE,
            url=fema_nri.BASE_URL,
            params={
                "where": where,
                "outFields": ",".join(fema_nri.OUT_FIELDS),
                "returnGeometry": "false",
                "orderByFields": "STCOFIPS ASC",
                "resultRecordCount": "1",
                "f": "json",
            },  # fmt: skip
        )
        save(name, req, fetch(req))


if __name__ == "__main__":
    main()
