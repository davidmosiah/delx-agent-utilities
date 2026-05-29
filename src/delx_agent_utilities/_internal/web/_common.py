"""Small URL/keyword helpers shared by more than one web domain module."""

from __future__ import annotations

from urllib.parse import urlparse

from .._helpers import _normalize_url


def _origin_from_url(raw: str) -> str:
    normalized = _normalize_url(raw)
    parsed = urlparse(normalized)
    if not parsed.netloc:
        return normalized
    return f"{parsed.scheme}://{parsed.netloc}"


def _domain_from_url_or_origin(raw: str) -> str:
    parsed = urlparse(_normalize_url(raw))
    return (parsed.hostname or str(raw or "").strip()).strip(".").lower()


def _keyword_hits(text: str, patterns: list[str]) -> list[str]:
    lowered = (text or "").lower()
    return [pattern for pattern in patterns if pattern in lowered]
