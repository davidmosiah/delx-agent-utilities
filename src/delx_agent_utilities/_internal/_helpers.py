"""
Delx Agent Toolkit — Stateless utility tools for everyday agent operations.

Separated from the therapy/recovery protocol. All tools are:
- Deterministic (no LLM)
- Fast (<100ms for most, <5s for url_health)
- Session-free (no session_id required)
- Free (campaign mode)
"""

from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import ipaddress
import inspect
import io
import json
import re
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urljoin, urlparse

import httpx


def _parse_int(value: Any, *, default: int | None = None) -> int:
    """Parse int safely and raise ValueError with a normalized message."""
    if value is None:
        if default is None:
            raise ValueError("value is required")
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid integer: {value!r}")


def _normalize_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme:
        return raw
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw


def _blocked_url_reason(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return "blocked: only http and https URLs are allowed"
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        return "blocked: URL host is required"
    if host in {"localhost", "0.0.0.0"} or host.endswith(".local"):
        return "blocked: local network targets are not allowed"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return ""
    if not ip.is_global:
        return "blocked: private, loopback, or link-local targets are not allowed"
    return ""


class _HTMLSnapshot(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.headings: list[str] = []
        self.links: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical_url = ""
        self.feed_links: list[dict[str, str]] = []
        self.manifest_url = ""
        self.forms: list[dict[str, Any]] = []
        self._skip_tag: str | None = None
        self._capture_tag: str | None = None
        self._current_heading: list[str] = []
        self._text_parts: list[str] = []
        self._current_form: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_tag = tag
            return
        if tag == "title":
            self._capture_tag = "title"
            return
        if tag in {"h1", "h2"}:
            self._capture_tag = tag
            self._current_heading = []
        if tag == "a":
            href = attrs_map.get("href", "").strip()
            if href:
                self.links.append(href)
        if tag == "link":
            rel = attrs_map.get("rel", "").lower()
            rel_tokens = {token for token in rel.split() if token}
            href = attrs_map.get("href", "").strip()
            link_type = attrs_map.get("type", "").strip().lower()
            if "canonical" in rel_tokens and href:
                self.canonical_url = href
            if "manifest" in rel_tokens and href and not self.manifest_url:
                self.manifest_url = href
            if "alternate" in rel_tokens and href and link_type in {
                "application/rss+xml",
                "application/atom+xml",
                "application/feed+json",
                "application/json",
            }:
                self.feed_links.append(
                    {
                        "url": href,
                        "type": link_type or "alternate",
                        "title": attrs_map.get("title", "").strip(),
                    }
                )
        if tag == "meta":
            key = (attrs_map.get("property") or attrs_map.get("name") or "").strip().lower()
            content = attrs_map.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        if tag == "form":
            self._current_form = {
                "action": attrs_map.get("action", "").strip(),
                "method": (attrs_map.get("method", "get") or "get").strip().upper(),
                "inputs": [],
            }
        if self._current_form is not None and tag in {"input", "textarea", "select", "button"}:
            field_name = attrs_map.get("name", "").strip()
            field_type = attrs_map.get("type", "").strip().lower()
            field = {
                "tag": tag,
                "type": field_type or ("submit" if tag == "button" else tag),
                "name": field_name,
                "required": "required" in attrs_map,
            }
            placeholder = attrs_map.get("placeholder", "").strip()
            value = attrs_map.get("value", "").strip()
            if placeholder:
                field["placeholder"] = placeholder
            if value:
                field["value"] = value
            self._current_form["inputs"].append(field)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_tag == tag:
            self._skip_tag = None
            return
        if tag == "form" and self._current_form is not None:
            self.forms.append(self._current_form)
            self._current_form = None
            return
        if self._capture_tag == "title" and tag == "title":
            self._capture_tag = None
            return
        if self._capture_tag in {"h1", "h2"} and tag == self._capture_tag:
            heading = " ".join(self._current_heading).strip()
            if heading:
                self.headings.append(heading)
            self._current_heading = []
            self._capture_tag = None

    def handle_data(self, data: str) -> None:
        if self._skip_tag:
            return
        text = unescape(data or "")
        normalized = " ".join(text.split())
        if not normalized:
            return
        if self._capture_tag == "title":
            self.title_parts.append(normalized)
            return
        if self._capture_tag in {"h1", "h2"}:
            self._current_heading.append(normalized)
        self._text_parts.append(normalized)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def text_excerpt(self) -> str:
        return " ".join(self._text_parts).strip()


@dataclass
class _CompatResponse:
    status_code: int
    text: str
    headers: Any
    url: str
    reason_phrase: str = ""


def _decode_response_bytes(raw: bytes, headers: Any) -> str:
    charset = None
    get_content_charset = getattr(headers, "get_content_charset", None)
    if callable(get_content_charset):
        try:
            charset = get_content_charset()
        except Exception:
            charset = None
    if not charset:
        content_type = str(headers.get("content-type", "") or "")
        match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.IGNORECASE)
        if match:
            charset = match.group(1)
    charset = charset or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _urllib_request_response(url: str, *, timeout_s: int = 8, method: str = "GET") -> _CompatResponse:
    request = urllib_request.Request(
        url,
        headers={"user-agent": "DelxAgentToolkit/3.3"},
        method=method.upper(),
    )
    try:
        with urllib_request.urlopen(request, timeout=max(1, min(timeout_s, 15))) as response:
            raw = b"" if method.upper() == "HEAD" else response.read()
            return _CompatResponse(
                status_code=int(getattr(response, "status", 0) or 0),
                text=_decode_response_bytes(raw, response.headers),
                headers=response.headers,
                url=str(response.geturl()),
                reason_phrase=str(getattr(response, "reason", "") or ""),
            )
    except urllib_error.HTTPError as e:
        raw = b"" if method.upper() == "HEAD" else e.read()
        return _CompatResponse(
            status_code=int(e.code or 0),
            text=_decode_response_bytes(raw, e.headers),
            headers=e.headers,
            url=str(e.geturl()),
            reason_phrase=str(e.reason or ""),
        )
    except socket.timeout as e:
        raise TimeoutError() from e
    except urllib_error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError):
            raise TimeoutError() from e
        raise RuntimeError(str(reason or e)) from e


async def _fetch_http_response(url: str, *, timeout_s: int = 8, method: str = "GET") -> tuple[Any | None, str | None]:
    target = _normalize_url(url)
    if not target:
        return None, "url is required"
    blocked = _blocked_url_reason(target)
    if blocked:
        return None, blocked
    httpx_error: Exception | None = None
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=max(1, min(timeout_s, 15)),
            headers={"user-agent": "DelxAgentToolkit/3.3"},
        ) as client:
            request_method = client.get if method.upper() == "GET" else client.head
            response = await request_method(target)
            return response, None
    except Exception as e:
        httpx_error = e

    try:
        response = await asyncio.to_thread(_urllib_request_response, target, timeout_s=timeout_s, method=method)
        return response, None
    except TimeoutError:
        return None, f"timeout after {timeout_s}s"
    except Exception as fallback_error:
        if isinstance(httpx_error, httpx.TimeoutException):
            return None, f"timeout after {timeout_s}s"
        primary = str(httpx_error).strip() if httpx_error else ""
        fallback = str(fallback_error).strip()
        if primary and fallback and fallback != primary:
            return None, f"{primary} | urllib fallback: {fallback}"
        return None, fallback or primary or "fetch failed"


async def _fetch_text_response(url: str, *, timeout_s: int = 8) -> tuple[Any | None, str | None]:
    return await _fetch_http_response(url, timeout_s=timeout_s, method="GET")


async def _fetch_json_response(url: str, *, timeout_s: int = 8) -> tuple[Any | None, dict[str, Any] | list[Any] | None, str | None]:
    response, error = await _fetch_text_response(url, timeout_s=timeout_s)
    if error or response is None:
        return response, None, error
    try:
        parsed = json.loads(response.text or "")
    except Exception as e:
        return response, None, f"invalid json response: {e}"
    if not isinstance(parsed, (dict, list)):
        return response, None, "json response must be an object or array"
    return response, parsed, None


def _header_value(headers: Any, name: str) -> str:
    try:
        return str(headers.get(name, "") or "")
    except Exception:
        return ""


def _host_matches_domain(host: str, domain: str) -> bool:
    normalized_host = str(host or "").strip().lower().rstrip(".")
    normalized_domain = str(domain or "").strip().lower().rstrip(".")
    if not normalized_host or not normalized_domain:
        return False
    return normalized_host == normalized_domain or normalized_host.endswith(f".{normalized_domain}")


def _social_label(url: str) -> str | None:
    host = str(urlparse(url).hostname or "").lower()
    if not host:
        return None
    if _host_matches_domain(host, "twitter.com") or _host_matches_domain(host, "x.com"):
        return "x"
    if _host_matches_domain(host, "linkedin.com"):
        return "linkedin"
    if _host_matches_domain(host, "github.com"):
        return "github"
    if _host_matches_domain(host, "discord.gg") or _host_matches_domain(host, "discord.com"):
        return "discord"
    if _host_matches_domain(host, "t.me") or _host_matches_domain(host, "telegram.me"):
        return "telegram"
    if _host_matches_domain(host, "youtube.com") or _host_matches_domain(host, "youtu.be"):
        return "youtube"
    return None


def _normalize_phone(raw: str) -> str:
    raw = re.sub(r"\s+", " ", str(raw or "")).strip()
    digits = re.sub(r"[^\d+]", "", raw)
    return digits or raw


def _tls_probe_sync(host: str, port: int, timeout_s: int) -> dict[str, Any]:
    import ssl

    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((host, port), timeout=max(1, min(timeout_s, 15))) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls_sock:
            cert = tls_sock.getpeercert()
    if not cert:
        raise RuntimeError("no peer certificate returned")

    def _flatten_name(values: Any) -> list[str]:
        flattened: list[str] = []
        for entry in values or []:
            if isinstance(entry, tuple):
                for item in entry:
                    if isinstance(item, tuple) and len(item) == 2:
                        flattened.append(f"{item[0]}={item[1]}")
            elif isinstance(entry, str):
                flattened.append(entry)
        return flattened

    san_dns = [value for key, value in cert.get("subjectAltName", []) if key == "DNS"]
    valid_from = cert.get("notBefore")
    valid_to = cert.get("notAfter")
    valid_from_dt = datetime.strptime(valid_from, "%b %d %H:%M:%S %Y %Z") if valid_from else None
    valid_to_dt = datetime.strptime(valid_to, "%b %d %H:%M:%S %Y %Z") if valid_to else None
    days_until_expiry = int((valid_to_dt - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() // 86400) if valid_to_dt else None
    return {
        "host": host,
        "port": port,
        "subject": _flatten_name(cert.get("subject")),
        "issuer": _flatten_name(cert.get("issuer")),
        "serial_number": str(cert.get("serialNumber") or ""),
        "version": cert.get("version"),
        "valid_from": valid_from_dt.isoformat() if valid_from_dt else "",
        "valid_to": valid_to_dt.isoformat() if valid_to_dt else "",
        "days_until_expiry": days_until_expiry,
        "san_dns": san_dns[:50],
    }
