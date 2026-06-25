from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from uuid import uuid4

from app.agent.tools import (
    DEMO_TODAY,
    _refund_count_last_12_months,
    _return_request_count_last_90_days,
    find_customer,
    find_order,
    get_fraud_assessment,
)
from app.db.database import get_connection, int_to_bool
from app.rag.fraud_index import retrieve_fraud_sections
from app.services.log_bus import log_bus

RISK_LOW = "LOW_RISK"
RISK_MEDIUM = "MEDIUM_RISK"
RISK_HIGH = "HIGH_RISK"
RISK_CRITICAL = "CRITICAL_RISK"


@dataclass
class FraudSignal:
    rule_id: str
    category: str
    description: str
    score_delta: int
    severity: str


@dataclass
class FraudDetectionResult:
    run_id: str
    request_id: str
    customer_id: str
    order_id: str
    fraud_score: int
    risk_level: str
    is_fraud_flagged: bool
    signals: list[FraudSignal]
    reasoning: str
    policy_sections: list[dict]
    recommendation: str


def classify_risk_level(score: int) -> str:
    if score <= 25:
        return RISK_LOW
    if score <= 50:
        return RISK_MEDIUM
    if score <= 75:
        return RISK_HIGH
    return RISK_CRITICAL


def _risk_recommendation(risk_level: str) -> str:
    return {
        RISK_LOW: "Continue automated refund processing where refund policy allows.",
        RISK_MEDIUM: "Request additional evidence or customer verification before continuing.",
        RISK_HIGH: "Forward to manual fraud review. Automatic approval should not occur.",
        RISK_CRITICAL: "Suspend automatic processing and escalate to the Fraud Investigation Team.",
    }[risk_level]


def _account_age_days(account_created: str | None) -> int | None:
    if not account_created:
        return None
    created = date.fromisoformat(str(account_created))
    return (DEMO_TODAY - created).days


def _return_request_count_last_12_months(customer_id: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM ReturnRequest
            WHERE customer_id = ?
              AND request_date >= DATE(?, '-12 months')
            """,
            (customer_id, DEMO_TODAY.isoformat()),
        ).fetchone()
    return int(row["count"])


def _refund_amount_last_12_months(customer_id: str) -> float:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(refund_amount), 0) AS total
            FROM RefundHistory
            WHERE customer_id = ?
              AND approved_date >= DATE(?, '-12 months')
            """,
            (customer_id, DEMO_TODAY.isoformat()),
        ).fetchone()
    return float(row["total"] or 0)


def _duplicate_return_for_order(customer_id: str, order_id: str, request_id: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM ReturnRequest
            WHERE customer_id = ?
              AND order_id = ?
              AND request_id != ?
              AND status NOT IN ('Closed')
            """,
            (customer_id, order_id, request_id),
        ).fetchone()
    return int(row["count"]) > 0


def _category_refund_count(customer_id: str, category: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM ReturnRequest rr
            JOIN Orders o ON rr.order_id = o.order_id
            JOIN OrderItem oi ON oi.order_id = o.order_id
            JOIN Product p ON p.product_id = oi.product_id
            WHERE rr.customer_id = ?
              AND p.category = ?
              AND rr.status IN ('Approved', 'Pending', 'Manual Review', 'Manager Review')
            """,
            (customer_id, category),
        ).fetchone()
    return int(row["count"])


def _load_return_request(request_id: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM ReturnRequest WHERE request_id = ?",
            (request_id,),
        ).fetchone()
    return dict(row) if row else None


def _load_evidence(request_id: str) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT evidence_id, type, verified, file_path FROM Evidence WHERE request_id = ?",
            (request_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _collect_signals(
    *,
    customer_id: str,
    order_id: str,
    request_id: str,
) -> list[FraudSignal]:
    customer = find_customer(customer_id)
    order = find_order(customer, order_id) if customer else None
    return_request = _load_return_request(request_id)
    fraud_assessment, _ = get_fraud_assessment(customer) if customer else (None, None)
    evidence = _load_evidence(request_id)
    signals: list[FraudSignal] = []

    if not customer:
        return signals

    account_age = _account_age_days(customer.account_created)
    if account_age is not None and account_age < 30:
        signals.append(
            FraudSignal(
                "account_age_under_30",
                "Customer Account",
                f"Account age is {account_age} days (under 30 days).",
                10,
                "high",
            )
        )
    elif account_age is not None and account_age < 90:
        signals.append(
            FraudSignal(
                "account_age_under_90",
                "Customer Account",
                f"Account age is {account_age} days (between 30 and 90 days).",
                5,
                "medium",
            )
        )

    if customer.fraud_flag:
        signals.append(
            FraudSignal(
                "customer_fraud_flag",
                "Customer Account",
                "Customer account has an active fraud flag.",
                35,
                "critical",
            )
        )
    if "Under investigation: yes" in customer.notes:
        signals.append(
            FraudSignal(
                "under_investigation",
                "Customer Account",
                "Customer is under refund abuse investigation.",
                30,
                "critical",
            )
        )

    refunds_12m = _refund_count_last_12_months(customer_id)
    if refunds_12m > 3:
        signals.append(
            FraudSignal(
                "refunds_over_3_12m",
                "Refund Behaviour",
                f"Customer has {refunds_12m} approved refunds in the last 12 months.",
                20,
                "high",
            )
        )
    elif refunds_12m == 3:
        signals.append(
            FraudSignal(
                "refunds_equal_3_12m",
                "Refund Behaviour",
                "Customer has 3 approved refunds in the last 12 months.",
                10,
                "medium",
            )
        )

    return_requests_90d = _return_request_count_last_90_days(customer_id)
    if return_requests_90d > 5:
        signals.append(
            FraudSignal(
                "returns_over_5_90d",
                "Refund Behaviour",
                f"Customer has {return_requests_90d} return requests in the last 90 days.",
                15,
                "high",
            )
        )

    return_requests_12m = _return_request_count_last_12_months(customer_id)
    if return_requests_12m > 10:
        signals.append(
            FraudSignal(
                "returns_over_10_12m",
                "Refund Behaviour",
                f"Customer has {return_requests_12m} return requests in the last 12 months.",
                25,
                "critical",
            )
        )

    refunded_total = _refund_amount_last_12_months(customer_id)
    lifetime = max(float(customer.lifetime_value or 0), 1.0)
    if refunded_total / lifetime > 0.7:
        signals.append(
            FraudSignal(
                "refund_value_over_70pct_lifetime",
                "Refund Behaviour",
                "Refund value exceeds 70% of lifetime purchases.",
                30,
                "critical",
            )
        )

    chargebacks = int(customer.chargeback_count or 0)
    if chargebacks >= 3:
        signals.append(
            FraudSignal(
                "chargebacks_critical",
                "Chargeback",
                f"Customer has {chargebacks} chargebacks.",
                35,
                "critical",
            )
        )
    elif chargebacks == 2:
        signals.append(
            FraudSignal(
                "chargebacks_high",
                "Chargeback",
                "Customer has 2 chargebacks.",
                30,
                "high",
            )
        )
    elif chargebacks == 1:
        signals.append(
            FraudSignal(
                "chargebacks_medium",
                "Chargeback",
                "Customer has 1 previous chargeback.",
                15,
                "medium",
            )
        )

    if _duplicate_return_for_order(customer_id, order_id, request_id):
        signals.append(
            FraudSignal(
                "duplicate_return_request",
                "Communication",
                "Duplicate refund request detected for the same order.",
                20,
                "critical",
            )
        )

    if fraud_assessment:
        if not int_to_bool(fraud_assessment.get("identity_verified")):
            signals.append(
                FraudSignal(
                    "identity_not_verified",
                    "Identity Verification",
                    "Identity verification failed or is incomplete.",
                    25,
                    "critical",
                )
            )
        if int_to_bool(fraud_assessment.get("multiple_account_match")):
            signals.append(
                FraudSignal(
                    "multiple_linked_accounts",
                    "Device & Network",
                    "Multiple linked customer accounts detected.",
                    25,
                    "high",
                )
            )
        if int_to_bool(fraud_assessment.get("ip_mismatch")):
            signals.append(
                FraudSignal(
                    "ip_mismatch",
                    "Device & Network",
                    "Device or network IP mismatch detected.",
                    10,
                    "medium",
                )
            )
        payment_risk = float(fraud_assessment.get("payment_risk_score") or 0)
        if payment_risk >= 0.75:
            signals.append(
                FraudSignal(
                    "payment_risk_high",
                    "Identity Verification",
                    f"Payment risk score is elevated ({payment_risk:.2f}).",
                    15,
                    "high",
                )
            )

    if order:
        electronics_items = [item for item in order.items if item.category == "electronics"]
        if electronics_items and order.total >= 300:
            signals.append(
                FraudSignal(
                    "high_value_electronics_return",
                    "Purchase Behaviour",
                    "High-value electronics purchase with an active return request.",
                    15,
                    "high",
                )
            )
        opened_items = [item for item in order.items if item.condition in {"opened", "used"}]
        if opened_items and return_request:
            reason = str(return_request.get("reason", "")).lower()
            comment = str(return_request.get("customer_comment", "")).lower()
            unused_claim = any(term in f"{reason} {comment}" for term in ("unused", "unopened", "never opened"))
            if unused_claim:
                signals.append(
                    FraudSignal(
                        "opened_item_unused_claim",
                        "Product Return Behaviour",
                        "Customer described the product as unused but order records show opened/used condition.",
                        20,
                        "high",
                    )
                )
            elif opened_items:
                signals.append(
                    FraudSignal(
                        "opened_product_return",
                        "Product Return Behaviour",
                        "Customer is returning opened products.",
                        10,
                        "medium",
                    )
                )
        for item in order.items:
            if _category_refund_count(customer_id, item.category) > 2:
                signals.append(
                    FraudSignal(
                        f"repeat_category_{item.category}",
                        "Product Return Behaviour",
                        f"Repeated refunds for {item.category} category products.",
                        10,
                        "medium",
                    )
                )
                break

    if evidence:
        unverified = [row for row in evidence if not int_to_bool(row.get("verified"))]
        if unverified:
            signals.append(
                FraudSignal(
                    "unverified_evidence",
                    "Image Verification",
                    "Uploaded evidence has not passed automated verification.",
                    15,
                    "medium",
                )
            )
    elif return_request and any(
        term in str(return_request.get("reason", "")).lower()
        for term in ("damaged", "defect", "wrong item", "missing")
    ):
        signals.append(
            FraudSignal(
                "missing_evidence_for_claim",
                "Image Verification",
                "Damage or defect claim submitted without verified supporting images.",
                10,
                "medium",
            )
        )

    deduped: dict[str, FraudSignal] = {}
    for signal in signals:
        deduped[signal.rule_id] = signal
    return list(deduped.values())


def _build_rag_query(signals: list[FraudSignal], return_request: dict | None) -> str:
    categories = sorted({signal.category for signal in signals})
    rule_text = " ".join(signal.description for signal in signals[:6])
    reason = str((return_request or {}).get("reason", ""))
    return f"Shopward anti-fraud policy {' '.join(categories)} {reason} {rule_text}"


def _build_admin_reasoning(
    *,
    signals: list[FraudSignal],
    policy_sections: list[dict],
    fraud_score: int,
    risk_level: str,
) -> str:
    lines = [
        f"Fraud score: {fraud_score}/100 ({risk_level.replace('_', ' ').title()}).",
        _risk_recommendation(risk_level),
        "",
        "Triggered indicators:",
    ]
    if signals:
        for signal in sorted(signals, key=lambda item: item.score_delta, reverse=True):
            lines.append(f"- [{signal.category}] {signal.description} (+{signal.score_delta})")
    else:
        lines.append("- No significant fraud indicators detected.")

    if policy_sections:
        lines.extend(["", "Relevant anti-fraud policy guidance:"])
        for section in policy_sections[:3]:
            excerpt = section["content"].split("\n")[0][:220]
            lines.append(f"- {section['section_title']}: {excerpt}")

    return "\n".join(lines)


def _persist_detection(result: FraudDetectionResult) -> None:
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM FraudDetectionRun WHERE request_id = ?",
            (result.request_id,),
        )
        connection.execute(
            """
            INSERT INTO FraudDetectionRun (
                run_id, request_id, customer_id, order_id, fraud_score, risk_level,
                is_fraud_flagged, signals_json, reasoning, policy_sections_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.run_id,
                result.request_id,
                result.customer_id,
                result.order_id,
                result.fraud_score,
                result.risk_level,
                int(result.is_fraud_flagged),
                json.dumps([asdict(signal) for signal in result.signals]),
                result.reasoning,
                json.dumps(result.policy_sections),
                datetime.utcnow().isoformat(),
            ),
        )


def get_latest_fraud_detection(request_id: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM FraudDetectionRun
            WHERE request_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (request_id,),
        ).fetchone()
    return dict(row) if row else None


async def evaluate_fraud_for_return(
    *,
    customer_id: str,
    order_id: str,
    request_id: str,
) -> FraudDetectionResult:
    return_request = _load_return_request(request_id)
    signals = _collect_signals(
        customer_id=customer_id,
        order_id=order_id,
        request_id=request_id,
    )
    fraud_score = min(100, sum(signal.score_delta for signal in signals))
    risk_level = classify_risk_level(fraud_score)
    is_fraud_flagged = risk_level in {RISK_HIGH, RISK_CRITICAL}
    policy_sections = retrieve_fraud_sections(_build_rag_query(signals, return_request), limit=4)
    reasoning = _build_admin_reasoning(
        signals=signals,
        policy_sections=policy_sections,
        fraud_score=fraud_score,
        risk_level=risk_level,
    )
    result = FraudDetectionResult(
        run_id=f"frd_{uuid4().hex[:8]}",
        request_id=request_id,
        customer_id=customer_id,
        order_id=order_id,
        fraud_score=fraud_score,
        risk_level=risk_level,
        is_fraud_flagged=is_fraud_flagged,
        signals=signals,
        reasoning=reasoning,
        policy_sections=policy_sections,
        recommendation=_risk_recommendation(risk_level),
    )
    _persist_detection(result)
    await log_bus.publish(
        "fraud_scored",
        f"Fraud engine scored return request {request_id} as {risk_level} ({fraud_score}/100).",
        customer_id=customer_id,
        order_id=order_id,
        metadata={
            "request_id": request_id,
            "run_id": result.run_id,
            "fraud_score": fraud_score,
            "risk_level": risk_level,
            "is_fraud_flagged": is_fraud_flagged,
            "signals": [asdict(signal) for signal in signals],
            "reasoning": reasoning,
            "policy_sections": policy_sections,
        },
    )
    return result
