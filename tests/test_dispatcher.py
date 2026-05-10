"""Smoke tests for the public dispatcher and registry."""

from __future__ import annotations

import asyncio

import pytest

from delx_agent_utilities import (
    UTIL_REQUIRED_PARAMS,
    UTIL_TOOL_NAMES,
    UTIL_TOOL_SCHEMAS,
    build_agent_manifest,
    build_connection_status,
    build_privacy_audit,
    call_util_tool,
    list_util_tool_schemas,
)


def test_registry_consistency():
    assert len(UTIL_TOOL_NAMES) == 41
    assert len(UTIL_TOOL_SCHEMAS) == 41
    assert set(UTIL_TOOL_NAMES) == set(UTIL_TOOL_SCHEMAS.keys())
    for name in UTIL_TOOL_NAMES:
        assert name in UTIL_REQUIRED_PARAMS, f"required-params missing: {name}"
        schema = UTIL_TOOL_SCHEMAS[name]
        assert schema["name"] == name
        assert "description" in schema
        assert "inputSchema" in schema


def test_list_util_tool_schemas_returns_all_tools():
    schemas = list_util_tool_schemas()
    assert len(schemas) == 41
    assert all("name" in s for s in schemas)


def test_agent_surfaces():
    manifest = build_agent_manifest()
    assert manifest["project"] == "delx-agent-utilities"
    assert manifest["tool_count"] == 41
    assert "delx_utilities_connection_status" in manifest["recommended_first_calls"]

    status = build_connection_status({})
    assert status["ok"] is True
    assert status["tool_count"] == 41

    audit = build_privacy_audit()
    assert audit["stores_credentials"] is False
    assert audit["telemetry"] is False
    assert any("rdap.org" in ep["name"] for ep in audit["third_party_endpoints"])


@pytest.mark.asyncio
async def test_unknown_tool_returns_error():
    result = await call_util_tool("util_does_not_exist", {})
    assert "error" in result
    assert "available" in result


@pytest.mark.asyncio
async def test_uuid_generate_is_local_and_fast():
    result = await call_util_tool("util_uuid_generate", {})
    assert "uuids" in result
    assert len(result["uuids"]) == 1
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_base64_encode_roundtrip():
    encoded = await call_util_tool("util_base64", {"input": "hello", "action": "encode"})
    assert encoded["result"] == "aGVsbG8="

    decoded = await call_util_tool("util_base64", {"input": "aGVsbG8=", "action": "decode"})
    assert decoded["result"] == "hello"


@pytest.mark.asyncio
async def test_hash_sha256():
    result = await call_util_tool("util_hash", {"input": "hello", "algorithm": "sha256"})
    assert (
        result["hash"]
        == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


@pytest.mark.asyncio
async def test_regex_test_finds_digits():
    result = await call_util_tool(
        "util_regex_test", {"pattern": r"\d+", "text": "abc123def"}
    )
    assert result["valid_pattern"] is True
    assert result["match_count"] == 1
    assert result["matches"][0]["match"] == "123"


@pytest.mark.asyncio
async def test_jwt_inspect_decodes_header_payload():
    token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    result = await call_util_tool("util_jwt_inspect", {"token": token})
    assert result["valid"] is True
    assert result["header"] == {"alg": "HS256", "typ": "JWT"}
    assert result["payload"]["name"] == "John Doe"


@pytest.mark.asyncio
async def test_csv_to_json_roundtrip():
    csv_text = "name,age\nAlice,30\nBob,25"
    csv_result = await call_util_tool("util_csv_to_json", {"csv_text": csv_text})
    assert csv_result["row_count"] == 2
    assert csv_result["rows"][0] == {"name": "Alice", "age": "30"}

    json_text = '[{"x": 1, "y": 2}, {"x": 3, "y": 4}]'
    json_result = await call_util_tool("util_json_to_csv", {"json_text": json_text})
    assert json_result["row_count"] == 2
    assert "x,y" in json_result["csv"] or "y,x" in json_result["csv"]


@pytest.mark.asyncio
async def test_cron_describe_quarter_hour():
    result = await call_util_tool(
        "util_cron_describe", {"expression": "*/15 * * * *"}
    )
    assert result["valid"] is True
    assert result["fields"]["minute"] == [0, 15, 30, 45]


@pytest.mark.asyncio
async def test_http_codes_lookup():
    result = await call_util_tool("util_http_codes", {"code": 418})
    assert result["code"] == 418
    assert "teapot" in result["name"].lower() or "joke" in result["description"].lower()


@pytest.mark.asyncio
async def test_alias_normalization():
    # `text` instead of `input` for util_hash
    result = await call_util_tool(
        "util_hash", {"text": "hello", "algorithm": "md5"}
    )
    assert result["hash"] == "5d41402abc4b2a76b9719d911017c592"


@pytest.mark.asyncio
async def test_api_integration_readiness_returns_decision_ready_contract(monkeypatch):
    from delx_agent_utilities._internal import _tools_web

    async def fake_health(args):
        return {"reachable": True, "status": 200, "latency_ms": 41, "content_type": "text/html"}

    async def fake_headers(args):
        return {
            "security_headers_present": ["strict-transport-security", "x-content-type-options"],
            "missing_security_headers": [],
        }

    async def fake_openapi(args):
        return {
            "reachable": True,
            "url": "https://api.example.com/openapi.json",
            "title": "Example API",
            "version": "1.0.0",
            "path_count": 6,
            "auth_hints": ["bearer", "api key"],
            "sample_paths": ["/v1/widgets", "/v1/users"],
        }

    async def fake_page(args):
        return {
            "reachable": True,
            "title": "Example API docs",
            "description": "Bearer auth, SDK quickstart, and rate limit guidance.",
            "text_excerpt": "Install the Python SDK, use Bearer auth, and respect documented rate limits.",
        }

    async def fake_links(args):
        return {
            "links": [
                {"url": "https://api.example.com/docs", "kind": "internal"},
                {"url": "https://api.example.com/openapi.json", "kind": "internal"},
                {"url": "https://github.com/example/sdk-python", "kind": "external"},
                {"url": "https://api.example.com/docs/quickstart", "kind": "internal"},
            ]
        }

    monkeypatch.setattr(_tools_web, "_api_health_report", fake_health)
    monkeypatch.setattr(_tools_web, "_http_headers_inspect", fake_headers)
    monkeypatch.setattr(_tools_web, "_openapi_summary", fake_openapi)
    monkeypatch.setattr(_tools_web, "_page_extract", fake_page)
    monkeypatch.setattr(_tools_web, "_links_extract", fake_links)

    report = await call_util_tool(
        "util_api_integration_readiness",
        {"url": "https://api.example.com/docs", "timeout": 8},
    )

    assert report["tool_name"] == "util_api_integration_readiness"
    assert report["surface"] == "delx-agent-utilities"
    assert report["verdict"] == "ready"
    assert report["api_readiness_score"] >= 85
    assert report["readiness_level"] == "high"
    assert report["auth"]["classification"] == "bearer_or_api_key_detected"
    assert report["docs"]["openapi"]["found"] is True
    assert "https://github.com/example/sdk-python" in report["docs"]["sdk_links"]
    assert "missing_rate_limit_docs" not in report["blockers"]
    assert "generate" in report["agent_next_action"].lower()
    assert report["deterministic"] is True
    assert report["llm_used"] is False


@pytest.mark.asyncio
async def test_mcp_server_readiness_is_registered_and_blocks_localhost():
    assert "util_mcp_server_readiness_report" in UTIL_TOOL_NAMES

    result = await call_util_tool("util_mcp_server_readiness_report", {"url": "http://localhost:3000"})

    assert result["tool_name"] == "util_mcp_server_readiness_report"
    assert "local" in result["error"]


@pytest.mark.asyncio
async def test_url_health_blocks_non_http_and_link_local_targets():
    file_payload = await call_util_tool("util_url_health", {"url": "file:///etc/passwd"})
    metadata_payload = await call_util_tool("util_url_health", {"url": "http://169.254.169.254/latest/meta-data/"})

    assert file_payload["url"] == "file:///etc/passwd"
    assert "blocked" in file_payload["reason"]
    assert "blocked" in metadata_payload["reason"]


@pytest.mark.asyncio
async def test_required_params_missing():
    result = await call_util_tool("util_url_health", {})
    assert "error" in result
    assert "url" in result["required"]
