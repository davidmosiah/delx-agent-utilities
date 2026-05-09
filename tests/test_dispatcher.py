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
    assert len(UTIL_TOOL_NAMES) == 40
    assert len(UTIL_TOOL_SCHEMAS) == 40
    assert set(UTIL_TOOL_NAMES) == set(UTIL_TOOL_SCHEMAS.keys())
    for name in UTIL_TOOL_NAMES:
        assert name in UTIL_REQUIRED_PARAMS, f"required-params missing: {name}"
        schema = UTIL_TOOL_SCHEMAS[name]
        assert schema["name"] == name
        assert "description" in schema
        assert "inputSchema" in schema


def test_list_util_tool_schemas_returns_40():
    schemas = list_util_tool_schemas()
    assert len(schemas) == 40
    assert all("name" in s for s in schemas)


def test_agent_surfaces():
    manifest = build_agent_manifest()
    assert manifest["project"] == "delx-agent-utilities"
    assert manifest["tool_count"] == 40
    assert "delx_utilities_connection_status" in manifest["recommended_first_calls"]

    status = build_connection_status({})
    assert status["ok"] is True
    assert status["tool_count"] == 40

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
async def test_required_params_missing():
    result = await call_util_tool("util_url_health", {})
    assert "error" in result
    assert "url" in result["required"]
