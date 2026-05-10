"""Deterministic MCP server readiness reporting."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_USER_AGENT = "DelxAgentUtilities/0.1 mcp-readiness"


def _normalize_origin(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_blocked_host(origin: str) -> str:
    host = (urlparse(origin).hostname or "").strip().lower()
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return "local hosts are blocked"
    if host.endswith(".local"):
        return "local network names are blocked"
    return ""


def _json_rpc_payload(method: str, request_id: int) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if method == "initialize":
        payload["params"] = {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "delx-mcp-readiness", "version": "1.0.0"},
        }
    return payload


async def _post_mcp_jsonrpc(client: httpx.AsyncClient, url: str, method: str, *, timeout_s: int, request_id: int) -> dict[str, Any]:
    try:
        response = await client.post(
            url,
            json=_json_rpc_payload(method, request_id),
            headers={"accept": "application/json", "content-type": "application/json", "user-agent": _USER_AGENT},
            timeout=timeout_s,
        )
        text = response.text[:200_000]
        payload = response.json() if text else {}
        return {
            "ok": 200 <= response.status_code < 300 and isinstance(payload, dict) and "error" not in payload,
            "status": int(response.status_code),
            "payload": payload if isinstance(payload, dict) else {},
            "error": "",
        }
    except Exception as exc:
        return {"ok": False, "status": 0, "payload": {}, "error": f"{type(exc).__name__}: {exc}"[:240]}


async def _get_json(client: httpx.AsyncClient, url: str, *, timeout_s: int) -> dict[str, Any]:
    try:
        response = await client.get(url, headers={"accept": "application/json", "user-agent": _USER_AGENT}, timeout=timeout_s)
        payload = response.json() if response.text else {}
        return {
            "ok": 200 <= response.status_code < 300 and isinstance(payload, dict),
            "status": int(response.status_code),
            "payload": payload if isinstance(payload, dict) else {},
            "error": "",
        }
    except Exception as exc:
        return {"ok": False, "status": 0, "payload": {}, "error": f"{type(exc).__name__}: {exc}"[:240]}


def _tools_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("tools"), list):
        return [tool for tool in result["tools"] if isinstance(tool, dict)]
    if isinstance(payload.get("tools"), list):
        return [tool for tool in payload["tools"] if isinstance(tool, dict)]
    return []


def _schema_quality(tools: list[dict[str, Any]]) -> tuple[dict[str, int], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    valid_names = 0
    valid_input_schemas = 0
    tools_with_descriptions = 0
    tools_with_arg_descriptions = 0

    for tool in tools:
        name = str(tool.get("name") or "").strip()
        description = str(tool.get("description") or "").strip()
        schema = tool.get("inputSchema")
        if _TOOL_NAME_RE.match(name):
            valid_names += 1
        else:
            issues.append({"severity": "high", "code": "invalid_tool_name", "detail": f"{name or '<missing>'} is not agent-safe"})
        if description:
            tools_with_descriptions += 1
        else:
            issues.append({"severity": "medium", "code": "missing_tool_description", "detail": f"{name or '<missing>'} has no description"})
        if isinstance(schema, dict) and schema.get("type") == "object" and isinstance(schema.get("properties", {}), dict):
            valid_input_schemas += 1
            properties = schema.get("properties") or {}
            if properties and all(isinstance(value, dict) and str(value.get("description") or "").strip() for value in properties.values()):
                tools_with_arg_descriptions += 1
        else:
            issues.append({"severity": "high", "code": "invalid_input_schema", "detail": f"{name or '<missing>'} has no object inputSchema"})

    quality = {
        "tool_count": len(tools),
        "valid_tool_names": valid_names,
        "valid_input_schemas": valid_input_schemas,
        "tools_with_descriptions": tools_with_descriptions,
        "tools_with_arg_descriptions": tools_with_arg_descriptions,
    }
    return quality, issues


def _score(*, initialize_ok: bool, tools_ok: bool, manifest_ok: bool, quality: dict[str, int]) -> int:
    total = max(1, int(quality.get("tool_count") or 0))
    score = 0
    if initialize_ok:
        score += 20
    if tools_ok:
        score += 20
    if manifest_ok:
        score += 10
    if quality.get("valid_input_schemas", 0) == total:
        score += 10
    if quality.get("tools_with_descriptions", 0) / total >= 0.5:
        score += 5
    if quality.get("tools_with_arg_descriptions", 0) / total >= 0.5:
        score += 5
    if quality.get("valid_tool_names", 0) == total:
        score += 10
    if total >= 5:
        score += 10
    return max(0, min(100, score))


def _verdict(score: int, issues: list[dict[str, str]]) -> str:
    high_count = sum(1 for issue in issues if issue.get("severity") == "high")
    if score >= 85 and high_count == 0:
        return "ready"
    if score >= 60:
        return "review_before_use"
    return "not_ready"


def _next_action(verdict: str, issues: list[dict[str, str]]) -> str:
    if not issues and verdict == "ready":
        return "Safe to attempt MCP integration; cache tools/list and run one low-risk tool call."
    if any(issue.get("code") in {"invalid_tool_name", "invalid_input_schema"} for issue in issues):
        return "Fix schema/name hygiene before asking agents to depend on this MCP server."
    return "Add richer tool descriptions and argument descriptions, then rerun the readiness report."


async def build_mcp_server_readiness_report(args: dict[str, Any], *, http_client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    timeout_s = max(1, min(15, int(args.get("timeout") or 8)))
    origin = _normalize_origin(str(args.get("url") or ""))
    if not origin:
        return {"error": "invalid url", "tool_name": "util_mcp_server_readiness_report", "required": ["url"]}
    blocked = _is_blocked_host(origin)
    if blocked:
        return {"error": blocked, "tool_name": "util_mcp_server_readiness_report", "url": origin}

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(follow_redirects=True)
    try:
        mcp_url = origin.rstrip("/") + "/mcp"
        manifest_url = origin.rstrip("/") + "/.well-known/mcp.json"
        initialize = await _post_mcp_jsonrpc(client, mcp_url, "initialize", timeout_s=timeout_s, request_id=1)
        tools_list = await _post_mcp_jsonrpc(client, mcp_url, "tools/list", timeout_s=timeout_s, request_id=2)
        manifest = await _get_json(client, manifest_url, timeout_s=timeout_s)
    finally:
        if owns_client:
            await client.aclose()

    tools = _tools_from_payload(tools_list.get("payload") or {})
    quality, issues = _schema_quality(tools)
    score = _score(
        initialize_ok=bool(initialize["ok"]),
        tools_ok=bool(tools_list["ok"] and tools),
        manifest_ok=bool(manifest["ok"]),
        quality=quality,
    )
    verdict = _verdict(score, issues)
    next_action = _next_action(verdict, issues)

    return {
        "ok": True,
        "surface": "delx-agent-utilities",
        "tool_name": "util_mcp_server_readiness_report",
        "url": origin,
        "verdict": verdict,
        "mcp_readiness_score": score,
        "risk_level": "low" if verdict == "ready" else "medium" if verdict == "review_before_use" else "high",
        "checks": {
            "mcp_initialize": {"ok": bool(initialize["ok"]), "status": initialize["status"], "error": initialize["error"]},
            "tools_list": {"ok": bool(tools_list["ok"]), "status": tools_list["status"], "tool_count": len(tools), "error": tools_list["error"]},
            "manifest": {"ok": bool(manifest["ok"]), "status": manifest["status"], "error": manifest["error"]},
        },
        "schema_quality": quality,
        "issues": issues[:20],
        "next_action": next_action,
        "agent_next_action": next_action,
        "deterministic": True,
        "llm_used": False,
    }
