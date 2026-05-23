"""URL canonicalization helpers.

A small, deterministic, dependency-free toolbox for cleaning URLs before
caching, deduplication or analytics. Strips common tracking parameters
(``utm_*``, ``gclid``, ``fbclid``, ``mc_eid``, ``ref``, ``ref_src``),
lowercases the host, removes default ports, drops a trailing fragment that
points to no real anchor (``#``) and ensures a scheme.
"""

from __future__ import annotations

from typing import Iterable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

# Tracking parameters removed by default. Lowercase, exact match unless the key
# starts with ``utm_`` (handled by prefix).
_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "gclid",
        "dclid",
        "fbclid",
        "msclkid",
        "yclid",
        "mc_eid",
        "mc_cid",
        "ref",
        "ref_src",
        "ref_url",
        "_hsenc",
        "_hsmi",
        "vero_conv",
        "vero_id",
        "igshid",
    }
)

_DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}


def url_canonicalize(
    url: str,
    *,
    extra_tracking_params: Iterable[str] | None = None,
    keep_fragment: bool = False,
) -> str:
    """Return a canonical form of ``url``.

    - Lowercases scheme and host.
    - Adds ``https://`` if no scheme is present.
    - Strips default ports (``:80`` for http, ``:443`` for https).
    - Removes tracking parameters (``utm_*``, ``gclid``, ``fbclid``,
      ``mc_eid``, ``ref``, ``ref_src``, and friends).
    - Sorts the remaining query parameters for stable output.
    - Drops empty fragment (``#``); set ``keep_fragment=True`` to preserve
      meaningful anchors.

    Raises :class:`TypeError` if ``url`` is not a string and :class:`ValueError`
    if it is empty after trimming.
    """

    if not isinstance(url, str):
        raise TypeError("url must be a string")
    raw = url.strip()
    if not raw:
        raise ValueError("url must not be empty")

    # Ensure scheme so urlsplit puts the host in netloc, not path.
    if "://" not in raw:
        raw = "https://" + raw

    parts = urlsplit(raw)
    scheme = parts.scheme.lower() or "https"

    host = (parts.hostname or "").lower()
    if not host:
        # Nothing useful to canonicalize; return scheme-prefixed input.
        return raw

    userinfo = ""
    if parts.username:
        userinfo = quote(parts.username, safe="")
        if parts.password:
            userinfo += ":" + quote(parts.password, safe="")
        userinfo += "@"

    port = parts.port
    if port is not None and _DEFAULT_PORTS.get(scheme) == port:
        port = None

    netloc = userinfo + host + (f":{port}" if port else "")

    path = parts.path or "/"

    drop = set(_TRACKING_PARAMS)
    if extra_tracking_params:
        drop.update(p.lower() for p in extra_tracking_params)

    kept_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lk = key.lower()
        if lk in drop:
            continue
        if lk.startswith("utm_"):
            continue
        kept_pairs.append((key, value))
    kept_pairs.sort()
    query = urlencode(kept_pairs)

    fragment = parts.fragment if keep_fragment else ""

    return urlunsplit((scheme, netloc, path, query, fragment))


__all__ = ["url_canonicalize"]
