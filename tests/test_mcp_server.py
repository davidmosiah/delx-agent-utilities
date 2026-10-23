"""Exercise the installed MCP runtime, not only dispatcher helpers.

Local dev-only installs skip this test; CI requires the MCP extra and fails
if it is missing. A present but incompatible MCP package must never be skipped.
"""

import importlib.util
import os

import pytest

from delx_agent_utilities.mcp_server import create_mcp
from delx_agent_utilities.schemas import UTIL_TOOL_SCHEMAS


@pytest.mark.asyncio
async def test_mcp_server_constructs_and_lists_all_tools():
    if importlib.util.find_spec("mcp") is None:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("CI requires the MCP extra: install .[dev,mcp]")
        pytest.skip("Optional MCP extra not installed; install .[dev,mcp] to exercise it")
    server = create_mcp()
    tools = await server.list_tools()
    expected = set(UTIL_TOOL_SCHEMAS) | {
        "delx_utilities_manifest",
        "delx_utilities_connection_status",
        "delx_utilities_privacy_audit",
    }
    names = [tool.name for tool in tools]
    assert len(names) == len(expected)
    assert set(names) == expected
