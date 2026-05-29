"""HTML extraction tools: page snapshot, open graph, links, feeds, forms, contacts."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from .._helpers import (
    _HTMLSnapshot,
    _fetch_text_response,
    _normalize_phone,
    _normalize_url,
    _parse_int,
    _social_label,
)


async def _page_extract(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    response, error = await _fetch_text_response(url, timeout_s=timeout_s)
    if error or response is None:
        return {"url": _normalize_url(url), "reachable": False, "error": error or "fetch failed"}

    parser = _HTMLSnapshot()
    parser.feed(response.text or "")
    text_excerpt = parser.text_excerpt[:500]
    description = parser.meta.get("description") or parser.meta.get("og:description") or parser.meta.get("twitter:description") or ""
    return {
        "url": _normalize_url(url),
        "final_url": str(response.url),
        "status": int(response.status_code),
        "reachable": 200 <= int(response.status_code) < 400,
        "content_type": str(response.headers.get("content-type", "")),
        "title": parser.title,
        "description": description,
        "canonical_url": parser.canonical_url or str(response.url),
        "headings": parser.headings[:10],
        "text_excerpt": text_excerpt,
    }


async def _open_graph(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    response, error = await _fetch_text_response(url, timeout_s=timeout_s)
    if error or response is None:
        return {"url": _normalize_url(url), "reachable": False, "error": error or "fetch failed"}

    parser = _HTMLSnapshot()
    parser.feed(response.text or "")
    og = {k: v for k, v in parser.meta.items() if k.startswith("og:")}
    twitter = {k: v for k, v in parser.meta.items() if k.startswith("twitter:")}
    return {
        "url": _normalize_url(url),
        "final_url": str(response.url),
        "status": int(response.status_code),
        "reachable": 200 <= int(response.status_code) < 400,
        "title": og.get("og:title") or twitter.get("twitter:title") or parser.title,
        "description": og.get("og:description") or twitter.get("twitter:description") or parser.meta.get("description", ""),
        "image": og.get("og:image") or twitter.get("twitter:image") or "",
        "site_name": og.get("og:site_name") or "",
        "open_graph": og,
        "twitter": twitter,
    }


async def _links_extract(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
        limit = _parse_int(args.get("limit", 25), default=25)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer"}
    limit = min(100, max(1, limit))
    response, error = await _fetch_text_response(url, timeout_s=timeout_s)
    if error or response is None:
        return {"url": _normalize_url(url), "reachable": False, "error": error or "fetch failed"}

    parser = _HTMLSnapshot()
    parser.feed(response.text or "")
    base = str(response.url)
    seen: set[str] = set()
    links: list[dict[str, str]] = []
    base_host = urlparse(base).netloc.lower()
    internal = 0
    external = 0
    for href in parser.links:
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        resolved = urljoin(base, href)
        if resolved in seen:
            continue
        seen.add(resolved)
        host = urlparse(resolved).netloc.lower()
        same_host = bool(host and host == base_host)
        if same_host:
            internal += 1
        else:
            external += 1
        links.append({"url": resolved, "kind": "internal" if same_host else "external"})
        if len(links) >= limit:
            break
    return {
        "url": _normalize_url(url),
        "final_url": base,
        "status": int(response.status_code),
        "reachable": 200 <= int(response.status_code) < 400,
        "total_links": len(links),
        "internal_links": internal,
        "external_links": external,
        "links": links,
    }


async def _feed_discover(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    response, error = await _fetch_text_response(url, timeout_s=timeout_s)
    if error or response is None:
        return {"url": _normalize_url(url), "reachable": False, "error": error or "fetch failed"}
    parser = _HTMLSnapshot()
    parser.feed(response.text or "")
    base = str(response.url)
    feeds: list[dict[str, str]] = []
    seen: set[str] = set()
    for feed in parser.feed_links:
        resolved = urljoin(base, feed.get("url", ""))
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        feeds.append(
            {
                "url": resolved,
                "type": feed.get("type", ""),
                "title": feed.get("title", ""),
            }
        )
    return {
        "url": _normalize_url(url),
        "final_url": base,
        "status": int(response.status_code),
        "reachable": 200 <= int(response.status_code) < 400,
        "feed_count": len(feeds),
        "feeds": feeds,
        "manifest_url": urljoin(base, parser.manifest_url) if parser.manifest_url else "",
    }


async def _forms_extract(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    response, error = await _fetch_text_response(url, timeout_s=timeout_s)
    if error or response is None:
        return {"url": _normalize_url(url), "reachable": False, "error": error or "fetch failed"}
    parser = _HTMLSnapshot()
    parser.feed(response.text or "")
    base = str(response.url)
    forms: list[dict[str, Any]] = []
    for form in parser.forms[:25]:
        forms.append(
            {
                "action": urljoin(base, str(form.get("action") or "")) if form.get("action") else base,
                "method": str(form.get("method") or "GET").upper(),
                "input_count": len(form.get("inputs") or []),
                "inputs": list(form.get("inputs") or []),
            }
        )
    return {
        "url": _normalize_url(url),
        "final_url": base,
        "status": int(response.status_code),
        "reachable": 200 <= int(response.status_code) < 400,
        "form_count": len(forms),
        "forms": forms,
    }


async def _contact_extract(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    response, error = await _fetch_text_response(url, timeout_s=timeout_s)
    if error or response is None:
        return {"url": _normalize_url(url), "reachable": False, "error": error or "fetch failed"}
    parser = _HTMLSnapshot()
    parser.feed(response.text or "")
    base = str(response.url)
    emails: set[str] = set()
    phones: set[str] = set()
    socials: dict[str, str] = {}
    for href in parser.links:
        lowered = href.lower()
        if lowered.startswith("mailto:"):
            emails.add(href.split(":", 1)[1].split("?", 1)[0].strip())
        elif lowered.startswith("tel:"):
            phones.add(_normalize_phone(href.split(":", 1)[1]))
        else:
            resolved = urljoin(base, href)
            label = _social_label(resolved)
            if label and label not in socials:
                socials[label] = resolved
    for email in re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", response.text or "", flags=re.IGNORECASE):
        emails.add(email.lower())
    for phone_match in re.findall(r"\+?\d[\d\s().-]{6,}\d", response.text or ""):
        phones.add(_normalize_phone(phone_match))
    return {
        "url": _normalize_url(url),
        "final_url": base,
        "status": int(response.status_code),
        "reachable": 200 <= int(response.status_code) < 400,
        "emails": sorted(emails)[:25],
        "phone_numbers": sorted(phones)[:25],
        "social_links": socials,
        "manifest_url": urljoin(base, parser.manifest_url) if parser.manifest_url else "",
    }
