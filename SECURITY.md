# Security Policy

## Scope

This package is a **local, stateless** utility toolkit. It does not store credentials, manage sessions, or call authenticated APIs. The threat surface is limited to:

- Argument parsing for all utility tools (every input is validated by the Zod-like Python schemas before dispatch).
- Outbound HTTP to user-supplied URLs (per-tool target).
- Outbound HTTP to two public endpoints: `rdap.org` (RDAP) and `dns.google` (DNS-over-HTTPS).

No tool reads from `os.environ` for secrets. No tool writes to disk. No tool accepts a callback URL or executes code from a remote source.

## Reporting a vulnerability

Email **david@delx.ai** with the subject `delx-agent-utilities security`.

Please include:
- Affected version(s)
- Reproduction steps
- Suspected impact

Acknowledgement target: 72 hours.
