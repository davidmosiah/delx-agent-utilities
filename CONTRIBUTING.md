# Contributing to delx-agent-utilities

PRs welcome.

## Setup

```bash
git clone https://github.com/davidmosiah/delx-agent-utilities.git
cd delx-agent-utilities
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,mcp]"
pytest
```

## Adding a new tool

1. **Pick a category file** in `src/delx_agent_utilities/_internal/` (encoding, cron, http_codes, jwt_csv, web). If the tool doesn't fit, open a discussion before adding a new file.
2. **Define the handler** as `_<tool_name>(args: dict) -> dict` (or `async def` if it does I/O).
3. **Register it**:
   - Append the canonical name to `UTIL_TOOL_NAMES` in `_internal/_schemas.py`.
   - Add a required-params entry to `UTIL_REQUIRED_PARAMS`.
   - Add an MCP-compatible schema entry to `UTIL_TOOL_SCHEMAS`.
   - Add the dispatcher mapping in `dispatcher.py` (`_HANDLERS`).
4. **Add a test** in `tests/test_dispatcher.py` covering at least one happy path.
5. **Update `README.md` and `llms.txt`** with the new tool.

## Design rules

- **Stateless** — no module-level state between calls, no caches.
- **No API keys** — only public, unauthenticated endpoints.
- **Deterministic** — no LLM calls, no time-of-day dependencies that aren't documented.
- **Fast** — sync tools < 100ms; networked tools < 5s with explicit timeout.
- **MCP-compatible schema** — every tool has `name`, `description`, `inputSchema`.

## v0.2.0 roadmap (good first PRs)

- Split `_internal/_tools_web.py` (~1k LOC) into:
  - `_tools_web_extract.py` (page / open_graph / links / forms / contact / feed)
  - `_tools_network.py` (url_health / robots / sitemap / tls / security_txt / http_headers / dns / rdap)
  - `_tools_x402.py` (x402_server_probe / resource_summary / audit / api_health / openapi_summary)
  - `_tools_composite.py` (website_intel / domain_trust / docs_site_map / pricing / company_contact / api_integration / login_surface / content_distribution)
- One unit-test file per tool (currently we have a single dispatcher smoke).
- Optional `httpx.AsyncClient` reuse for batched probes (would help composite reports).

## Style

- Type hints on every public function.
- Functions in `_internal/` are prefixed with `_` and not part of the stable API.
- Public re-exports live at the top of the package (`agent.py`, `dispatcher.py`, `schemas.py`, `__init__.py`).

## License

MIT. By contributing you agree to license your work under MIT.
