"""Dispatch a util tool call by name to the appropriate handler.

Public API:
- ``call_util_tool(tool_name, arguments)`` — async dispatcher returning a result dict
- ``list_util_tool_schemas()`` — returns MCP-compatible schemas for all tools
"""

from __future__ import annotations

import inspect
from typing import Any
from urllib.parse import urlparse

from ._internal._helpers import _normalize_url
from ._internal._mcp_readiness import build_mcp_server_readiness_report
from ._internal._schemas import (
    UTIL_REQUIRED_PARAMS,
    UTIL_TOOL_NAMES,
    UTIL_TOOL_SCHEMAS,
)
from ._internal._tools_cron import _cron_describe
from ._internal._tools_encoding import (
    _base64_op,
    _hash,
    _json_validate,
    _regex_test,
    _timestamp_convert,
    _token_estimate,
    _url_health,
    _uuid_generate,
)
from ._internal._tools_http_codes import _http_codes
from ._internal._tools_jwt_csv import _csv_to_json, _json_to_csv, _jwt_inspect
from ._internal._tools_web import (
    _api_health_report,
    _api_integration_readiness,
    _company_contact_pack,
    _contact_extract,
    _content_distribution_report,
    _dns_lookup,
    _docs_site_map,
    _domain_trust_report,
    _email_validate,
    _feed_discover,
    _forms_extract,
    _http_headers_inspect,
    _links_extract,
    _login_surface_report,
    _open_graph,
    _openapi_summary,
    _page_extract,
    _pricing_page_extract,
    _rdap_lookup,
    _robots_inspect,
    _security_txt_inspect,
    _sitemap_probe,
    _tls_inspect,
    _website_intelligence_report,
    _x402_resource_summary,
    _x402_server_audit,
    _x402_server_probe,
)

_HANDLERS: dict[str, Any] = {
    "util_json_validate": _json_validate,
    "util_token_estimate": _token_estimate,
    "util_uuid_generate": _uuid_generate,
    "util_timestamp_convert": _timestamp_convert,
    "util_base64": _base64_op,
    "util_url_health": _url_health,
    "util_hash": _hash,
    "util_regex_test": _regex_test,
    "util_cron_describe": _cron_describe,
    "util_http_codes": _http_codes,
    "util_page_extract": _page_extract,
    "util_open_graph": _open_graph,
    "util_links_extract": _links_extract,
    "util_sitemap_probe": _sitemap_probe,
    "util_robots_inspect": _robots_inspect,
    "util_dns_lookup": _dns_lookup,
    "util_email_validate": _email_validate,
    "util_jwt_inspect": _jwt_inspect,
    "util_csv_to_json": _csv_to_json,
    "util_json_to_csv": _json_to_csv,
    "util_tls_inspect": _tls_inspect,
    "util_security_txt_inspect": _security_txt_inspect,
    "util_http_headers_inspect": _http_headers_inspect,
    "util_feed_discover": _feed_discover,
    "util_forms_extract": _forms_extract,
    "util_contact_extract": _contact_extract,
    "util_rdap_lookup": _rdap_lookup,
    "util_api_health_report": _api_health_report,
    "util_x402_server_probe": _x402_server_probe,
    "util_x402_resource_summary": _x402_resource_summary,
    "util_website_intelligence_report": _website_intelligence_report,
    "util_domain_trust_report": _domain_trust_report,
    "util_openapi_summary": _openapi_summary,
    "util_x402_server_audit": _x402_server_audit,
    "util_mcp_server_readiness_report": build_mcp_server_readiness_report,
    "util_docs_site_map": _docs_site_map,
    "util_pricing_page_extract": _pricing_page_extract,
    "util_company_contact_pack": _company_contact_pack,
    "util_api_integration_readiness": _api_integration_readiness,
    "util_login_surface_report": _login_surface_report,
    "util_content_distribution_report": _content_distribution_report,
}


def _normalize_util_args(tool_name: str, arguments: dict) -> dict:
    """Soft-alias common alternative parameter names to the canonical key."""
    args = dict(arguments or {})

    if tool_name in {"util_json_validate", "util_hash", "util_base64"}:
        if "input" not in args:
            for alias in ("text", "value", "payload", "data"):
                if alias in args and args.get(alias) is not None:
                    args["input"] = args.get(alias)
                    break
    if tool_name == "util_base64" and "action" not in args:
        for alias in ("mode", "op", "operation", "direction"):
            if alias in args and args.get(alias) is not None:
                args["action"] = args.get(alias)
                break
    if tool_name == "util_token_estimate" and "text" not in args:
        for alias in ("input", "value", "content", "prompt"):
            if alias in args and args.get(alias) is not None:
                args["text"] = args.get(alias)
                break
    if tool_name == "util_timestamp_convert" and "input" not in args:
        for alias in ("timestamp", "value", "datetime", "time"):
            if alias in args and args.get(alias) is not None:
                args["input"] = args.get(alias)
                break
    if tool_name == "util_url_health" and "url" not in args:
        for alias in ("uri", "target", "link", "host"):
            if alias in args and args.get(alias) is not None:
                args["url"] = args.get(alias)
                break

    url_alias_tools = {
        "util_page_extract",
        "util_open_graph",
        "util_links_extract",
        "util_sitemap_probe",
        "util_robots_inspect",
        "util_tls_inspect",
        "util_security_txt_inspect",
        "util_http_headers_inspect",
        "util_feed_discover",
        "util_forms_extract",
        "util_contact_extract",
        "util_api_health_report",
        "util_x402_server_probe",
        "util_x402_resource_summary",
        "util_website_intelligence_report",
        "util_domain_trust_report",
        "util_openapi_summary",
        "util_x402_server_audit",
        "util_mcp_server_readiness_report",
        "util_docs_site_map",
        "util_pricing_page_extract",
        "util_company_contact_pack",
        "util_api_integration_readiness",
        "util_login_surface_report",
        "util_content_distribution_report",
    }
    if tool_name in url_alias_tools and "url" not in args:
        for alias in ("uri", "target", "link", "website", "domain"):
            if alias in args and args.get(alias) is not None:
                args["url"] = args.get(alias)
                break

    if tool_name in {"util_dns_lookup", "util_rdap_lookup"} and "domain" not in args:
        for alias in ("host", "hostname", "name", "url"):
            if alias in args and args.get(alias) is not None:
                value = str(args.get(alias) or "").strip()
                args["domain"] = urlparse(_normalize_url(value)).netloc or value
                break
    if tool_name == "util_email_validate" and "email" not in args:
        for alias in ("address", "value", "input"):
            if alias in args and args.get(alias) is not None:
                args["email"] = args.get(alias)
                break
    if tool_name == "util_jwt_inspect" and "token" not in args:
        for alias in ("jwt", "value", "input"):
            if alias in args and args.get(alias) is not None:
                args["token"] = args.get(alias)
                break
    if tool_name == "util_csv_to_json" and "csv_text" not in args:
        for alias in ("input", "csv", "text", "content"):
            if alias in args and args.get(alias) is not None:
                args["csv_text"] = args.get(alias)
                break
    if tool_name == "util_json_to_csv" and "json_text" not in args:
        for alias in ("input", "json", "text", "content"):
            if alias in args and args.get(alias) is not None:
                args["json_text"] = args.get(alias)
                break
    if tool_name == "util_regex_test":
        if "pattern" not in args and "regex" in args:
            args["pattern"] = args.get("regex")
        if "text" not in args:
            for alias in ("input", "value", "content"):
                if alias in args and args.get(alias) is not None:
                    args["text"] = args.get(alias)
                    break
    if tool_name == "util_cron_describe" and "expression" not in args:
        for alias in ("cron", "schedule", "value"):
            if alias in args and args.get(alias) is not None:
                args["expression"] = args.get(alias)
                break
    if tool_name == "util_http_codes" and "code" not in args and "status" in args:
        args["code"] = args.get("status")

    return args


async def call_util_tool(tool_name: str, arguments: dict) -> dict:
    """Dispatch a util tool call. Returns the result dict.

    Unknown tools return ``{"error": ..., "available": [...]}``.
    Missing required params return ``{"error": ..., "tool": ..., "required": [...]}``.
    Tool exceptions are caught and returned as ``{"error": ..., "tool": ...}``.
    """
    handler = _HANDLERS.get(tool_name)
    if handler is None:
        return {"error": f"Unknown util tool: {tool_name}", "available": UTIL_TOOL_NAMES}

    arguments = _normalize_util_args(tool_name, arguments)

    required = UTIL_REQUIRED_PARAMS.get(tool_name, [])
    missing = [p for p in required if p not in arguments or arguments[p] is None]
    if missing:
        return {"error": f"Missing required params: {missing}", "tool": tool_name, "required": required}

    try:
        if inspect.iscoroutinefunction(handler):
            return await handler(arguments)
        return handler(arguments)
    except Exception as e:
        return {"error": f"tool execution failed: {type(e).__name__}: {e}", "tool": tool_name}


def list_util_tool_schemas() -> list[dict]:
    """Return MCP-compatible tool schemas for all util tools."""
    return list(UTIL_TOOL_SCHEMAS.values())
