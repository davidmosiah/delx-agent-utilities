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
    "util_timezone_lookup",
    "util_unit_convert",
    "util_business_days",
    "util_vin_decode",
    "util_wmi_decode",
    "util_lei_lookup",
    "util_inflation_calculator",
    "util_holidays",
    "util_slugify",
    "util_mime_lookup",
    "util_color_convert",
    "util_ip_classify",
    "util_cidr_contains",
    "util_ulid_generate",
    "util_html_strip",
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
    "util_timezone_lookup": ["timezone"],
    "util_unit_convert": [],
    "util_business_days": ["start_date", "end_date"],
    "util_vin_decode": ["vin"],
    "util_wmi_decode": ["wmi"],
    "util_lei_lookup": ["lei"],
    "util_holidays": ["year"],
    "util_slugify": ["text"],
    "util_mime_lookup": ["extension"],
    "util_color_convert": ["color"],
    "util_ip_classify": ["ip"],
    "util_cidr_contains": ["network", "ip"],
    "util_ulid_generate": [],
    "util_html_strip": ["html"],
    "util_inflation_calculator": ["amount", "from_year", "to_year"],
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
    "util_timezone_lookup": {
        "name": "util_timezone_lookup",
        "description": "Resolve an IANA timezone to offset, abbreviation, DST flag, and local time for a given instant (or now).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone id, e.g. America/New_York or Europe/Lisbon",
                },
                "at": {
                    "type": "string",
                    "description": "Optional instant: ISO 8601, Unix seconds, or 'now' (default)",
                    "default": "now",
                },
            },
            "required": ["timezone"],
        },
    },
    "util_unit_convert": {
        "name": "util_unit_convert",
        "description": "Convert values between units (length, mass, volume, time, data, temperature). Supports one conversion or a batch of up to 100.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "value": {"type": "number", "description": "Single value to convert (or use conversions[])"},
                "from_unit": {"type": "string", "description": "Source unit, e.g. km, lb, c, mib"},
                "to_unit": {"type": "string", "description": "Target unit, e.g. mi, kg, f, gib"},
                "conversions": {
                    "type": "array",
                    "description": "Optional batch of {value, from_unit, to_unit} (max 100)",
                    "items": {"type": "object"},
                },
            },
        },
    },
    "util_business_days": {
        "name": "util_business_days",
        "description": "Count and list business days between two inclusive ISO dates. Calendars: weekdays (Mon–Fri) or us_federal (excludes observed US federal holidays).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Inclusive start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "Inclusive end date YYYY-MM-DD"},
                "calendar": {
                    "type": "string",
                    "enum": ["weekdays", "us_federal"],
                    "default": "weekdays",
                    "description": "Holiday calendar",
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
    "util_vin_decode": {
        "name": "util_vin_decode",
        "description": "Decode a 17-character VIN via NHTSA vPIC into make, model, year, body class, and related fields with attribution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "vin": {"type": "string", "description": "17-character Vehicle Identification Number"},
            },
            "required": ["vin"],
        },
    },
    "util_wmi_decode": {
        "name": "util_wmi_decode",
        "description": "Decode a 3-character WMI (World Manufacturer Identifier) via NHTSA vPIC into manufacturer and vehicle type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wmi": {"type": "string", "description": "3-character WMI (often VIN prefix)"},
            },
            "required": ["wmi"],
        },
    },
    "util_lei_lookup": {
        "name": "util_lei_lookup",
        "description": "Look up a 20-character Legal Entity Identifier (LEI) via GLEIF: legal name, status, jurisdiction, registration.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lei": {"type": "string", "description": "20-character LEI"},
            },
            "required": ["lei"],
        },
    },
    "util_inflation_calculator": {
        "name": "util_inflation_calculator",
        "description": "Revalue an amount between two years using U.S. BLS CPI (CPI-U default). Informational only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Amount in from_year dollars"},
                "from_year": {"type": "integer", "description": "Start calendar year"},
                "to_year": {"type": "integer", "description": "End calendar year"},
                "series": {
                    "type": "string",
                    "description": "cpi_u (default), cpi_w, or a BLS series id",
                    "default": "cpi_u",
                },
            },
            "required": ["amount", "from_year", "to_year"],
        },
    },
    "util_holidays": {
        "name": "util_holidays",
        "description": "List observed US federal holidays for a year.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer", "minimum": 1971, "maximum": 2100},
                "calendar": {"type": "string", "enum": ["us_federal"], "default": "us_federal"}
            },
            "required": ["year"],
            "additionalProperties": False
        }
    },
    "util_slugify": {
        "name": "util_slugify",
        "description": "Convert text to a URL-safe slug.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "separator": {"type": "string", "default": "-"},
                "lowercase": {"type": "boolean", "default": True},
                "max_length": {"type": "integer", "minimum": 1, "maximum": 4000}
            },
            "required": ["text"],
            "additionalProperties": False
        }
    },
    "util_mime_lookup": {
        "name": "util_mime_lookup",
        "description": "Look up a common MIME type from a file extension or filename.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "extension": {"type": "string"},
                "filename": {"type": "string"}
            },
            "additionalProperties": False
        }
    },
    "util_color_convert": {
        "name": "util_color_convert",
        "description": "Convert #hex or rgb() colors to hex/rgb/hsl.",
        "inputSchema": {
            "type": "object",
            "properties": {"color": {"type": "string"}},
            "required": ["color"],
            "additionalProperties": False
        }
    },
    "util_ip_classify": {
        "name": "util_ip_classify",
        "description": "Classify an IPv4/IPv6 address as private, loopback, global, etc. No geolocation.",
        "inputSchema": {
            "type": "object",
            "properties": {"ip": {"type": "string"}},
            "required": ["ip"],
            "additionalProperties": False
        }
    },
    "util_cidr_contains": {
        "name": "util_cidr_contains",
        "description": "Check whether an IP address is inside a CIDR network.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "network": {"type": "string"},
                "ip": {"type": "string"}
            },
            "required": ["network", "ip"],
            "additionalProperties": False
        }
    },
    "util_ulid_generate": {
        "name": "util_ulid_generate",
        "description": "Generate one or more Crockford Base32 ULIDs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1}
            },
            "additionalProperties": False
        }
    },
    "util_html_strip": {
        "name": "util_html_strip",
        "description": "Strip HTML tags to plain text (best-effort, no browser).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "html": {"type": "string"},
                "max_length": {"type": "integer", "minimum": 1, "maximum": 100000}
            },
            "required": ["html"],
            "additionalProperties": False
        }
    }
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
    "util_loyalty_reward_quote",
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
        "util_loyalty_reward_quote": ["purchase_amount"],
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
        "util_loyalty_reward_quote": {
            "name": "util_loyalty_reward_quote",
            "description": "Calculate loyalty points, reward value, effective rebate, and a ledger-ready credit instruction without storing customer state.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "purchase_amount": {"type": "number", "minimum": 0, "description": "Eligible purchase amount."},
                    "currency": {"type": "string", "minLength": 3, "maxLength": 3, "default": "USD"},
                    "points_per_unit": {"type": "number", "minimum": 0, "default": 1},
                    "tier_multiplier": {"type": "number", "minimum": 0, "default": 1},
                    "bonus_points": {"type": "integer", "minimum": 0, "default": 0},
                    "redemption_value_per_point": {"type": "number", "minimum": 0, "default": 0.01},
                    "event_id": {"type": "string", "description": "Optional caller-owned idempotency identifier for the downstream ledger."}
                },
                "required": ["purchase_amount"],
                "additionalProperties": False
            },
        },
    }
)
