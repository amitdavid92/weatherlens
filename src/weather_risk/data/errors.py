"""Typed errors for the data layer. Callers can branch on type instead of parsing messages."""

from __future__ import annotations


class DataLayerError(Exception):
    """Base class for all data-layer errors."""


class InvalidRequestError(DataLayerError, ValueError):
    """The caller asked for something invalid (bad station id, inverted date range, ...)."""


class ExternalDataError(DataLayerError):
    """An external source failed or returned something we cannot use."""

    def __init__(self, source_id: str, message: str) -> None:
        super().__init__(f"[{source_id}] {message}")
        self.source_id = source_id


class SourceTimeoutError(ExternalDataError):
    """The source did not respond in time (after retries)."""


class RateLimitedError(ExternalDataError):
    """The source returned HTTP 429 (after retries)."""


class SourceHTTPError(ExternalDataError):
    """The source returned a non-success HTTP status (after retries for 5xx)."""

    def __init__(self, source_id: str, status_code: int, message: str) -> None:
        super().__init__(source_id, f"HTTP {status_code}: {message}")
        self.status_code = status_code


class InvalidResponseError(ExternalDataError):
    """The response could not be parsed or failed validation (schema, duplicates, counts)."""


class DatasetVersionMismatchError(DataLayerError):
    """Two datasets that must share a version (e.g. NRI county record and reference) do not."""


class DataUnavailableError(DataLayerError):
    """No live, cached, or snapshot data could satisfy the request. Never silently filled."""

    def __init__(self, what: str, causes: list[str]) -> None:
        detail = "; ".join(causes) if causes else "no source attempted"
        super().__init__(f"Data unavailable for {what}: {detail}")
        self.what = what
        self.causes = causes


class UnsupportedHubError(DataLayerError, LookupError):
    def __init__(self, query: str, suggestions: list[str], supported: list[str]) -> None:
        msg = f"'{query}' is not a supported hub."
        if suggestions:
            msg += f" Did you mean: {', '.join(suggestions)}?"
        super().__init__(msg)
        self.query = query
        self.suggestions = suggestions
        self.supported = supported


class AmbiguousHubError(DataLayerError, LookupError):
    def __init__(self, query: str, candidates: list[str]) -> None:
        super().__init__(f"'{query}' is ambiguous; candidates: {', '.join(candidates)}")
        self.query = query
        self.candidates = candidates
