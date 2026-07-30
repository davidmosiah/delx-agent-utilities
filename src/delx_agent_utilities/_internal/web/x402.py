"""x402 server probing and OpenAPI specification summarisation."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .._helpers import (
    _fetch_json_response,
    _fetch_text_response,
    _parse_int,
)
from ._common import _keyword_hits, _origin_from_url


async def _x402_server_probe(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 8), default=8)
    except ValueError as e:
        return {"error": str(e), "field": "timeout", "expected": "integer (1-15)"}
    origin = _origin_from_url(url)
    check_specs = [
        ("x402_discovery", "/.well-known/x402"),
        ("status", "/api/v1/status"),
        ("tools", "/api/v1/tools?format=ultracompact"),
        ("reliability", "/api/v1/reliability"),
        ("openapi", "/spec/openapi.json"),
    ]

    async def run_check(name: str, path: str) -> dict[str, Any]:
        target = origin.rstrip("/") + path
        response, error = await _fetch_text_response(target, timeout_s=timeout_s)
        return {
            "name": name,
            "url": target,
            "status": int(response.status_code) if response else 0,
            "reachable": bool(response and 200 <= int(response.status_code) < 400),
            "error": error or "",
        }

    checks = await asyncio.gather(
        *(run_check(name, path) for name, path in check_specs)
    )
    x402_check = next((row for row in checks if row["name"] == "x402_discovery" and row["reachable"]), None)
    tools_check = next((row for row in checks if row["name"] == "tools" and row["reachable"]), None)

    async def read_resource_count() -> int:
        if not x402_check:
            return 0
        _, payload, error = await _fetch_json_response(x402_check["url"], timeout_s=timeout_s)
        if not error and isinstance(payload, dict):
            resources = payload.get("resourceCatalog")
            if not isinstance(resources, list):
                resources = payload.get("resources") or []
            return len(resources)
        return 0

    async def read_tool_count() -> int:
        if not tools_check:
            return 0
        _, payload, error = await _fetch_json_response(tools_check["url"], timeout_s=timeout_s)
        if not error and isinstance(payload, dict):
            return int(payload.get("count") or 0)
        return 0

    resource_count, tool_count = await asyncio.gather(
        read_resource_count(),
        read_tool_count(),
    )
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
        return {
            "url": origin,
            "reachable": False,
            "status": int(response.status_code) if response else 0,
            "resource_count": 0,
            "networks": [],
            "resources": [],
            "warning": error or "fetch failed",
            "error": error or "fetch failed",
        }
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
