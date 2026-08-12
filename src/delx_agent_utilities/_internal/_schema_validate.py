"""Reject documented input constraints before a handler can rewrite or charge.

Would Pay Again issue 5: out-of-range UUID `count` was clamped and billed.
The honest contract is HTTP 400 / error dict with charged=false, not a warning
field buried in a successful paid result.
"""

from __future__ import annotations

from typing import Any

_MERGE_KEYS = (
    "type",
    "enum",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "items",
    "properties",
)


def merge_input_schema(
    bazaar: dict[str, Any] | None,
    util: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prefer bazaar properties, fill missing constraint keys from the util schema."""
    bazaar_schema = bazaar if isinstance(bazaar, dict) else {}
    util_schema = util if isinstance(util, dict) else {}
    bazaar_props = bazaar_schema.get("properties")
    util_props = util_schema.get("properties")
    if not isinstance(bazaar_props, dict) or not bazaar_props:
        return util_schema or bazaar_schema
    merged = dict(bazaar_schema)
    merged_props: dict[str, Any] = {
        key: dict(spec) if isinstance(spec, dict) else spec
        for key, spec in bazaar_props.items()
    }
    if isinstance(util_props, dict):
        for field, spec in util_props.items():
            if not isinstance(spec, dict):
                continue
            current = merged_props.get(field)
            if not isinstance(current, dict):
                merged_props[field] = dict(spec)
                continue
            for key in _MERGE_KEYS:
                if key not in current and key in spec:
                    current[key] = spec[key]
    merged["properties"] = merged_props
    return merged


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return _is_int(value) or isinstance(value, float)


def _type_error(field: str, expected: str) -> dict[str, Any]:
    return {
        "error": "invalid_input",
        "field": field,
        "expected": expected,
        "charged": False,
    }


def _range_expected(schema: dict[str, Any]) -> str:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    json_type = schema.get("type")
    if minimum is not None and maximum is not None:
        kind = "integer" if json_type == "integer" else "number"
        return f"{kind} between {minimum} and {maximum}"
    if minimum is not None:
        return f"at least {minimum}"
    if maximum is not None:
        return f"at most {maximum}"
    return "value within documented bounds"


def constraint_error_from_schema(
    arguments: dict[str, Any] | None,
    schema: dict[str, Any] | None,
    *,
    path: str = "",
) -> dict[str, Any] | None:
    """Return a charged=false error dict, or None when the payload is in-contract.

    Only inspects properties that the caller actually sent. Missing required
    fields stay the caller's existing 400/402 policy. Extra fields are ignored
    so AgentCash session/source headers copied into JSON do not fail closed.
    `additionalProperties` is never enforced here.
    """
    if not isinstance(schema, dict):
        return None
    if arguments is None:
        return None
    if not isinstance(arguments, dict) or isinstance(arguments, bool):
        return {
            "error": "invalid_input",
            "field": path or "body",
            "expected": "object",
            "charged": False,
        }

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None

    for field, spec in properties.items():
        if field not in arguments or arguments[field] is None:
            continue
        if not isinstance(spec, dict):
            continue
        error = _constraint_error_for_value(
            arguments[field],
            spec,
            field if not path else f"{path}.{field}",
        )
        if error:
            return error
    return None


def _constraint_error_for_value(
    value: Any,
    spec: dict[str, Any],
    field: str,
) -> dict[str, Any] | None:
    json_type = spec.get("type")
    if json_type == "integer":
        if not _is_int(value):
            return _type_error(field, "integer")
    elif json_type == "number":
        if not _is_number(value):
            return _type_error(field, "number")
    elif json_type == "string":
        if not isinstance(value, str):
            return _type_error(field, "string")
    elif json_type == "boolean":
        if not isinstance(value, bool):
            return _type_error(field, "boolean")
    elif json_type == "array":
        if not isinstance(value, list):
            return _type_error(field, "array")
    elif json_type == "object":
        if not isinstance(value, dict) or isinstance(value, bool):
            return _type_error(field, "object")
        return constraint_error_from_schema(value, spec, path=field)

    if json_type in {"integer", "number"} and _is_number(value):
        minimum = spec.get("minimum")
        maximum = spec.get("maximum")
        if minimum is not None and value < minimum:
            return {
                "error": "invalid_input",
                "field": field,
                "expected": _range_expected(spec),
                "minimum": minimum,
                "maximum": maximum,
                "charged": False,
            }
        if maximum is not None and value > maximum:
            return {
                "error": "invalid_input",
                "field": field,
                "expected": _range_expected(spec),
                "minimum": minimum,
                "maximum": maximum,
                "charged": False,
            }

    if json_type == "string" and isinstance(value, str):
        min_length = spec.get("minLength")
        max_length = spec.get("maxLength")
        if min_length is not None and len(value) < min_length:
            return {
                "error": "invalid_input",
                "field": field,
                "expected": f"string of at least {min_length} characters",
                "minLength": min_length,
                "charged": False,
            }
        if max_length is not None and len(value) > max_length:
            return {
                "error": "invalid_input",
                "field": field,
                "expected": f"string of at most {max_length} characters",
                "maxLength": max_length,
                "charged": False,
            }

    if json_type == "array" and isinstance(value, list):
        min_items = spec.get("minItems")
        max_items = spec.get("maxItems")
        if min_items is not None and len(value) < min_items:
            return {
                "error": "invalid_input",
                "field": field,
                "expected": f"array of at least {min_items} items",
                "minItems": min_items,
                "charged": False,
            }
        if max_items is not None and len(value) > max_items:
            return {
                "error": "invalid_input",
                "field": field,
                "expected": f"array of at most {max_items} items",
                "maxItems": max_items,
                "charged": False,
            }

    allowed = spec.get("enum")
    if isinstance(allowed, list) and allowed and value not in allowed:
        return {
            "error": "invalid_input",
            "field": field,
            "expected": f"one of {allowed}",
            "enum": allowed,
            "charged": False,
        }
    return None
