from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from weather_risk.catalog import HubCatalog, Region, load_catalog
from weather_risk.config import PROJECT_ROOT
from weather_risk.data.errors import AmbiguousHubError, UnsupportedHubError

HUBS = PROJECT_ROOT / "config" / "hubs.yaml"


@pytest.fixture(scope="module")
def catalog() -> HubCatalog:
    return load_catalog(HUBS)


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(HUBS.read_text())


def test_catalog_has_12_illustrative_hubs_with_required_scenario_hubs(catalog):
    assert catalog.illustrative is True
    assert len(catalog.hubs) == 12
    for required in ("miami_fl", "houston_tx", "denver_co", "dallas_tx"):
        assert required in catalog.ids


def test_midwest_has_enough_hubs_for_a_regional_ranking(catalog):
    midwest = catalog.in_region(Region.MIDWEST)
    assert len(midwest) == 6
    assert {h.state for h in midwest} <= {"IL", "IN", "OH", "MI", "MN", "MO"}


def test_fips_are_strings_and_preserve_leading_zero(catalog):
    denver = catalog.get("denver_co")
    assert denver.hazard_county.fips == "08031"
    assert isinstance(denver.noaa_station.county_fips, str)


def test_station_county_differences_are_recorded_with_assumptions(catalog):
    differing = {h.id for h in catalog.hubs if h.station_county_differs}
    assert differing == {"chicago_il", "kansas_city_mo", "atlanta_ga"}
    for hub_id in differing:
        assert catalog.get(hub_id).assumptions, f"{hub_id} must document the mismatch"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Dallas", "dallas_tx"),
        ("dallas hub", "dallas_tx"),
        ("DFW", "dallas_tx"),
        ("Dallas-Fort Worth", "dallas_tx"),
        ("Kansas City, MO", "kansas_city_mo"),
        ("Twin Cities", "minneapolis_mn"),
        ("O'Hare", "chicago_il"),
        ("miami_fl", "miami_fl"),
        ("Houston Hub", "houston_tx"),
        ("  DENVER  ", "denver_co"),
        ("Columbus, Ohio", "columbus_oh"),
    ],
)
def test_resolve_aliases(catalog, text, expected):
    assert catalog.resolve(text).id == expected


@pytest.mark.parametrize("text", ["Boston", "Seattle", "Paris", "", "Springfield"])
def test_unsupported_hubs_raise_with_supported_list(catalog, text):
    with pytest.raises(UnsupportedHubError) as exc:
        catalog.resolve(text)
    assert set(exc.value.supported) == set(catalog.ids)


def test_typo_is_not_silently_resolved_but_suggested(catalog):
    with pytest.raises(UnsupportedHubError) as exc:
        catalog.resolve("Dalas")
    assert exc.value.suggestions == ["dallas_tx"]


@pytest.mark.parametrize(
    "text,candidates",
    [
        ("Texas", {"dallas_tx", "houston_tx"}),
        ("TX", {"dallas_tx", "houston_tx"}),
        ("Midwest", {"chicago_il", "indianapolis_in", "columbus_oh", "detroit_mi",
                     "minneapolis_mn", "kansas_city_mo"}),
        ("Colorado", {"denver_co"}),
    ],
)  # fmt: skip
def test_state_and_region_references_are_ambiguous(catalog, text, candidates):
    with pytest.raises(AmbiguousHubError) as exc:
        catalog.resolve(text)
    assert set(exc.value.candidates) == candidates


def test_duplicate_alias_across_hubs_is_rejected(raw):
    bad = copy.deepcopy(raw)
    bad["hubs"][1]["aliases"].append("chicago")
    with pytest.raises(ValidationError, match="alias"):
        HubCatalog.model_validate(bad)


def test_unquoted_numeric_fips_is_rejected(raw):
    bad = copy.deepcopy(raw)
    bad["hubs"][6]["hazard_county"]["fips"] = 8031  # YAML int would lose the leading zero
    with pytest.raises(ValidationError, match="5-digit"):
        HubCatalog.model_validate(bad)


def test_state_region_mismatch_is_rejected(raw):
    bad = copy.deepcopy(raw)
    bad["hubs"][0]["region"] = "South"
    with pytest.raises(ValidationError, match="not in region"):
        HubCatalog.model_validate(bad)


def test_catalog_must_be_marked_illustrative(raw):
    bad = copy.deepcopy(raw)
    bad["illustrative"] = False
    with pytest.raises(ValidationError, match="illustrative"):
        HubCatalog.model_validate(bad)


def test_invalid_station_id_rejected(raw):
    bad = copy.deepcopy(raw)
    bad["hubs"][0]["noaa_station"]["id"] = "ORD"
    with pytest.raises(ValidationError, match="station"):
        HubCatalog.model_validate(bad)
