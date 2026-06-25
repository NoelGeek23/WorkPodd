from __future__ import annotations

from typing import Any, TypedDict

from app.agent.tools import find_customer, get_order, load_policy, lookup_customer
from app.models import ChatRequest, ToolCallLog
from app.services.log_bus import log_bus
from app.services.return_prescreening import ReturnPrescreenResult, evaluate_return_prescreen

try:
    from langgraph.graph import END, StateGraph  # type: ignore
except Exception:  # pragma: no cover
    END = "__end__"  # type: ignore
    StateGraph = None  # type: ignore


class PrescreenState(TypedDict, total=False):
    request: ChatRequest
    policy_text: str
    customer: Any
    order: Any
    prescreen: ReturnPrescreenResult
    tool_calls: list[ToolCallLog]


def _append_tool(state: PrescreenState, call: ToolCallLog) -> PrescreenState:
    return {**state, "tool_calls": [*state.get("tool_calls", []), call]}


def _node_load_policy(state: PrescreenState) -> PrescreenState:
    return {**state, "policy_text": load_policy(), "tool_calls": state.get("tool_calls", [])}


def _node_lookup_customer(state: PrescreenState) -> PrescreenState:
    request = state["request"]
    customer, customer_call = lookup_customer(request.customer_id)
    return {**_append_tool(state, customer_call), "customer": customer}


def _node_lookup_order(state: PrescreenState) -> PrescreenState:
    customer = state.get("customer")
    if not customer:
        return state
    request = state["request"]
    order, order_call = get_order(customer, request.order_id)
    return {**_append_tool(state, order_call), "order": order}


def _node_run_prescreen(state: PrescreenState) -> PrescreenState:
    request = state["request"]
    prescreen = evaluate_return_prescreen(request.customer_id, request.order_id)
    prescreen_call = ToolCallLog(
        tool="evaluate_return_prescreen",
        input={"customer_id": request.customer_id, "order_id": request.order_id},
        output={
            "outcome": prescreen.outcome,
            "internal_reason": prescreen.internal_reason,
            "policy_rules": prescreen.policy_rules,
        },
    )
    return {
        **_append_tool(state, prescreen_call),
        "prescreen": prescreen,
        "tool_calls": [*state.get("tool_calls", []), *prescreen.tool_calls],
    }


def build_prescreen_langgraph_definition() -> Any:
    if StateGraph is None:
        return None

    graph = StateGraph(PrescreenState)
    graph.add_node("loadPolicy", _node_load_policy)
    graph.add_node("lookupCustomer", _node_lookup_customer)
    graph.add_node("lookupOrder", _node_lookup_order)
    graph.add_node("runPrescreen", _node_run_prescreen)

    graph.set_entry_point("loadPolicy")
    graph.add_edge("loadPolicy", "lookupCustomer")
    graph.add_edge("lookupCustomer", "lookupOrder")
    graph.add_edge("lookupOrder", "runPrescreen")
    graph.add_edge("runPrescreen", END)
    return graph.compile()


def _run_prescreen_graph(request: ChatRequest) -> PrescreenState:
    compiled = build_prescreen_langgraph_definition()
    initial: PrescreenState = {"request": request, "tool_calls": []}
    if compiled is not None:
        return compiled.invoke(initial)

    state = _node_load_policy(initial)
    state = _node_lookup_customer(state)
    state = _node_lookup_order(state)
    return _node_run_prescreen(state)


async def run_return_prescreen_agent(
    *,
    customer_id: str,
    order_id: str,
) -> ReturnPrescreenResult:
    request = ChatRequest(
        customer_id=customer_id,
        order_id=order_id,
        message="Pre-return eligibility screening after product selection.",
    )
    state = _run_prescreen_graph(request)
    prescreen = state["prescreen"]
    customer = state.get("customer") or find_customer(customer_id)

    await log_bus.publish(
        "prescreen",
        f"Pre-return prescreen for order {order_id}: {prescreen.outcome}.",
        customer_id=customer_id,
        order_id=order_id,
        metadata={
            "outcome": prescreen.outcome,
            "internal_reason": prescreen.internal_reason,
            "customer_message": prescreen.customer_message,
            "tool_calls": [call.model_dump(mode="json") for call in state.get("tool_calls", [])],
            "customer_name": getattr(customer, "name", None),
        },
    )
    return prescreen
