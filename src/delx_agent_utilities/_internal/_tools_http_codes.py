"""HTTP status code reference table + lookup tool."""

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

from ._helpers import _parse_int


# ─── HTTP Status Codes Reference ──────────────────────────────────────

HTTP_CODES: dict[int, dict[str, str]] = {
    100: {"name": "Continue", "description": "Server received request headers; client should proceed with body.", "category": "Informational"},
    101: {"name": "Switching Protocols", "description": "Server is switching protocols as requested (e.g., WebSocket upgrade).", "category": "Informational"},
    200: {"name": "OK", "description": "Request succeeded.", "category": "Success"},
    201: {"name": "Created", "description": "Resource created successfully.", "category": "Success"},
    202: {"name": "Accepted", "description": "Request accepted for processing but not yet completed.", "category": "Success"},
    204: {"name": "No Content", "description": "Request succeeded but no content to return.", "category": "Success"},
    301: {"name": "Moved Permanently", "description": "Resource permanently moved to a new URL.", "category": "Redirection"},
    302: {"name": "Found", "description": "Resource temporarily at a different URL.", "category": "Redirection"},
    304: {"name": "Not Modified", "description": "Resource not modified since last request (use cached version).", "category": "Redirection"},
    307: {"name": "Temporary Redirect", "description": "Temporary redirect, preserving HTTP method.", "category": "Redirection"},
    308: {"name": "Permanent Redirect", "description": "Permanent redirect, preserving HTTP method.", "category": "Redirection"},
    400: {"name": "Bad Request", "description": "Server cannot process the request due to client error (malformed syntax, invalid parameters).", "category": "Client Error"},
    401: {"name": "Unauthorized", "description": "Authentication required. The request lacks valid credentials.", "category": "Client Error"},
    402: {"name": "Payment Required", "description": "Payment required to access this resource. Used by x402 protocol for micropayments.", "category": "Client Error"},
    403: {"name": "Forbidden", "description": "Server understood the request but refuses to authorize it.", "category": "Client Error"},
    404: {"name": "Not Found", "description": "Resource not found at the requested URL.", "category": "Client Error"},
    405: {"name": "Method Not Allowed", "description": "HTTP method not supported for this endpoint.", "category": "Client Error"},
    408: {"name": "Request Timeout", "description": "Server timed out waiting for the request.", "category": "Client Error"},
    409: {"name": "Conflict", "description": "Request conflicts with current server state (e.g., duplicate resource).", "category": "Client Error"},
    413: {"name": "Payload Too Large", "description": "Request body exceeds server limits.", "category": "Client Error"},
    415: {"name": "Unsupported Media Type", "description": "Content-Type not supported by the endpoint.", "category": "Client Error"},
    418: {"name": "I'm a Teapot", "description": "RFC 2324 joke status code.", "category": "Client Error"},
    422: {"name": "Unprocessable Entity", "description": "Request was well-formed but semantically invalid.", "category": "Client Error"},
    429: {"name": "Too Many Requests", "description": "Rate limit exceeded. Back off and retry with exponential delay.", "category": "Client Error"},
    500: {"name": "Internal Server Error", "description": "Unexpected server error. Not your fault.", "category": "Server Error"},
    502: {"name": "Bad Gateway", "description": "Server received an invalid response from an upstream server.", "category": "Server Error"},
    503: {"name": "Service Unavailable", "description": "Server temporarily unavailable (maintenance or overload). Retry later.", "category": "Server Error"},
    504: {"name": "Gateway Timeout", "description": "Upstream server did not respond in time.", "category": "Server Error"},
}


def _http_codes(args: dict) -> dict:
    code = args.get("code")
    if code is not None:
        try:
            code = _parse_int(code)
        except ValueError as e:
            return {"error": str(e), "field": "code", "expected": "integer (100-599)"}
        if code in HTTP_CODES:
            return {"code": code, **HTTP_CODES[code]}
        # Guess category
        cat = "Unknown"
        if 100 <= code < 200:
            cat = "Informational"
        elif 200 <= code < 300:
            cat = "Success"
        elif 300 <= code < 400:
            cat = "Redirection"
        elif 400 <= code < 500:
            cat = "Client Error"
        elif 500 <= code < 600:
            cat = "Server Error"
        return {"code": code, "name": "Unknown", "description": f"Non-standard {cat.lower()} code.", "category": cat}

    # Return common codes grouped by category
    grouped: dict[str, list] = {}
    for c, info in sorted(HTTP_CODES.items()):
        cat = info["category"]
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append({"code": c, "name": info["name"]})
    return {"codes": grouped, "total": len(HTTP_CODES)}


