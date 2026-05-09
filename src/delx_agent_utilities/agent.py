"""Standard agent-readiness surfaces used by the CLI and MCP server.

Mirrors the shape of other Delx and `davidmosiah/*` agent-first packages so
agents can call ``manifest``, ``connection_status``, and ``privacy_audit``
before exercising any tool.
"""

from __future__ import annotations

from collections.abc import Mapping

from .schemas import UTIL_TOOL_NAMES

SUPPORTED_CLIENTS = [
    "generic",
    "claude",
    "codex",
    "cursor",
    "windsurf",
    "hermes",
    "openclaw",
]


def _safe_client(client: str = "generic") -> str:
    return client if client in SUPPORTED_CLIENTS else "generic"


def _present(env: Mapping[str, str], key: str) -> bool:
    return bool(str(env.get(key, "")).strip())


def build_agent_manifest(client: str = "generic") -> dict:
    """Return the agent-readiness manifest for the requested client."""
    return {
        "project": "delx-agent-utilities",
        "mcp_name": "io.github.davidmosiah/delx-agent-utilities",
        "client": _safe_client(client),
        "package": {
            "pip": "pipx install delx-agent-utilities[mcp]",
            "cli": "delx-agent-utilities",
            "alias_cli": "delx-utils",
            "mcp": "delx-utils-mcp",
        },
        "supported_clients": SUPPORTED_CLIENTS,
        "tool_count": len(UTIL_TOOL_NAMES),
        "tools": list(UTIL_TOOL_NAMES),
        "recommended_first_calls": [
            "delx_utilities_connection_status",
            "delx_utilities_privacy_audit",
        ],
        "default_mode": "local_offline",
        "design": {
            "stateless": True,
            "deterministic": True,
            "session_free": True,
            "no_api_keys": True,
        },
        "external_endpoints": {
            "rdap_org": "https://rdap.org/domain/<domain>",
            "google_dns": "https://dns.google/resolve",
        },
        "license": "MIT",
        "homepage": "https://github.com/davidmosiah/delx-agent-utilities",
    }


def build_connection_status(env: Mapping[str, str] | None = None) -> dict:
    """Return current runtime status. No network calls."""
    env = env or {}
    return {
        "ok": True,
        "tool_count": len(UTIL_TOOL_NAMES),
        "configured": {
            "DELX_UTILITIES_USER_AGENT": _present(env, "DELX_UTILITIES_USER_AGENT"),
            "DELX_UTILITIES_DEFAULT_TIMEOUT_S": _present(env, "DELX_UTILITIES_DEFAULT_TIMEOUT_S"),
        },
        "next_steps": [
            "Call delx_utilities_privacy_audit before invoking any network tool.",
            "Call any util_* tool by name; see manifest.tools for the full list.",
        ],
    }


def build_privacy_audit() -> dict:
    """Return a self-described privacy posture so agents can reason about safety."""
    return {
        "summary": (
            "Stateless local utilities. Does not require, store, or transmit "
            "API keys or user secrets. Network calls are limited to public, "
            "unauthenticated endpoints (rdap.org for RDAP, dns.google for "
            "DNS-over-HTTPS) plus user-supplied URLs."
        ),
        "stores_state": False,
        "stores_credentials": False,
        "calls_third_parties": True,
        "third_party_endpoints": [
            {"name": "rdap.org", "purpose": "RDAP domain lookup", "auth": "none"},
            {"name": "dns.google", "purpose": "DNS-over-HTTPS", "auth": "none"},
            {
                "name": "user-supplied URL",
                "purpose": "Per-tool target (page extract, x402 probe, etc.)",
                "auth": "none",
            },
        ],
        "logs": [],
        "telemetry": False,
        "rate_limits": {
            "default_timeout_seconds": 8,
            "url_health_timeout_seconds": 8,
            "guidance": (
                "Caller is responsible for rate-limiting tool invocations. "
                "Public endpoints (rdap.org, dns.google) have their own limits "
                "that vary; treat them as best-effort."
            ),
        },
        "recommended_use": [
            "Local agent reasoning / pre-flight checks",
            "x402 ecosystem discovery and audits",
            "Web/API readiness probes before integration",
        ],
        "non_use": [
            "Authoritative DNS / WHOIS verification",
            "High-throughput automated scraping",
            "Credential or PII handling",
        ],
    }
