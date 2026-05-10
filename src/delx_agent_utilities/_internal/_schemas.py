"""Tool registry - names, required params, and MCP-compatible schemas for all utilities."""

from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import inspect
import io
import json
import re
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urljoin, urlparse

import httpx


# ─── Tool Registry ────────────────────────────────────────────────────

UTIL_TOOL_NAMES: list[str] = [
    "util_json_validate",
    "util_token_estimate",
    "util_uuid_generate",
    "util_timestamp_convert",
    "util_base64",
    "util_url_health",
    "util_hash",
    "util_regex_test",
    "util_cron_describe",
    "util_http_codes",
]

UTIL_REQUIRED_PARAMS: dict[str, list[str]] = {
    "util_json_validate": ["input"],
    "util_token_estimate": ["text"],
    "util_uuid_generate": [],
    "util_timestamp_convert": ["input"],
    "util_base64": ["input", "action"],
    "util_url_health": ["url"],
    "util_hash": ["input"],
    "util_regex_test": ["pattern", "text"],
    "util_cron_describe": ["expression"],
    "util_http_codes": [],
}

UTIL_TOOL_SCHEMAS: dict[str, dict] = {
    "util_json_validate": {
        "name": "util_json_validate",
        "description": "Validate and pretty-print JSON. Returns validity, errors, and formatted output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "JSON string to validate"},
            },
            "required": ["input"],
        },
    },
    "util_token_estimate": {
        "name": "util_token_estimate",
        "description": "Estimate token count for text. Uses word/4 heuristic (GPT-family) and char/4 (Claude-family).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to estimate tokens for"},
                "model": {"type": "string", "description": "Optional model hint: gpt-4, claude-3, etc.", "default": "gpt-4"},
            },
            "required": ["text"],
        },
    },
    "util_uuid_generate": {
        "name": "util_uuid_generate",
        "description": "Generate one or more UUIDv4 strings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of UUIDs (1-10)", "default": 1, "minimum": 1, "maximum": 10},
            },
        },
    },
    "util_timestamp_convert": {
        "name": "util_timestamp_convert",
        "description": "Convert between timestamp formats: Unix epoch, ISO 8601, and human-readable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Timestamp: Unix epoch (seconds), ISO 8601 string, or 'now'"},
                "to": {"type": "string", "description": "Target format", "enum": ["all", "unix", "iso", "human"], "default": "all"},
            },
            "required": ["input"],
        },
    },
    "util_base64": {
        "name": "util_base64",
        "description": "Encode or decode Base64 strings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "String to encode or Base64 string to decode"},
                "action": {"type": "string", "description": "Action to perform", "enum": ["encode", "decode"]},
            },
            "required": ["input", "action"],
        },
    },
    "util_url_health": {
        "name": "util_url_health",
        "description": "Check if a URL is reachable. Returns HTTP status, latency, and key headers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to check (must start with http:// or https://)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (1-10)", "default": 5, "minimum": 1, "maximum": 10},
            },
            "required": ["url"],
        },
    },
    "util_hash": {
        "name": "util_hash",
        "description": "Hash a string with SHA-256, SHA-1, or MD5.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "String to hash"},
                "algorithm": {"type": "string", "description": "Hash algorithm", "enum": ["sha256", "sha1", "md5"], "default": "sha256"},
            },
            "required": ["input"],
        },
    },
    "util_regex_test": {
        "name": "util_regex_test",
        "description": "Test a regex pattern against text. Returns matches, groups, and count.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression pattern"},
                "text": {"type": "string", "description": "Text to test against"},
                "flags": {"type": "string", "description": "Optional flags: i=ignorecase, m=multiline, s=dotall", "default": ""},
            },
            "required": ["pattern", "text"],
        },
    },
    "util_cron_describe": {
        "name": "util_cron_describe",
        "description": "Validate and describe a cron expression in plain English. Shows next 5 scheduled runs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Cron expression (5 fields: min hour dom month dow)"},
            },
            "required": ["expression"],
        },
    },
    "util_http_codes": {
        "name": "util_http_codes",
        "description": "Look up HTTP status codes. Returns name, description, and category. Without code param, returns common codes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "integer", "description": "HTTP status code (100-599). Omit for full reference."},
            },
        },
    },
}

PAID_UTILITY_TOOL_NAMES: list[str] = [
    "util_page_extract",
    "util_open_graph",
    "util_links_extract",
    "util_sitemap_probe",
    "util_robots_inspect",
    "util_dns_lookup",
    "util_email_validate",
    "util_jwt_inspect",
    "util_csv_to_json",
    "util_json_to_csv",
]

UTIL_TOOL_NAMES.extend(PAID_UTILITY_TOOL_NAMES)
UTIL_REQUIRED_PARAMS.update(
    {
        "util_page_extract": ["url"],
        "util_open_graph": ["url"],
        "util_links_extract": ["url"],
        "util_sitemap_probe": ["url"],
        "util_robots_inspect": ["url"],
        "util_dns_lookup": ["domain"],
        "util_email_validate": ["email"],
        "util_jwt_inspect": ["token"],
        "util_csv_to_json": ["csv_text"],
        "util_json_to_csv": ["json_text"],
    }
)
UTIL_TOOL_SCHEMAS.update(
    {
        "util_page_extract": {
            "name": "util_page_extract",
            "description": "Turn any URL into clean page metadata and readable text for search, routing, and summarization.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_open_graph": {
            "name": "util_open_graph",
            "description": "Extract Open Graph and Twitter card fields to preview how a URL will render in feeds and agents.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_links_extract": {
            "name": "util_links_extract",
            "description": "Map internal and external links on a page for crawling, routing, and site inspection.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                    "limit": {"type": "integer", "description": "Maximum links to return (1-100)", "default": 25, "minimum": 1, "maximum": 100},
                },
                "required": ["url"],
            },
        },
        "util_sitemap_probe": {
            "name": "util_sitemap_probe",
            "description": "Check sitemap and crawl-structure hints fast to see how a site exposes crawlable structure.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Domain or URL to probe"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_robots_inspect": {
            "name": "util_robots_inspect",
            "description": "Read robots.txt rules and sitemap declarations before crawling or indexing a domain.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Domain or URL to inspect"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_dns_lookup": {
            "name": "util_dns_lookup",
            "description": "Resolve A, AAAA, CNAME, MX, TXT, and NS records for fast domain and delivery checks.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain to resolve"},
                    "record_type": {"type": "string", "description": "DNS record type", "enum": ["A", "AAAA", "CNAME", "MX", "NS", "TXT"], "default": "A"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["domain"],
            },
        },
        "util_email_validate": {
            "name": "util_email_validate",
            "description": "Validate an email and its domain-level delivery records before outreach, signup, or routing.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "description": "Email address to validate"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["email"],
            },
        },
        "util_jwt_inspect": {
            "name": "util_jwt_inspect",
            "description": "Decode JWT claims quickly for auth debugging, routing, and token inspection.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "token": {"type": "string", "description": "JWT token"},
                },
                "required": ["token"],
            },
        },
        "util_csv_to_json": {
            "name": "util_csv_to_json",
            "description": "Convert raw CSV into JSON rows for downstream agents, prompts, and ETL steps.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "csv_text": {"type": "string", "description": "CSV document"},
                    "delimiter": {"type": "string", "description": "Optional one-character delimiter", "default": ","},
                },
                "required": ["csv_text"],
            },
        },
        "util_json_to_csv": {
            "name": "util_json_to_csv",
            "description": "Convert structured JSON rows into CSV for exports, spreadsheets, and handoff.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "json_text": {"type": "string", "description": "JSON array or object"},
                    "delimiter": {"type": "string", "description": "Optional one-character delimiter", "default": ","},
                },
                "required": ["json_text"],
            },
        },
    }
)

ADVANCED_PAID_UTILITY_TOOL_NAMES: list[str] = [
    "util_tls_inspect",
    "util_security_txt_inspect",
    "util_http_headers_inspect",
    "util_feed_discover",
    "util_forms_extract",
    "util_contact_extract",
    "util_rdap_lookup",
    "util_api_health_report",
    "util_x402_server_probe",
    "util_x402_resource_summary",
]

COMPOSITE_PAID_UTILITY_TOOL_NAMES: list[str] = [
    "util_website_intelligence_report",
    "util_domain_trust_report",
    "util_openapi_summary",
    "util_x402_server_audit",
    "util_mcp_server_readiness_report",
    "util_docs_site_map",
    "util_pricing_page_extract",
    "util_company_contact_pack",
    "util_api_integration_readiness",
    "util_login_surface_report",
    "util_content_distribution_report",
]

UTIL_TOOL_NAMES.extend(ADVANCED_PAID_UTILITY_TOOL_NAMES)
UTIL_TOOL_NAMES.extend(COMPOSITE_PAID_UTILITY_TOOL_NAMES)
UTIL_REQUIRED_PARAMS.update(
    {
        "util_tls_inspect": ["url"],
        "util_security_txt_inspect": ["url"],
        "util_http_headers_inspect": ["url"],
        "util_feed_discover": ["url"],
        "util_forms_extract": ["url"],
        "util_contact_extract": ["url"],
        "util_rdap_lookup": ["domain"],
        "util_api_health_report": ["url"],
        "util_x402_server_probe": ["url"],
        "util_x402_resource_summary": ["url"],
        "util_website_intelligence_report": ["url"],
        "util_domain_trust_report": ["url"],
        "util_openapi_summary": ["url"],
        "util_x402_server_audit": ["url"],
        "util_mcp_server_readiness_report": ["url"],
        "util_docs_site_map": ["url"],
        "util_pricing_page_extract": ["url"],
        "util_company_contact_pack": ["url"],
        "util_api_integration_readiness": ["url"],
        "util_login_surface_report": ["url"],
        "util_content_distribution_report": ["url"],
    }
)
UTIL_TOOL_SCHEMAS.update(
    {
        "util_tls_inspect": {
            "name": "util_tls_inspect",
            "description": "Inspect TLS issuer, subject, SANs, and expiry to check trust and renewal risk.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTPS URL or hostname to inspect"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_security_txt_inspect": {
            "name": "util_security_txt_inspect",
            "description": "Find security.txt contacts, disclosure policy, and trust links for a domain.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Origin or URL to inspect"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_http_headers_inspect": {
            "name": "util_http_headers_inspect",
            "description": "Inspect security, cache, redirect, and server headers to audit a URL quickly.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to inspect"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_feed_discover": {
            "name": "util_feed_discover",
            "description": "Find RSS, Atom, and JSON feeds so agents can subscribe instead of scrape.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to inspect"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_forms_extract": {
            "name": "util_forms_extract",
            "description": "Extract forms, methods, actions, and fields for browser automation and workflow planning.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to inspect"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_contact_extract": {
            "name": "util_contact_extract",
            "description": "Extract emails, phones, and social links from a page for outreach, routing, and support.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to inspect"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_rdap_lookup": {
            "name": "util_rdap_lookup",
            "description": "Fetch registrar, status, and registration dates for trust, compliance, and domain ops.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain to inspect"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["domain"],
            },
        },
        "util_api_health_report": {
            "name": "util_api_health_report",
            "description": "Measure endpoint status, latency, redirects, content type, and reachability in one call.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to probe"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_x402_server_probe": {
            "name": "util_x402_server_probe",
            "description": "Probe an x402 server end-to-end: discovery, status, tools, reliability, and OpenAPI.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "x402 server origin"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_x402_resource_summary": {
            "name": "util_x402_resource_summary",
            "description": "Summarize a server's .well-known/x402 resources, pricing surface, networks, and paths.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "x402 server origin"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["url"],
            },
        },
        "util_website_intelligence_report": {
            "name": "util_website_intelligence_report",
            "description": "Composite website intelligence report with page, social, link, form, feed, and contact signals.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "URL to inspect"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15}}, "required": ["url"]},
        },
        "util_domain_trust_report": {
            "name": "util_domain_trust_report",
            "description": "Composite trust report with TLS, security.txt, headers, RDAP, DNS, and uptime signals.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "Domain or URL to inspect"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15}}, "required": ["url"]},
        },
        "util_openapi_summary": {
            "name": "util_openapi_summary",
            "description": "Summarize an OpenAPI document including title, version, paths, tags, and likely auth surface.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "Origin or direct OpenAPI URL"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15}}, "required": ["url"]},
        },
        "util_x402_server_audit": {
            "name": "util_x402_server_audit",
            "description": "Audit an x402 server with discovery, pricing, reliability, and documentation readiness signals.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "x402 server origin"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15}}, "required": ["url"]},
        },
        "util_mcp_server_readiness_report": {
            "name": "util_mcp_server_readiness_report",
            "description": "Score an MCP server for initialize, tools/list, schema hygiene, manifest discovery, and agent usability.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "HTTP origin or MCP server URL to inspect"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15}}, "required": ["url"]},
        },
        "util_docs_site_map": {
            "name": "util_docs_site_map",
            "description": "Map a docs surface with crawl hints, docs links, feeds, and likely reference sections.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "Docs or product URL"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15}}, "required": ["url"]},
        },
        "util_pricing_page_extract": {
            "name": "util_pricing_page_extract",
            "description": "Extract pricing-page signals like plan names, free trial hints, CTA patterns, and sales routes.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "Pricing page URL"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15}}, "required": ["url"]},
        },
        "util_company_contact_pack": {
            "name": "util_company_contact_pack",
            "description": "Build a contact pack from page contacts, forms, social links, registrar, and disclosure channels.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "Company or product URL"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15}}, "required": ["url"]},
        },
        "util_api_integration_readiness": {
            "name": "util_api_integration_readiness",
            "description": "Evaluate whether an API surface looks easy to integrate by combining health, OpenAPI, and auth hints.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "API origin or docs URL"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15}}, "required": ["url"]},
        },
        "util_login_surface_report": {
            "name": "util_login_surface_report",
            "description": "Inspect auth surface signals like login forms, signup links, reset links, and security headers.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "Login or app URL"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15}}, "required": ["url"]},
        },
        "util_content_distribution_report": {
            "name": "util_content_distribution_report",
            "description": "Summarize how a site distributes content across Open Graph, feeds, socials, and crawl surface.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "Content or homepage URL"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-15)", "default": 8, "minimum": 1, "maximum": 15}}, "required": ["url"]},
        },
    }
)

