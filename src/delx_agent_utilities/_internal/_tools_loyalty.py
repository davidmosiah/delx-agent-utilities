"""Deterministic loyalty calculations with no stored customer state."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any


def _decimal(value: object, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal number") from exc
    if parsed < 0:
        raise ValueError(f"{field} must be non-negative")
    return parsed


def _loyalty_reward_quote(args: dict[str, Any]) -> dict[str, Any]:
    purchase_amount = _decimal(args.get("purchase_amount"), "purchase_amount")
    points_per_unit = _decimal(args.get("points_per_unit", 1), "points_per_unit")
    tier_multiplier = _decimal(args.get("tier_multiplier", 1), "tier_multiplier")
    bonus_points = int(_decimal(args.get("bonus_points", 0), "bonus_points"))
    redemption_value = _decimal(
        args.get("redemption_value_per_point", "0.01"),
        "redemption_value_per_point",
    )
    currency = str(args.get("currency") or "USD").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency must be a three-letter code")

    base_points = int(
        (purchase_amount * points_per_unit).quantize(Decimal("1"), rounding=ROUND_DOWN)
    )
    multiplied_points = int(
        (Decimal(base_points) * tier_multiplier).quantize(Decimal("1"), rounding=ROUND_DOWN)
    )
    total_points = multiplied_points + bonus_points
    reward_value = (Decimal(total_points) * redemption_value).quantize(Decimal("0.000001"))
    rebate_pct = (
        (reward_value / purchase_amount * Decimal(100)).quantize(Decimal("0.01"))
        if purchase_amount
        else Decimal(0)
    )

    return {
        "purchase_amount": format(purchase_amount, "f"),
        "currency": currency,
        "base_points": base_points,
        "tier_multiplier": format(tier_multiplier, "f"),
        "bonus_points": bonus_points,
        "total_points": total_points,
        "redemption_value_per_point": format(redemption_value, "f"),
        "estimated_reward_value": format(reward_value, "f"),
        "effective_rebate_pct": format(rebate_pct, "f"),
        "rounding": "floor_points_then_apply_bonus",
        "deterministic": True,
        "stores_customer_state": False,
        "ledger_instruction": {
            "event_id": str(args.get("event_id") or "").strip() or None,
            "operation": "credit",
            "amount": total_points,
            "unit": "points",
            "idempotency_required": True,
        },
    }
