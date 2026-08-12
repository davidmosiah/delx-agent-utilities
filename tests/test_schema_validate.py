from delx_agent_utilities._internal._schema_validate import constraint_error_from_schema
from delx_agent_utilities._internal._schemas import UTIL_TOOL_SCHEMAS


def _schema(tool_name: str) -> dict:
    return UTIL_TOOL_SCHEMAS[tool_name]["inputSchema"]


def test_uuid_count_999_is_invalid_input():
    error = constraint_error_from_schema({"count": 999}, _schema("util_uuid_generate"))
    assert error["error"] == "invalid_input"
    assert error["field"] == "count"
    assert error["minimum"] == 1
    assert error["maximum"] == 10
    assert error["charged"] is False


def test_uuid_valid_count_passes():
    assert constraint_error_from_schema({"count": 3}, _schema("util_uuid_generate")) is None


def test_hash_rejects_undocumented_algorithm():
    error = constraint_error_from_schema(
        {"input": "x", "algorithm": "blake3"},
        _schema("util_hash"),
    )
    assert error["error"] == "invalid_input"
    assert error["field"] == "algorithm"
    assert error["charged"] is False
    assert "sha256" in error["enum"]


def test_extra_session_fields_are_ignored():
    error = constraint_error_from_schema(
        {"count": 2, "session_id": "qa-wpa", "source": "agentcash"},
        _schema("util_uuid_generate"),
    )
    assert error is None


def test_missing_required_is_not_this_gate():
    assert constraint_error_from_schema({}, _schema("util_hash")) is None


def test_uuid_count_schema_is_integer():
    assert _schema("util_uuid_generate")["properties"]["count"]["type"] == "integer"
