"""Illustrative hub catalog: loading, validation and strict name resolution.

Resolution is exact-match only (after normalization) against id, display name, city,
"city state" and aliases. No fuzzy auto-resolution: unknown names raise UnsupportedHubError
(with suggestions), and names matching several hubs or a whole state/region raise
AmbiguousHubError.
"""

from __future__ import annotations

import difflib
import re
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from weather_risk.data.adapters.noaa_ghcn import STATION_RE
from weather_risk.data.errors import AmbiguousHubError, UnsupportedHubError


class Region(StrEnum):
    """US Census Bureau regions."""

    MIDWEST = "Midwest"
    NORTHEAST = "Northeast"
    SOUTH = "South"
    WEST = "West"


CENSUS_REGION_STATES: dict[Region, frozenset[str]] = {
    Region.MIDWEST: frozenset("IL IN IA KS MI MN MO NE ND OH SD WI".split()),
    Region.NORTHEAST: frozenset("CT ME MA NH RI VT NJ NY PA".split()),
    Region.SOUTH: frozenset("DE DC FL GA MD NC SC VA WV AL KY MS TN AR LA OK TX".split()),
    Region.WEST: frozenset("AZ CO ID MT NV NM UT WY AK CA HI OR WA".split()),
}

STATE_NAMES = {
    "IL": "illinois", "IN": "indiana", "OH": "ohio", "MI": "michigan", "MN": "minnesota",
    "MO": "missouri", "CO": "colorado", "TX": "texas", "FL": "florida", "GA": "georgia",
    "TN": "tennessee",
}  # fmt: skip


def _fips(v: str) -> str:
    if not isinstance(v, str) or len(v) != 5 or not v.isdigit():
        raise ValueError(f"FIPS must be a 5-digit string (quote it in YAML), got {v!r}")
    return v


class County(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    fips: str

    @field_validator("fips", mode="before")
    @classmethod
    def _check_fips(cls, v: object) -> str:
        return _fips(v)  # type: ignore[arg-type]


class Station(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    name: str
    latitude: float
    longitude: float
    county_name: str
    county_fips: str

    @field_validator("id")
    @classmethod
    def _station(cls, v: str) -> str:
        if not STATION_RE.match(v):
            raise ValueError(f"invalid GHCN station id {v!r}")
        return v

    @field_validator("county_fips", mode="before")
    @classmethod
    def _check_fips(cls, v: object) -> str:
        return _fips(v)  # type: ignore[arg-type]


class Hub(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    city: str
    state: str
    region: Region
    latitude: float = Field(ge=18, le=72)  # US bounds incl. AK/HI-ish; catalog is CONUS
    longitude: float = Field(ge=-180, le=-60)
    timezone: str
    hazard_county: County
    noaa_station: Station
    aliases: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError(f"hub id must be snake_case, got {v!r}")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> Hub:
        if self.state not in CENSUS_REGION_STATES[self.region]:
            raise ValueError(f"{self.id}: state {self.state} is not in region {self.region}")
        if not self.hazard_county.fips.startswith(_STATE_FIPS[self.state]):
            raise ValueError(
                f"{self.id}: county FIPS {self.hazard_county.fips} not in {self.state}"
            )
        return self

    @property
    def station_county_differs(self) -> bool:
        return self.noaa_station.county_fips != self.hazard_county.fips


_STATE_FIPS = {
    "IL": "17", "IN": "18", "OH": "39", "MI": "26", "MN": "27", "MO": "29", "CO": "08",
    "TX": "48", "FL": "12", "GA": "13", "TN": "47",
}  # fmt: skip


def normalize(text: str) -> str:
    t = text.casefold().strip()
    t = t.replace("’", "'")
    t = re.sub(r"[.,;:!?()\"]", " ", t)
    t = re.sub(r"\b(hub|distribution center|dc|the)\b", " ", t)
    t = t.replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", t).strip()


class HubCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    catalog_version: str
    illustrative: bool
    hubs: list[Hub]

    @model_validator(mode="after")
    def _unique(self) -> HubCatalog:
        if not self.illustrative:
            raise ValueError("catalog must be explicitly marked illustrative")
        ids = [h.id for h in self.hubs]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate hub ids")
        seen: dict[str, str] = {}
        for h in self.hubs:
            for key in _keys_for(h):
                if key in seen and seen[key] != h.id:
                    raise ValueError(f"alias {key!r} maps to both {seen[key]} and {h.id}")
                seen[key] = h.id
        return self

    # ---------------------------------------------------------------- lookup
    def get(self, hub_id: str) -> Hub:
        for h in self.hubs:
            if h.id == hub_id:
                return h
        raise UnsupportedHubError(hub_id, [], self.ids)

    @property
    def ids(self) -> list[str]:
        return [h.id for h in self.hubs]

    def in_region(self, region: Region | str) -> list[Hub]:
        r = Region(region) if not isinstance(region, Region) else region
        return [h for h in self.hubs if h.region is r]

    def resolve(self, text: str) -> Hub:
        q = normalize(text)
        if not q:
            raise UnsupportedHubError(text, [], self.ids)
        index = self._index()
        if q in index:
            return self.get(index[q])

        # Whole-state / whole-region references are ambiguous when they cover >1 hub.
        group = self._group_match(q)
        if group is not None:
            if len(group) == 1:
                raise AmbiguousHubError(text, [group[0].id])  # a state is not a hub name
            raise AmbiguousHubError(text, [h.id for h in group])

        suggestions = difflib.get_close_matches(q, list(index), n=3, cutoff=0.75)
        suggested_ids = sorted({index[s] for s in suggestions})
        raise UnsupportedHubError(text, suggested_ids, self.ids)

    def _index(self) -> dict[str, str]:
        return {k: h.id for h in self.hubs for k in _keys_for(h)}

    def _group_match(self, q: str) -> list[Hub] | None:
        for r in Region:
            if q == normalize(r.value):
                return self.in_region(r)
        for abbrev, name in STATE_NAMES.items():
            if q in (abbrev.casefold(), name):
                return [h for h in self.hubs if h.state == abbrev]
        return None


def _keys_for(h: Hub) -> set[str]:
    keys = {
        normalize(h.id.replace("_", " ")),
        normalize(h.display_name),
        normalize(h.city),
        normalize(f"{h.city} {h.state}"),
        normalize(f"{h.city} {STATE_NAMES.get(h.state, '')}"),
    }
    keys |= {normalize(a) for a in h.aliases}
    return {k for k in keys if k}


def load_catalog(path: Path) -> HubCatalog:
    with path.open() as f:
        raw = yaml.safe_load(f)
    return HubCatalog.model_validate(raw)
