"""Local-first utilities derived from verified Delx Commerce sales.

These handlers are deliberately stateless and offline. They accept caller-owned
snapshots or policies, return bounded JSON, and never fetch URLs, sign payments,
generate media, store inputs, or echo credential-bearing values.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse


SALES_LED_TOOL_NAMES = [
    "util_seeded_random_sample",
    "util_base_gas_budget_check",
    "util_dns_record_diff",
    "util_http_header_diff",
    "util_x402_payment_preflight",
    "util_image_result_contract_check",
]

SALES_LED_REQUIRED_PARAMS = {
    "util_seeded_random_sample": ["items", "count", "seed"],
    "util_base_gas_budget_check": ["gas_price_gwei", "gas_limit", "budget_eth"],
    "util_dns_record_diff": ["before", "after"],
    "util_http_header_diff": ["before", "after"],
    "util_x402_payment_preflight": [
        "requirements",
        "max_amount_usdc",
        "allowed_networks",
    ],
    "util_image_result_contract_check": ["result"],
}

SALES_LED_TOOL_SCHEMAS = {
    "util_seeded_random_sample": {
        "name": "util_seeded_random_sample",
        "description": "Select a reproducible sample without replacement from a bounded caller-supplied list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "items": {"type": "array", "maxItems": 1000},
                "count": {"type": "integer", "minimum": 1, "maximum": 1000},
                "seed": {"type": "string", "minLength": 1, "maxLength": 256},
            },
            "required": ["items", "count", "seed"],
            "additionalProperties": False,
        },
    },
    "util_base_gas_budget_check": {
        "name": "util_base_gas_budget_check",
        "description": "Check a caller-supplied Base gas quote against an ETH fee budget with exact Wei arithmetic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "gas_price_gwei": {"type": "number", "minimum": 0},
                "gas_limit": {"type": "integer", "minimum": 1, "maximum": 30_000_000},
                "budget_eth": {"type": "number", "minimum": 0},
                "eth_usd": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["gas_price_gwei", "gas_limit", "budget_eth"],
            "additionalProperties": False,
        },
    },
    "util_dns_record_diff": {
        "name": "util_dns_record_diff",
        "description": "Compare two DNS record snapshots and return canonical added, removed, and unchanged records.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "before": {"type": "array", "maxItems": 500},
                "after": {"type": "array", "maxItems": 500},
            },
            "required": ["before", "after"],
            "additionalProperties": False,
        },
    },
    "util_http_header_diff": {
        "name": "util_http_header_diff",
        "description": "Compare HTTP header maps case-insensitively while redacting credential-bearing values.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "before": {"type": "object", "maxProperties": 200},
                "after": {"type": "object", "maxProperties": 200},
            },
            "required": ["before", "after"],
            "additionalProperties": False,
        },
    },
    "util_x402_payment_preflight": {
        "name": "util_x402_payment_preflight",
        "description": "Evaluate caller-supplied x402 accepts against price, network, recipient, scheme, and optional expiry policy.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "requirements": {"type": "object"},
                "max_amount_usdc": {"type": "number", "minimum": 0},
                "allowed_networks": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": {"type": "string"},
                },
                "asset_decimals": {"type": "integer", "minimum": 0, "maximum": 18, "default": 6},
                "now_epoch_seconds": {"type": "integer", "minimum": 0},
                "min_expiry_seconds": {"type": "integer", "minimum": 0, "maximum": 86_400, "default": 30},
            },
            "required": ["requirements", "max_amount_usdc", "allowed_networks"],
            "additionalProperties": False,
        },
    },
    "util_image_result_contract_check": {
        "name": "util_image_result_contract_check",
        "description": "Validate image delivery metadata without fetching, transforming, or generating media.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "result": {"type": "object"},
                "max_size_bytes": {"type": "integer", "minimum": 1, "maximum": 104_857_600, "default": 20_971_520},
                "max_width": {"type": "integer", "minimum": 1, "maximum": 32_768, "default": 8192},
                "max_height": {"type": "integer", "minimum": 1, "maximum": 32_768, "default": 8192},
            },
            "required": ["result"],
            "additionalProperties": False,
        },
    },
}


def _schema(name: str, **values: Any) -> dict[str, Any]:
    return {"schema": f"delx/{name.replace('_', '-')}/v1", **values}


def _error(name: str, code: str, message: str, **values: Any) -> dict[str, Any]:
    return _schema(name, error=code, message=message, **values)


def _bounded_list(name: str, value: Any, limit: int) -> list[Any] | dict[str, Any]:
    if not isinstance(value, list):
        return _error(name, "invalid_input", "Expected an array input.")
    if len(value) > limit:
        return _error(
            name,
            "input_limit_exceeded",
            f"Array exceeds the {limit}-item limit.",
            limit=limit,
            received=len(value),
        )
    return value


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _decimal(value: Any) -> Decimal:
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise InvalidOperation("non-finite number")
    return parsed


def _seeded_random_sample(args: dict[str, Any]) -> dict[str, Any]:
    name = "util_seeded_random_sample"
    bounded = _bounded_list(name, args.get("items"), 1000)
    if isinstance(bounded, dict):
        return bounded
    items = bounded
    if not items:
        return _error(name, "invalid_input", "items must not be empty")
    seed = args.get("seed")
    if not isinstance(seed, str) or not 1 <= len(seed) <= 256:
        return _error(name, "invalid_input", "seed must contain 1-256 characters")
    try:
        count = int(args.get("count"))
    except (TypeError, ValueError):
        return _error(name, "invalid_input", "count must be an integer")
    if count < 1 or count > len(items):
        return _error(
            name,
            "invalid_input",
            "count must be between 1 and the number of items",
            item_count=len(items),
        )

    indices = list(range(len(items)))
    seed_bytes = seed.encode("utf-8")
    counter = 0
    for position in range(len(indices) - 1, 0, -1):
        digest = hashlib.sha256(
            seed_bytes + b"\x00" + counter.to_bytes(8, "big")
        ).digest()
        selected = int.from_bytes(digest, "big") % (position + 1)
        indices[position], indices[selected] = indices[selected], indices[position]
        counter += 1
    chosen = indices[:count]
    return _schema(
        name,
        sample=[items[index] for index in chosen],
        indices=chosen,
        count=count,
        source_count=len(items),
        without_replacement=True,
        seed_sha256=hashlib.sha256(seed_bytes).hexdigest(),
    )


def _base_gas_budget_check(args: dict[str, Any]) -> dict[str, Any]:
    name = "util_base_gas_budget_check"
    try:
        gas_price_gwei = _decimal(args.get("gas_price_gwei"))
        budget_eth = _decimal(args.get("budget_eth"))
        gas_limit = int(args.get("gas_limit"))
        eth_usd = _decimal(args["eth_usd"]) if args.get("eth_usd") is not None else None
    except (InvalidOperation, TypeError, ValueError):
        return _error(name, "invalid_input", "Gas, budget, and price fields must be finite numbers.")
    if gas_price_gwei < 0 or budget_eth < 0 or not 1 <= gas_limit <= 30_000_000:
        return _error(name, "invalid_input", "Gas price and budget must be non-negative and gas_limit must be 1-30000000.")
    if eth_usd is not None and eth_usd <= 0:
        return _error(name, "invalid_input", "eth_usd must be greater than zero")

    estimated_wei_decimal = gas_price_gwei * Decimal(10**9) * gas_limit
    budget_wei_decimal = budget_eth * Decimal(10**18)
    if estimated_wei_decimal != estimated_wei_decimal.to_integral_value():
        return _error(name, "precision_exceeded", "gas_price_gwei resolves to fractional Wei")
    if budget_wei_decimal != budget_wei_decimal.to_integral_value():
        return _error(name, "precision_exceeded", "budget_eth resolves to fractional Wei")
    estimated_wei = int(estimated_wei_decimal)
    budget_wei = int(budget_wei_decimal)
    estimated_eth = Decimal(estimated_wei) / Decimal(10**18)
    headroom_wei = budget_wei - estimated_wei
    output: dict[str, Any] = {
        "estimated_fee_wei": str(estimated_wei),
        "estimated_fee_eth": _decimal_text(estimated_eth),
        "budget_wei": str(budget_wei),
        "budget_eth": _decimal_text(budget_eth),
        "within_budget": estimated_wei <= budget_wei,
        "headroom_wei": str(headroom_wei),
        "headroom_eth": _decimal_text(Decimal(headroom_wei) / Decimal(10**18)),
    }
    if eth_usd is not None:
        output["estimated_fee_usd"] = _decimal_text(estimated_eth * eth_usd)
    return _schema(name, **output)


_DOMAIN_VALUE_TYPES = {"CNAME", "DNAME", "MX", "NS", "PTR"}


def _normalize_dns_record(record: Any) -> Any:
    if not isinstance(record, dict):
        return str(record).strip()
    normalized: dict[str, Any] = {}
    record_type = str(record.get("type") or "").strip().upper()
    for key in sorted(record):
        value = record[key]
        canonical_key = str(key).strip().lower()
        if canonical_key == "type":
            normalized[canonical_key] = record_type
        elif canonical_key == "name" and isinstance(value, str):
            normalized[canonical_key] = value.strip().rstrip(".").lower()
        elif canonical_key == "value" and isinstance(value, str):
            clean = value.strip()
            normalized[canonical_key] = (
                clean.rstrip(".").lower()
                if record_type in _DOMAIN_VALUE_TYPES
                else clean
            )
        else:
            normalized[canonical_key] = value
    return normalized


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _dns_record_diff(args: dict[str, Any]) -> dict[str, Any]:
    name = "util_dns_record_diff"
    before = _bounded_list(name, args.get("before"), 500)
    if isinstance(before, dict):
        return before
    after = _bounded_list(name, args.get("after"), 500)
    if isinstance(after, dict):
        return after
    before_map = {_canonical_json(value): value for value in map(_normalize_dns_record, before)}
    after_map = {_canonical_json(value): value for value in map(_normalize_dns_record, after)}
    removed_keys = sorted(set(before_map) - set(after_map))
    added_keys = sorted(set(after_map) - set(before_map))
    unchanged = set(before_map) & set(after_map)
    return _schema(
        name,
        changed=bool(removed_keys or added_keys),
        added=[after_map[key] for key in added_keys],
        removed=[before_map[key] for key in removed_keys],
        unchanged_count=len(unchanged),
        before_count=len(before_map),
        after_count=len(after_map),
    )


_SECRET_HEADERS = {"authorization", "cookie", "proxy-authorization", "set-cookie"}
_SECURITY_HEADERS = {
    "content-security-policy",
    "cross-origin-embedder-policy",
    "cross-origin-opener-policy",
    "cross-origin-resource-policy",
    "permissions-policy",
    "referrer-policy",
    "strict-transport-security",
    "x-content-type-options",
    "x-frame-options",
    "x-xss-protection",
}


def _normalize_headers(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict) or len(value) > 200:
        return None
    normalized: dict[str, str] = {}
    for raw_name, raw_value in value.items():
        name = str(raw_name).strip().lower()
        if not name or len(name) > 128:
            continue
        if name in _SECRET_HEADERS:
            normalized[name] = "[redacted]"
        elif isinstance(raw_value, list):
            normalized[name] = ", ".join(str(item) for item in raw_value)[:4096]
        else:
            normalized[name] = str(raw_value)[:4096]
    return normalized


def _http_header_diff(args: dict[str, Any]) -> dict[str, Any]:
    name = "util_http_header_diff"
    before = _normalize_headers(args.get("before"))
    after = _normalize_headers(args.get("after"))
    if before is None or after is None:
        return _error(name, "input_limit_exceeded", "Header maps must contain at most 200 entries.")
    before_keys = set(before)
    after_keys = set(after)
    added = [
        {"name": key, "value": after[key]} for key in sorted(after_keys - before_keys)
    ]
    removed = [
        {"name": key, "value": before[key]} for key in sorted(before_keys - after_keys)
    ]
    changed = [
        {"name": key, "before": before[key], "after": after[key]}
        for key in sorted(before_keys & after_keys)
        if before[key] != after[key]
    ]
    touched = {
        row["name"] for row in [*added, *removed, *changed] if row["name"] in _SECURITY_HEADERS
    }
    return _schema(
        name,
        changed=changed,
        added=added,
        removed=removed,
        unchanged_count=sum(
            1 for key in before_keys & after_keys if before[key] == after[key]
        ),
        security_sensitive_changes=sorted(touched),
        credential_values_redacted=True,
    )


def _amount_usdc(value: Any, decimals: int) -> Decimal | None:
    try:
        text = str(value).strip()
        if not text:
            return None
        parsed = Decimal(text)
        if not parsed.is_finite() or parsed < 0:
            return None
        return parsed if "." in text else parsed / (Decimal(10) ** decimals)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _expiry_epoch(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed > 10_000_000_000:
        parsed //= 1000
    return parsed if parsed >= 0 else None


def _x402_payment_preflight(args: dict[str, Any]) -> dict[str, Any]:
    name = "util_x402_payment_preflight"
    requirements = args.get("requirements")
    if not isinstance(requirements, dict):
        return _error(name, "invalid_input", "requirements must be an object")
    accepts_value = requirements.get("accepts")
    if isinstance(accepts_value, list):
        accepts = accepts_value[:50]
    elif any(key in requirements for key in ("amount", "maxAmountRequired", "network")):
        accepts = [requirements]
    else:
        accepts = []
    try:
        ceiling = _decimal(args.get("max_amount_usdc"))
        decimals = int(args.get("asset_decimals", 6))
        min_expiry = int(args.get("min_expiry_seconds", 30))
        now_epoch = (
            int(args["now_epoch_seconds"])
            if args.get("now_epoch_seconds") is not None
            else None
        )
    except (InvalidOperation, TypeError, ValueError):
        return _error(name, "invalid_input", "Invalid price, decimals, or expiry policy")
    allowed = args.get("allowed_networks")
    if (
        ceiling < 0
        or not isinstance(allowed, list)
        or not 1 <= len(allowed) <= 20
        or not 0 <= decimals <= 18
        or not 0 <= min_expiry <= 86_400
    ):
        return _error(name, "invalid_input", "Price and policy bounds are invalid")
    allowed_set = {str(item).strip() for item in allowed if str(item).strip()}
    evaluations: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for index, accept in enumerate(accepts):
        if not isinstance(accept, dict):
            evaluations.append({"index": index, "blockers": ["accept_not_object"]})
            continue
        amount = _amount_usdc(
            accept.get("amount", accept.get("maxAmountRequired")), decimals
        )
        network = str(accept.get("network") or "").strip()
        pay_to = str(accept.get("payTo") or accept.get("pay_to") or "").strip()
        scheme = str(accept.get("scheme") or "").strip().lower()
        blockers: list[str] = []
        if amount is None:
            blockers.append("amount_invalid")
        elif amount > ceiling:
            blockers.append("amount_above_ceiling")
        if network not in allowed_set:
            blockers.append("network_not_allowed")
        if not pay_to:
            blockers.append("pay_to_missing")
        if scheme != "exact":
            blockers.append("scheme_not_exact")
        expires = _expiry_epoch(accept.get("expires"))
        expiry_status = "not_evaluated"
        if expires is not None and now_epoch is not None:
            expiry_status = "ok" if expires - now_epoch >= min_expiry else "too_short"
            if expiry_status == "too_short":
                blockers.append("expiry_buffer_too_short")
        safe = {
            "index": index,
            "scheme": scheme,
            "network": network,
            "amount_usdc": _decimal_text(amount) if amount is not None else None,
            "pay_to_present": bool(pay_to),
            "expiry_status": expiry_status,
            "blockers": blockers,
        }
        evaluations.append(safe)
        if not blockers:
            eligible.append(
                {
                    "index": index,
                    "scheme": scheme,
                    "network": network,
                    "amount_usdc": _decimal_text(amount or Decimal(0)),
                    "pay_to": pay_to,
                    "expiry_status": expiry_status,
                }
            )
    eligible.sort(key=lambda item: (Decimal(item["amount_usdc"]), item["index"]))
    return _schema(
        name,
        approved=bool(eligible),
        evaluated_count=len(evaluations),
        eligible_count=len(eligible),
        selected=eligible[0] if eligible else None,
        evaluations=evaluations,
        policy={
            "max_amount_usdc": _decimal_text(ceiling),
            "allowed_networks": sorted(allowed_set),
            "asset_decimals": decimals,
            "min_expiry_seconds": min_expiry,
            "expiry_checked": now_epoch is not None,
        },
    )


_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _image_result_contract_check(args: dict[str, Any]) -> dict[str, Any]:
    name = "util_image_result_contract_check"
    result = args.get("result")
    if not isinstance(result, dict):
        return _error(name, "invalid_input", "result must be an object")
    try:
        max_size = int(args.get("max_size_bytes", 20_971_520))
        max_width = int(args.get("max_width", 8192))
        max_height = int(args.get("max_height", 8192))
    except (TypeError, ValueError):
        return _error(name, "invalid_input", "Image limits must be integers")
    if not 1 <= max_size <= 104_857_600 or not 1 <= max_width <= 32_768 or not 1 <= max_height <= 32_768:
        return _error(name, "invalid_input", "Image limits are outside supported bounds")

    url = str(result.get("url") or result.get("image_url") or "").strip()
    sha256 = str(result.get("sha256") or result.get("sha_256") or "").strip().lower()
    content_type = str(
        result.get("content_type") or result.get("mime_type") or ""
    ).strip().lower()
    size = _positive_int(result.get("size_bytes"))
    width = _positive_int(result.get("width"))
    height = _positive_int(result.get("height"))
    parsed_url = urlparse(url)
    gaps: list[str] = []
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        gaps.append("https_artifact_url_required")
    if not _SHA256.fullmatch(sha256):
        gaps.append("sha256_invalid")
    if content_type not in _IMAGE_MIME_TYPES:
        gaps.append("content_type_unsupported")
    if size is None:
        gaps.append("size_bytes_missing")
    elif size > max_size:
        gaps.append("size_above_limit")
    if width is None:
        gaps.append("width_missing")
    elif width > max_width:
        gaps.append("width_above_limit")
    if height is None:
        gaps.append("height_missing")
    elif height > max_height:
        gaps.append("height_above_limit")
    return _schema(
        name,
        valid=not gaps,
        gaps=gaps,
        checked_without_fetch=True,
        normalized_receipt={
            "url": url,
            "sha256": sha256,
            "content_type": content_type,
            "size_bytes": size,
            "width": width,
            "height": height,
        },
        limits={
            "max_size_bytes": max_size,
            "max_width": max_width,
            "max_height": max_height,
        },
    )


SALES_LED_HANDLERS = {
    "util_seeded_random_sample": _seeded_random_sample,
    "util_base_gas_budget_check": _base_gas_budget_check,
    "util_dns_record_diff": _dns_record_diff,
    "util_http_header_diff": _http_header_diff,
    "util_x402_payment_preflight": _x402_payment_preflight,
    "util_image_result_contract_check": _image_result_contract_check,
}

assert set(SALES_LED_TOOL_NAMES) == set(SALES_LED_HANDLERS)
assert set(SALES_LED_TOOL_NAMES) == set(SALES_LED_REQUIRED_PARAMS)
assert set(SALES_LED_TOOL_NAMES) == set(SALES_LED_TOOL_SCHEMAS)

