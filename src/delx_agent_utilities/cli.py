"""Command-line interface for delx-agent-utilities.

Usage:
    delx-agent-utilities manifest [--client <name>]
    delx-agent-utilities status
    delx-agent-utilities privacy-audit
    delx-agent-utilities list-tools
    delx-agent-utilities call <tool_name> --json '{"key": "value"}'

The CLI is a thin wrapper over the public dispatcher; see ``call_util_tool``
in ``delx_agent_utilities`` for programmatic access.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from .agent import build_agent_manifest, build_connection_status, build_privacy_audit
from .dispatcher import call_util_tool
from .schemas import UTIL_TOOL_NAMES, UTIL_TOOL_SCHEMAS


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="delx-agent-utilities",
        description="Stateless utility tools for AI agents (40 tools).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="Print agent-readiness manifest.")
    manifest.add_argument("--client", default="generic")

    sub.add_parser("status", help="Print connection status.")
    sub.add_parser("privacy-audit", help="Print privacy posture.")
    sub.add_parser("list-tools", help="List the 40 util tool names.")

    show = sub.add_parser("show", help="Show a single tool's schema.")
    show.add_argument("tool", help="Tool name, e.g. util_url_health")

    call = sub.add_parser("call", help="Invoke a tool with JSON-encoded args.")
    call.add_argument("tool", help="Tool name, e.g. util_url_health")
    call.add_argument(
        "--json",
        dest="payload",
        default="{}",
        help="JSON-encoded argument object. Default: {}",
    )

    args = parser.parse_args(argv)

    if args.command == "manifest":
        _print_json(build_agent_manifest(args.client))
        return 0

    if args.command == "status":
        _print_json(build_connection_status(os.environ))
        return 0

    if args.command == "privacy-audit":
        _print_json(build_privacy_audit())
        return 0

    if args.command == "list-tools":
        _print_json({"count": len(UTIL_TOOL_NAMES), "tools": list(UTIL_TOOL_NAMES)})
        return 0

    if args.command == "show":
        schema = UTIL_TOOL_SCHEMAS.get(args.tool)
        if schema is None:
            print(f"Unknown tool: {args.tool}", file=sys.stderr)
            return 2
        _print_json(schema)
        return 0

    if args.command == "call":
        try:
            payload = json.loads(args.payload) if args.payload else {}
        except json.JSONDecodeError as exc:
            print(f"Invalid --json payload: {exc}", file=sys.stderr)
            return 2
        if not isinstance(payload, dict):
            print("--json payload must be a JSON object.", file=sys.stderr)
            return 2
        result = asyncio.run(call_util_tool(args.tool, payload))
        _print_json(result)
        return 0 if "error" not in result else 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
