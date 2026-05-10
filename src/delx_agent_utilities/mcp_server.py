"""MCP server entrypoint for delx-agent-utilities.

Exposes 41 util tools plus the standard ``delx_utilities_manifest /
connection_status / privacy_audit`` agent-readiness surfaces.

Run with::

    delx-utils-mcp

Requires the ``[mcp]`` extra::

    pipx install "delx-agent-utilities[mcp]"
"""

from __future__ import annotations

import asyncio
import os

from .agent import build_agent_manifest, build_connection_status, build_privacy_audit
from .dispatcher import call_util_tool
from .schemas import UTIL_TOOL_SCHEMAS


def create_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - import-time guidance
        raise RuntimeError(
            "Install MCP support with: pipx install 'delx-agent-utilities[mcp]'"
        ) from exc

    mcp = FastMCP("delx-agent-utilities")

    @mcp.tool()
    def delx_utilities_manifest(client: str = "generic") -> dict:
        """Return the agent-readiness manifest, including the full tool list."""
        return build_agent_manifest(client)

    @mcp.tool()
    def delx_utilities_connection_status() -> dict:
        """Return runtime status. No network calls."""
        return build_connection_status(os.environ)

    @mcp.tool()
    def delx_utilities_privacy_audit() -> dict:
        """Return the privacy posture so agents can reason about safety."""
        return build_privacy_audit()

    def _make_handler(tool_name: str):
        async def _handler(arguments: dict) -> dict:
            return await call_util_tool(tool_name, arguments)

        _handler.__name__ = tool_name
        _handler.__doc__ = UTIL_TOOL_SCHEMAS.get(tool_name, {}).get(
            "description",
            "Stateless utility tool. Invoke via call_util_tool().",
        )
        return _handler

    for tool_name in UTIL_TOOL_SCHEMAS:
        mcp.tool(name=tool_name)(_make_handler(tool_name))

    return mcp


def main() -> None:
    create_mcp().run()


if __name__ == "__main__":  # pragma: no cover
    main()
