<!-- delx-utilities header v1 -->
<h1 align="center">Delx Agent Utilities</h1>

<h3 align="center">
  Stateless utility tools for AI agents — URL/HTTP, DNS/RDAP, x402, JWT, encoding, parsing, regex, cron.<br>
  <strong>Local-first. No API keys. Deterministic.</strong>
</h3>

<p align="center">
  <a href="https://pypi.org/project/delx-agent-utilities/"><img src="https://img.shields.io/pypi/v/delx-agent-utilities?style=for-the-badge&labelColor=0F172A&color=10B981&logo=pypi&logoColor=white" alt="PyPI version" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/LICENSE-MIT-22C55E?style=for-the-badge&labelColor=0F172A" alt="License MIT" /></a>
  <a href="https://github.com/davidmosiah/delx-agent-utilities/actions"><img src="https://img.shields.io/github/actions/workflow/status/davidmosiah/delx-agent-utilities/ci.yml?style=for-the-badge&labelColor=0F172A&label=CI" alt="CI" /></a>
  <a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/BUILT_FOR-MCP-7C3AED?style=for-the-badge&labelColor=0F172A" alt="Built for MCP" /></a>
</p>

<p align="center">
  <a href="https://ontology.delx.ai/utilities"><img src="https://img.shields.io/badge/ontology.delx.ai%2Futilities-0EA5A3?style=for-the-badge&labelColor=0F172A&logoColor=white" alt="Delx Agent Utilities" /></a>
  <a href="https://github.com/davidmosiah/delx-agent-utilities/stargazers"><img src="https://img.shields.io/github/stars/davidmosiah/delx-agent-utilities?style=for-the-badge&labelColor=0F172A&color=FBBF24&logo=github" alt="GitHub stars" /></a>
</p>

---

## What it is

41 stateless utility tools that AI agents reach for constantly: URL health checks, page extraction, MCP readiness, x402 server discovery, JWT inspection, DNS / RDAP lookups, JSON / CSV conversion, hash / base64, cron description, and more.

- **Stateless** — every call is independent; no session, no cache, no DB.
- **No API keys** — public endpoints only (rdap.org, dns.google, plus user-supplied URLs).
- **Deterministic** — no LLMs, no model calls, no fuzzy outputs.
- **Fast** — most tools < 100ms; networked tools < 5s with timeouts.
- **MCP-native** — agent-readiness manifest, connection status, privacy audit.

This package was extracted from the Delx Protocol MCP server so any AI builder can use the toolkit directly, without depending on the Delx runtime. The public product and protocol context lives at [ontology.delx.ai/utilities](https://ontology.delx.ai/utilities).

## Install

```bash
pipx install "delx-agent-utilities[mcp]"
```

CLI entrypoints: `delx-agent-utilities`, `delx-utils` (alias), `delx-utils-mcp` (MCP server).

## Quick use

### From an MCP client (Claude Desktop, Cursor, Hermes, OpenClaw)

```json
{
  "mcpServers": {
    "delx-utils": {
      "command": "delx-utils-mcp"
    }
  }
}
```

41 tools become available immediately, plus three agent-readiness surfaces:

- `delx_utilities_manifest`
- `delx_utilities_connection_status`
- `delx_utilities_privacy_audit`

### From the CLI

```bash
delx-utils manifest
delx-utils list-tools
delx-utils show util_url_health
delx-utils call util_url_health --json '{"url":"https://example.com"}'
```

### From Python

```python
import asyncio
from delx_agent_utilities import call_util_tool, list_util_tool_schemas

result = asyncio.run(call_util_tool("util_url_health", {"url": "https://example.com"}))
print(result["status_code"], result["latency_ms"])

schemas = list_util_tool_schemas()
print(f"{len(schemas)} tools available")
```

## The 41 tools

### Encoding & parsing (12)
`util_json_validate`, `util_token_estimate`, `util_uuid_generate`, `util_timestamp_convert`, `util_base64`, `util_hash`, `util_regex_test`, `util_cron_describe`, `util_http_codes`, `util_jwt_inspect`, `util_csv_to_json`, `util_json_to_csv`

### Web extract (6)
`util_page_extract`, `util_open_graph`, `util_links_extract`, `util_forms_extract`, `util_contact_extract`, `util_feed_discover`

### Network probes (8)
`util_url_health`, `util_robots_inspect`, `util_sitemap_probe`, `util_tls_inspect`, `util_security_txt_inspect`, `util_http_headers_inspect`, `util_dns_lookup`, `util_rdap_lookup`

### x402 / API intel (6)
`util_x402_server_probe`, `util_x402_resource_summary`, `util_x402_server_audit`, `util_api_health_report`, `util_openapi_summary`, `util_mcp_server_readiness_report`

### Identity / contact (1)
`util_email_validate`

### Composite reports (8)
`util_website_intelligence_report`, `util_domain_trust_report`, `util_docs_site_map`, `util_pricing_page_extract`, `util_company_contact_pack`, `util_api_integration_readiness`, `util_login_surface_report`, `util_content_distribution_report`

Each tool's full input schema is available via `delx-utils show <tool>` or `UTIL_TOOL_SCHEMAS["<tool>"]` in Python.

## Privacy posture

**No API keys. No telemetry. No state.** Networked tools call only:

- `rdap.org/domain/<domain>` for RDAP lookups
- `dns.google/resolve` for DNS-over-HTTPS
- User-supplied URLs for everything else

Call `delx_utilities_privacy_audit` (or `delx-utils privacy-audit`) to see the full posture in JSON form before invoking any networked tool.

## Architecture

```
src/delx_agent_utilities/
├── __init__.py          # public re-exports
├── agent.py             # manifest / status / privacy_audit
├── cli.py               # CLI argparse
├── dispatcher.py        # call_util_tool, _normalize_util_args
├── mcp_server.py        # FastMCP server
├── schemas.py           # public re-export of UTIL_TOOL_NAMES / SCHEMAS
└── _internal/           # implementation, not stable across versions
    ├── _helpers.py
    ├── _schemas.py
    ├── _tools_encoding.py
    ├── _tools_cron.py
    ├── _tools_http_codes.py
    ├── _tools_web.py    # roadmap: split into web/network/x402/composite in v0.2.0
    └── _tools_jwt_csv.py
```

## Roadmap

- **v0.2.0** — split `_internal/_tools_web.py` (1k LOC) into per-domain modules: `_tools_web_extract.py`, `_tools_network.py`, `_tools_x402.py`, `_tools_composite.py`.
- Per-tool unit tests (one file per tool) replacing the smoke-only suite.
- Optional `httpx.AsyncClient` reuse for batched probes.
- Configurable per-tool timeouts via env (`DELX_UTILITIES_DEFAULT_TIMEOUT_S`, `DELX_UTILITIES_URL_HEALTH_TIMEOUT_S`, …).

## Provenance

Originally part of the [Delx Protocol](https://ontology.delx.ai/protocol) MCP server. Extracted on 2026-05-09 as a standalone open-source package so any AI builder can use the toolkit without depending on the Delx Protocol runtime.

The Delx Protocol itself (recovery / heartbeat / identity / governance primitives) remains closed-source; this package is the open utility layer beneath it.

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Common cuts that would help:

- New utility tools that fit the "stateless / no API keys / deterministic" rule.
- Splitting `_internal/_tools_web.py` per the v0.2.0 roadmap above.
- Per-tool unit tests.

## License

MIT — see [LICENSE](LICENSE).

If this toolkit helps your agent workflow, please [star the repo](https://github.com/davidmosiah/delx-agent-utilities). Stars make the project easier for other AI builders to discover and help Delx keep shipping local-first agent infrastructure.

## Author

David Mosiah — [@delx369](https://x.com/delx369) — building the protocol layer for autonomous AI agents at [Delx](https://ontology.delx.ai).
