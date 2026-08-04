"""First-party text/network helpers with no external API calls.

All tools are deterministic, session-free, and safe for x402 micro-utils.
"""

from __future__ import annotations

import ipaddress
import re
import secrets
import time
import unicodedata
from datetime import date
from html.parser import HTMLParser
from typing import Any

from ._tools_time_units import _nth_weekday, _observed

# ─── Holidays ─────────────────────────────────────────────────────────

def _us_federal_holiday_items(year: int) -> list[dict[str, str]]:
    labeled = [
        (date(year, 1, 1), "New Year's Day"),
        (_nth_weekday(year, 1, 0, 3), "Birthday of Martin Luther King, Jr."),
        (_nth_weekday(year, 2, 0, 3), "Washington's Birthday"),
        (_nth_weekday(year, 5, 0, -1), "Memorial Day"),
        (date(year, 6, 19), "Juneteenth National Independence Day"),
        (date(year, 7, 4), "Independence Day"),
        (_nth_weekday(year, 9, 0, 1), "Labor Day"),
        (_nth_weekday(year, 10, 0, 2), "Columbus Day"),
        (date(year, 11, 11), "Veterans Day"),
        (_nth_weekday(year, 11, 3, 4), "Thanksgiving Day"),
        (date(year, 12, 25), "Christmas Day"),
    ]
    items = []
    for raw, name in labeled:
        observed = _observed(raw)
        items.append(
            {
                "date": observed.isoformat(),
                "weekday": observed.strftime("%A"),
                "name": name,
                "observed": observed != raw,
            }
        )
    items.sort(key=lambda row: row["date"])
    return items


def _holidays(args: dict) -> dict:
    """List US federal holidays for one year (observed dates)."""
    try:
        year = int(args.get("year") or date.today().year)
    except (TypeError, ValueError):
        return {"error": "invalid_year", "hint": "Pass year as integer e.g. 2026."}
    if year < 1971 or year > 2100:
        return {"error": "year_out_of_range", "min": 1971, "max": 2100}

    calendar = str(args.get("calendar") or "us_federal").strip().lower()
    if calendar not in {"us_federal"}:
        return {
            "error": "unsupported_calendar",
            "calendar": calendar,
            "hint": "Only us_federal is supported in v1.",
        }

    items = _us_federal_holiday_items(year)
    return {
        "schema": "delx/holidays/v1",
        "year": year,
        "calendar": calendar,
        "count": len(items),
        "holidays": items,
        "note": "Observed US federal holiday dates. Not legal advice; confirm with OPM for official schedules.",
    }


# ─── Slugify ──────────────────────────────────────────────────────────

def _slugify(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or args.get("value") or "")
    if not text:
        return {"error": "text_required", "hint": "Pass text to slugify."}
    if len(text) > 4000:
        return {"error": "text_too_long", "max": 4000}

    separator = str(args.get("separator") or "-")[:1] or "-"
    lower = args.get("lowercase")
    if lower is None:
        lower = True
    lower = bool(lower)

    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    if lower:
        ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-zA-Z0-9]+", separator, ascii_text)
    ascii_text = ascii_text.strip(separator)
    max_len = args.get("max_length")
    truncated = False
    if max_len is not None:
        try:
            max_len = int(max_len)
        except (TypeError, ValueError):
            return {"error": "invalid_max_length"}
        if max_len < 1 or max_len > 4000:
            return {"error": "max_length_out_of_range", "min": 1, "max": 4000}
        if len(ascii_text) > max_len:
            ascii_text = ascii_text[:max_len].rstrip(separator)
            truncated = True

    return {
        "schema": "delx/slugify/v1",
        "slug": ascii_text,
        "length": len(ascii_text),
        "truncated": truncated,
        "separator": separator,
        "lowercase": lower,
    }


# ─── MIME lookup ──────────────────────────────────────────────────────

_MIME = {
    "html": "text/html",
    "htm": "text/html",
    "css": "text/css",
    "js": "text/javascript",
    "mjs": "text/javascript",
    "json": "application/json",
    "jsonld": "application/ld+json",
    "xml": "application/xml",
    "txt": "text/plain",
    "md": "text/markdown",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "ico": "image/x-icon",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "zip": "application/zip",
    "gz": "application/gzip",
    "tar": "application/x-tar",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "ttf": "font/ttf",
    "otf": "font/otf",
    "wasm": "application/wasm",
    "yaml": "application/yaml",
    "yml": "application/yaml",
    "toml": "application/toml",
    "py": "text/x-python",
    "go": "text/x-go",
    "rs": "text/x-rust",
    "ts": "text/typescript",
    "tsx": "text/tsx",
    "jsx": "text/jsx",
}


def _mime_lookup(args: dict) -> dict:
    raw = str(args.get("extension") or args.get("filename") or args.get("path") or args.get("input") or "").strip()
    if not raw:
        return {"error": "extension_required", "hint": "Pass extension (pdf) or filename (report.pdf)."}
    name = raw.rsplit("/", 1)[-1]
    if "." in name:
        ext = name.rsplit(".", 1)[-1]
    else:
        ext = name.lstrip(".")
    ext = ext.lower().strip()
    if not ext or len(ext) > 16:
        return {"error": "invalid_extension"}
    mime = _MIME.get(ext)
    return {
        "schema": "delx/mime-lookup/v1",
        "extension": ext,
        "mime_type": mime,
        "known": mime is not None,
        "note": "Static first-party table of common types; not a full IANA database.",
    }


# ─── Color convert ────────────────────────────────────────────────────

def _parse_hex_color(text: str) -> tuple[int, int, int] | None:
    t = text.strip().lstrip("#")
    if len(t) == 3 and re.fullmatch(r"[0-9a-fA-F]{3}", t):
        return tuple(int(c * 2, 16) for c in t)  # type: ignore[return-value]
    if len(t) == 6 and re.fullmatch(r"[0-9a-fA-F]{6}", t):
        return int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)
    return None


def _color_convert(args: dict) -> dict:
    color = str(args.get("color") or args.get("input") or args.get("value") or "").strip()
    if not color:
        return {"error": "color_required", "hint": "Pass #RGB, #RRGGBB, or rgb(r,g,b)."}

    rgb = _parse_hex_color(color)
    if rgb is None:
        m = re.fullmatch(
            r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)",
            color,
            flags=re.I,
        )
        if m:
            r, g, b = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if max(r, g, b) > 255:
                return {"error": "rgb_out_of_range", "max": 255}
            rgb = (r, g, b)
    if rgb is None:
        return {"error": "unsupported_color", "hint": "Use #hex or rgb(r,g,b)."}

    r, g, b = rgb
    hex_out = f"#{r:02x}{g:02x}{b:02x}"
    # HSL
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(rf, gf, bf), min(rf, gf, bf)
    l = (mx + mn) / 2.0
    if mx == mn:
        h = s = 0.0
    else:
        d = mx - mn
        s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == rf:
            h = (gf - bf) / d + (6.0 if gf < bf else 0.0)
        elif mx == gf:
            h = (bf - rf) / d + 2.0
        else:
            h = (rf - gf) / d + 4.0
        h /= 6.0

    return {
        "schema": "delx/color-convert/v1",
        "hex": hex_out,
        "rgb": {"r": r, "g": g, "b": b},
        "rgb_css": f"rgb({r}, {g}, {b})",
        "hsl": {
            "h": round(h * 360.0, 2),
            "s": round(s * 100.0, 2),
            "l": round(l * 100.0, 2),
        },
        "hsl_css": f"hsl({round(h * 360.0, 1)}, {round(s * 100.0, 1)}%, {round(l * 100.0, 1)}%)",
    }


# ─── IP classify ──────────────────────────────────────────────────────

def _ip_classify(args: dict) -> dict:
    raw = str(args.get("ip") or args.get("address") or args.get("input") or "").strip()
    if not raw:
        return {"error": "ip_required"}
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return {"error": "invalid_ip", "hint": "Pass a single IPv4 or IPv6 address."}

    flags = {
        "is_private": ip.is_private,
        "is_loopback": ip.is_loopback,
        "is_link_local": ip.is_link_local,
        "is_multicast": ip.is_multicast,
        "is_reserved": ip.is_reserved,
        "is_unspecified": ip.is_unspecified,
        "is_global": ip.is_global,
    }
    version = ip.version
    return {
        "schema": "delx/ip-classify/v1",
        "ip": str(ip),
        "version": version,
        "classification": (
            "loopback"
            if flags["is_loopback"]
            else "link_local"
            if flags["is_link_local"]
            else "private"
            if flags["is_private"]
            else "multicast"
            if flags["is_multicast"]
            else "reserved"
            if flags["is_reserved"]
            else "global"
            if flags["is_global"]
            else "other"
        ),
        **flags,
        "note": "Classification uses Python stdlib ipaddress rules only; no geolocation.",
    }


# ─── CIDR contains ────────────────────────────────────────────────────

def _cidr_contains(args: dict) -> dict:
    network = str(args.get("network") or args.get("cidr") or args.get("subnet") or "").strip()
    ip_raw = str(args.get("ip") or args.get("address") or "").strip()
    if not network or not ip_raw:
        return {"error": "network_and_ip_required", "hint": "Pass network=CIDR and ip=address."}
    try:
        net = ipaddress.ip_network(network, strict=False)
        ip = ipaddress.ip_address(ip_raw)
    except ValueError as exc:
        return {"error": "invalid_network_or_ip", "detail": str(exc)[:160]}
    if net.version != ip.version:
        return {
            "error": "version_mismatch",
            "network_version": net.version,
            "ip_version": ip.version,
        }
    return {
        "schema": "delx/cidr-contains/v1",
        "network": str(net),
        "ip": str(ip),
        "contains": ip in net,
        "prefixlen": net.prefixlen,
        "num_addresses": net.num_addresses if net.num_addresses < 2**32 else None,
    }


# ─── ULID ─────────────────────────────────────────────────────────────

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_crockford(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def _ulid_generate(args: dict) -> dict:
    try:
        count = int(args.get("count") or 1)
    except (TypeError, ValueError):
        return {"error": "invalid_count"}
    if count < 1 or count > 20:
        return {"error": "count_out_of_range", "min": 1, "max": 20}

    now_ms = int(time.time() * 1000)
    # optional override for tests
    if args.get("timestamp_ms") is not None:
        try:
            now_ms = int(args["timestamp_ms"])
        except (TypeError, ValueError):
            return {"error": "invalid_timestamp_ms"}
    if now_ms < 0 or now_ms >= 2**48:
        return {"error": "timestamp_out_of_range"}

    ulids = []
    for _ in range(count):
        randomness = int.from_bytes(secrets.token_bytes(10), "big")
        # 48-bit time + 80-bit randomness = 128 bits → 26 crockford chars
        value = (now_ms << 80) | randomness
        ulids.append(_encode_crockford(value, 26))

    return {
        "schema": "delx/ulid/v1",
        "count": count,
        "timestamp_ms": now_ms,
        "ulids": ulids,
        "note": "Crockford Base32 ULIDs; not UUIDs.",
    }


# ─── HTML strip ───────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag.lower() in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if data:
            self.parts.append(data)


def _html_strip(args: dict) -> dict:
    html = str(args.get("html") or args.get("input") or args.get("text") or "")
    if not html:
        return {"error": "html_required"}
    if len(html) > 100_000:
        return {"error": "html_too_long", "max": 100_000}

    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        return {"error": "html_parse_failed", "detail": str(exc)[:160]}

    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    max_out = args.get("max_length")
    truncated = False
    if max_out is not None:
        try:
            max_out = int(max_out)
        except (TypeError, ValueError):
            return {"error": "invalid_max_length"}
        if max_out < 1 or max_out > 100_000:
            return {"error": "max_length_out_of_range"}
        if len(text) > max_out:
            text = text[:max_out]
            truncated = True

    return {
        "schema": "delx/html-strip/v1",
        "text": text,
        "length": len(text),
        "truncated": truncated,
        "note": "Best-effort HTML→text; not a browser rendering engine.",
    }
