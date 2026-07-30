# Changelog

## Unreleased
- Internal refactor: split the ~1k-LOC `_internal/_tools_web` monolith into per-domain modules under `_internal/web/` (`extract`, `network`, `x402`, plus shared `_common` helpers). The composite report tools stay in `_tools_web`, which now re-exports every leaf so all existing imports and patch targets are unchanged. No public API, tool names, or behaviour changed; added per-domain tests.
- Run the independent x402 endpoint checks concurrently, then fetch discovered resource and tool counts concurrently. This preserves the response contract while bounding the probe by network phases instead of the sum of seven request timeouts.

## 0.1.2 - 2026-05-22
- Add `url_canonicalize(url)` pure helper that lowercases scheme/host, drops default ports, strips `utm_*`, `gclid`, `fbclid`, `mc_eid`, `ref`, `ref_src` and related tracking params, sorts the surviving query, and optionally preserves a meaningful fragment. Useful for cache keys and dedup.
- Exposes `url_canonicalize` from package root.

## 0.1.1
- Contact/support email surfaced across docs and manifest.
