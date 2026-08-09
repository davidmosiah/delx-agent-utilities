import pytest

from delx_agent_utilities import (
    UTIL_REQUIRED_PARAMS,
    UTIL_TOOL_NAMES,
    UTIL_TOOL_SCHEMAS,
    call_util_tool,
)


TOOLS = {
    "util_seeded_random_sample",
    "util_base_gas_budget_check",
    "util_dns_record_diff",
    "util_http_header_diff",
    "util_x402_payment_preflight",
    "util_image_result_contract_check",
}


def test_sales_led_tools_are_registered_with_mcp_schemas():
    assert TOOLS <= set(UTIL_TOOL_NAMES)
    assert TOOLS <= set(UTIL_REQUIRED_PARAMS)
    assert TOOLS <= set(UTIL_TOOL_SCHEMAS)
    for name in TOOLS:
        schema = UTIL_TOOL_SCHEMAS[name]
        assert schema["name"] == name
        assert schema["inputSchema"]["type"] == "object"
        assert schema["inputSchema"]["required"]


@pytest.mark.asyncio
async def test_seeded_random_sample_is_reproducible_and_does_not_echo_seed():
    args = {
        "items": ["alpha", "beta", "gamma", "delta", "epsilon"],
        "count": 3,
        "seed": "workflow-secret-42",
    }
    first = await call_util_tool("util_seeded_random_sample", args)
    second = await call_util_tool("util_seeded_random_sample", args)
    other = await call_util_tool(
        "util_seeded_random_sample", {**args, "seed": "different-seed"}
    )

    assert first == second
    assert first["sample"] != other["sample"]
    assert len(first["sample"]) == 3
    assert len(set(first["indices"])) == 3
    assert first["seed_sha256"] != args["seed"]
    assert args["seed"] not in repr(first)


@pytest.mark.asyncio
async def test_base_gas_budget_uses_exact_wei_arithmetic():
    result = await call_util_tool(
        "util_base_gas_budget_check",
        {
            "gas_price_gwei": 0.08,
            "gas_limit": 21000,
            "budget_eth": 0.00001,
            "eth_usd": 3500,
        },
    )

    assert result["estimated_fee_wei"] == "1680000000000"
    assert result["estimated_fee_eth"] == "0.00000168"
    assert result["budget_wei"] == "10000000000000"
    assert result["within_budget"] is True
    assert result["headroom_eth"] == "0.00000832"
    assert result["estimated_fee_usd"] == "0.00588"


@pytest.mark.asyncio
async def test_dns_record_diff_is_canonical_and_bounded():
    result = await call_util_tool(
        "util_dns_record_diff",
        {
            "before": [
                {"type": "A", "name": "EXAMPLE.COM.", "value": "192.0.2.1"},
                {"value": "mail.example.com.", "type": "MX", "priority": 10},
            ],
            "after": [
                {"value": "192.0.2.2", "name": "example.com", "type": "a"},
                {"priority": 10, "type": "mx", "value": "mail.example.com"},
            ],
        },
    )

    assert result["changed"] is True
    assert result["unchanged_count"] == 1
    assert result["removed"] == [
        {"name": "example.com", "type": "A", "value": "192.0.2.1"}
    ]
    assert result["added"] == [
        {"name": "example.com", "type": "A", "value": "192.0.2.2"}
    ]


@pytest.mark.asyncio
async def test_http_header_diff_is_case_insensitive_and_redacts_credentials():
    result = await call_util_tool(
        "util_http_header_diff",
        {
            "before": {
                "Content-Type": "text/html",
                "Authorization": "Bearer before-secret",
                "Strict-Transport-Security": "max-age=60",
            },
            "after": {
                "content-type": "text/html",
                "authorization": "Bearer after-secret",
                "strict-transport-security": "max-age=31536000",
                "x-content-type-options": "nosniff",
            },
        },
    )

    assert result["unchanged_count"] == 2
    assert result["changed"] == [
        {
            "name": "strict-transport-security",
            "before": "max-age=60",
            "after": "max-age=31536000",
        }
    ]
    assert result["added"] == [
        {"name": "x-content-type-options", "value": "nosniff"}
    ]
    assert "before-secret" not in repr(result)
    assert "after-secret" not in repr(result)
    assert "strict-transport-security" in result["security_sensitive_changes"]


@pytest.mark.asyncio
async def test_x402_payment_preflight_fails_closed_on_price_network_and_expiry():
    accepted = await call_util_tool(
        "util_x402_payment_preflight",
        {
            "requirements": {
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "eip155:8453",
                        "amount": "1000",
                        "payTo": "0x1111111111111111111111111111111111111111",
                        "expires": 1786272600,
                    }
                ]
            },
            "max_amount_usdc": 0.002,
            "allowed_networks": ["eip155:8453"],
            "now_epoch_seconds": 1786272500,
            "min_expiry_seconds": 30,
        },
    )
    assert accepted["approved"] is True
    assert accepted["eligible_count"] == 1
    assert accepted["selected"]["amount_usdc"] == "0.001"
    assert "payment_signature" not in repr(accepted).lower()

    rejected = await call_util_tool(
        "util_x402_payment_preflight",
        {
            "requirements": {
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "eip155:1",
                        "amount": "5000",
                        "payTo": "",
                        "expires": 1786272510,
                    }
                ]
            },
            "max_amount_usdc": 0.002,
            "allowed_networks": ["eip155:8453"],
            "now_epoch_seconds": 1786272500,
            "min_expiry_seconds": 30,
        },
    )
    assert rejected["approved"] is False
    assert rejected["eligible_count"] == 0
    blockers = rejected["evaluations"][0]["blockers"]
    assert blockers == [
        "amount_above_ceiling",
        "network_not_allowed",
        "pay_to_missing",
        "expiry_buffer_too_short",
    ]


@pytest.mark.asyncio
async def test_image_result_contract_check_validates_without_fetching():
    valid = await call_util_tool(
        "util_image_result_contract_check",
        {
            "result": {
                "url": "https://cdn.example.com/output.webp",
                "sha256": "01" * 32,
                "content_type": "image/webp",
                "size_bytes": 245760,
                "width": 1024,
                "height": 1024,
            }
        },
    )
    assert valid["valid"] is True
    assert valid["gaps"] == []
    assert valid["normalized_receipt"]["url"] == "https://cdn.example.com/output.webp"

    invalid = await call_util_tool(
        "util_image_result_contract_check",
        {
            "result": {
                "url": "http://localhost/private.png",
                "sha256": "bad",
                "content_type": "text/html",
                "size_bytes": 50_000_000,
                "width": 20_000,
                "height": 1,
            },
            "max_size_bytes": 1_000_000,
            "max_width": 8192,
            "max_height": 8192,
        },
    )
    assert invalid["valid"] is False
    assert invalid["gaps"] == [
        "https_artifact_url_required",
        "sha256_invalid",
        "content_type_unsupported",
        "size_above_limit",
        "width_above_limit",
    ]


@pytest.mark.asyncio
async def test_sales_led_tools_reject_missing_and_oversized_inputs():
    missing = await call_util_tool("util_seeded_random_sample", {})
    assert missing["error"].startswith("Missing required params:")
    assert missing["required"] == ["items", "count", "seed"]

    oversized = await call_util_tool(
        "util_dns_record_diff", {"before": list(range(501)), "after": []}
    )
    assert oversized["error"] == "input_limit_exceeded"
