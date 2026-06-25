from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.agent.tools import (
    check_item_condition,
    check_opened_item_loyalty,
    check_return_window,
    find_customer,
    find_order,
)
from app.models import Order, RefundDecision, ToolCallLog
from app.services.customer_decisions import customer_facing_message

PrescreenOutcome = Literal["PROCEED", "REJECT"]


@dataclass
class ReturnPrescreenResult:
    outcome: PrescreenOutcome
    customer_message: str
    internal_reason: str
    policy_rules: list[str]
    tool_calls: list[ToolCallLog]
    order_id: str | None = None
    product_names: str | None = None


def _gift_card_item(order: Order) -> str | None:
    for item in order.items:
        if item.category == "gift_card" or "gift card" in item.name.lower():
            return item.name
    return None


def _reject(
    *,
    internal_reason: str,
    tool_calls: list[ToolCallLog],
    order: Order | None = None,
) -> ReturnPrescreenResult:
    decision = RefundDecision(
        status="denied",
        customer_message="",
        internal_reason=internal_reason,
        amount=0,
        order_id=order.id if order else None,
        policy_rules=[internal_reason],
        tool_calls=tool_calls,
    )
    product_names = ", ".join(item.name for item in order.items) if order else None
    return ReturnPrescreenResult(
        outcome="REJECT",
        customer_message=customer_facing_message(decision),
        internal_reason=internal_reason,
        policy_rules=[internal_reason],
        tool_calls=tool_calls,
        order_id=order.id if order else None,
        product_names=product_names,
    )


def _proceed(*, order: Order, tool_calls: list[ToolCallLog]) -> ReturnPrescreenResult:
    return ReturnPrescreenResult(
        outcome="PROCEED",
        customer_message="",
        internal_reason="Order passed pre-return eligibility screening.",
        policy_rules=[],
        tool_calls=tool_calls,
        order_id=order.id,
        product_names=", ".join(item.name for item in order.items),
    )


def evaluate_return_prescreen(customer_id: str, order_id: str) -> ReturnPrescreenResult:
    """Run policy checks that do not require a customer reason or supporting documents."""
    customer = find_customer(customer_id)
    if not customer:
        return _reject(
            internal_reason="Customer profile was not found in CRM.",
            tool_calls=[],
        )

    order = find_order(customer, order_id)
    if not order:
        return _reject(
            internal_reason="Order was not found under the customer profile.",
            tool_calls=[],
        )

    tool_calls: list[ToolCallLog] = []

    window_call = check_return_window(customer, order)
    tool_calls.append(window_call)
    window_output = window_call.output
    if not window_output.get("eligible"):
        if window_output.get("escalate"):
            # Lost shipments and similar cases still need the customer's reason.
            pass
        else:
            return _reject(
                internal_reason=str(window_output.get("rule", "Return is not eligible.")),
                tool_calls=tool_calls,
                order=order,
            )

    gift_card = _gift_card_item(order)
    if gift_card:
        return _reject(
            internal_reason=f"{gift_card} is a gift card and cannot be refunded once issued.",
            tool_calls=tool_calls,
            order=order,
        )

    condition_call = check_item_condition(order)
    tool_calls.append(condition_call)
    if not condition_call.output.get("eligible"):
        denials = condition_call.output.get("denials") or []
        reason = "; ".join(str(denial) for denial in denials) or "Item condition is not eligible."
        return _reject(internal_reason=reason, tool_calls=tool_calls, order=order)

    loyalty_call = check_opened_item_loyalty(customer, order)
    tool_calls.append(loyalty_call)
    if not loyalty_call.output.get("eligible"):
        return _reject(
            internal_reason=str(
                loyalty_call.output.get("rule", "Opened items require an eligible membership tier.")
            ),
            tool_calls=tool_calls,
            order=order,
        )

    return _proceed(order=order, tool_calls=tool_calls)
