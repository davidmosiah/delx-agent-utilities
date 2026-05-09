"""Private internal modules — implementation details, not part of the public API.

Public surface lives in `delx_agent_utilities`:
- ``call_util_tool`` / ``list_util_tool_schemas`` (dispatcher)
- ``UTIL_TOOL_NAMES`` / ``UTIL_TOOL_SCHEMAS`` / ``UTIL_REQUIRED_PARAMS`` (schemas)
- ``build_agent_manifest`` / ``build_connection_status`` / ``build_privacy_audit`` (agent)

Direct imports from `_internal.*` are not stable across versions.
"""
