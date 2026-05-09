"""Quickstart: invoke a few delx-agent-utilities tools from Python."""

from __future__ import annotations

import asyncio

from delx_agent_utilities import call_util_tool, list_util_tool_schemas


async def main() -> None:
    schemas = list_util_tool_schemas()
    print(f"Available tools: {len(schemas)}")

    uuid_result = await call_util_tool("util_uuid_generate", {"count": 3})
    print("uuids:", uuid_result["uuids"])

    hash_result = await call_util_tool(
        "util_hash", {"input": "hello world", "algorithm": "sha256"}
    )
    print("sha256(hello world):", hash_result["hash"])

    cron_result = await call_util_tool(
        "util_cron_describe", {"expression": "0 9 * * mon-fri"}
    )
    print("cron description:", cron_result["description"])


if __name__ == "__main__":
    asyncio.run(main())
