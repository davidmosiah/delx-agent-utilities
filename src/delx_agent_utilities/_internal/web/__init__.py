"""Per-domain web/network tool implementations.

Split out of the former ``_tools_web`` monolith (v0.2.0). Modules:

- ``extract``   — HTML extraction tools (page, open graph, links, feeds, forms, contacts)
- ``network``   — network/DNS/TLS/security tools (robots, sitemap, TLS, headers, RDAP, DNS, email, health)
- ``x402``      — x402 server probing + OpenAPI summarisation
- ``_common``   — small shared URL/keyword helpers used by more than one domain

These are private implementation details. The stable surface is
``delx_agent_utilities.call_util_tool`` / ``list_util_tool_schemas``.
"""
