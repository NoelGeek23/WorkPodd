from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import uuid4

from app.agent.tools import DEMO_TODAY, find_customer, find_order
from app.db.database import get_connection
from app.models import Order, OrderItem
from app.rag.refund_policy_index import retrieve_refund_policy_sections
from app.services.log_bus import log_bus
from app.services.product_classification import is_hygiene_sensitive_product, product_type_label

OUTCOME_APPROVED = "APPROVED"
OUTCOME_DENIED = "DENIED"
OUTCOME_ESCALATED = "ESCALATED"


@dataclass
class RefundRuleSignal:
    rule_id: str
    category: str
    description: str
    outcome: str


@dataclass
class RefundEvaluationResult:
    run_id: str
    request_id: str
    customer_id: str
    order_id: str
    outcome: str
    reasoning: str
    policy_sections: list[dict]
    signals: list[RefundRuleSignal]
    customer_reason: str
    customer_description: str


def _load_return_request(request_id: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM ReturnRequest WHERE request_id = ?",
            (request_id,),
        ).fetchone()
    return dict(row) if row else None


def _days_since_delivery(order: Order) -> int | None:
    if not order.delivered_date:
        return None
    from datetime import date

    delivered = date.fromisoformat(str(order.delivered_date))
    return (DEMO_TODAY - delivered).days


def _allowed_return_days(customer) -> int:
    if customer.loyalty_tier.value in {"gold", "platinum"} or "VIP: yes" in customer.notes:
        return 45
    return 30


def _evaluate_item(
    item: OrderItem,
    *,
    reason: str,
    description: str,
    days_since_delivery: int | None,
    allowed_days: int,
) -> list[RefundRuleSignal]:
    signals: list[RefundRuleSignal] = []
    label = item.name
    reason_text = f"{reason} {description}".lower()

    if item.final_sale:
        signals.append(
            RefundRuleSignal(
                "final_sale",
                "Product Category",
                f"{label} is a final sale item and cannot be refunded.",
                OUTCOME_DENIED,
            )
        )
    if item.digital_download or item.condition == "digital_delivered":
        signals.append(
            RefundRuleSignal(
                "digital_product",
                "Digital Downloads",
                f"{label} is a digital purchase and is not eligible for automatic refund.",
                OUTCOME_DENIED,
            )
        )
    if item.subscription_product:
        signals.append(
            RefundRuleSignal(
                "subscription",
                "Subscription Services",
                f"{label} is a subscription product and requires subscription support review.",
                OUTCOME_ESCALATED,
            )
        )
    if item.category == "grocery" or "coffee" in label.lower() or "perishable" in reason_text:
        quality_issue = any(
            term in reason_text
            for term in ("spoiled", "damaged", "expired", "freshness", "quality", "defect")
        )
        if not quality_issue and any(term in reason_text for term in ("changed mind", "don't want", "no longer")):
            signals.append(
                RefundRuleSignal(
                    "perishable_change_of_mind",
                    "Grocery & Perishable Goods",
                    f"{label} is a perishable or grocery item; change-of-mind returns are not eligible.",
                    OUTCOME_DENIED,
                )
            )
    if "gift" in label.lower() or item.category == "gift_card":
        signals.append(
            RefundRuleSignal(
                "gift_card",
                "Gift Cards",
                f"{label} is a gift card and cannot be refunded once issued.",
                OUTCOME_DENIED,
            )
        )
    if is_hygiene_sensitive_product(item) and item.condition != "unopened":
        signals.append(
            RefundRuleSignal(
                "hygiene_opened",
                product_type_label(item.category),
                f"{label} is an opened hygiene-sensitive product and cannot be refunded automatically.",
                OUTCOME_DENIED,
            )
        )
    if item.condition == "used":
        signals.append(
            RefundRuleSignal(
                "used_condition",
                "Product Condition",
                f"{label} was returned in used condition.",
                OUTCOME_DENIED,
            )
        )
    if days_since_delivery is not None and days_since_delivery > allowed_days:
        signals.append(
            RefundRuleSignal(
                "return_window",
                "Return Window",
                f"{label}: return submitted {days_since_delivery} days after delivery "
                f"(allowed {allowed_days} days).",
                OUTCOME_DENIED,
            )
        )
    if item.condition == "damaged" and "carrier" not in reason_text and "shipping" not in reason_text:
        if "defect" not in reason_text and "damaged" not in reason_text:
            signals.append(
                RefundRuleSignal(
                    "damaged_needs_review",
                    "Product Condition",
                    f"{label} is marked damaged; customer reason should be reviewed against policy.",
                    OUTCOME_ESCALATED,
                )
            )

    return signals


def _aggregate_outcome(signals: list[RefundRuleSignal]) -> str:
    if any(signal.outcome == OUTCOME_DENIED for signal in signals):
        return OUTCOME_DENIED
    if any(signal.outcome == OUTCOME_ESCALATED for signal in signals):
        return OUTCOME_ESCALATED
    return OUTCOME_APPROVED


def _build_rag_query(
    *,
    reason: str,
    description: str,
    order: Order,
    signals: list[RefundRuleSignal],
) -> str:
    categories = ", ".join(item.category for item in order.items)
    names = ", ".join(item.name for item in order.items)
    signal_text = " ".join(signal.description for signal in signals[:4])
    return f"refund policy {reason} {description} {names} {categories} {signal_text}"


def _build_admin_reasoning(
    *,
    outcome: str,
    signals: list[RefundRuleSignal],
    policy_sections: list[dict],
    reason: str,
    description: str,
) -> str:
    lines = [
        f"Refund rule evaluation: {outcome.replace('_', ' ').title()}.",
        "",
        f"Customer reason: {reason or 'Not provided'}",
        f"Customer description: {description or 'Not provided'}",
        "",
        "Policy findings:",
    ]
    if signals:
        for signal in signals:
            lines.append(f"- [{signal.category}] {signal.description}")
    else:
        lines.append("- No blocking refund rule violations detected.")

    if policy_sections:
        lines.extend(["", "Relevant refund policy guidance:"])
        for section in policy_sections[:3]:
            excerpt = section["content"].split("\n")[0][:220]
            lines.append(f"- {section['section_title']}: {excerpt}")

    return "\n".join(lines)


def _persist_evaluation(result: RefundEvaluationResult) -> None:
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM RefundEvaluationRun WHERE request_id = ?",
            (result.request_id,),
        )
        connection.execute(
            """
            INSERT INTO RefundEvaluationRun (
                run_id, request_id, customer_id, order_id, outcome,
                reasoning, policy_sections_json, signals_json,
                customer_reason, customer_description, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.run_id,
                result.request_id,
                result.customer_id,
                result.order_id,
                result.outcome,
                result.reasoning,
                json.dumps(result.policy_sections),
                json.dumps([asdict(signal) for signal in result.signals]),
                result.customer_reason,
                result.customer_description,
                datetime.utcnow().isoformat(),
            ),
        )


def get_latest_refund_evaluation(request_id: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM RefundEvaluationRun
            WHERE request_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (request_id,),
        ).fetchone()
    return dict(row) if row else None


def evaluate_refund_rules(
    *,
    customer_id: str,
    order_id: str,
    request_id: str,
) -> RefundEvaluationResult:
    customer = find_customer(customer_id)
    order = find_order(customer, order_id) if customer else None
    return_request = _load_return_request(request_id)
    reason = str((return_request or {}).get("reason", ""))
    description = str((return_request or {}).get("customer_comment", ""))

    signals: list[RefundRuleSignal] = []
    if customer and order:
        allowed_days = _allowed_return_days(customer)
        days = _days_since_delivery(order)
        for item in order.items:
            signals.extend(
                _evaluate_item(
                    item,
                    reason=reason,
                    description=description,
                    days_since_delivery=days,
                    allowed_days=allowed_days,
                )
            )

    outcome = _aggregate_outcome(signals)
    policy_sections = retrieve_refund_policy_sections(
        _build_rag_query(reason=reason, description=description, order=order, signals=signals),
        limit=4,
    )
    reasoning = _build_admin_reasoning(
        outcome=outcome,
        signals=signals,
        policy_sections=policy_sections,
        reason=reason,
        description=description,
    )
    return RefundEvaluationResult(
        run_id=f"rev_{uuid4().hex[:8]}",
        request_id=request_id,
        customer_id=customer_id,
        order_id=order_id,
        outcome=outcome,
        reasoning=reasoning,
        policy_sections=policy_sections,
        signals=signals,
        customer_reason=reason,
        customer_description=description,
    )


async def evaluate_refund_for_return(
    *,
    customer_id: str,
    order_id: str,
    request_id: str,
) -> RefundEvaluationResult:
    result = evaluate_refund_rules(
        customer_id=customer_id,
        order_id=order_id,
        request_id=request_id,
    )
    _persist_evaluation(result)
    await log_bus.publish(
        "refund_evaluated",
        f"Refund rule engine evaluated request {request_id} as {result.outcome}.",
        customer_id=customer_id,
        order_id=order_id,
        metadata={
            "request_id": request_id,
            "run_id": result.run_id,
            "outcome": result.outcome,
            "reasoning": result.reasoning,
            "signals": [asdict(signal) for signal in result.signals],
            "policy_sections": result.policy_sections,
        },
    )
    return result
