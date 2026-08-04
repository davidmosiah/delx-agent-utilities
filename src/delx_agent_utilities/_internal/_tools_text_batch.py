"""Batch of first-party text/data helpers for agent micro-utils (no network)."""

from __future__ import annotations

import random
import re
import secrets
from typing import Any
from urllib.parse import quote, unquote


# ─── Levenshtein ──────────────────────────────────────────────────────

def _levenshtein(args: dict) -> dict:
    a = str(args.get("a") or args.get("left") or args.get("s1") or "")
    b = str(args.get("b") or args.get("right") or args.get("s2") or "")
    if a == "" and b == "":
        return {"error": "a_and_b_required"}
    if len(a) > 2000 or len(b) > 2000:
        return {"error": "text_too_long", "max": 2000}
    n, m = len(a), len(b)
    if n == 0:
        return {"schema": "delx/levenshtein/v1", "a_len": 0, "b_len": m, "distance": m, "similarity": 0.0 if m else 1.0}
    if m == 0:
        return {"schema": "delx/levenshtein/v1", "a_len": n, "b_len": 0, "distance": n, "similarity": 0.0}
    prev = list(range(m + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    dist = prev[m]
    sim = 1.0 - (dist / max(n, m))
    return {
        "schema": "delx/levenshtein/v1",
        "a_len": n,
        "b_len": m,
        "distance": dist,
        "similarity": round(sim, 6),
    }


# ─── Similarity (ratio via Levenshtein) ────────────────────────────────

def _similarity(args: dict) -> dict:
    result = _levenshtein(args)
    if "error" in result:
        return result
    return {
        "schema": "delx/similarity/v1",
        "similarity": result["similarity"],
        "distance": result["distance"],
        "method": "normalized_levenshtein",
    }


# ─── Normalize whitespace ─────────────────────────────────────────────

def _normalize_whitespace(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or "")
    if text == "" and args.get("text") is None and args.get("input") is None:
        return {"error": "text_required"}
    if len(text) > 200_000:
        return {"error": "text_too_long", "max": 200000}
    mode = str(args.get("mode") or "collapse").strip().lower()
    if mode in {"collapse", "spaces"}:
        out = re.sub(r"[ \t]+", " ", text)
        out = re.sub(r"\n{3,}", "\n\n", out)
        out = "\n".join(line.strip() for line in out.splitlines())
        out = out.strip()
    elif mode in {"all", "flat"}:
        out = re.sub(r"\s+", " ", text).strip()
    elif mode in {"trim"}:
        out = "\n".join(line.rstrip() for line in text.splitlines()).strip("\n")
    else:
        return {"error": "unsupported_mode", "hint": "collapse|all|trim"}
    return {
        "schema": "delx/normalize-whitespace/v1",
        "mode": mode,
        "text": out,
        "length_before": len(text),
        "length_after": len(out),
    }


# ─── Extract URLs ─────────────────────────────────────────────────────

_URL_RE = re.compile(
    r"https?://[^\s<>\"']+|www\.[^\s<>\"']+",
    re.I,
)


def _extract_urls(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or "")
    if not text:
        return {"error": "text_required"}
    if len(text) > 200_000:
        return {"error": "text_too_long", "max": 200000}
    found = _URL_RE.findall(text)
    # strip trailing punctuation
    cleaned = []
    for u in found:
        cleaned.append(u.rstrip(".,);]!?"))
    unique = list(dict.fromkeys(cleaned))
    max_n = int(args.get("max") or 50)
    max_n = max(1, min(max_n, 100))
    return {
        "schema": "delx/extract-urls/v1",
        "count": len(unique),
        "urls": unique[:max_n],
        "truncated": len(unique) > max_n,
    }


# ─── Extract emails ───────────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)


def _extract_emails(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or "")
    if not text:
        return {"error": "text_required"}
    if len(text) > 200_000:
        return {"error": "text_too_long", "max": 200000}
    found = _EMAIL_RE.findall(text)
    unique = list(dict.fromkeys(e.lower() for e in found))
    max_n = int(args.get("max") or 50)
    max_n = max(1, min(max_n, 100))
    return {
        "schema": "delx/extract-emails/v1",
        "count": len(unique),
        "emails": unique[:max_n],
        "truncated": len(unique) > max_n,
        "note": "Regex extraction only — not mailbox verification.",
    }


# ─── URL encode/decode ────────────────────────────────────────────────

def _url_encode(args: dict) -> dict:
    text = args.get("text")
    if text is None:
        text = args.get("input")
    if text is None:
        return {"error": "text_required"}
    text = str(text)
    if len(text) > 50_000:
        return {"error": "text_too_long", "max": 50000}
    action = str(args.get("action") or args.get("mode") or "encode").strip().lower()
    safe = str(args.get("safe") or "")
    if action in {"encode", "quote"}:
        out = quote(text, safe=safe)
        return {"schema": "delx/url-encode/v1", "action": "encode", "result": out, "length": len(out)}
    if action in {"decode", "unquote"}:
        out = unquote(text)
        return {"schema": "delx/url-encode/v1", "action": "decode", "result": out, "length": len(out)}
    return {"error": "unsupported_action", "hint": "encode|decode"}


# ─── Hex convert ──────────────────────────────────────────────────────

def _hex_convert(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or args.get("data") or "")
    if not text:
        return {"error": "text_required"}
    if len(text) > 50_000:
        return {"error": "text_too_long", "max": 50000}
    action = str(args.get("action") or args.get("mode") or "encode").strip().lower()
    if action in {"encode", "to_hex"}:
        out = text.encode("utf-8").hex()
        return {"schema": "delx/hex-convert/v1", "action": "encode", "result": out, "bytes": len(text.encode('utf-8'))}
    if action in {"decode", "from_hex"}:
        cleaned = re.sub(r"\s+|0x", "", text, flags=re.I)
        if not re.fullmatch(r"[0-9a-fA-F]*", cleaned) or len(cleaned) % 2:
            return {"error": "invalid_hex"}
        try:
            raw = bytes.fromhex(cleaned)
            out = raw.decode("utf-8", errors="replace")
        except Exception as exc:
            return {"error": "decode_failed", "detail": str(exc)[:120]}
        return {"schema": "delx/hex-convert/v1", "action": "decode", "result": out, "bytes": len(raw)}
    return {"error": "unsupported_action", "hint": "encode|decode"}


# ─── Number base convert ──────────────────────────────────────────────

def _number_base(args: dict) -> dict:
    value = args.get("value")
    if value is None:
        value = args.get("number") or args.get("input")
    if value is None:
        return {"error": "value_required"}
    try:
        from_base = int(args.get("from_base") or args.get("from") or 10)
        to_base = int(args.get("to_base") or args.get("to") or 16)
    except (TypeError, ValueError):
        return {"error": "invalid_base"}
    if not (2 <= from_base <= 36 and 2 <= to_base <= 36):
        return {"error": "base_out_of_range", "min": 2, "max": 36}
    text = str(value).strip().lower()
    if text.startswith("0x") and from_base == 16:
        text = text[2:]
    try:
        decimal = int(text, from_base)
    except ValueError:
        return {"error": "invalid_number_for_base", "from_base": from_base}
    if abs(decimal) > 2**256:
        return {"error": "number_too_large"}
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if decimal == 0:
        out = "0"
    else:
        neg = decimal < 0
        n = abs(decimal)
        digits = []
        while n:
            n, rem = divmod(n, to_base)
            digits.append(alphabet[rem])
        out = ("-" if neg else "") + "".join(reversed(digits))
    return {
        "schema": "delx/number-base/v1",
        "value": str(value),
        "from_base": from_base,
        "to_base": to_base,
        "result": out,
        "decimal": decimal,
    }


# ─── Dedupe lines ─────────────────────────────────────────────────────

def _dedupe_lines(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or "")
    if text == "" and args.get("text") is None:
        return {"error": "text_required"}
    if len(text) > 200_000:
        return {"error": "text_too_long", "max": 200000}
    lines = text.splitlines()
    if len(lines) > 5000:
        return {"error": "too_many_lines", "max": 5000}
    keep_order = args.get("keep_order")
    if keep_order is None:
        keep_order = True
    if keep_order:
        seen = set()
        out = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                out.append(line)
    else:
        out = sorted(set(lines))
    return {
        "schema": "delx/dedupe-lines/v1",
        "lines_before": len(lines),
        "lines_after": len(out),
        "removed": len(lines) - len(out),
        "text": "\n".join(out),
    }


# ─── Sort lines ───────────────────────────────────────────────────────

def _sort_lines(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or "")
    if text == "" and args.get("text") is None:
        return {"error": "text_required"}
    if len(text) > 200_000:
        return {"error": "text_too_long", "max": 200000}
    lines = text.splitlines()
    if len(lines) > 5000:
        return {"error": "too_many_lines", "max": 5000}
    reverse = bool(args.get("reverse") or False)
    numeric = bool(args.get("numeric") or False)
    if numeric:
        def key(s: str):
            try:
                return (0, float(s.strip()))
            except ValueError:
                return (1, s)
        out = sorted(lines, key=key, reverse=reverse)
    else:
        case_insensitive = args.get("case_insensitive")
        if case_insensitive is None:
            case_insensitive = False
        if case_insensitive:
            out = sorted(lines, key=lambda s: s.lower(), reverse=reverse)
        else:
            out = sorted(lines, reverse=reverse)
    return {
        "schema": "delx/sort-lines/v1",
        "count": len(out),
        "reverse": reverse,
        "numeric": numeric,
        "text": "\n".join(out),
    }


# ─── Random int ───────────────────────────────────────────────────────

def _random_int(args: dict) -> dict:
    try:
        lo = int(args.get("min") if args.get("min") is not None else args.get("low") if args.get("low") is not None else 0)
        hi = int(args.get("max") if args.get("max") is not None else args.get("high") if args.get("high") is not None else 100)
        count = int(args.get("count") or 1)
    except (TypeError, ValueError):
        return {"error": "invalid_range", "hint": "Pass integer min, max, optional count."}
    if lo > hi:
        return {"error": "min_greater_than_max"}
    if hi - lo > 10**12:
        return {"error": "range_too_large"}
    if count < 1 or count > 100:
        return {"error": "count_out_of_range", "min": 1, "max": 100}
    values = [secrets.randbelow(hi - lo + 1) + lo for _ in range(count)]
    return {
        "schema": "delx/random-int/v1",
        "min": lo,
        "max": hi,
        "count": count,
        "values": values,
        "note": "CSPRNG via secrets module.",
    }


# ─── ROT13 ────────────────────────────────────────────────────────────

def _rot13(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or "")
    if text == "" and args.get("text") is None:
        return {"error": "text_required"}
    if len(text) > 100_000:
        return {"error": "text_too_long", "max": 100000}
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - 97 + 13) % 26 + 97))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - 65 + 13) % 26 + 65))
        else:
            out.append(ch)
    return {"schema": "delx/rot13/v1", "result": "".join(out), "length": len(text)}


# ─── Text truncate ────────────────────────────────────────────────────

def _text_truncate(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or "")
    if text == "" and args.get("text") is None:
        return {"error": "text_required"}
    if len(text) > 200_000:
        return {"error": "text_too_long", "max": 200000}
    try:
        max_len = int(args.get("max_length") or args.get("max") or args.get("limit"))
    except (TypeError, ValueError):
        return {"error": "max_length_required"}
    if max_len < 1 or max_len > 200_000:
        return {"error": "max_length_out_of_range"}
    ellipsis = str(args.get("ellipsis") if args.get("ellipsis") is not None else "…")
    if len(text) <= max_len:
        return {
            "schema": "delx/text-truncate/v1",
            "text": text,
            "truncated": False,
            "length": len(text),
            "max_length": max_len,
        }
    # keep room for ellipsis
    keep = max_len - len(ellipsis)
    if keep < 1:
        out = ellipsis[:max_len]
    else:
        out = text[:keep] + ellipsis
    return {
        "schema": "delx/text-truncate/v1",
        "text": out,
        "truncated": True,
        "length": len(out),
        "original_length": len(text),
        "max_length": max_len,
    }


# ─── Reading time ─────────────────────────────────────────────────────

def _reading_time(args: dict) -> dict:
    text = str(args.get("text") or args.get("input") or "")
    if not text:
        return {"error": "text_required"}
    if len(text) > 500_000:
        return {"error": "text_too_long", "max": 500000}
    try:
        wpm = int(args.get("wpm") or 200)
    except (TypeError, ValueError):
        return {"error": "invalid_wpm"}
    if wpm < 50 or wpm > 1000:
        return {"error": "wpm_out_of_range", "min": 50, "max": 1000}
    words = re.findall(r"\b[\w']+\b", text, flags=re.UNICODE)
    minutes = len(words) / wpm
    seconds = minutes * 60
    return {
        "schema": "delx/reading-time/v1",
        "words": len(words),
        "wpm": wpm,
        "minutes": round(minutes, 2),
        "seconds": round(seconds, 1),
        "human": f"{max(1, round(minutes))} min" if minutes >= 0.5 else f"{max(1, round(seconds))} sec",
        "note": "Estimate only; not a comprehension model.",
    }


# ─── Random choice ────────────────────────────────────────────────────

def _random_choice(args: dict) -> dict:
    items = args.get("items") or args.get("choices") or args.get("options")
    if isinstance(items, str):
        items = [x for x in items.splitlines() if x != ""]
    if not isinstance(items, list) or not items:
        return {"error": "items_required", "hint": "Pass items as string array or multiline text."}
    if len(items) > 500:
        return {"error": "too_many_items", "max": 500}
    try:
        count = int(args.get("count") or 1)
    except (TypeError, ValueError):
        return {"error": "invalid_count"}
    if count < 1 or count > min(100, len(items)):
        return {"error": "count_out_of_range", "min": 1, "max": min(100, len(items))}
    # without replacement for multi
    pool = list(items)
    chosen = []
    for _ in range(count):
        idx = secrets.randbelow(len(pool))
        chosen.append(pool.pop(idx))
    return {
        "schema": "delx/random-choice/v1",
        "count": count,
        "choices": chosen,
        "note": "CSPRNG without replacement when count > 1.",
    }
