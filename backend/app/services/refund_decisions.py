from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.db.database import get_connection
from app.models import RefundDecision
from app.services.customer_decisions import (
    customer_facing_message,
    ticket_denial_message,
)
from app.services.fraud_detection import evaluate_fraud_for_return, get_latest_fraud_detection
from app.services.refund_evaluation import evaluate_refund_for_return, get_latest_refund_evaluation
from app.services.log_bus import log_bus


def decision_status(decision: RefundDecision, review_level: str = "Manual Review") -> str:
    if decision.status == "approved":
        return "Approved"
    if decision.status == "denied":
        return "Denied"
    return review_level


def approval_message(amount: float) -> str:
    return (
        f"Refund of ${amount:.2f} will be transferred to your original bank account "
        "within 5-7 business days."
    )


def _review_level_from_decision(decision: RefundDecision) -> str:
    text = " ".join([decision.internal_reason, *decision.policy_rules]).lower()
    return "Manager Review" if "manager review" in text else "Manual Review"


def _ensure_return_request(
    *,
    customer_id: str,
    order_id: str,
    reason: str,
) -> str:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT request_id
            FROM ReturnRequest
            WHERE customer_id = ?
              AND order_id = ?
            ORDER BY request_date DESC, request_id DESC
            LIMIT 1
            """,
            (customer_id, order_id),
        ).fetchone()
        if row:
            return str(row["request_id"])

        request_id = f"ret_{uuid4().hex[:8]}"
        connection.execute(
            """
            INSERT INTO ReturnRequest (
                request_id, customer_id, order_id, request_date, reason,
                customer_comment, requested_resolution, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                customer_id,
                order_id,
                date.today().isoformat(),
                reason,
                "",
                "refund",
                "Pending",
            ),
        )
    return request_id


async def apply_refund_decision(
    *,
    decision: RefundDecision,
    customer_id: str,
    order_id: str,
    request_id: str | None = None,
    actor: str = "agent",
) -> str:
    resolved_request_id = request_id or _ensure_return_request(
        customer_id=customer_id,
        order_id=order_id,
        reason="Refund request",
    )

    if not get_latest_fraud_detection(resolved_request_id):
        await evaluate_fraud_for_return(
            customer_id=customer_id,
            order_id=order_id,
            request_id=resolved_request_id,
        )
    if not get_latest_refund_evaluation(resolved_request_id):
        await evaluate_refund_for_return(
            customer_id=customer_id,
            order_id=order_id,
            request_id=resolved_request_id,
        )
    fraud_detection = get_latest_fraud_detection(resolved_request_id)
    refund_evaluation = get_latest_refund_evaluation(resolved_request_id)
    if (
        fraud_detection
        and fraud_detection.get("is_fraud_flagged")
        and decision.status == "approved"
        and actor == "agent"
    ):
        review_level = (
            "Manager Review"
            if fraud_detection.get("risk_level") == "CRITICAL_RISK"
            else "Manual Review"
        )
        decision = decision.model_copy(
            update={
                "status": "escalated",
                "internal_reason": (
                    f"{decision.internal_reason}; Anti-fraud score "
                    f"{fraud_detection.get('fraud_score')}/100 requires manual review."
                ),
            }
        )

    if refund_evaluation and actor == "agent":
        eval_outcome = str(refund_evaluation.get("outcome", ""))
        if eval_outcome == "DENIED" and decision.status == "approved":
            decision = decision.model_copy(
                update={
                    "status": "denied",
                    "internal_reason": str(refund_evaluation.get("reasoning", "")).split("\n")[0],
                    "amount": 0,
                }
            )
        elif eval_outcome == "ESCALATED" and decision.status == "approved":
            decision = decision.model_copy(
                update={
                    "status": "escalated",
                    "internal_reason": str(refund_evaluation.get("reasoning", "")).split("\n")[0],
                }
            )

    review_level = _review_level_from_decision(decision)
    status = decision_status(decision, review_level)
    if decision.status == "denied":
        message = ticket_denial_message(decision, actor=actor)
    else:
        message = customer_facing_message(decision)

    with get_connection() as connection:
        ticket = connection.execute(
            """
            SELECT rr.request_id, rr.customer_id, rr.order_id, rr.reason, o.total_amount
            FROM ReturnRequest rr
            JOIN Orders o ON rr.order_id = o.order_id
            WHERE rr.request_id = ?
            """,
            (resolved_request_id,),
        ).fetchone()
        if not ticket:
            raise ValueError(f"Return request {resolved_request_id} was not found")

        if decision.status == "approved":
            refund_amount = float(decision.amount or ticket["total_amount"])
            message = approval_message(refund_amount)
            connection.execute(
                """
                UPDATE ReturnRequest
                SET status = 'Approved', admin_message = ?
                WHERE request_id = ?
                """,
                (message, resolved_request_id),
            )
            connection.execute(
                "UPDATE Orders SET status = 'returned' WHERE order_id = ?",
                (ticket["order_id"],),
            )
            existing_refund = connection.execute(
                """
                SELECT 1
                FROM RefundHistory
                WHERE customer_id = ?
                  AND order_id = ?
                LIMIT 1
                """,
                (ticket["customer_id"], ticket["order_id"]),
            ).fetchone()
            if not existing_refund:
                connection.execute(
                    """
                    INSERT INTO RefundHistory (
                        refund_id, customer_id, order_id, refund_amount, refund_reason, approved_date
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"ref_{uuid4().hex[:8]}",
                        ticket["customer_id"],
                        ticket["order_id"],
                        refund_amount,
                        ticket["reason"],
                        date.today().isoformat(),
                    ),
                )
        elif decision.status == "denied":
            connection.execute(
                """
                UPDATE ReturnRequest
                SET status = 'Denied', admin_message = ?
                WHERE request_id = ?
                """,
                (message, resolved_request_id),
            )
        else:
            connection.execute(
                """
                UPDATE ReturnRequest
                SET status = ?, admin_message = ?
                WHERE request_id = ?
                """,
                (status, message, resolved_request_id),
            )

    await log_bus.publish(
        "decision_synced",
        f"{actor.title()} synced refund decision to return request {resolved_request_id}.",
        customer_id=customer_id,
        order_id=order_id,
        metadata={
            "request_id": resolved_request_id,
            "status": status,
            "decision_status": decision.status,
            "actor": actor,
            "amount": decision.amount,
        },
    )
    return resolved_request_id
