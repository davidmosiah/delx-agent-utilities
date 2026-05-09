# Agent Development Notes

## Scope

`delx-agent-utilities` is a stateless, MCP-compatible toolkit. 40 utility tools + 3 agent-readiness surfaces (`manifest` / `connection_status` / `privacy_audit`).

## Commands

- Install: `pipx install "delx-agent-utilities[mcp]"` or `pip install -e ".[dev,mcp]"`
- Test: `pytest`
- CLI: `delx-utils <subcommand>` (`manifest`, `status`, `privacy-audit`, `list-tools`, `show <tool>`, `call <tool> --json '{...}'`)
- MCP server: `delx-utils-mcp` (stdio, FastMCP-based)

## Rules for changes

- Never add a tool that requires an API key, OAuth flow, or stored credential.
- Never add module-level state (caches / counters / handles) between calls.
- Networked tools must have an explicit per-call timeout (default 8s).
- Add a regression test for every new tool in `tests/test_dispatcher.py`.
- Keep schemas.py in sync with the dispatcher (`_HANDLERS` map) and the README tool list.
