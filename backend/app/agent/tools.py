from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from app.db.database import get_connection, int_to_bool, rows_to_dicts
from app.models import CustomerProfile, Order, OrderItem, RefundDecision, ToolCallLog
from app.rag.policy_index import load_policy, retrieve_policy_sections as rag_retrieve_policy_sections

DEMO_TODAY = date(2026, 6, 22)


def _call(tool: str, tool_input: dict[str, Any], output: dict[str, Any]) -> ToolCallLog:
    return ToolCallLog(tool=tool, input=tool_input, output=output)


def _refund_count_last_12_months(customer_id: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM RefundHistory
            WHERE customer_id = ?
              AND approved_date >= DATE(?, '-12 months')
            """,
            (customer_id, DEMO_TODAY.isoformat()),
        ).fetchone()
    return int(row["count"])


def _return_request_count_last_90_days(customer_id: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM ReturnRequest
            WHERE customer_id = ?
              AND request_date >= DATE(?, '-90 days')
            """,
            (customer_id, DEMO_TODAY.isoformat()),
        ).fetchone()
    return int(row["count"])


def _order_items(order_id: str) -> list[OrderItem]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                oi.order_item_id,
                oi.quantity,
                oi.unit_price,
                oi.condition,
                oi.serial_number_present,
                oi.original_packaging_present,
                oi.original_accessories_present,
                p.sku,
                p.name,
                p.category,
                p.product_type,
                p.final_sale,
                p.digital_download,
                p.subscription_product,
                p.hygiene_sensitive
            FROM OrderItem oi
            JOIN Product p ON oi.product_id = p.product_id
            WHERE oi.order_id = ?
            ORDER BY oi.order_item_id
            """,
            (order_id,),
        ).fetchall()

    return [
        OrderItem(
            sku=row["sku"],
            name=row["name"],
            category=row["category"],
            product_type=row["product_type"],
            price=float(row["unit_price"]),
            quantity=int(row["quantity"]),
            condition=row["condition"],
            final_sale=int_to_bool(row["final_sale"]),
            digital_download=int_to_bool(row["digital_download"]),
            subscription_product=int_to_bool(row["subscription_product"]),
            hygiene_sensitive=int_to_bool(row["hygiene_sensitive"]),
            serial_number_present=int_to_bool(row["serial_number_present"]),
            original_packaging_present=int_to_bool(row["original_packaging_present"]),
            original_accessories_present=int_to_bool(row["original_accessories_present"]),
        )
        for row in rows
    ]


def _customer_from_row(row: Any) -> CustomerProfile:
    return CustomerProfile(
        id=row["customer_id"],
        name=row["name"],
        email=row["email"],
        loyalty_tier=row["loyalty_tier"],
        account_created=row["account_created_date"],
        fraud_flag=int_to_bool(row["fraud_flag"]),
        chargeback_count=int(row["chargeback_count"] or 0),
        refund_count_last_12_months=_refund_count_last_12_months(row["customer_id"]),
        lifetime_value=float(row["lifetime_spend"] or 0),
        notes=(
            f"{row['account_type']} account in {row['country']}; "
            f"VIP: {'yes' if int_to_bool(row['vip_status']) else 'no'}; "
            f"Under investigation: {'yes' if int_to_bool(row['under_investigation']) else 'no'}"
        ),
        orders=[],
    )


def _order_from_row(row: Any) -> Order:
    return Order(
        id=row["order_id"],
        order_date=row["purchase_date"],
        delivered_date=row["delivered_date"],
        status=row["status"],
        total=float(row["total_amount"] or 0),
        currency=row["currency"],
        items=_order_items(row["order_id"]),
        payment_method="stored_payment_method",
        shipping_country=row["shipping_country"],
        tracking_status=row["tracking_status"],
    )


def load_customers() -> list[CustomerProfile]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM Customer ORDER BY customer_id"
        ).fetchall()

    customers = [_customer_from_row(row) for row in rows]
    for customer in customers:
        customer.orders = get_orders_for_customer(customer.id)
    return customers


def find_customer(customer_id: str) -> CustomerProfile | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM Customer WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
    if not row:
        return None
    customer = _customer_from_row(row)
    customer.orders = get_orders_for_customer(customer.id)
    return customer


def get_orders_for_customer(customer_id: str) -> list[Order]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM Orders
            WHERE customer_id = ?
            ORDER BY purchase_date DESC, order_id
            """,
            (customer_id,),
        ).fetchall()
    return [_order_from_row(row) for row in rows]


def find_order(customer: CustomerProfile, order_id: str | None = None) -> Order | None:
    params: tuple[Any, ...]
    where = "customer_id = ?"
    params = (customer.id,)
    if order_id:
        where += " AND order_id = ?"
        params = (customer.id, order_id)

    with get_connection() as connection:
        row = connection.execute(
            f"""
            SELECT *
            FROM Orders
            WHERE {where}
            ORDER BY purchase_date DESC, order_id
            LIMIT 1
            """,
            params,
        ).fetchone()
    return _order_from_row(row) if row else None


def get_return_request(customer_id: str, order_id: str) -> tuple[dict | None, ToolCallLog]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM ReturnRequest
            WHERE customer_id = ? AND order_id = ?
            ORDER BY request_date DESC
            LIMIT 1
            """,
            (customer_id, order_id),
        ).fetchone()
    output = dict(row) if row else {"found": False}
    if row:
        output["found"] = True
    return (dict(row) if row else None), _call(
        "get_return_request",
        {"customer_id": customer_id, "order_id": order_id},
        output,
    )


def lookup_customer(customer_id: str) -> tuple[CustomerProfile | None, ToolCallLog]:
    customer = find_customer(customer_id)
    output = (
        {
            "found": True,
            "name": customer.name,
            "loyalty_tier": customer.loyalty_tier.value,
            "fraud_flag": customer.fraud_flag,
            "chargeback_count": customer.chargeback_count,
            "refund_count_last_12_months": customer.refund_count_last_12_months,
        }
        if customer
        else {"found": False}
    )
    return customer, _call("lookup_customer", {"customer_id": customer_id}, output)


def get_order(customer: CustomerProfile, order_id: str | None) -> tuple[Order | None, ToolCallLog]:
    order = find_order(customer, order_id)
    output = (
        {
            "found": True,
            "order_id": order.id,
            "status": order.status,
            "total": order.total,
            "delivered_date": order.delivered_date,
            "tracking_status": order.tracking_status,
            "items": [item.model_dump() for item in order.items],
        }
        if order
        else {"found": False}
    )
    return order, _call("get_order", {"customer_id": customer.id, "order_id": order_id}, output)


def get_refund_history(customer: CustomerProfile) -> tuple[list[dict], ToolCallLog]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM RefundHistory
            WHERE customer_id = ?
            ORDER BY approved_date DESC
            """,
            (customer.id,),
        ).fetchall()
    refunds = rows_to_dicts(rows)
    return refunds, _call(
        "get_refund_history",
        {"customer_id": customer.id},
        {
            "refund_count": len(refunds),
            "refund_count_last_12_months": customer.refund_count_last_12_months,
            "refunds": refunds,
        },
    )


def get_fraud_assessment(customer: CustomerProfile) -> tuple[dict | None, ToolCallLog]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM FraudAssessment
            WHERE customer_id = ?
            ORDER BY assessment_date DESC
            LIMIT 1
            """,
            (customer.id,),
        ).fetchone()
    assessment = dict(row) if row else None
    output = assessment | {"found": True} if assessment else {"found": False}
    return assessment, _call("get_fraud_assessment", {"customer_id": customer.id}, output)


def retrieve_policy_sections(query: str, order: Order | None = None) -> tuple[list[dict], ToolCallLog]:
    item_context = " ".join(
        f"{item.name} {item.category} {item.condition} final_sale={item.final_sale} "
        f"hygiene={item.hygiene_sensitive}"
        for item in (order.items if order else [])
    )
    full_query = f"{query} {order.status if order else ''} {order.tracking_status if order else ''} {item_context}"
    sections = rag_retrieve_policy_sections(full_query)
    return sections, _call(
        "retrieve_policy_sections",
        {"query": query, "order_id": order.id if order else None},
        {"sections": sections},
    )


def check_return_window(customer: CustomerProfile, order: Order) -> ToolCallLog:
    if order.status == "lost":
        output = {
            "eligible": False,
            "escalate": True,
            "review_level": "Manual Review",
            "rule": "Lost shipments must be escalated.",
            "days_since_delivery": None,
        }
        return _call("check_return_window", {"order_id": order.id}, output)

    if order.status == "returned":
        output = {
            "eligible": False,
            "escalate": False,
            "rule": "This order has already been returned.",
            "days_since_delivery": None,
        }
        return _call("check_return_window", {"order_id": order.id}, output)

    if order.status != "delivered" or not order.delivered_date:
        output = {
            "eligible": False,
            "escalate": False,
            "rule": "Shipped but undelivered orders are not refundable.",
            "days_since_delivery": None,
        }
        return _call("check_return_window", {"order_id": order.id}, output)

    delivered = datetime.strptime(order.delivered_date, "%Y-%m-%d").date()
    days_since_delivery = (DEMO_TODAY - delivered).days
    if "business account" in customer.notes:
        allowed_days = 15
        window_reason = "Business accounts must submit returns within 15 days of delivery."
    elif order.shipping_country != "US":
        allowed_days = 20
        window_reason = "International orders must be returned within 20 days of delivery."
    elif customer.lifetime_value > 5000 or "VIP: yes" in customer.notes:
        allowed_days = 45
        window_reason = "VIP customers may use a 45 day return window."
    else:
        allowed_days = 30
        window_reason = "Physical products must be returned within 30 days of delivery."
    eligible = days_since_delivery <= allowed_days
    output = {
        "eligible": eligible,
        "escalate": False,
        "rule": window_reason,
        "days_since_delivery": days_since_delivery,
        "allowed_days": allowed_days,
    }
    return _call("check_return_window", {"customer_id": customer.id, "order_id": order.id}, output)


def check_item_condition(order: Order) -> ToolCallLog:
    denials: list[str] = []
    approvals: list[str] = []

    for item in order.items:
        label = f"{item.name} ({item.sku})"
        if item.final_sale:
            denials.append(f"{label}: final sale items are never refundable.")
        elif item.digital_download or item.condition == "digital_delivered":
            denials.append(f"{label}: digital delivered goods are not refundable.")
        elif item.subscription_product:
            denials.append(f"{label}: subscription products require manual subscription support.")
        elif item.hygiene_sensitive and item.condition != "unopened":
            denials.append(f"{label}: opened hygiene-sensitive items are not refundable.")
        elif not item.original_packaging_present:
            denials.append(f"{label}: original packaging is required for automatic refunds.")
        elif item.condition == "used":
            denials.append(f"{label}: used items are not refundable.")
        elif item.condition == "damaged" and "carrier damage" in order.tracking_status.lower():
            approvals.append(f"{label}: carrier damage noted by tracking.")
        elif item.condition == "damaged":
            denials.append(f"{label}: customer-caused damage is not refundable.")
        elif item.condition == "opened":
            approvals.append(f"{label}: opened item requires loyalty eligibility check.")
        else:
            approvals.append(f"{label}: unopened item condition is refundable.")

    output = {
        "eligible": not denials,
        "escalate": False,
        "denials": denials,
        "approvals": approvals,
    }
    return _call("check_item_condition", {"order_id": order.id}, output)


def check_opened_item_loyalty(customer: CustomerProfile, order: Order) -> ToolCallLog:
    has_opened = any(item.condition == "opened" and not item.hygiene_sensitive for item in order.items)
    eligible = not has_opened or customer.loyalty_tier.value in {"gold", "platinum"} or "VIP: yes" in customer.notes
    output = {
        "eligible": eligible,
        "rule": "Opened items are refundable only for gold, platinum, or VIP customers.",
        "has_opened_item": has_opened,
        "loyalty_tier": customer.loyalty_tier.value,
    }
    return _call(
        "check_opened_item_loyalty",
        {"customer_id": customer.id, "order_id": order.id},
        output,
    )


def check_refund_limit(customer: CustomerProfile, order: Order, refund_history: list[dict]) -> ToolCallLog:
    reasons: list[str] = []
    review_level = "Manual Review"
    refunds_last_12_months = customer.refund_count_last_12_months
    refunded_last_12_months = sum(
        float(refund["refund_amount"] or 0)
        for refund in refund_history
        if str(refund["approved_date"]) >= "2025-06-22"
    )
    return_requests_last_90_days = _return_request_count_last_90_days(customer.id)
    if refunds_last_12_months > 3:
        reasons.append("Customer has more than 3 refunds in the last 12 months.")
    if refunded_last_12_months > 2000:
        reasons.append("Customer has more than $2,000 refunded in the last 12 months.")
    if return_requests_last_90_days > 5:
        reasons.append("Customer has more than 5 return requests in 90 days.")
    if customer.chargeback_count >= 2:
        reasons.append("Customer has 2 or more chargebacks.")
    if order.total > 5000:
        reasons.append("Order exceeds $5,000 and requires senior manager approval.")
        review_level = "Manager Review"
    elif order.total > 1500:
        reasons.append("Order exceeds $1,500 and requires manager approval.")
        review_level = "Manager Review"
    elif order.total > 500:
        reasons.append("Order exceeds $500 and requires additional review.")
    output = {
        "eligible_for_auto_refund": not reasons,
        "escalate": bool(reasons),
        "review_level": review_level if reasons else None,
        "reasons": reasons,
        "refunds_last_12_months": refunds_last_12_months,
        "refunded_last_12_months": refunded_last_12_months,
        "return_requests_last_90_days": return_requests_last_90_days,
        "refund_history_records": len(refund_history),
    }
    return _call("check_refund_limit", {"customer_id": customer.id, "order_id": order.id}, output)


def check_fraud_risk(customer: CustomerProfile, fraud_assessment: dict | None) -> ToolCallLog:
    reasons: list[str] = []
    if customer.fraud_flag:
        reasons.append("Customer has a fraud flag.")
    if "Under investigation: yes" in customer.notes:
        reasons.append("Customer is under refund abuse investigation.")
    if fraud_assessment:
        if int_to_bool(fraud_assessment.get("manual_review_required")):
            reasons.append("Latest fraud assessment requires manual review.")
        if float(fraud_assessment.get("payment_risk_score") or 0) >= 0.75:
            reasons.append("Payment risk score is high.")
        if int_to_bool(fraud_assessment.get("ip_mismatch")):
            reasons.append("Fraud assessment detected an IP mismatch.")
        if int_to_bool(fraud_assessment.get("multiple_account_match")):
            reasons.append("Fraud assessment matched multiple accounts.")

    output = {
        "escalate": bool(reasons),
        "review_level": "Manual Review" if reasons else None,
        "rule": "Fraud flags and high-risk fraud assessments must be escalated.",
        "fraud_flag": customer.fraud_flag,
        "reasons": reasons,
        "fraud_assessment": fraud_assessment,
    }
    return _call("check_fraud_risk", {"customer_id": customer.id}, output)


def store_agent_decision(
    request_id: str | None,
    decision: RefundDecision,
    confidence_score: float,
    policy_sections: list[dict],
    audit_decision: str | None = None,
) -> ToolCallLog:
    decision_id = f"dec_{uuid4().hex[:12]}"
    section_refs = [
        {
            "chunk_id": section["chunk_id"],
            "section_title": section["section_title"],
            "score": section["score"],
        }
        for section in policy_sections
    ]
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO AgentDecisionLog (
                decision_id, request_id, decision, confidence_score, reasoning,
                policy_sections_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                request_id,
                audit_decision or decision.status,
                confidence_score,
                decision.internal_reason,
                json.dumps(section_refs),
                datetime.utcnow().isoformat(),
            ),
        )
    return _call(
        "store_agent_decision",
        {"request_id": request_id, "decision": audit_decision or decision.status},
        {"decision_id": decision_id, "policy_sections_used": section_refs},
    )
