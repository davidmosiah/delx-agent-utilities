# Public HTTP/TLS destination policy

URL inspection/extraction and TLS inspection are public-internet utilities, not
internal-network probes. Each TCP connection resolves once, rejects any non-public
answer, and connects directly to a numeric address from that validated set.
Each redirect is a new validated connection (maximum five redirects). The HTTP
Host header, TLS SNI and certificate verification use the original DNS identity,
not the pinned address. Certificate validation failures are never retried with an
insecure client. Mixed public/private DNS responses are rejected as a whole.

## Compatibility changes

- HTTP requests now use direct HTTP/1.1 connections. Nonempty `HTTP_PROXY` for
  HTTP, `HTTPS_PROXY` for HTTPS, or `ALL_PROXY` for either scheme (including
  lowercase variants) cause a clear fail-closed error before DNS or connection.
  Empty values do not configure a proxy. `NO_PROXY` alone has no effect; it does
  not override a configured proxy because bypass rules are not implemented.
  Proxy values/credentials are never included in this diagnostic. This is NOT a
  drop-in transport for proxy-required environments. A future explicit proxy
  mode needs a trusted-proxy destination-validation design; ordinary forwarding
  or CONNECT would undo numeric pinning. No environment setting is auto-mutated.
- Only HTTP(S) GET and HEAD are supported. URL userinfo credentials are rejected.
  Requests do not retain cookies between redirects or send authorization headers.
- Responses negotiate `Accept-Encoding: identity`; a nonidentity response is
  rejected explicitly rather than automatically decompressed. Maximum body is
  8 MiB per hop, including error and redirect responses. HEAD does not read a body.
- HTTP error status codes remain inspectable responses. Text charset, final URL,
  status and reason fields are retained. Redirects may cross public hosts/schemes
  but each destination undergoes the same policy and fresh numeric pinning.
- Scoped IPv6, 6to4/Teredo and standardized NAT64 prefixes are conservatively
  rejected; mapped IPv4 addresses must have a public underlying IPv4 address.
  No arbitrary public domain denylist is used.

## Limits

The per-call timeout covers redirect/connect/read budgets, but OS DNS resolution
cannot be interrupted by this synchronous resolver. Socket/header reads and internal chunk-framing reads use
inactivity timeouts; an attacker trickling headers or chunk extensions can keep
a parser operation alive beyond the budget checks between operations; this is not a strict real-time cancellation guarantee. No
concurrency quota or protection from a compromised operating system/custom network
routing is implied. IP classification can vary by supported Python version and
must be included in the release test matrix. Direct pinning does not prevent a
public website from independently offering a server-side proxy to other systems.

Production verification must include the supported Python/OS matrix, full toolkit
regressions and a controlled TLS integration test. Offline fake-socket tests do
not verify real certificate chains or production routing.
