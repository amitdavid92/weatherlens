"""Committed, reproducible snapshot of raw source responses.

The snapshot stores *raw response bodies* (gzip, deterministic mtime=0) keyed by the same
deterministic request key as the cache, so fallback data goes through exactly the same parsers
and validation as live data. `manifest.json` records query parameters, retrieval times, periods,
dataset versions, content hashes and licensing for every file.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
from datetime import UTC, date, datetime
from pathlib import Path

from weather_risk.data.http import SourceRequest
from weather_risk.data.models import SnapshotEntry, SnapshotManifest, SourceId

log = logging.getLogger("weather_risk.snapshot")

MANIFEST_NAME = "manifest.json"
LICENSES = {
    SourceId.NOAA_GHCN_DAILY.value: "Public domain (U.S. Government work, NOAA NCEI). "
    "Redistribution permitted.",
    SourceId.FEMA_NRI.value: "Public domain (U.S. Government work, FEMA). Redistribution permitted.",
    SourceId.OPEN_METEO_ARCHIVE.value: "CC BY 4.0 — redistribution permitted with attribution: "
    "'Weather data by Open-Meteo.com' (ERA5, Copernicus/ECMWF).",
}


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class SnapshotStore:
    """Read-only access to a snapshot directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._entries: dict[str, SnapshotEntry] = {}
        self.manifest: SnapshotManifest | None = None
        path = directory / MANIFEST_NAME
        if path.exists():
            self.manifest = SnapshotManifest.model_validate_json(path.read_text())
            self._entries = {e.key: e for e in self.manifest.entries}

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, req: SourceRequest) -> tuple[bytes, SnapshotEntry] | None:
        entry = self._entries.get(req.key)
        if entry is None:
            return None
        path = self.directory / entry.file
        try:
            body = gzip.decompress(path.read_bytes())
        except (OSError, EOFError) as exc:
            log.warning("snapshot_unreadable", extra={"file": entry.file, "error": str(exc)})
            return None
        if _sha256(body) != entry.body_sha256:
            log.warning("snapshot_hash_mismatch", extra={"file": entry.file})
            return None
        return body, entry

    def verify(self) -> list[str]:
        """Return a list of problems (empty == all files present and hashes match)."""
        problems = []
        for e in self._entries.values():
            path = self.directory / e.file
            if not path.exists():
                problems.append(f"missing file {e.file}")
                continue
            try:
                body = gzip.decompress(path.read_bytes())
            except (OSError, EOFError):
                problems.append(f"unreadable {e.file}")
                continue
            if _sha256(body) != e.body_sha256:
                problems.append(f"hash mismatch {e.file}")
        return problems


class SnapshotWriter:
    def __init__(self, directory: Path, *, description: str, generator: str) -> None:
        self.directory = directory
        self.description = description
        self.generator = generator
        self.entries: list[SnapshotEntry] = []

    def add(
        self,
        req: SourceRequest,
        body: bytes,
        *,
        relative_file: str,
        retrieved_at: datetime,
        dataset_version: str | None = None,
    ) -> SnapshotEntry:
        path = self.directory / relative_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))
        period = req.period
        entry = SnapshotEntry(
            key=req.key,
            file=relative_file,
            source_id=SourceId(req.source_id),
            url=req.url,
            params=req.params,
            retrieved_at=retrieved_at,
            dataset_version=dataset_version,
            period_start=date.fromisoformat(period[0]) if period else None,
            period_end=date.fromisoformat(period[1]) if period else None,
            location_id=req.location_id,
            body_sha256=_sha256(body),
            bytes_uncompressed=len(body),
        )
        self.entries = [e for e in self.entries if e.key != entry.key] + [entry]
        return entry

    def write_manifest(self) -> Path:
        manifest = SnapshotManifest(
            generated_at=datetime.now(UTC),
            generator=self.generator,
            description=self.description,
            licenses=LICENSES,
            entries=sorted(self.entries, key=lambda e: e.file),
        )
        path = self.directory / MANIFEST_NAME
        path.write_text(manifest.model_dump_json(indent=2) + "\n")
        return path
