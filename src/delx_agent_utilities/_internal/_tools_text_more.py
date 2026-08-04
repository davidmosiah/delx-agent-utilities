"""Additional first-party text/data helpers — no network, no API keys."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse


# ─── Semver ───────────────────────────────────────────────────────────

_SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)


def _parse_semver(raw: object) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    m = _SEMVER_RE.match(text)
    if not m:
        return None
    pre = m.group("pre")
    return {
        "major": int(m.group("major")),
        "minor": int(m.group("minor")),
        "patch": int(m.group("patch")),
        "prerelease": pre.split(".") if pre else [],
        "raw": text,
    }


def _cmp_pre(a: list[str], b: list[str]) -> int:
    # empty prerelease > any prerelease
    if not a and not b:
        return 0
    if not a:
        return 1
    if not b:
        return -1
    for x, y in zip(a, b):
        x_num, y_num = x.isdigit(), y.isdigit()
        if x_num and y_num:
            xi, yi = int(x), int(y)
            if xi != yi:
                return -1 if xi < yi else 1
        elif x_num != y_num:
            return -1 if x_num else 1
        elif x != y:
            return -1 if x < y else 1
    if len(a) != len(b):
        return -1 if len(a) < len(b) else 1
    return 0


def _semver_compare(args: dict) -> dict:
    left = _parse_semver(args.get("a") or args.get("left") or args.get("version_a"))
    right = _parse_semver(args.get("b") or args.get("right") or args.get("version_b"))
    if left is None or right is None:
        return {
            "error": "invalid_semver",
            "hint": "Pass a and b as major.minor.patch with optional prerelease.",
        }
    for key in ("major", "minor", "patch"):
        if left[key] != right[key]:
            cmp = -1 if left[key] < right[key] else 1
            break
    else:
        cmp = _cmp_pre(left["prerelease"], right["prerelease"])
    return {
        "schema": "delx/semver-compare/v1",
        "a": left["raw"],
        "b": right["raw"],
        "cmp": cmp,
        "relation": "lt" if cmp < 0 else "gt" if cmp > 0 else "eq",
        "a_gte_b": cmp >= 0,
        "b_gte_a": cmp <= 0,
    }


# ─── Word count ───────────────────────────────────────────────────────

def _word_count(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or args.get("content") or "")
    if not text:
        return {"error": "text_required"}
    if len(text) > 200_000:
        return {"error": "text_too_long", "max": 200_000}
    words = re.findall(r"\b[\w']+\b", text, flags=re.UNICODE)
    lines = text.splitlines() or ([""] if text == "" else [])
    chars = len(text)
    chars_no_space = sum(1 for c in text if not c.isspace())
    return {
        "schema": "delx/word-count/v1",
        "words": len(words),
        "characters": chars,
        "characters_no_space": chars_no_space,
        "lines": len(lines),
        "paragraphs": len([p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]) if text.strip() else 0,
        "avg_word_length": round(sum(len(w) for w in words) / len(words), 2) if words else 0.0,
    }


# ─── Markdown to text ─────────────────────────────────────────────────

def _markdown_to_text(args: dict) -> dict:
    md = str(args.get("markdown") or args.get("text") or args.get("input") or "")
    if not md:
        return {"error": "markdown_required"}
    if len(md) > 100_000:
        return {"error": "markdown_too_long", "max": 100_000}
    text = md
    # fenced code → keep content
    text = re.sub(r"```[\w-]*\n([\s\S]*?)```", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"[*_~]{1,3}", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.M)
    text = re.sub(r"^>\s?", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    truncated = False
    max_len = args.get("max_length")
    if max_len is not None:
        try:
            max_len = int(max_len)
        except (TypeError, ValueError):
            return {"error": "invalid_max_length"}
        if max_len < 1 or max_len > 100_000:
            return {"error": "max_length_out_of_range"}
        if len(text) > max_len:
            text = text[:max_len]
            truncated = True
    return {
        "schema": "delx/markdown-to-text/v1",
        "text": text,
        "length": len(text),
        "truncated": truncated,
        "note": "Best-effort markdown strip; not a full CommonMark renderer.",
    }


# ─── Duration parse ───────────────────────────────────────────────────

_DURATION_TOKEN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>milliseconds?|ms|seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)(?![a-z])",
    re.I,
)


def _duration_parse(args: dict) -> dict:
    raw = str(args.get("duration") or args.get("input") or args.get("text") or "").strip()
    if not raw:
        return {"error": "duration_required", "hint": "e.g. 1h30m, 90s, 2 days"}
    if len(raw) > 200:
        return {"error": "duration_too_long"}
    total_ms = 0.0
    matched = 0
    for m in _DURATION_TOKEN.finditer(raw):
        matched += 1
        value = float(m.group("value"))
        unit = m.group("unit").lower()
        if unit in {"ms", "millisecond", "milliseconds"}:
            total_ms += value
        elif unit in {"s", "sec", "secs", "second", "seconds"}:
            total_ms += value * 1000
        elif unit in {"m", "min", "mins", "minute", "minutes"}:
            total_ms += value * 60_000
        elif unit in {"h", "hr", "hrs", "hour", "hours"}:
            total_ms += value * 3_600_000
        elif unit in {"d", "day", "days"}:
            total_ms += value * 86_400_000
    if matched == 0:
        # plain number = seconds
        try:
            total_ms = float(raw) * 1000
            matched = 1
        except ValueError:
            return {"error": "unrecognized_duration", "hint": "Use 1h30m, 90s, or seconds as number."}
    total_s = total_ms / 1000.0
    return {
        "schema": "delx/duration-parse/v1",
        "input": raw,
        "tokens": matched,
        "milliseconds": int(total_ms) if total_ms == int(total_ms) else total_ms,
        "seconds": total_s,
        "minutes": total_s / 60.0,
        "hours": total_s / 3600.0,
        "iso8601_approx": _to_iso_duration(total_s),
    }


def _to_iso_duration(seconds: float) -> str:
    if seconds < 0:
        return "PT0S"
    whole = int(seconds)
    days, rem = divmod(whole, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = ["P"]
    if days:
        parts.append(f"{days}D")
    parts.append("T")
    if hours:
        parts.append(f"{hours}H")
    if minutes:
        parts.append(f"{minutes}M")
    if secs or (days == 0 and hours == 0 and minutes == 0):
        parts.append(f"{secs}S")
    return "".join(parts)


# ─── Case convert ─────────────────────────────────────────────────────

def _split_words(text: str) -> list[str]:
    text = text.replace("-", " ").replace("_", " ")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return [w for w in re.split(r"\s+", text.strip()) if w]


def _case_convert(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or args.get("value") or "")
    if not text:
        return {"error": "text_required"}
    if len(text) > 4000:
        return {"error": "text_too_long", "max": 4000}
    target = str(args.get("case") or args.get("to") or args.get("style") or "snake").strip().lower()
    words = _split_words(text)
    if not words:
        return {"error": "no_words"}
    lower = [w.lower() for w in words]
    if target in {"snake", "snake_case"}:
        out = "_".join(lower)
    elif target in {"kebab", "kebab-case", "slug"}:
        out = "-".join(lower)
    elif target in {"camel", "camelcase"}:
        out = lower[0] + "".join(w.capitalize() for w in lower[1:])
    elif target in {"pascal", "pascalcase"}:
        out = "".join(w.capitalize() for w in lower)
    elif target in {"constant", "screaming_snake", "upper_snake"}:
        out = "_".join(w.upper() for w in lower)
    elif target in {"title", "title_case"}:
        out = " ".join(w.capitalize() for w in lower)
    elif target in {"lower", "lowercase"}:
        out = " ".join(lower)
    elif target in {"upper", "uppercase"}:
        out = " ".join(w.upper() for w in lower)
    else:
        return {
            "error": "unsupported_case",
            "hint": "snake|kebab|camel|pascal|constant|title|lower|upper",
        }
    return {
        "schema": "delx/case-convert/v1",
        "input": text,
        "case": target,
        "result": out,
        "words": lower,
    }


# ─── Query string ─────────────────────────────────────────────────────

def _query_string(args: dict) -> dict:
    action = str(args.get("action") or args.get("mode") or "parse").strip().lower()
    if action in {"parse", "decode"}:
        raw = str(args.get("query") or args.get("input") or args.get("text") or "")
        if not raw:
            return {"error": "query_required"}
        if len(raw) > 20_000:
            return {"error": "query_too_long", "max": 20000}
        if raw.startswith("?"):
            raw = raw[1:]
        # if full URL, take query
        if "://" in raw or raw.startswith("/"):
            raw = urlparse(raw).query
        pairs = parse_qsl(raw, keep_blank_values=True)
        if len(pairs) > 200:
            return {"error": "too_many_params", "max": 200}
        obj: dict[str, Any] = {}
        for k, v in pairs:
            if k in obj:
                if isinstance(obj[k], list):
                    obj[k].append(v)
                else:
                    obj[k] = [obj[k], v]
            else:
                obj[k] = v
        return {
            "schema": "delx/query-string/v1",
            "action": "parse",
            "params": obj,
            "count": len(pairs),
        }
    if action in {"build", "encode", "stringify"}:
        params = args.get("params") or args.get("data") or args.get("object")
        if not isinstance(params, dict):
            return {"error": "params_object_required"}
        if len(params) > 200:
            return {"error": "too_many_params", "max": 200}
        items: list[tuple[str, str]] = []
        for k, v in params.items():
            key = str(k)
            if isinstance(v, list):
                for item in v[:50]:
                    items.append((key, str(item)))
            elif v is None:
                continue
            else:
                items.append((key, str(v)))
        qs = urlencode(items, doseq=False)
        return {
            "schema": "delx/query-string/v1",
            "action": "build",
            "query": qs,
            "with_question_mark": f"?{qs}" if qs else "",
            "count": len(items),
        }
    return {"error": "unsupported_action", "hint": "parse or build"}


# ─── URL join ─────────────────────────────────────────────────────────

def _url_join(args: dict) -> dict:
    base = str(args.get("base") or args.get("base_url") or "").strip()
    path = str(args.get("path") or args.get("href") or args.get("relative") or "").strip()
    if not base:
        return {"error": "base_required"}
    if len(base) > 4000 or len(path) > 4000:
        return {"error": "url_too_long"}
    try:
        joined = urljoin(base if base.endswith("/") or not path.startswith("?") else base + "/", path)
        parsed = urlparse(joined)
    except Exception as exc:
        return {"error": "join_failed", "detail": str(exc)[:160]}
    return {
        "schema": "delx/url-join/v1",
        "base": base,
        "path": path,
        "url": joined,
        "scheme": parsed.scheme or None,
        "netloc": parsed.netloc or None,
        "path_part": parsed.path or None,
        "query": parsed.query or None,
        "fragment": parsed.fragment or None,
    }


# ─── Percent change ───────────────────────────────────────────────────

def _percent_change(args: dict) -> dict:
    try:
        old = float(args.get("from") if args.get("from") is not None else args.get("old") if args.get("old") is not None else args.get("start"))
        new = float(args.get("to") if args.get("to") is not None else args.get("new") if args.get("new") is not None else args.get("end"))
    except (TypeError, ValueError):
        return {"error": "from_and_to_required", "hint": "Pass numeric from and to."}
    if old == 0:
        return {
            "schema": "delx/percent-change/v1",
            "from": old,
            "to": new,
            "absolute_change": new - old,
            "percent_change": None,
            "error": "division_by_zero",
            "hint": "Cannot compute percent change from zero baseline.",
        }
    abs_change = new - old
    pct = (abs_change / abs(old)) * 100.0
    return {
        "schema": "delx/percent-change/v1",
        "from": old,
        "to": new,
        "absolute_change": abs_change,
        "percent_change": round(pct, 6),
        "ratio": round(new / old, 6),
        "direction": "up" if abs_change > 0 else "down" if abs_change < 0 else "flat",
    }


# ─── Clamp ────────────────────────────────────────────────────────────

def _clamp(args: dict) -> dict:
    try:
        value = float(args.get("value") if args.get("value") is not None else args.get("x"))
        lo = float(args.get("min") if args.get("min") is not None else args.get("low") if args.get("low") is not None else args.get("minimum"))
        hi = float(args.get("max") if args.get("max") is not None else args.get("high") if args.get("high") is not None else args.get("maximum"))
    except (TypeError, ValueError):
        return {"error": "value_min_max_required", "hint": "Pass numeric value, min, max."}
    if lo > hi:
        return {"error": "min_greater_than_max", "min": lo, "max": hi}
    clamped = min(max(value, lo), hi)
    return {
        "schema": "delx/clamp/v1",
        "value": value,
        "min": lo,
        "max": hi,
        "result": clamped,
        "was_below": value < lo,
        "was_above": value > hi,
        "clamped": value != clamped,
    }


# ─── Luhn check ───────────────────────────────────────────────────────

def _luhn_check(args: dict) -> dict:
    raw = str(args.get("number") or args.get("input") or args.get("pan") or "").strip()
    digits = re.sub(r"[\s-]", "", raw)
    if not digits or not digits.isdigit():
        return {"error": "digits_required", "hint": "Pass a digit string (spaces/dashes ok)."}
    if len(digits) < 2 or len(digits) > 32:
        return {"error": "length_out_of_range", "min": 2, "max": 32}
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    valid = total % 10 == 0
    return {
        "schema": "delx/luhn-check/v1",
        "valid": valid,
        "length": len(digits),
        "check_digit": digits[-1],
        "note": "Checksum only — does not validate card brand, issuer, or that a number is real. Never log full PANs in production systems.",
        "redacted": ("*" * max(0, len(digits) - 4)) + digits[-4:],
    }


# ─── ISBN check ───────────────────────────────────────────────────────

def _isbn_check(args: dict) -> dict:
    raw = str(args.get("isbn") or args.get("input") or args.get("number") or "").strip()
    cleaned = re.sub(r"[-\s]", "", raw).upper()
    if not cleaned:
        return {"error": "isbn_required"}
    if len(cleaned) == 10:
        if not re.fullmatch(r"\d{9}[\dX]", cleaned):
            return {"error": "invalid_isbn10_charset"}
        total = 0
        for i, ch in enumerate(cleaned):
            n = 10 if ch == "X" else int(ch)
            total += n * (10 - i)
        valid = total % 11 == 0
        return {
            "schema": "delx/isbn-check/v1",
            "isbn": cleaned,
            "type": "ISBN-10",
            "valid": valid,
            "note": "Checksum validation only.",
        }
    if len(cleaned) == 13:
        if not cleaned.isdigit():
            return {"error": "invalid_isbn13_charset"}
        total = 0
        for i, ch in enumerate(cleaned):
            n = int(ch)
            total += n * (1 if i % 2 == 0 else 3)
        valid = total % 10 == 0
        return {
            "schema": "delx/isbn-check/v1",
            "isbn": cleaned,
            "type": "ISBN-13",
            "valid": valid,
            "note": "Checksum validation only.",
        }
    return {"error": "unsupported_length", "hint": "ISBN-10 or ISBN-13 only.", "length": len(cleaned)}


# ─── Diff lines ───────────────────────────────────────────────────────

def _diff_lines(args: dict) -> dict:
    a = str(args.get("a") or args.get("left") or args.get("old") or "")
    b = str(args.get("b") or args.get("right") or args.get("new") or "")
    if a == "" and b == "":
        return {"error": "a_and_b_required"}
    if len(a) > 50_000 or len(b) > 50_000:
        return {"error": "text_too_long", "max": 50000}
    left = a.splitlines()
    right = b.splitlines()
    # simple LCS-based line diff, bounded
    if len(left) > 500 or len(right) > 500:
        return {"error": "too_many_lines", "max_lines": 500}
    n, m = len(left), len(right)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if left[i] == right[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    i = j = 0
    ops: list[dict[str, Any]] = []
    while i < n and j < m:
        if left[i] == right[j]:
            ops.append({"op": "equal", "line": left[i]})
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            ops.append({"op": "remove", "line": left[i]})
            i += 1
        else:
            ops.append({"op": "add", "line": right[j]})
            j += 1
    while i < n:
        ops.append({"op": "remove", "line": left[i]})
        i += 1
    while j < m:
        ops.append({"op": "add", "line": right[j]})
        j += 1
    added = sum(1 for o in ops if o["op"] == "add")
    removed = sum(1 for o in ops if o["op"] == "remove")
    equal = sum(1 for o in ops if o["op"] == "equal")
    # truncate ops payload
    truncated = False
    if len(ops) > 200:
        ops = ops[:200]
        truncated = True
    return {
        "schema": "delx/diff-lines/v1",
        "added": added,
        "removed": removed,
        "equal": equal,
        "ops": ops,
        "truncated": truncated,
        "note": "Line-level LCS diff; not a word-level or binary diff.",
    }
