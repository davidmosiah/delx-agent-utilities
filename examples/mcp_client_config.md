# MCP client configuration examples

## Claude Desktop / Cursor / Windsurf

`~/.config/<client>/mcp_settings.json` (path varies):

```json
{
  "mcpServers": {
    "delx-utils": {
      "command": "delx-utils-mcp"
    }
  }
}
```

Run `delx-utilities_manifest` first; it returns the full tool list and recommended-first-calls so the client can introspect.

## Hermes Agent (`~/.hermes/config.yaml`)

```yaml
mcp_servers:
  delx-utils:
    command: delx-utils-mcp
```

## OpenClaw (`~/.openclaw/openclaw.json` `plugins` block)

OpenClaw discovers MCP servers via the `entrypoint` field; add a manual entry pointing at the binary if your runtime doesn't auto-discover from the MCP registry.

## CLI (no MCP client required)

```bash
delx-utils manifest
delx-utils call util_url_health --json '{"url":"https://example.com"}'
delx-utils call util_jwt_inspect --json '{"token":"eyJ..."}'
```
