# Migrating from 0.1.10 to 0.2.0

The pinned public HTTP transport is intentionally incompatible with proxy-required environments: a nonempty scheme-relevant `HTTP_PROXY` or `HTTPS_PROXY`, or `ALL_PROXY` (including lowercase), fails closed. `NO_PROXY` does not override this. Do not remove organizational egress controls to work around the error; use an approved environment or wait for a safely designed proxy mode.

This transport uses HTTP/1.1, does not retain a cookie jar, requests identity encoding and rejects compressed responses. A response body is limited to 8 MiB per hop. It validates each public destination and redirect, pins the connection, verifies TLS using the original host, and requires TLS 1.2 or newer. See [NETWORK_SECURITY.md](NETWORK_SECURITY.md) for limits and exact scope. These guarantees apply to the pinned public HTTP/TLS inspection paths, not automatically to every provider-specific client in the toolkit. Assess trust and outbound access for each tool and runtime profile, including the CLI, before running it.

For MCP install the compatible SDK range `mcp>=1.30.0,<2`. Check your integrations and response-size assumptions before upgrading; test with representative controlled endpoints.

`util_mcp_server_readiness_report` uses pinned public destinations for each request, rejects redirects and URL credentials, and caps each response at 200,000 bytes. MCP endpoints requiring redirects, credentials, proxies or responses above that limit will fail. A caller-supplied HTTP client is no longer supported.
