from __future__ import annotations

import json
import os
from typing import Any, TypedDict

from app.agent.tools import (
    check_fraud_risk,
    check_item_condition,
    check_opened_item_loyalty,
    check_refund_limit,
    check_return_window,
    find_customer,
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
from app.services.customer_decisions import customer_facing_message
from app.services.fraud_detection import RISK_CRITICAL, RISK_HIGH, get_latest_fraud_detection
from app.services.refund_evaluation import get_latest_refund_evaluation
from app.services.log_bus import log_bus

try:  # LangGraph is the intended production runtime; this keeps local demos resilient.
    from langgraph.graph import END, StateGraph  # type: ignore
except Exception:  # pragma: no cover - dependency may not be installed during static checks.
    END = "__end__"  # type: ignore
    StateGraph = None  # type: ignore


class AgentState(TypedDict, total=False):
    request: ChatRequest
    policy_text: str
    customer: Any
    order: Any
    return_request: dict | None
    refund_history: list[dict]
    fraud_assessment: dict | None
    fraud_detection: dict | None
    refund_evaluation: dict | None
    policy_sections: list[dict]
    checks: list[ToolCallLog]
    tool_calls: list[ToolCallLog]
    decision: RefundDecision
    audit_decision: str
    review_level: str


async def _log_tool(customer_id: str | None, order_id: str | None, call: ToolCallLog) -> None:
    await log_bus.publish(
        "tool_call",
        f"Tool `{call.tool}` returned {call.output}",
        customer_id=customer_id,
        order_id=order_id,
        metadata=call.model_dump(mode="json"),
    )


async def _optional_llm_customer_copy(decision: RefundDecision, customer_message: str) -> str:
    """Keep customer copy short and free of internal policy or CRM details."""
    _ = customer_message
    return customer_facing_message(decision)


def build_langgraph_definition() -> Any:
    """Build the refund-policy workflow over deterministic tool nodes."""
    if StateGraph is None:
        return None

    graph = StateGraph(AgentState)
    graph.add_node("loadPolicy", _node_load_policy)
    graph.add_node("lookupCustomer", _node_lookup_customer)
    graph.add_node("lookupOrder", _node_lookup_order)
    graph.add_node("loadRefundContext", _node_load_refund_context)
    graph.add_node("retrievePolicySections", _node_retrieve_policy_sections)
    graph.add_node("runPolicyChecks", _node_run_policy_checks)
    graph.add_node("evaluateRefundRules", _node_evaluate_refund_rules)
    graph.add_node("decideRefund", _node_decide_refund)
    graph.add_node("persistDecision", _node_persist_decision)

    graph.set_entry_point("loadPolicy")
    graph.add_edge("loadPolicy", "lookupCustomer")
    graph.add_conditional_edges(
        "lookupCustomer",
        _route_after_customer,
        {"lookupOrder": "lookupOrder", "decideRefund": "decideRefund"},
    )
    graph.add_conditional_edges(
        "lookupOrder",
        _route_after_order,
        {"loadRefundContext": "loadRefundContext", "decideRefund": "decideRefund"},
    )
    graph.add_edge("loadRefundContext", "retrievePolicySections")
    graph.add_edge("retrievePolicySections", "runPolicyChecks")
    graph.add_edge("runPolicyChecks", "evaluateRefundRules")
    graph.add_edge("evaluateRefundRules", "decideRefund")
    graph.add_edge("decideRefund", "persistDecision")
    graph.add_edge("persistDecision", END)
    return graph.compile()


def _append_tool(state: AgentState, call: ToolCallLog) -> AgentState:
    return {**state, "tool_calls": [*state.get("tool_calls", []), call]}


def _node_load_policy(state: AgentState) -> AgentState:
    return {**state, "policy_text": load_policy(), "tool_calls": state.get("tool_calls", [])}


def _node_lookup_customer(state: AgentState) -> AgentState:
    request = state["request"]
    customer, customer_call = lookup_customer(request.customer_id)
    return {**_append_tool(state, customer_call), "customer": customer}


def _route_after_customer(state: AgentState) -> str:
    return "lookupOrder" if state.get("customer") else "decideRefund"


def _node_lookup_order(state: AgentState) -> AgentState:
    request = state["request"]
    order, order_call = get_order(state["customer"], request.order_id)
    return {**_append_tool(state, order_call), "order": order}


def _route_after_order(state: AgentState) -> str:
    return "loadRefundContext" if state.get("order") else "decideRefund"


def _node_load_refund_context(state: AgentState) -> AgentState:
    customer = state["customer"]
    order = state["order"]
    return_request, return_request_call = get_return_request(customer.id, order.id)
    refund_history, refund_history_call = get_refund_history(customer)
    fraud_assessment, fraud_assessment_call = get_fraud_assessment(customer)
    next_state = _append_tool(state, return_request_call)
    next_state = _append_tool(next_state, refund_history_call)
    next_state = _append_tool(next_state, fraud_assessment_call)
    return {
        **next_state,
        "return_request": return_request,
        "refund_history": refund_history,
        "fraud_assessment": fraud_assessment,
        "fraud_detection": get_latest_fraud_detection(return_request["request_id"])
        if return_request
        else None,
        "refund_evaluation": get_latest_refund_evaluation(return_request["request_id"])
        if return_request
        else None,
    }


def _node_retrieve_policy_sections(state: AgentState) -> AgentState:
    request = state["request"]
    policy_sections, policy_sections_call = retrieve_policy_sections(request.message, state["order"])
    return {
        **_append_tool(state, policy_sections_call),
        "policy_sections": policy_sections,
    }


def _node_run_policy_checks(state: AgentState) -> AgentState:
    customer = state["customer"]
    order = state["order"]
    checks = [
        check_fraud_risk(customer, state.get("fraud_assessment")),
        check_return_window(customer, order),
        check_item_condition(order),
        check_opened_item_loyalty(customer, order),
        check_refund_limit(customer, order, state.get("refund_history", [])),
    ]
    next_state = state
    for call in checks:
        next_state = _append_tool(next_state, call)
    return {**next_state, "checks": checks}


def _node_evaluate_refund_rules(state: AgentState) -> AgentState:
    return_request = state.get("return_request")
    evaluation = state.get("refund_evaluation")
    if not return_request or not evaluation:
        return state

    signals = json.loads(evaluation.get("signals_json") or "[]")
    call = ToolCallLog(
        tool="evaluate_refund_rules",
        input={"request_id": return_request["request_id"]},
        output={
            "outcome": evaluation.get("outcome"),
            "reasoning_excerpt": str(evaluation.get("reasoning", ""))[:280],
            "signal_count": len(signals),
            "signals": signals[:5],
        },
    )
    return {**_append_tool(state, call), "refund_evaluation": evaluation}


def _node_decide_refund(state: AgentState) -> AgentState:
    customer = state.get("customer")
    order = state.get("order")
    tool_calls = state.get("tool_calls", [])

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
        return {**state, "decision": decision, "audit_decision": "Manual Review", "review_level": "Manual Review"}

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
        return {**state, "decision": decision, "audit_decision": "Manual Review", "review_level": "Manual Review"}

    escalation_reasons: list[str] = []
    denial_reasons: list[str] = []
    policy_rules: list[str] = []
    review_level = "Manual Review"

    fraud_detection = state.get("fraud_detection")
    if fraud_detection and fraud_detection.get("is_fraud_flagged"):
        risk_level = str(fraud_detection.get("risk_level", RISK_HIGH))
        escalation_reasons.append(
            f"Anti-fraud engine scored this request {fraud_detection.get('fraud_score')}/100 ({risk_level})."
        )
        policy_rules.append("Shopward Anti-Fraud & Refund Abuse Policy")
        if risk_level == RISK_CRITICAL:
            review_level = "Manager Review"

    refund_evaluation = state.get("refund_evaluation")
    if refund_evaluation:
        eval_outcome = str(refund_evaluation.get("outcome", ""))
        eval_reason = str(refund_evaluation.get("reasoning", "")).split("\n")[0]
        policy_rules.append("Shopward Refund Policy (AI rule engine)")
        if eval_outcome == "DENIED":
            denial_reasons.append(eval_reason or "Refund rule engine denied this request.")
        elif eval_outcome == "ESCALATED":
            escalation_reasons.append(eval_reason or "Refund rule engine escalated this request.")

    for call in state.get("checks", []):
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

    policy_sections = state.get("policy_sections", [])
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
                "We couldn't approve an automatic refund for this order. "
                "Check Active Tickets for the outcome."
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
                f"Your return request for ${order.total:.2f} passed policy checks and "
                "has been sent to an admin for final approval."
            ),
            internal_reason="All policy checks passed for an automatic refund.",
            amount=order.total,
            order_id=order.id,
            policy_rules=list(
                dict.fromkeys(policy_rules + [section["section_title"] for section in policy_sections])
            ),
            tool_calls=tool_calls,
        )

    audit_decision = (
        "Pending Admin Review"
        if decision.status == "approved"
        else ("Denied" if decision.status == "denied" else review_level)
    )
    return {**state, "decision": decision, "audit_decision": audit_decision, "review_level": review_level}


def _node_persist_decision(state: AgentState) -> AgentState:
    decision = state["decision"]
    confidence_score = 0.92 if decision.status == "approved" else 0.86
    return_request = state.get("return_request")
    store_call = store_agent_decision(
        return_request["request_id"] if return_request else None,
        decision,
        confidence_score,
        state.get("policy_sections", []),
        state.get("audit_decision"),
    )
    next_state = _append_tool(state, store_call)
    return {**next_state, "decision": decision.model_copy(update={"tool_calls": next_state["tool_calls"]})}


def _run_graph(request: ChatRequest) -> AgentState:
    initial_state: AgentState = {"request": request, "tool_calls": []}
    compiled_graph = build_langgraph_definition()
    if compiled_graph is not None:
        return compiled_graph.invoke(initial_state)

    state = _node_load_policy(initial_state)
    state = _node_lookup_customer(state)
    if _route_after_customer(state) == "lookupOrder":
        state = _node_lookup_order(state)
    if _route_after_order(state) == "loadRefundContext":
        state = _node_load_refund_context(state)
        state = _node_retrieve_policy_sections(state)
        state = _node_run_policy_checks(state)
        state = _node_evaluate_refund_rules(state)
    state = _node_decide_refund(state)
    return _node_persist_decision(state)


async def run_refund_agent(request: ChatRequest) -> RefundDecision:
    await log_bus.publish(
        "start",
        "Received refund request and started policy validation.",
        customer_id=request.customer_id,
        order_id=request.order_id,
        metadata={"message": request.message},
    )

    customer = find_customer(request.customer_id)
    if customer and request.order_id:
        return_request, _ = get_return_request(customer.id, request.order_id)
        if return_request:
            from app.services.fraud_detection import evaluate_fraud_for_return
            from app.services.refund_evaluation import evaluate_refund_for_return

            await evaluate_fraud_for_return(
                customer_id=customer.id,
                order_id=request.order_id,
                request_id=str(return_request["request_id"]),
            )
            await evaluate_refund_for_return(
                customer_id=customer.id,
                order_id=request.order_id,
                request_id=str(return_request["request_id"]),
            )

    state = _run_graph(request)
    policy_text = state.get("policy_text", "")
    await log_bus.publish(
        "policy",
        "Loaded strict refund policy source document.",
        customer_id=request.customer_id,
        order_id=request.order_id,
        metadata={"policy_excerpt": policy_text[:700]},
    )
    customer = state.get("customer")
    order = state.get("order")
    policy_sections = state.get("policy_sections", [])
    for call in state.get("tool_calls", []):
        await _log_tool(getattr(customer, "id", request.customer_id), getattr(order, "id", request.order_id), call)
    if policy_sections and customer and order:
        await log_bus.publish(
            "policy_rag",
            "Retrieved policy sections from local vector index.",
            customer_id=customer.id,
            order_id=order.id,
            metadata={"sections": policy_sections},
        )

    decision = state["decision"]
    decision.customer_message = await _optional_llm_customer_copy(decision, request.message)
    await log_bus.publish(
        "decision",
        f"Final decision: {decision.status}",
        customer_id=getattr(customer, "id", request.customer_id),
        order_id=getattr(order, "id", request.order_id),
        metadata={
            **decision.model_dump(mode="json"),
            "return_request_status": state.get("audit_decision"),
            "policy_sections": policy_sections,
        },
    )
    return decision
