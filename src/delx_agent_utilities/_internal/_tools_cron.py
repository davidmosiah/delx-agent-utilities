"""Cron expression parser and human-readable describer (no external dependency)."""

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


# ─── Cron Parser (no external dependency) ─────────────────────────────

_CRON_FIELDS = ["minute", "hour", "day_of_month", "month", "day_of_week"]
_CRON_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
_DOW_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
_MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def _parse_cron_field(field: str, min_val: int, max_val: int) -> list[int] | None:
    """Parse a single cron field into a list of valid values."""
    values: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            try:
                step = int(step_s)
            except ValueError:
                return None

        if part == "*":
            values.update(range(min_val, max_val + 1, step))
        elif "-" in part:
            try:
                lo, hi = part.split("-", 1)
                lo_i, hi_i = int(lo), int(hi)
                if lo_i < min_val or hi_i > max_val or lo_i > hi_i:
                    return None
                values.update(range(lo_i, hi_i + 1, step))
            except ValueError:
                return None
        else:
            try:
                v = int(part)
                if v < min_val or v > max_val:
                    return None
                values.add(v)
            except ValueError:
                return None

    return sorted(values) if values else None


def _describe_cron_field(vals: list[int], field_name: str, min_val: int, max_val: int) -> str:
    if vals == list(range(min_val, max_val + 1)):
        return f"every {field_name}"
    if len(vals) == 1:
        v = vals[0]
        if field_name == "day_of_week":
            return _DOW_NAMES[v]
        if field_name == "month":
            return _MONTH_NAMES[v] if 1 <= v <= 12 else str(v)
        return str(v)
    return ",".join(str(v) for v in vals)


def _cron_describe(args: dict) -> dict:
    expr = args.get("expression", "").strip()
    parts = expr.split()
    if len(parts) != 5:
        return {"valid": False, "parse_error": f"Expected 5 fields (min hour dom month dow), got {len(parts)}", "expression": expr}

    parsed = []
    for i, (field, (lo, hi)) in enumerate(zip(parts, _CRON_RANGES)):
        vals = _parse_cron_field(field, lo, hi)
        if vals is None:
            return {"valid": False, "parse_error": f"Invalid {_CRON_FIELDS[i]}: {field}", "expression": expr}
        parsed.append(vals)

    # Build human description
    desc_parts = []
    mins, hours, doms, months, dows = parsed

    # Minute
    if mins == list(range(0, 60)):
        desc_parts.append("Every minute")
    elif len(mins) == 1:
        desc_parts.append(f"At minute {mins[0]}")
    else:
        desc_parts.append(f"At minutes {','.join(str(m) for m in mins)}")

    # Hour
    if hours != list(range(0, 24)):
        if len(hours) == 1:
            desc_parts.append(f"past hour {hours[0]}")
        else:
            desc_parts.append(f"past hours {','.join(str(h) for h in hours)}")

    # DOM
    if doms != list(range(1, 32)):
        desc_parts.append(f"on day {','.join(str(d) for d in doms)}")

    # Month
    if months != list(range(1, 13)):
        month_names = [_MONTH_NAMES[m] for m in months if 1 <= m <= 12]
        desc_parts.append(f"in {','.join(month_names)}")

    # DOW
    if dows != list(range(0, 7)):
        dow_names = [_DOW_NAMES[d] for d in dows]
        desc_parts.append(f"on {','.join(dow_names)}")

    description = " ".join(desc_parts)

    # Compute next 5 runs
    now = datetime.now(timezone.utc)
    next_runs = []
    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    safety = 0
    while len(next_runs) < 5 and safety < 525960:  # max 1 year of minutes
        safety += 1
        if (candidate.minute in mins
                and candidate.hour in hours
                and candidate.day in doms
                and candidate.month in months
                and candidate.weekday() in [(d - 1) % 7 for d in dows]  # cron: 0=Sun
            ):
            next_runs.append(candidate.isoformat())
        candidate += timedelta(minutes=1)

    return {
        "valid": True,
        "expression": expr,
        "description": description,
        "fields": {name: vals for name, vals in zip(_CRON_FIELDS, parsed)},
        "next_5_runs": next_runs,
    }


