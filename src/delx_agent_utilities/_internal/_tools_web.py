"""Composite web/network/x402 report tools, plus the stable re-export surface.

The single-file monolith was split into per-domain modules under ``web/`` in
v0.2.0. This module now:

1. Re-exports every leaf tool (extract / network / x402) so existing imports —
   ``from ._internal._tools_web import _page_extract`` etc. — keep working and
   stay patchable via this module's namespace.
2. Defines the *composite* tools that fan out to several leaf probes
   (``asyncio.gather``) and roll the results into a single report.

Composite tools reference the leaf functions by their module-global name on
*this* module, so monkeypatching ``_tools_web._api_health_report`` (and friends)
in tests transparently swaps the dependency for every composite.
"""

from __future__ import annotations

import asyncio

from ._api_readiness import build_api_integration_readiness_report
from ._helpers import _normalize_url
from .web._common import _domain_from_url_or_origin, _keyword_hits, _origin_from_url
from .web.extract import (
    _contact_extract,
    _feed_discover,
    _forms_extract,
    _links_extract,
    _open_graph,
    _page_extract,
)
from .web.network import (
    _api_health_report,
    _dns_lookup,
    _email_validate,
    _http_headers_inspect,
    _rdap_lookup,
    _robots_inspect,
    _security_txt_inspect,
    _sitemap_probe,
    _tls_inspect,
)
from .web.x402 import (
    _openapi_summary,
    _x402_resource_summary,
    _x402_server_probe,
)

__all__ = [
    # extract leaves
    "_page_extract",
    "_open_graph",
    "_links_extract",
    "_feed_discover",
    "_forms_extract",
    "_contact_extract",
    # network leaves
    "_robots_inspect",
    "_sitemap_probe",
    "_tls_inspect",
    "_security_txt_inspect",
    "_http_headers_inspect",
    "_rdap_lookup",
    "_api_health_report",
    "_dns_lookup",
    "_email_validate",
    # x402 leaves
    "_x402_server_probe",
    "_x402_resource_summary",
    "_openapi_summary",
    # composites (defined below)
    "_website_intelligence_report",
    "_domain_trust_report",
    "_x402_server_audit",
    "_docs_site_map",
    "_pricing_page_extract",
    "_company_contact_pack",
    "_api_integration_readiness",
    "_login_surface_report",
    "_content_distribution_report",
]


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
    return await build_api_integration_readiness_report(
        {"url": url, "timeout": timeout},
        probes={
            "health": _api_health_report,
            "headers": _http_headers_inspect,
            "openapi": _openapi_summary,
            "page": _page_extract,
            "links": _links_extract,
        },
        normalize_url=_normalize_url,
    )


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
