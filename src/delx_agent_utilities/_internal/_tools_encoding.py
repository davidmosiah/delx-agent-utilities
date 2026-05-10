"""Encoding/local utilities — json validate, token estimate, uuid, timestamp, base64, hash, regex, url_health (sync wrappers + 1 async)."""

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

from ._helpers import _parse_int, _fetch_http_response, _normalize_url, _header_value


# ─── Tool Implementations ─────────────────────────────────────────────

def _json_validate(args: dict) -> dict:
    raw = args.get("input", "")
    try:
        parsed = json.loads(raw)
        formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
        return {
            "valid": True,
            "errors": [],
            "formatted": formatted,
            "type": type(parsed).__name__,
            "keys": list(parsed.keys()) if isinstance(parsed, dict) else None,
            "length": len(parsed) if isinstance(parsed, (list, dict)) else None,
        }
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "errors": [{"message": str(e), "line": e.lineno, "column": e.colno, "position": e.pos}],
            "formatted": None,
        }


def _token_estimate(args: dict) -> dict:
    text = args.get("text", "")
    model = args.get("model", "gpt-4")
    chars = len(text)
    words = len(text.split())
    lines = text.count("\n") + 1

    # Heuristics per model family
    if chars == 0:
        tokens_est = 0
        method = "empty_input"
    elif "claude" in model.lower():
        tokens_est = max(1, int(chars / 3.5))
        method = "char/3.5 (Claude family)"
    else:
        tokens_est = max(1, int(words / 0.75))
        method = "words/0.75 (GPT family)"

    return {
        "char_count": chars,
        "word_count": words,
        "line_count": lines,
        "estimated_tokens": tokens_est,
        "estimation_method": method,
        "model_hint": model,
        "cost_estimate": {
            "gpt4_input_usd": round(tokens_est * 0.00003, 6),
            "claude_sonnet_input_usd": round(tokens_est * 0.000003, 6),
        },
        "note": "Estimates are approximate. Actual tokenization varies by model.",
    }


def _uuid_generate(args: dict) -> dict:
    try:
        count = _parse_int(args.get("count", 1), default=1)
    except ValueError as e:
        return {"error": str(e), "field": "count", "expected": "integer (1-10)"}
    clamped = min(10, max(1, count))
    out = {
        "uuids": [],
        "count": clamped,
        "version": 4,
    }
    if clamped != count:
        out["warning"] = f"count was clamped from {count} to {clamped}"
    out["uuids"] = [str(uuid.uuid4()) for _ in range(clamped)]
    return out


def _timestamp_convert(args: dict) -> dict:
    raw = args.get("input", "").strip()
    target = args.get("to", "all")

    dt: datetime | None = None

    if raw.lower() == "now":
        dt = datetime.now(timezone.utc)
    else:
        # Try Unix epoch (int or float)
        try:
            ts = float(raw)
            if ts > 1e12:  # milliseconds
                ts = ts / 1000
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass

        # Try ISO 8601
        if dt is None:
            for fmt in [
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y",
            ]:
                try:
                    dt = datetime.strptime(raw, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue

    if dt is None:
        return {
            "valid": False,
            "input": raw,
            "parse_error": f"Could not parse timestamp: {raw}",
            "supported_formats": ["Unix epoch (seconds/ms)", "ISO 8601", "YYYY-MM-DD", "DD/MM/YYYY", "now"],
        }

    now = datetime.now(timezone.utc)
    delta = now - dt
    if delta.total_seconds() >= 0:
        relative = f"{int(delta.total_seconds())}s ago"
        if delta.days > 0:
            relative = f"{delta.days}d ago"
        elif delta.total_seconds() > 3600:
            relative = f"{int(delta.total_seconds() / 3600)}h ago"
        elif delta.total_seconds() > 60:
            relative = f"{int(delta.total_seconds() / 60)}m ago"
    else:
        future = -delta.total_seconds()
        relative = f"in {int(future)}s"
        if abs(delta.days) > 0:
            relative = f"in {abs(delta.days)}d"
        elif future > 3600:
            relative = f"in {int(future / 3600)}h"
        elif future > 60:
            relative = f"in {int(future / 60)}m"

    result = {
        "unix": int(dt.timestamp()),
        "unix_ms": int(dt.timestamp() * 1000),
        "iso": dt.isoformat(),
        "human": dt.strftime("%B %d, %Y at %H:%M:%S UTC"),
        "date": dt.strftime("%Y-%m-%d"),
        "time": dt.strftime("%H:%M:%S"),
        "day_of_week": dt.strftime("%A"),
        "relative": relative,
    }

    if target != "all":
        return {target: result.get(target, result)}
    return result


def _base64_op(args: dict) -> dict:
    raw = args.get("input", "")
    action = args.get("action", "encode")

    if action == "encode":
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return {
            "action": "encode",
            "result": encoded,
            "input_bytes": len(raw.encode("utf-8")),
            "output_length": len(encoded),
        }
    elif action == "decode":
        try:
            decoded = base64.b64decode(raw).decode("utf-8")
            return {
                "valid": True,
                "action": "decode",
                "result": decoded,
                "input_length": len(raw),
                "output_bytes": len(decoded.encode("utf-8")),
            }
        except Exception as e:
            return {"valid": False, "action": "decode", "result": "", "decode_error": f"Invalid Base64: {e}"}
    else:
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return {
            "action": "encode",
            "result": encoded,
            "input_bytes": len(raw.encode("utf-8")),
            "output_length": len(encoded),
            "warning": f"unknown action '{action}', defaulted to encode",
        }


async def _url_health(args: dict) -> dict:
    url = args.get("url", "")
    try:
        timeout_s = _parse_int(args.get("timeout", 5), default=5)
    except ValueError as e:
        return {"url": url, "reachable": False, "status": 0, "reason": str(e), "field": "timeout", "expected": "integer (1-10)"}
    timeout_s = min(10, max(1, timeout_s))

    url = _normalize_url(url)

    start = datetime.now(timezone.utc)
    resp, error = await _fetch_http_response(url, timeout_s=timeout_s, method="HEAD")
    elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    if error or resp is None:
        payload = {"url": url, "reachable": False, "status": 0, "reason": error or "fetch failed", "latency_ms": elapsed_ms}
        if "only http and https" in str(error or ""):
            payload["code"] = "invalid_protocol"
        elif "blocked" in str(error or ""):
            payload["code"] = "blocked_target"
        return payload

    return {
        "url": url,
        "status": resp.status_code,
        "status_text": getattr(resp, "reason_phrase", "") or "",
        "reachable": 200 <= resp.status_code < 400,
        "latency_ms": elapsed_ms,
        "headers": {
            "content-type": resp.headers.get("content-type", ""),
            "server": resp.headers.get("server", ""),
            "x-powered-by": resp.headers.get("x-powered-by", ""),
        },
        "redirected": str(resp.url) != url,
        "final_url": str(resp.url),
    }


def _hash(args: dict) -> dict:
    raw = args.get("input", "")
    algo = args.get("algorithm", "sha256").lower()

    algos = {
        "sha256": hashlib.sha256,
        "sha1": hashlib.sha1,
        "md5": hashlib.md5,
    }

    if algo not in algos:
        algo = "sha256"
        warning = "unknown algorithm; defaulted to sha256"
    else:
        warning = None

    h = algos[algo](raw.encode("utf-8"))
    out = {
        "hash": h.hexdigest(),
        "algorithm": algo,
        "input_bytes": len(raw.encode("utf-8")),
        "digest_length": h.digest_size * 2,
    }
    if warning:
        out["warning"] = warning
    return out


def _regex_test(args: dict) -> dict:
    pattern = args.get("pattern", "")
    text = args.get("text", "")
    flags_str = args.get("flags", "")

    flags = 0
    for f in flags_str:
        if f == "i":
            flags |= re.IGNORECASE
        elif f == "m":
            flags |= re.MULTILINE
        elif f == "s":
            flags |= re.DOTALL

    try:
        compiled = re.compile(pattern, flags)
    except re.error as e:
        return {"valid_pattern": False, "parse_error": f"Invalid regex: {e}", "match_count": 0, "matches": []}

    matches = []
    for m in compiled.finditer(text):
        entry: dict[str, Any] = {
            "match": m.group(),
            "start": m.start(),
            "end": m.end(),
        }
        if m.groups():
            entry["groups"] = list(m.groups())
        if m.groupdict():
            entry["named_groups"] = m.groupdict()
        matches.append(entry)

    return {
        "valid_pattern": True,
        "pattern": pattern,
        "flags": flags_str,
        "match_count": len(matches),
        "matches": matches[:50],  # cap at 50
        "has_more": len(matches) > 50,
    }
