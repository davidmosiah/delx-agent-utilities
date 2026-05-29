"""Tests for the per-domain web module split (extract / network / x402 / composite).

These guard the v0.2.0 refactor of the former ``_tools_web`` monolith: the leaf
tools now live in ``_internal.web.*`` while ``_tools_web`` keeps re-exporting them
and hosts the composite reports. The public dispatcher must stay identical.
"""

from __future__ import annotations

import pytest

from delx_agent_utilities import call_util_tool
from delx_agent_utilities._internal import _tools_web
from delx_agent_utilities._internal.web import extract, network, x402


def test_leaf_tools_live_in_their_domain_modules():
    # extract domain
    for name in ("_page_extract", "_open_graph", "_links_extract", "_feed_discover", "_forms_extract", "_contact_extract"):
        assert hasattr(extract, name), f"missing from extract: {name}"
    # network domain
    for name in (
        "_robots_inspect", "_sitemap_probe", "_tls_inspect", "_security_txt_inspect",
        "_http_headers_inspect", "_rdap_lookup", "_api_health_report", "_dns_lookup", "_email_validate",
    ):
        assert hasattr(network, name), f"missing from network: {name}"
    # x402 domain
    for name in ("_x402_server_probe", "_x402_resource_summary", "_openapi_summary"):
        assert hasattr(x402, name), f"missing from x402: {name}"


def test_tools_web_reexports_same_leaf_objects():
    # The facade must re-export the *same* function objects so existing imports
    # (e.g. dispatcher) and patch targets keep working unchanged.
    assert _tools_web._page_extract is extract._page_extract
    assert _tools_web._api_health_report is network._api_health_report
    assert _tools_web._openapi_summary is x402._openapi_summary


def test_composites_defined_on_facade():
    for name in (
        "_website_intelligence_report", "_domain_trust_report", "_x402_server_audit",
        "_docs_site_map", "_pricing_page_extract", "_company_contact_pack",
        "_api_integration_readiness", "_login_surface_report", "_content_distribution_report",
    ):
        assert hasattr(_tools_web, name), f"composite missing from facade: {name}"


@pytest.mark.asyncio
async def test_email_validate_syntax_only_is_local(monkeypatch):
    # Invalid syntax should short-circuit without any DNS work.
    async def explode(args):  # pragma: no cover - must not be called
        raise AssertionError("DNS lookup should not run for invalid syntax")

    monkeypatch.setattr(network, "_dns_lookup", explode)
    result = await call_util_tool("util_email_validate", {"email": "not-an-email"})
    assert result["syntax_valid"] is False
    assert result["likely_deliverable"] is False


@pytest.mark.asyncio
async def test_email_validate_uses_network_dns(monkeypatch):
    calls: list[str] = []

    async def fake_dns(args):
        calls.append(args.get("record_type"))
        if args.get("record_type") == "MX":
            return {"answers": [{"data": "mx1.example.com"}]}
        return {"answers": [{"data": "93.184.216.34"}]}

    # Patching the leaf module is enough because _email_validate lives there and
    # resolves _dns_lookup from network's namespace.
    monkeypatch.setattr(network, "_dns_lookup", fake_dns)
    result = await call_util_tool("util_email_validate", {"email": "hi@example.com"})
    assert result["syntax_valid"] is True
    assert result["domain"] == "example.com"
    assert result["mx_records"] == ["mx1.example.com"]
    assert result["likely_deliverable"] is True
    assert set(calls) == {"MX", "A"}


@pytest.mark.asyncio
async def test_domain_trust_report_composes_patched_leaves(monkeypatch):
    async def fake_tls(args):
        return {"reachable": True, "days_until_expiry": 90}

    async def fake_sec(args):
        return {"found": True, "contacts": ["security@example.com"]}

    async def fake_headers(args):
        return {"security_headers_present": ["a", "b", "c"], "missing_security_headers": []}

    async def fake_rdap(args):
        return {"registrar": "Example Registrar"}

    async def fake_dns(args):
        return {"answer_count": 1, "answers": [{"data": "x"}]}

    async def fake_health(args):
        return {"reachable": True}

    # Composites resolve leaves via the facade namespace, so patch _tools_web.
    monkeypatch.setattr(_tools_web, "_tls_inspect", fake_tls)
    monkeypatch.setattr(_tools_web, "_security_txt_inspect", fake_sec)
    monkeypatch.setattr(_tools_web, "_http_headers_inspect", fake_headers)
    monkeypatch.setattr(_tools_web, "_rdap_lookup", fake_rdap)
    monkeypatch.setattr(_tools_web, "_dns_lookup", fake_dns)
    monkeypatch.setattr(_tools_web, "_api_health_report", fake_health)

    report = await call_util_tool("util_domain_trust_report", {"url": "https://example.com"})
    assert report["domain"] == "example.com"
    # 20(tls)+10(expiry)+15(sec)+20(headers)+15(health)+10(A)+10(MX) == 100
    assert report["trust_score"] == 100
    assert report["trust_level"] == "high"
