from __future__ import annotations

import os
from typing import Any

from app.agent.tools import (
    check_fraud_risk,
    check_item_condition,
    check_opened_item_loyalty,
    check_refund_limit,
    check_return_window,
    get_fraud_assessment,
    get_order,
    get_refund_history,
    get_return_request,
    load_policy,
    lookup_customer,
    retrieve_policy_sections,
    store_agent_decision,
)
from app.models import ChatRequest, RefundDecision, ToolCallLog
from app.services.log_bus import log_bus

try:  # LangGraph is the intended production runtime; this keeps local demos resilient.
    from langgraph.graph import StateGraph  # type: ignore
except Exception:  # pragma: no cover - dependency may not be installed during static checks.
    StateGraph = None  # type: ignore


async def _log_tool(customer_id: str | None, order_id: str | None, call: ToolCallLog) -> None:
    await log_bus.publish(
        "tool_call",
        f"Tool `{call.tool}` returned {call.output}",
        customer_id=customer_id,
        order_id=order_id,
        metadata=call.model_dump(mode="json"),
    )


async def _optional_llm_customer_copy(decision: RefundDecision, customer_message: str) -> str:
    """Use the LLM for wording when configured, while keeping the policy verdict deterministic."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return decision.customer_message

    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"), temperature=0.2)
        response = await llm.ainvoke(
            [
                (
                    "system",
                    "Rewrite the refund decision for a customer. Do not change status, amount, or policy facts.",
                ),
                (
                    "user",
                    f"Customer request: {customer_message}\nDecision: {decision.model_dump_json()}",
                ),
            ]
        )
        content = getattr(response, "content", "")
        return str(content).strip() or decision.customer_message
    except Exception:
        return decision.customer_message


def build_langgraph_definition() -> Any:
    """Expose a LangGraph definition for teams that want to expand the workflow."""
    if StateGraph is None:
        return None

    graph = StateGraph(dict)
    graph.add_node("start", lambda state: state)
    graph.set_entry_point("start")
    graph.set_finish_point("start")
    return graph.compile()


async def run_refund_agent(request: ChatRequest) -> RefundDecision:
    await log_bus.publish(
        "start",
        "Received refund request and started policy validation.",
        customer_id=request.customer_id,
        order_id=request.order_id,
        metadata={"message": request.message},
    )

    policy_text = load_policy()
    await log_bus.publish(
        "policy",
        "Loaded strict refund policy source document.",
        customer_id=request.customer_id,
        order_id=request.order_id,
        metadata={"policy_excerpt": policy_text[:700]},
    )

    tool_calls: list[ToolCallLog] = []
    customer, customer_call = lookup_customer(request.customer_id)
    tool_calls.append(customer_call)
    await _log_tool(request.customer_id, request.order_id, customer_call)

    if not customer:
        decision = RefundDecision(
            status="escalated",
            customer_message=(
                "I could not find your customer profile, so a human specialist will review this request."
            ),
            internal_reason="Customer profile was not found in CRM.",
            policy_rules=["Requests without a verifiable CRM profile require review."],
            tool_calls=tool_calls,
        )
        return decision

    order, order_call = get_order(customer, request.order_id)
    tool_calls.append(order_call)
    await _log_tool(customer.id, request.order_id, order_call)

    if not order:
        decision = RefundDecision(
            status="escalated",
            customer_message=(
                "I could not locate that order, so a human specialist will review this request."
            ),
            internal_reason="Order was not found under the customer profile.",
            policy_rules=["Refunds require a matching order in CRM."],
            tool_calls=tool_calls,
        )
        return decision

    return_request, return_request_call = get_return_request(customer.id, order.id)
    tool_calls.append(return_request_call)
    await _log_tool(customer.id, order.id, return_request_call)

    refund_history, refund_history_call = get_refund_history(customer)
    tool_calls.append(refund_history_call)
    await _log_tool(customer.id, order.id, refund_history_call)

    fraud_assessment, fraud_assessment_call = get_fraud_assessment(customer)
    tool_calls.append(fraud_assessment_call)
    await _log_tool(customer.id, order.id, fraud_assessment_call)

    policy_sections, policy_sections_call = retrieve_policy_sections(request.message, order)
    tool_calls.append(policy_sections_call)
    await _log_tool(customer.id, order.id, policy_sections_call)
    await log_bus.publish(
        "policy_rag",
        "Retrieved policy sections from local vector index.",
        customer_id=customer.id,
        order_id=order.id,
        metadata={"sections": policy_sections},
    )

    checks = [
        check_fraud_risk(customer, fraud_assessment),
        check_return_window(customer, order),
        check_item_condition(order),
        check_opened_item_loyalty(customer, order),
        check_refund_limit(customer, order, refund_history),
    ]

    for call in checks:
        tool_calls.append(call)
        await _log_tool(customer.id, order.id, call)

    escalation_reasons: list[str] = []
    denial_reasons: list[str] = []
    policy_rules: list[str] = []
    review_level = "Manual Review"

    for call in checks:
        output = call.output
        rule = output.get("rule")
        if rule:
            policy_rules.append(str(rule))
        if output.get("escalate"):
            escalation_reasons.extend(str(reason) for reason in output.get("reasons", []) or [])
            if output.get("review_level") == "Manager Review":
                review_level = "Manager Review"
            if rule:
                escalation_reasons.append(str(rule))
        if output.get("eligible") is False:
            denial_reasons.append(str(rule or f"{call.tool} failed eligibility."))
        if output.get("eligible_for_auto_refund") is False and output.get("escalate"):
            escalation_reasons.extend(str(reason) for reason in output.get("reasons", []) or [])
        denial_reasons.extend(str(reason) for reason in output.get("denials", []) or [])

    if escalation_reasons:
        decision = RefundDecision(
            status="escalated",
            customer_message=(
                f"Thanks for the details. This refund needs {review_level.lower()} before we can make a final decision."
            ),
            internal_reason="; ".join(dict.fromkeys(escalation_reasons)),
            amount=order.total,
            order_id=order.id,
            policy_rules=list(
                dict.fromkeys(
                    policy_rules
                    + escalation_reasons
                    + [section["section_title"] for section in policy_sections]
                )
            ),
            tool_calls=tool_calls,
        )
    elif denial_reasons:
        reason_text = "; ".join(dict.fromkeys(denial_reasons))
        decision = RefundDecision(
            status="denied",
            customer_message=(
                "I’m sorry, but this order is not eligible for an automatic refund under our policy. "
                f"Reason: {reason_text}"
            ),
            internal_reason=reason_text,
            amount=0,
            order_id=order.id,
            policy_rules=list(
                dict.fromkeys(
                    policy_rules
                    + denial_reasons
                    + [section["section_title"] for section in policy_sections]
                )
            ),
            tool_calls=tool_calls,
        )
    else:
        decision = RefundDecision(
            status="approved",
            customer_message=(
                f"Your refund is approved for ${order.total:.2f}. You’ll receive confirmation once it is processed."
            ),
            internal_reason="All policy checks passed for an automatic refund.",
            amount=order.total,
            order_id=order.id,
            policy_rules=list(
                dict.fromkeys(policy_rules + [section["section_title"] for section in policy_sections])
            ),
            tool_calls=tool_calls,
        )

    decision.customer_message = await _optional_llm_customer_copy(decision, request.message)

    audit_decision = (
        "Approved"
        if decision.status == "approved"
        else "Denied"
        if decision.status == "denied"
        else review_level
    )
    confidence_score = 0.92 if decision.status == "approved" else 0.86
    store_call = store_agent_decision(
        return_request["request_id"] if return_request else None,
        decision,
        confidence_score,
        policy_sections,
        audit_decision,
    )
    tool_calls.append(store_call)
    decision.tool_calls = tool_calls
    await _log_tool(customer.id, order.id, store_call)

    await log_bus.publish(
        "decision",
        f"Final decision: {decision.status}",
        customer_id=customer.id,
        order_id=order.id,
        metadata={
            **decision.model_dump(mode="json"),
            "return_request_status": audit_decision,
            "policy_sections": policy_sections,
        },
    )
    return decision
