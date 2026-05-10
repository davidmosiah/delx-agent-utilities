"""Deterministic API integration readiness composition.

This module combines lower-level web probes into one agent-facing integration
decision. It intentionally stays LLM-free and stateless so the public utility
contract is reproducible across CLI, MCP, and Delx runtime calls.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable
from typing import Any

Probe = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]

_AUTH_KEYWORDS = {
    "api key",
    "apikey",
    "x-api-key",
    "bearer",
    "authorization",
    "token",
    "personal access token",
}
_OAUTH_KEYWORDS = {"oauth", "openid", "oidc", "pkce"}
_X402_KEYWORDS = {"x402", "payment-signature", "http 402", "402 payment"}
_RATE_LIMIT_PATTERN = re.compile(r"\brate[-\s]?limit|\bquota\b|\b429\b", re.IGNORECASE)


def _normalize_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        return raw
    return f"https://{raw}"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _dedupe(items: list[str], *, limit: int = 12) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _text_blob(*parts: Any) -> str:
    tokens: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            tokens.extend(str(v) for v in part.values() if v is not None)
        elif isinstance(part, list):
            tokens.extend(str(v) for v in part if v is not None)
        elif part is not None:
            tokens.append(str(part))
    return " ".join(tokens).lower()


def _link_urls(links_payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for row in _as_list(links_payload.get("links")):
        if isinstance(row, dict):
            urls.append(str(row.get("url") or "").strip())
        else:
            urls.append(str(row or "").strip())
    return _dedupe(urls, limit=80)


def _links_matching(urls: list[str], needles: tuple[str, ...], *, limit: int = 8) -> list[str]:
    matched = [url for url in urls if any(needle in url.lower() for needle in needles)]
    return _dedupe(matched, limit=limit)


def _classify_auth(openapi: dict[str, Any], page: dict[str, Any], urls: list[str]) -> dict[str, Any]:
    openapi_hints = [str(hint).strip().lower() for hint in _as_list(openapi.get("auth_hints")) if str(hint).strip()]
    blob = _text_blob(
        openapi_hints,
        openapi.get("description"),
        page.get("title"),
        page.get("description"),
        page.get("text_excerpt"),
        urls,
    )

    hints = set(openapi_hints)
    for keyword in _AUTH_KEYWORDS | _OAUTH_KEYWORDS | _X402_KEYWORDS:
        if keyword in blob:
            hints.add(keyword)

    if hints & _X402_KEYWORDS:
        classification = "x402_or_payment_detected"
    elif hints & _OAUTH_KEYWORDS:
        classification = "oauth_detected"
    elif hints & _AUTH_KEYWORDS:
        classification = "bearer_or_api_key_detected"
    else:
        classification = "unknown"

    return {
        "classification": classification,
        "hints": sorted(hints),
        "confidence": "high" if openapi_hints else "medium" if classification != "unknown" else "low",
    }


def _has_rate_limit_guidance(openapi: dict[str, Any], page: dict[str, Any], urls: list[str]) -> bool:
    return bool(
        _RATE_LIMIT_PATTERN.search(
            _text_blob(
                openapi.get("description"),
                page.get("title"),
                page.get("description"),
                page.get("text_excerpt"),
                urls,
            )
        )
    )


def _issue(code: str, severity: str, detail: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail}


def _score(
    *,
    health: dict[str, Any],
    headers: dict[str, Any],
    openapi: dict[str, Any],
    auth: dict[str, Any],
    docs_links: list[str],
    sdk_links: list[str],
    example_links: list[str],
) -> int:
    score = 0
    if health.get("reachable"):
        score += 20
    if openapi.get("reachable"):
        score += 30
    if auth.get("classification") != "unknown":
        score += 15
    if docs_links:
        score += 10
    if sdk_links or example_links:
        score += 10
    if len(headers.get("security_headers_present") or []) >= 2:
        score += 10
    if int(openapi.get("path_count") or 0) >= 3:
        score += 5

    if not health.get("reachable"):
        score = min(score, 45)
    if not openapi.get("reachable"):
        score = min(score, 70)
    return max(0, min(100, score))


async def _run_probe(name: str, probes: dict[str, Probe], args: dict[str, Any]) -> dict[str, Any]:
    probe = probes.get(name)
    if probe is None:
        return {"reachable": False, "error": f"probe_not_configured:{name}"}
    try:
        result = probe(args)
        if inspect.isawaitable(result):
            result = await result
        return result if isinstance(result, dict) else {"value": result}
    except Exception as exc:
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}


async def build_api_integration_readiness_report(
    args: dict[str, Any],
    *,
    probes: dict[str, Probe],
    normalize_url: Callable[[Any], str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, LLM-free API integration readiness report."""

    normalizer = normalize_url or _normalize_url
    url = normalizer(args.get("url", ""))
    timeout = args.get("timeout", 8)
    probe_args = {"url": url, "timeout": timeout}

    health, headers, openapi, page, links = await asyncio.gather(
        _run_probe("health", probes, probe_args),
        _run_probe("headers", probes, probe_args),
        _run_probe("openapi", probes, probe_args),
        _run_probe("page", probes, probe_args),
        _run_probe("links", probes, {**probe_args, "limit": 80}),
    )

    urls = _link_urls(links)
    docs_links = _links_matching(urls, ("docs", "developer", "api", "reference", "guide", "quickstart"))
    openapi_links = _links_matching(urls, ("openapi", "swagger", "spec/openapi", ".well-known/openapi"))
    sdk_links = _links_matching(urls, ("sdk", "github.com", "npmjs.com", "pypi.org", "package"))
    example_links = _links_matching(urls, ("quickstart", "example", "sample", "tutorial", "curl", "getting-started"))
    auth = _classify_auth(openapi, page, urls)
    has_openapi = bool(openapi.get("reachable"))
    has_rate_limit_docs = _has_rate_limit_guidance(openapi, page, urls)

    blockers: list[str] = []
    issues: list[dict[str, str]] = []
    if not health.get("reachable"):
        blockers.append("unreachable")
        issues.append(_issue("unreachable", "critical", "The target URL did not return a reachable HTTP response."))
    if not has_openapi:
        blockers.append("missing_openapi")
        issues.append(_issue("missing_openapi", "high", "No reachable OpenAPI document was found from this URL."))
    if auth["classification"] == "unknown":
        blockers.append("auth_unknown")
        issues.append(_issue("auth_unknown", "medium", "Authentication expectations are not clear enough for autonomous integration."))
    if not has_rate_limit_docs:
        blockers.append("missing_rate_limit_docs")
        issues.append(_issue("missing_rate_limit_docs", "medium", "Rate-limit or quota guidance was not detected."))
    if not docs_links and not page.get("reachable"):
        blockers.append("docs_unavailable")
        issues.append(_issue("docs_unavailable", "medium", "No usable public docs surface was detected."))

    score = _score(
        health=health,
        headers=headers,
        openapi=openapi,
        auth=auth,
        docs_links=docs_links,
        sdk_links=sdk_links,
        example_links=example_links,
    )
    readiness_level = "high" if score >= 80 else "medium" if score >= 50 else "low"
    hard_blockers = {"unreachable", "missing_openapi"}
    verdict = "ready" if score >= 80 and not hard_blockers & set(blockers) else "review_before_use" if score >= 50 else "not_ready"

    if verdict == "ready":
        next_action = "Fetch the OpenAPI document, generate a typed client, then run one low-risk authenticated request."
    elif "missing_openapi" in blockers:
        next_action = "Find or publish an OpenAPI document before asking an agent to integrate this API autonomously."
    elif "auth_unknown" in blockers:
        next_action = "Document the authentication scheme, required headers, and one minimal successful request."
    else:
        next_action = "Resolve the listed blockers, then rerun the readiness report before integration."

    return {
        "tool_name": "util_api_integration_readiness",
        "surface": "delx-agent-utilities",
        "url": url,
        "verdict": verdict,
        "api_readiness_score": score,
        "readiness_score": score,
        "readiness_level": readiness_level,
        "has_openapi": has_openapi,
        "auth_hints": auth["hints"],
        "auth": auth,
        "docs": {
            "openapi": {
                "found": has_openapi,
                "url": openapi.get("url") or (openapi_links[0] if openapi_links else ""),
                "title": openapi.get("title", ""),
                "version": openapi.get("version", ""),
                "path_count": int(openapi.get("path_count") or 0),
                "sample_paths": openapi.get("sample_paths") or [],
            },
            "docs_links": docs_links,
            "openapi_links": openapi_links,
            "sdk_links": sdk_links,
            "example_links": example_links,
            "has_rate_limit_guidance": has_rate_limit_docs,
        },
        "runtime": {
            "reachable": bool(health.get("reachable")),
            "status": health.get("status"),
            "latency_ms": health.get("latency_ms"),
            "content_type": health.get("content_type"),
            "security_headers_present": headers.get("security_headers_present") or [],
        },
        "blockers": blockers,
        "issues": issues,
        "next_action": next_action,
        "agent_next_action": next_action,
        "deterministic": True,
        "llm_used": False,
        "components": {
            "health": health,
            "headers": headers,
            "openapi": openapi,
            "page": page,
            "links": links,
        },
    }
