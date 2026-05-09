"""Async web/network/x402/composite tools (~30 utilities). Roadmap: split into web_extract, network, x402, composite in v0.2.0."""

from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
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

from ._helpers import _HTMLSnapshot, _fetch_http_response, _fetch_json_response, _fetch_text_response, _header_value, _host_matches_domain, _normalize_phone, _normalize_url, _parse_int, _social_label, _tls_probe_sync


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


def _origin_from_url(raw: str) -> str:
    normalized = _normalize_url(raw)
    parsed = urlparse(normalized)
    if not parsed.netloc:
        return normalized
    return f"{parsed.scheme}://{parsed.netloc}"


async def _robots_inspect(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    origin = _origin_from_url(url)
    robots_url = origin.rstrip("/") + "/robots.txt"
    response, error = await _fetch_text_response(robots_url, timeout_s=timeout_s)
    if error or response is None:
        return {"url": origin, "robots_url": robots_url, "reachable": False, "error": error or "fetch failed"}

    sitemaps: list[str] = []
    allow: list[str] = []
    disallow: list[str] = []
    user_agents: list[str] = []
    for raw_line in (response.text or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "sitemap" and value:
            sitemaps.append(value)
        elif key == "allow" and value:
            allow.append(value)
        elif key == "disallow" and value:
            disallow.append(value)
        elif key == "user-agent" and value:
            user_agents.append(value)
    return {
        "url": origin,
        "robots_url": robots_url,
        "status": int(response.status_code),
        "reachable": 200 <= int(response.status_code) < 400,
        "user_agents": user_agents[:20],
        "allow": allow[:20],
        "disallow": disallow[:20],
        "sitemaps": sitemaps[:20],
        "line_count": len((response.text or "").splitlines()),
    }


async def _sitemap_probe(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    origin = _origin_from_url(url)
    robots = await _robots_inspect({"url": origin, "timeout": timeout_s})
    candidates = list(robots.get("sitemaps") or [])
    for default_path in ("/sitemap.xml", "/sitemap_index.xml"):
        candidate = origin.rstrip("/") + default_path
        if candidate not in candidates:
            candidates.append(candidate)
    checks = []
    for candidate in candidates[:10]:
        response, error = await _fetch_text_response(candidate, timeout_s=timeout_s)
        checks.append(
            {
                "url": candidate,
                "reachable": bool(response and 200 <= int(response.status_code) < 400),
                "status": int(response.status_code) if response else 0,
                "error": error or "",
            }
        )
    return {
        "url": origin,
        "robots_url": robots.get("robots_url"),
        "declared_sitemaps": list(robots.get("sitemaps") or []),
        "sitemaps": checks,
        "reachable_count": sum(1 for row in checks if row["reachable"]),
    }


async def _tls_inspect(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    parsed = urlparse(_normalize_url(url))
    host = parsed.hostname or str(url or "").strip()
    port = int(parsed.port or 443)
    if not host:
        return {"error": "url is required", "field": "url"}
    try:
        payload = await asyncio.to_thread(_tls_probe_sync, host, port, timeout_s)
        payload["reachable"] = True
        payload["url"] = _normalize_url(url)
        return payload
    except Exception as e:
        return {"url": _normalize_url(url), "host": host, "port": port, "reachable": False, "error": str(e)}


async def _security_txt_inspect(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    origin = _origin_from_url(url)
    candidates = [origin.rstrip("/") + "/.well-known/security.txt", origin.rstrip("/") + "/security.txt"]
    for candidate in candidates:
        response, error = await _fetch_text_response(candidate, timeout_s=timeout_s)
        if error or response is None:
            continue
        if not (200 <= int(response.status_code) < 400):
            continue
        contacts: list[str] = []
        policies: list[str] = []
        hiring: list[str] = []
        acknowledgements: list[str] = []
        preferred_languages: list[str] = []
        expires = ""
        for raw_line in (response.text or "").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "contact" and value:
                contacts.append(value)
            elif key == "policy" and value:
                policies.append(value)
            elif key == "hiring" and value:
                hiring.append(value)
            elif key == "acknowledgments" and value:
                acknowledgements.append(value)
            elif key == "preferred-languages" and value:
                preferred_languages.extend([part.strip() for part in value.split(",") if part.strip()])
            elif key == "expires" and value and not expires:
                expires = value
        return {
            "url": origin,
            "security_txt_url": candidate,
            "found": True,
            "status": int(response.status_code),
            "contacts": contacts,
            "policies": policies,
            "hiring": hiring,
            "acknowledgments": acknowledgements,
            "preferred_languages": preferred_languages,
            "expires": expires,
        }
    return {
        "url": origin,
        "security_txt_url": candidates[0],
        "found": False,
        "status": 0,
        "contacts": [],
        "policies": [],
        "hiring": [],
        "acknowledgments": [],
        "preferred_languages": [],
        "expires": "",
    }


async def _http_headers_inspect(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    response, error = await _fetch_http_response(url, timeout_s=timeout_s, method="HEAD")
    if error or response is None:
        return {"url": _normalize_url(url), "reachable": False, "error": error or "fetch failed"}
    interesting = [
        "content-type",
        "server",
        "cache-control",
        "strict-transport-security",
        "content-security-policy",
        "x-frame-options",
        "x-content-type-options",
        "referrer-policy",
        "permissions-policy",
        "cross-origin-resource-policy",
    ]
    headers = {name: _header_value(response.headers, name) for name in interesting}
    security_header_names = [
        "strict-transport-security",
        "content-security-policy",
        "x-frame-options",
        "x-content-type-options",
        "referrer-policy",
    ]
    missing = [name for name in security_header_names if not headers.get(name)]
    return {
        "url": _normalize_url(url),
        "final_url": str(response.url),
        "status": int(response.status_code),
        "reachable": 200 <= int(response.status_code) < 400,
        "headers": headers,
        "security_headers_present": [name for name in security_header_names if headers.get(name)],
        "missing_security_headers": missing,
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


async def _rdap_lookup(args: dict) -> dict:
    domain = str(args.get("domain", "")).strip().strip(".")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    if not domain:
        return {"error": "domain is required", "field": "domain"}
    response, payload, error = await _fetch_json_response(f"https://rdap.org/domain/{domain}", timeout_s=timeout_s)
    if error or response is None or payload is None:
        return {"domain": domain, "reachable": False, "error": error or "fetch failed"}
    if not isinstance(payload, dict):
        return {"domain": domain, "reachable": False, "error": "unexpected RDAP payload"}
    registrar = ""
    for entity in payload.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        roles = [str(role).lower() for role in entity.get("roles") or []]
        if "registrar" not in roles:
            continue
        vcard = entity.get("vcardArray") or []
        if isinstance(vcard, list) and len(vcard) == 2 and isinstance(vcard[1], list):
            for item in vcard[1]:
                if isinstance(item, list) and len(item) >= 4 and item[0] == "fn":
                    registrar = str(item[3] or "")
                    break
        if registrar:
            break
    events_by_action = {
        str(item.get("eventAction") or ""): str(item.get("eventDate") or "")
        for item in (payload.get("events") or [])
        if isinstance(item, dict)
    }
    return {
        "domain": domain,
        "reachable": 200 <= int(response.status_code) < 400,
        "status": int(response.status_code),
        "handle": str(payload.get("handle") or ""),
        "ldh_name": str(payload.get("ldhName") or domain),
        "statuses": list(payload.get("status") or []),
        "registrar": registrar,
        "registered_at": events_by_action.get("registration", ""),
        "expires_at": events_by_action.get("expiration", ""),
        "last_changed_at": events_by_action.get("last changed", ""),
    }


async def _api_health_report(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    started = datetime.now(timezone.utc)
    response, error = await _fetch_text_response(url, timeout_s=timeout_s)
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    if error or response is None:
        return {"url": _normalize_url(url), "reachable": False, "latency_ms": elapsed_ms, "error": error or "fetch failed"}
    text = response.text or ""
    content_type = _header_value(response.headers, "content-type")
    is_json = "json" in content_type.lower()
    json_valid = False
    if is_json:
        try:
            json.loads(text)
            json_valid = True
        except Exception:
            json_valid = False
    return {
        "url": _normalize_url(url),
        "final_url": str(response.url),
        "status": int(response.status_code),
        "reachable": 200 <= int(response.status_code) < 400,
        "latency_ms": elapsed_ms,
        "content_type": content_type,
        "response_bytes": len(text.encode("utf-8")),
        "server": _header_value(response.headers, "server"),
        "cache_control": _header_value(response.headers, "cache-control"),
        "redirected": str(response.url) != _normalize_url(url),
        "is_json": is_json,
        "json_valid": json_valid,
    }


async def _x402_server_probe(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    origin = _origin_from_url(url)
    checks: list[dict[str, Any]] = []
    for name, path in [
        ("x402_discovery", "/.well-known/x402"),
        ("status", "/api/v1/status"),
        ("tools", "/api/v1/tools?format=ultracompact"),
        ("reliability", "/api/v1/reliability"),
        ("openapi", "/spec/openapi.json"),
    ]:
        target = origin.rstrip("/") + path
        response, error = await _fetch_text_response(target, timeout_s=timeout_s)
        checks.append(
            {
                "name": name,
                "url": target,
                "status": int(response.status_code) if response else 0,
                "reachable": bool(response and 200 <= int(response.status_code) < 400),
                "error": error or "",
            }
        )
    resource_count = 0
    tool_count = 0
    x402_check = next((row for row in checks if row["name"] == "x402_discovery" and row["reachable"]), None)
    if x402_check:
        _, payload, error = await _fetch_json_response(x402_check["url"], timeout_s=timeout_s)
        if not error and isinstance(payload, dict):
            resources = payload.get("resourceCatalog")
            if not isinstance(resources, list):
                resources = payload.get("resources") or []
            resource_count = len(resources)
    tools_check = next((row for row in checks if row["name"] == "tools" and row["reachable"]), None)
    if tools_check:
        _, payload, error = await _fetch_json_response(tools_check["url"], timeout_s=timeout_s)
        if not error and isinstance(payload, dict):
            tool_count = int(payload.get("count") or 0)
    return {
        "url": origin,
        "reachable_count": sum(1 for row in checks if row["reachable"]),
        "check_count": len(checks),
        "resource_count": resource_count,
        "tool_count": tool_count,
        "checks": checks,
    }


async def _x402_resource_summary(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    origin = _origin_from_url(url)
    response, payload, error = await _fetch_json_response(origin.rstrip("/") + "/.well-known/x402", timeout_s=timeout_s)
    if error or response is None or payload is None:
        return {"url": origin, "reachable": False, "error": error or "fetch failed"}
    if not isinstance(payload, dict):
        return {"url": origin, "reachable": False, "error": "unexpected x402 payload"}
    resources = payload.get("resourceCatalog")
    if not isinstance(resources, list):
        resources = payload.get("resources") or []
    preview: list[dict[str, Any]] = []
    networks: set[str] = set()
    for row in resources[:20]:
        if not isinstance(row, dict):
            continue
        accepts = row.get("accepts") or []
        row_networks = []
        if isinstance(accepts, list):
            for accept in accepts:
                if isinstance(accept, dict):
                    network = str(accept.get("network") or "").strip()
                    if network:
                        networks.add(network)
                        row_networks.append(network)
        preview.append(
            {
                "tool_name": str(row.get("tool_name") or ""),
                "resource": str(row.get("resource") or ""),
                "networks": sorted(set(row_networks)),
            }
        )
    return {
        "url": origin,
        "reachable": 200 <= int(response.status_code) < 400,
        "status": int(response.status_code),
        "resource_count": len(resources),
        "networks": sorted(networks),
        "resources": preview,
    }


def _keyword_hits(text: str, patterns: list[str]) -> list[str]:
    lowered = (text or "").lower()
    return [pattern for pattern in patterns if pattern in lowered]


def _domain_from_url_or_origin(raw: str) -> str:
    parsed = urlparse(_normalize_url(raw))
    return (parsed.hostname or str(raw or "").strip()).strip(".").lower()


async def _website_intelligence_report(args: dict) -> dict:
    timeout = args.get("timeout", 8)
    url = args.get("url", "")
    page, og, links, forms, contacts, feeds = await asyncio.gather(
        _page_extract({"url": url, "timeout": timeout}),
        _open_graph({"url": url, "timeout": timeout}),
        _links_extract({"url": url, "timeout": timeout, "limit": 40}),
        _forms_extract({"url": url, "timeout": timeout}),
        _contact_extract({"url": url, "timeout": timeout}),
        _feed_discover({"url": url, "timeout": timeout}),
    )
    summary = {
        "title": page.get("title") or og.get("title") or "",
        "description": page.get("description") or og.get("description") or "",
        "has_forms": bool(forms.get("form_count")),
        "has_feeds": bool(feeds.get("feed_count")),
        "has_contacts": bool(contacts.get("emails") or contacts.get("phone_numbers")),
        "internal_links": links.get("internal_links", 0),
        "external_links": links.get("external_links", 0),
    }
    return {
        "url": _normalize_url(url),
        "summary": summary,
        "page": page,
        "social_preview": og,
        "links": links,
        "forms": forms,
        "contacts": contacts,
        "feeds": feeds,
    }


async def _domain_trust_report(args: dict) -> dict:
    timeout = args.get("timeout", 8)
    url = args.get("url", "")
    domain = _domain_from_url_or_origin(url)
    tls, security_txt, headers, rdap, a_dns, mx_dns, health = await asyncio.gather(
        _tls_inspect({"url": url, "timeout": timeout}),
        _security_txt_inspect({"url": url, "timeout": timeout}),
        _http_headers_inspect({"url": url, "timeout": timeout}),
        _rdap_lookup({"domain": domain, "timeout": timeout}),
        _dns_lookup({"domain": domain, "record_type": "A", "timeout": timeout}),
        _dns_lookup({"domain": domain, "record_type": "MX", "timeout": timeout}),
        _api_health_report({"url": url, "timeout": timeout}),
    )
    score = 0
    if tls.get("reachable"):
        score += 20
    if (tls.get("days_until_expiry") or 0) > 14:
        score += 10
    if security_txt.get("found"):
        score += 15
    if len(headers.get("security_headers_present") or []) >= 3:
        score += 20
    if health.get("reachable"):
        score += 15
    if (a_dns.get("answer_count") or 0) > 0:
        score += 10
    if (mx_dns.get("answer_count") or 0) > 0:
        score += 10
    trust_level = "high" if score >= 70 else "medium" if score >= 40 else "low"
    return {
        "url": _normalize_url(url),
        "domain": domain,
        "trust_score": score,
        "trust_level": trust_level,
        "tls": tls,
        "security_txt": security_txt,
        "headers": headers,
        "rdap": rdap,
        "dns": {"a": a_dns, "mx": mx_dns},
        "health": health,
    }


async def _openapi_summary(args: dict) -> dict:
    url = str(args.get("url", "")).strip()
    timeout_s = _parse_int(args.get("timeout", 8), default=8)
    target = url if url.endswith(".json") else _origin_from_url(url).rstrip("/") + "/spec/openapi.json"
    response, payload, error = await _fetch_json_response(target, timeout_s=timeout_s)
    if error or response is None or payload is None or not isinstance(payload, dict):
        return {"url": target, "reachable": False, "error": error or "fetch failed"}
    info = payload.get("info") or {}
    paths = payload.get("paths") or {}
    tags = payload.get("tags") or []
    path_keys = list(paths.keys()) if isinstance(paths, dict) else []
    x402_paths = [path for path in path_keys if "/x402/" in path]
    premium_paths = [path for path in path_keys if "/premium/" in path]
    auth_hints = sorted(
        {
            token
            for path_item in (paths.values() if isinstance(paths, dict) else [])
            for operation in (path_item.values() if isinstance(path_item, dict) else [])
            if isinstance(operation, dict)
            for token in _keyword_hits(json.dumps(operation), ["bearer", "api key", "payment-signature", "x402", "siwx"])
        }
    )
    return {
        "url": target,
        "reachable": True,
        "title": str(info.get("title") or ""),
        "version": str(info.get("version") or ""),
        "description": str(info.get("description") or "")[:300],
        "path_count": len(path_keys),
        "x402_path_count": len(x402_paths),
        "premium_path_count": len(premium_paths),
        "tag_count": len(tags) if isinstance(tags, list) else 0,
        "sample_paths": path_keys[:12],
        "auth_hints": auth_hints,
    }


async def _x402_server_audit(args: dict) -> dict:
    timeout = args.get("timeout", 8)
    url = args.get("url", "")
    probe, resources, openapi = await asyncio.gather(
        _x402_server_probe({"url": url, "timeout": timeout}),
        _x402_resource_summary({"url": url, "timeout": timeout}),
        _openapi_summary({"url": url, "timeout": timeout}),
    )
    score = 0
    score += min(40, int(probe.get("reachable_count", 0)) * 8)
    if resources.get("reachable"):
        score += 20
    if (resources.get("resource_count") or 0) > 0:
        score += 20
    if openapi.get("reachable"):
        score += 20
    level = "excellent" if score >= 85 else "good" if score >= 60 else "weak"
    gaps = []
    if int(probe.get("reachable_count", 0)) < int(probe.get("check_count", 0)):
        gaps.append("some expected x402 endpoints are unreachable")
    if (resources.get("resource_count") or 0) == 0:
        gaps.append("no x402 resources discovered")
    if not openapi.get("reachable"):
        gaps.append("openapi unavailable")
    return {
        "url": _origin_from_url(url),
        "audit_score": score,
        "audit_level": level,
        "gaps": gaps,
        "probe": probe,
        "resources": resources,
        "openapi": openapi,
    }


async def _docs_site_map(args: dict) -> dict:
    timeout = args.get("timeout", 8)
    url = args.get("url", "")
    page, links, sitemap, robots, feeds = await asyncio.gather(
        _page_extract({"url": url, "timeout": timeout}),
        _links_extract({"url": url, "timeout": timeout, "limit": 80}),
        _sitemap_probe({"url": url, "timeout": timeout}),
        _robots_inspect({"url": url, "timeout": timeout}),
        _feed_discover({"url": url, "timeout": timeout}),
    )
    docs_links = [
        row["url"]
        for row in links.get("links", [])
        if any(token in row.get("url", "").lower() for token in ["/docs", "/api", "/reference", "/guides", "/changelog", "/blog"])
    ]
    return {
        "url": _normalize_url(url),
        "title": page.get("title", ""),
        "docs_link_count": len(docs_links),
        "docs_links": docs_links[:25],
        "has_sitemap": (sitemap.get("reachable_count") or 0) > 0,
        "has_feed": bool(feeds.get("feed_count")),
        "robots": robots,
        "sitemap": sitemap,
    }


async def _pricing_page_extract(args: dict) -> dict:
    timeout = args.get("timeout", 8)
    url = args.get("url", "")
    page, forms, contacts, links = await asyncio.gather(
        _page_extract({"url": url, "timeout": timeout}),
        _forms_extract({"url": url, "timeout": timeout}),
        _contact_extract({"url": url, "timeout": timeout}),
        _links_extract({"url": url, "timeout": timeout, "limit": 60}),
    )
    text = f"{page.get('title','')} {page.get('description','')} {page.get('text_excerpt','')}"
    signals = {
        "free_trial": bool(_keyword_hits(text, ["free trial", "start free", "try for free"])),
        "contact_sales": bool(_keyword_hits(text, ["contact sales", "book a demo", "talk to sales"])),
        "usage_based": bool(_keyword_hits(text, ["usage-based", "pay as you go", "per request", "per month"])),
        "enterprise": bool(_keyword_hits(text, ["enterprise", "custom pricing"])),
    }
    cta_links = [
        row["url"]
        for row in links.get("links", [])
        if any(token in row.get("url", "").lower() for token in ["pricing", "signup", "register", "contact", "demo", "sales"])
    ]
    return {
        "url": _normalize_url(url),
        "title": page.get("title", ""),
        "description": page.get("description", ""),
        "pricing_signals": signals,
        "cta_links": cta_links[:20],
        "form_count": forms.get("form_count", 0),
        "contact_channels": {
            "emails": contacts.get("emails", []),
            "phones": contacts.get("phone_numbers", []),
            "social_links": contacts.get("social_links", {}),
        },
    }


async def _company_contact_pack(args: dict) -> dict:
    timeout = args.get("timeout", 8)
    url = args.get("url", "")
    contacts, forms, security_txt, rdap, links = await asyncio.gather(
        _contact_extract({"url": url, "timeout": timeout}),
        _forms_extract({"url": url, "timeout": timeout}),
        _security_txt_inspect({"url": url, "timeout": timeout}),
        _rdap_lookup({"domain": _domain_from_url_or_origin(url), "timeout": timeout}),
        _links_extract({"url": url, "timeout": timeout, "limit": 60}),
    )
    priority_links = [
        row["url"]
        for row in links.get("links", [])
        if any(token in row.get("url", "").lower() for token in ["contact", "support", "about", "sales", "team", "security"])
    ]
    return {
        "url": _normalize_url(url),
        "emails": contacts.get("emails", []),
        "phones": contacts.get("phone_numbers", []),
        "social_links": contacts.get("social_links", {}),
        "form_count": forms.get("form_count", 0),
        "security_contacts": security_txt.get("contacts", []),
        "registrar": rdap.get("registrar", ""),
        "priority_links": priority_links[:20],
    }


async def _api_integration_readiness(args: dict) -> dict:
    timeout = args.get("timeout", 8)
    url = args.get("url", "")
    health, headers, openapi = await asyncio.gather(
        _api_health_report({"url": url, "timeout": timeout}),
        _http_headers_inspect({"url": url, "timeout": timeout}),
        _openapi_summary({"url": url, "timeout": timeout}),
    )
    has_openapi = bool(openapi.get("reachable"))
    auth_hints = openapi.get("auth_hints", [])
    readiness_score = 0
    if health.get("reachable"):
        readiness_score += 35
    if has_openapi:
        readiness_score += 35
    if len(headers.get("security_headers_present") or []) >= 2:
        readiness_score += 10
    if auth_hints:
        readiness_score += 10
    if (openapi.get("path_count") or 0) >= 3:
        readiness_score += 10
    readiness_level = "high" if readiness_score >= 75 else "medium" if readiness_score >= 45 else "low"
    return {
        "url": _normalize_url(url),
        "readiness_score": readiness_score,
        "readiness_level": readiness_level,
        "has_openapi": has_openapi,
        "auth_hints": auth_hints,
        "health": health,
        "headers": headers,
        "openapi": openapi,
    }


async def _login_surface_report(args: dict) -> dict:
    timeout = args.get("timeout", 8)
    url = args.get("url", "")
    forms, headers, links, page = await asyncio.gather(
        _forms_extract({"url": url, "timeout": timeout}),
        _http_headers_inspect({"url": url, "timeout": timeout}),
        _links_extract({"url": url, "timeout": timeout, "limit": 80}),
        _page_extract({"url": url, "timeout": timeout}),
    )
    auth_links = [
        row["url"]
        for row in links.get("links", [])
        if any(token in row.get("url", "").lower() for token in ["login", "signin", "signup", "register", "reset", "forgot", "sso", "oauth"])
    ]
    password_forms = [
        form for form in forms.get("forms", [])
        if any("password" in str(field).lower() for field in form.get("inputs", []))
    ]
    return {
        "url": _normalize_url(url),
        "title": page.get("title", ""),
        "auth_link_count": len(auth_links),
        "auth_links": auth_links[:20],
        "form_count": forms.get("form_count", 0),
        "password_form_count": len(password_forms),
        "security_headers_present": headers.get("security_headers_present", []),
        "missing_security_headers": headers.get("missing_security_headers", []),
    }


async def _content_distribution_report(args: dict) -> dict:
    timeout = args.get("timeout", 8)
    url = args.get("url", "")
    page, og, feeds, contacts, links = await asyncio.gather(
        _page_extract({"url": url, "timeout": timeout}),
        _open_graph({"url": url, "timeout": timeout}),
        _feed_discover({"url": url, "timeout": timeout}),
        _contact_extract({"url": url, "timeout": timeout}),
        _links_extract({"url": url, "timeout": timeout, "limit": 80}),
    )
    blog_like_links = [
        row["url"]
        for row in links.get("links", [])
        if any(token in row.get("url", "").lower() for token in ["/blog", "/news", "/press", "/updates", "/changelog"])
    ]
    return {
        "url": _normalize_url(url),
        "title": page.get("title", ""),
        "description": page.get("description", ""),
        "has_open_graph": bool(og.get("open_graph")),
        "has_twitter_card": bool(og.get("twitter")),
        "feed_count": feeds.get("feed_count", 0),
        "social_channels": sorted((contacts.get("social_links") or {}).keys()),
        "blog_like_links": blog_like_links[:20],
    }


async def _dns_lookup(args: dict) -> dict:
    domain = str(args.get("domain", "")).strip().strip(".")
    record_type = str(args.get("record_type", "A") or "A").strip().upper()
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    if not domain:
        return {"error": "domain is required", "field": "domain"}
    if record_type not in {"A", "AAAA", "CNAME", "MX", "NS", "TXT"}:
        return {"error": "unsupported record_type", "field": "record_type"}

    lookup_url = "https://dns.google/resolve"
    try:
        async with httpx.AsyncClient(timeout=max(1, min(timeout_s, 15))) as client:
            resp = await client.get(lookup_url, params={"name": domain, "type": record_type})
        payload = resp.json() if resp.content else {}
        answers = []
        for item in payload.get("Answer", []) or []:
            answers.append(
                {
                    "name": item.get("name", ""),
                    "type": item.get("type"),
                    "ttl": item.get("TTL"),
                    "data": item.get("data", ""),
                }
            )
        if answers:
            return {
                "domain": domain,
                "record_type": record_type,
                "status": int(payload.get("Status", 0) or 0),
                "answers": answers,
                "answer_count": len(answers),
            }
    except Exception:
        pass

    if record_type in {"A", "AAAA"}:
        family = socket.AF_INET if record_type == "A" else socket.AF_INET6
        try:
            infos = socket.getaddrinfo(domain, None, family, socket.SOCK_STREAM)
            seen = sorted({info[4][0] for info in infos})
            return {
                "domain": domain,
                "record_type": record_type,
                "status": 0,
                "answers": [{"name": domain, "type": record_type, "ttl": None, "data": value} for value in seen],
                "answer_count": len(seen),
                "resolver": "socket_fallback",
            }
        except Exception as e:
            return {"domain": domain, "record_type": record_type, "status": 0, "answers": [], "error": str(e)}

    return {"domain": domain, "record_type": record_type, "status": 0, "answers": []}


async def _email_validate(args: dict) -> dict:
    email = str(args.get("email", "")).strip().lower()
    syntax_valid = bool(re.fullmatch(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}", email, flags=re.IGNORECASE))
    if not syntax_valid:
        return {
            "email": email,
            "normalized": email,
            "syntax_valid": False,
            "domain": "",
            "mx_records": [],
            "a_records": [],
            "likely_deliverable": False,
        }
    local, domain = email.rsplit("@", 1)
    timeout_s = args.get("timeout", 8)
    mx_lookup = await _dns_lookup({"domain": domain, "record_type": "MX", "timeout": timeout_s})
    a_lookup = await _dns_lookup({"domain": domain, "record_type": "A", "timeout": timeout_s})
    mx_records = [row.get("data", "") for row in mx_lookup.get("answers", [])]
    a_records = [row.get("data", "") for row in a_lookup.get("answers", [])]
    return {
        "email": email,
        "normalized": email,
        "local_part": local,
        "domain": domain,
        "syntax_valid": True,
        "mx_records": mx_records,
        "a_records": a_records,
        "likely_deliverable": bool(mx_records or a_records),
    }


