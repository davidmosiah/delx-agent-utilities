"""Network / DNS / security tools: robots, sitemap, TLS, security.txt, headers, RDAP, DNS, email, health."""

from __future__ import annotations

import asyncio
import json
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from .._helpers import (
    _fetch_http_response,
    _fetch_json_response,
    _fetch_text_response,
    _header_value,
    _normalize_url,
    _parse_int,
    _tls_probe_sync,
)
from ._common import _origin_from_url


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
