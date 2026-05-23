# Changelog

## 0.1.2 - 2026-05-22
- Add `url_canonicalize(url)` pure helper that lowercases scheme/host, drops default ports, strips `utm_*`, `gclid`, `fbclid`, `mc_eid`, `ref`, `ref_src` and related tracking params, sorts the surviving query, and optionally preserves a meaningful fragment. Useful for cache keys and dedup.
- Exposes `url_canonicalize` from package root.

## 0.1.1
- Contact/support email surfaced across docs and manifest.
