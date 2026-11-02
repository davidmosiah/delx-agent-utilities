"""Deterministic MCP server readiness reporting."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any
from urllib.parse import urlsplit

from ._public_http import _request_public_http

_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_USER_AGENT = "DelxAgentUtilities/0.1 mcp-readiness"


def _normalize_origin(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return ""
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}"
    except ValueError:
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


async def _probe(url: str, method: str, *, deadline: float, payload: dict | None = None) -> dict[str, Any]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("readiness deadline exceeded")
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    status, raw, _, _ = await asyncio.to_thread(
        _request_public_http, url, timeout=remaining, method=method, max_bytes=200_000, body=body
    )
    if 300 <= status < 400:
        raise ValueError("redirects are not supported")
    try:
        parsed = json.loads(raw) if raw else {}
    except (UnicodeDecodeError, ValueError):
        return {"ok": False, "status": status, "payload": {}, "error": "invalid JSON response"}
    return {"ok": 200 <= status < 300 and isinstance(parsed, dict) and "error" not in parsed,
            "status": status, "payload": parsed if isinstance(parsed, dict) else {}, "error": ""}


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


async def build_mcp_server_readiness_report(args: dict[str, Any], *, http_client: Any = None) -> dict[str, Any]:
    tool_name = "util_mcp_server_readiness_report"
    if http_client is not None:
        return {"error": "unsupported_client", "tool_name": tool_name}
    origin = _normalize_origin(str(args.get("url") or ""))
    if not origin:
        return {"error": "invalid or blocked URL", "tool_name": tool_name, "required": ["url"]}
    try:
        timeout_s = max(1, min(15, int(args.get("timeout") or 8)))
        deadline = time.monotonic() + timeout_s
        mcp_url = origin + "/mcp"
        initialize = await _probe(mcp_url, "POST", deadline=deadline, payload=_json_rpc_payload("initialize", 1))
        tools_list = await _probe(mcp_url, "POST", deadline=deadline, payload=_json_rpc_payload("tools/list", 2))
        manifest = await _probe(origin + "/.well-known/mcp.json", "GET", deadline=deadline)
    except TimeoutError:
        return {"error": "timeout", "tool_name": tool_name}
    except ValueError as exc:
        reason = "redirects are not supported" if "redirects are not supported" in str(exc) else "response or network destination rejected"
        return {"error": "probe_blocked", "reason": reason, "tool_name": tool_name}
    except Exception:
        return {"error": "probe_failed", "reason": "network or response failure", "tool_name": tool_name}

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
