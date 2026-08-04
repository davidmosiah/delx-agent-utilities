"""Delx Agent Utilities — Stateless utility tools for AI agents.

45 deterministic, session-free utilities for everyday agent operations:
URL/HTTP intelligence, MCP readiness, DNS/RDAP, x402 server probing, JWT/JSON/CSV
parsing, encoding/hashing, regex, cron description, and more.

All tools are local-first. No API keys required. No state between calls.

Public API:

>>> from delx_agent_utilities import call_util_tool, list_util_tool_schemas
>>> import asyncio
>>> result = asyncio.run(call_util_tool("util_url_health", {"url": "https://example.com"}))
"""

from .agent import (
    SUPPORTED_CLIENTS,
    build_agent_manifest,
    build_connection_status,
    build_privacy_audit,
)
from .dispatcher import call_util_tool, list_util_tool_schemas
from .schemas import (
    UTIL_REQUIRED_PARAMS,
    UTIL_TOOL_NAMES,
    UTIL_TOOL_SCHEMAS,
)
from .url_clean import url_canonicalize

__version__ = "0.1.2"

__all__ = [
    "SUPPORTED_CLIENTS",
    "UTIL_REQUIRED_PARAMS",
    "UTIL_TOOL_NAMES",
    "UTIL_TOOL_SCHEMAS",
    "build_agent_manifest",
    "build_connection_status",
    "build_privacy_audit",
    "call_util_tool",
    "list_util_tool_schemas",
    "url_canonicalize",
    "__version__",
]
