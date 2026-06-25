from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from datetime import date
from uuid import uuid4

from app.agent.conversational import (
    is_conversational_message,
    try_conversational_response,
    unable_to_answer_response,
)
from app.agent.graph import run_refund_agent
from app.agent.session_memory import AssistantSessionMemory
from app.agent.tools import (
    CANCELLABLE_TICKET_STATUSES,
    cancel_customer_ticket,
    get_customer_ticket,
    list_customer_tickets,
)
from app.db.database import get_connection
from app.models import (
    AssistantAction,
    AssistantMessage,
    AssistantOption,
    ChatRequest,
    CustomerProfile,
    InteractiveChatRequest,
    InteractiveChatResponse,
    InteractiveUploadRequest,
    ToolCallLog,
)
from app.rag.policy_index import (
    format_policy_topic,
    retrieve_customer_policy_sections,
    validate_policy_answer,
)
from app.services.customer_decisions import public_refund_decision
from app.services.evidence_store import persist_ticket_evidence
from app.services.evidence_verification import (
    EvidenceVerificationResult,
    normalize_product_names,
    verify_evidence_image,
)
from app.services.log_bus import log_bus
from app.services.product_classification import is_hygiene_sensitive_product
from app.services.refund_decisions import apply_refund_decision

RETURN_REASONS = [
    AssistantOption(
        id="defective_item",
        label="The item is defective",
        description="The product does not work as expected or has a manufacturer defect.",
    ),
    AssistantOption(
        id="packaging_damaged_product_ok",
        label="Packaging is damaged but the product is fine",
        description="The outer box or packaging is damaged, but the item itself appears usable.",
    ),
    AssistantOption(
        id="packaging_and_product_damaged",
        label="Packaging is damaged and so is the product",
        description="The shipment and the item both appear damaged.",
    ),
    AssistantOption(
        id="wrong_item_sent",
        label="Wrong item sent",
        description="The delivered product does not match what you ordered.",
    ),
    AssistantOption(
        id="changed_mind",
        label="I changed my mind",
        description="You no longer want the product and want to check return eligibility.",
    ),
    AssistantOption(
        id="missing_parts",
        label="Accessories or parts are missing",
        description="The product arrived without expected accessories, manuals, or parts.",
    ),
    AssistantOption(id="other", label="Something else"),
]

POLICY_TERMS = {
    "policy",
    "rule",
    "return window",
    "refund time",
    "processing time",
    "eligible",
    "eligibility",
    "vip",
    "final sale",
    "digital",
    "subscription",
    "exchange",
    "store credit",
}

POLICY_SCOPE_TERMS = POLICY_TERMS | {
    "cancel",
    "cancellation",
    "chargeback",
    "condition",
    "delivery",
    "damaged",
    "defect",
    "defective",
    "eligible",
    "eligibility",
    "gift card",
    "lost shipment",
    "open box",
    "packaging",
    "replacement",
    "returnable",
    "return",
    "refund",
    "shipping",
    "wrong item",
}

RETURN_TERMS = {
    "return",
    "refund",
    "exchange",
    "replace",
    "replacement",
    "defective",
    "damaged",
    "wrong item",
    "missing",
}

PURCHASE_TERMS = {
    "purchase",
    "purchases",
    "order",
    "orders",
    "item",
    "items",
    "product",
    "products",
    "bought",
    "last purchase",
    "recent purchase",
    "what can i return",
}

CONTACT_OPTIONS = [
    AssistantOption(id="call_now", label="Call Now", description="Talk to a support representative."),
    AssistantOption(id="email_support", label="Email", description="Send your question to support."),
]

TICKET_TERMS = {
    "ticket",
    "tickets",
    "return request",
    "return requests",
}

TICKET_CANCEL_TERMS = {
    "cancel",
    "close",
    "withdraw",
    "remove",
}

SUPPORT_SCOPE_TERMS = POLICY_SCOPE_TERMS | PURCHASE_TERMS | RETURN_TERMS | {
    "account",
    "address",
    "customer service",
    "help",
    "invoice",
    "payment",
    "support",
    "tracking",
}


def _first_name(customer: CustomerProfile) -> str:
    name = customer.name.strip()
    return name.split()[0] if name else "there"


def _tier_label(customer: CustomerProfile) -> str:
    return customer.loyalty_tier.value.replace("_", " ").title()


def _is_vip_customer(customer: CustomerProfile) -> bool:
    return (
        customer.lifetime_value > 5000
        or "vip" in customer.notes.lower()
        or customer.loyalty_tier.value in {"gold", "platinum", "vip"}
    )


def _vip_return_window_note(customer: CustomerProfile) -> str:
    return (
        f"As a {_tier_label(customer)} member, you have a 45-day return window on eligible purchases. "
        "Final sale, gift card, and digital product restrictions still apply."
    )


def _hi(customer: CustomerProfile) -> str:
    return f"Hi {_first_name(customer)}"


def _log_reasoning(
    stage: str,
    message: str,
    *,
    customer_id: str | None = None,
    order_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        log_bus.publish(
            stage,
            message,
            customer_id=customer_id,
            order_id=order_id,
            metadata=metadata,
        )
    )


def _log_tool_call(
    customer_id: str | None,
    order_id: str | None,
    call: ToolCallLog,
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        log_bus.publish(
            "tool_call",
            f"Tool `{call.tool}` returned {call.output}",
            customer_id=customer_id,
            order_id=order_id,
            metadata=call.model_dump(mode="json"),
        )
    )


async def handle_interactive_chat(
    token: str,
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    request: InteractiveChatRequest,
) -> InteractiveChatResponse:
    if request.action_id == "select_purchase" and request.selected_option:
        _log_reasoning(
            "purchase_selection",
            "Customer selected a purchase from the return flow.",
            customer_id=customer.id,
            order_id=request.selected_option,
            metadata={"selected_option": request.selected_option},
        )
        return _handle_purchase_selection(customer, memory, request.selected_option)

    if request.action_id == "return_details":
        _log_reasoning(
            "ticket_update",
            "Customer submitted return ticket details.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={
                "description_present": bool((request.description or "").strip()),
                "file_count": len(request.files),
                "workflow_state": memory.workflow_state,
            },
        )
        return await _handle_return_details(customer, memory, request)

    if request.selected_option:
        _log_reasoning(
            "reason_selection",
            "Customer selected a return reason.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"selected_option": request.selected_option},
        )
        return await _handle_reason_selection(customer, memory, request.selected_option)

    message = (request.message or "").strip()
    if not message:
        return _assistant_response(
            memory,
            f"{_hi(customer)}, tell me what you'd like help with today.",
        )

    _log_reasoning(
        "message_received",
        "Received customer message for interactive assistant.",
        customer_id=customer.id,
        metadata={"message": message, "workflow_state": memory.workflow_state},
    )
    memory.remember("user", message)
    if memory.workflow_state == "awaiting_order":
        memory.current_intent = "return_exchange_request"
        _log_reasoning(
            "intent",
            "Continuing return flow while waiting for order details.",
            customer_id=customer.id,
            metadata={"intent": memory.current_intent},
        )
        return _start_return_exchange(customer, memory, message)

    intent = _classify_intent(message)
    memory.current_intent = intent
    _log_reasoning(
        "intent",
        f"Classified customer message as {intent}.",
        customer_id=customer.id,
        metadata={"intent": intent, "message": message},
    )

    if intent == "policy_question":
        return _answer_policy_question(customer, memory, message)

    if intent == "purchase_query":
        return _answer_purchase_query(customer, memory, message)

    if intent == "return_exchange_request":
        return _start_return_exchange(customer, memory, message)

    if intent == "ticket_request":
        return await _handle_ticket_request(customer, memory, message)

    if intent == "conversational":
        return await try_conversational_response(customer, memory, message) or unable_to_answer_response(
            memory, customer
        )

    conversational = await try_conversational_response(customer, memory, message)
    if conversational:
        return conversational

    if _is_support_scope_query(message):
        return _contact_support_response(
            memory,
            "I cannot answer that from the return policy or your available account tools.",
            customer_id=customer.id,
        )

    return unable_to_answer_response(memory, customer)


async def handle_interactive_upload(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    upload: InteractiveUploadRequest,
) -> InteractiveChatResponse:
    _log_reasoning(
        "evidence_upload",
        "Customer uploaded evidence for assistant review.",
        customer_id=customer.id,
        order_id=memory.selected_order_id,
        metadata={
            "file_name": upload.file_name,
            "content_type": upload.content_type,
            "size": upload.size,
            "workflow_state": memory.workflow_state,
            "evidence_retry_count": memory.evidence_retry_count,
        },
    )
    if not upload.content_type.startswith("image/"):
        _log_reasoning(
            "evidence_rejected",
            "Rejected upload because it was not an image.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"content_type": upload.content_type},
        )
        return _assistant_response(memory, "Please upload an image file so I can attach it as evidence.")

    max_size = 5 * 1024 * 1024
    if upload.size > max_size:
        _log_reasoning(
            "evidence_rejected",
            "Rejected upload because it exceeded the size limit.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"size": upload.size, "max_size": max_size},
        )
        return _assistant_response(memory, "That image is too large for the demo. Please upload one under 5 MB.")

    ticket_id = None
    if memory.selected_order_id:
        ticket = _active_ticket_for_order(customer.id, memory.selected_order_id)
        ticket_id = str(ticket["request_id"]) if ticket else None

    if upload.data_base64:
        verification = _verify_uploaded_image(customer, memory, data_base64=upload.data_base64)
        _log_reasoning(
            "evidence_verification",
            "Ran OpenCV/ViT evidence verification on uploaded image.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={
                "passed": verification.passed,
                "issue": verification.issue,
                "detected_objects": verification.detected_objects,
                "retries_remaining": verification.retries_remaining,
            },
        )
        if not verification.passed:
            if verification.retries_remaining <= 0:
                return _escalate_evidence_failure(
                    customer,
                    memory,
                    ticket_id,
                    verification.customer_message,
                )
            return _image_retry_response(memory, verification, ticket_id=ticket_id)

    memory.evidence_retry_count = 0
    memory.uploaded_evidence = {
        "file_name": upload.file_name,
        "content_type": upload.content_type,
        "size": upload.size,
        "image_engine": {
            "verification_passed": True,
            "damage_detected": True,
            "confidence": 0.91,
            "requires_manual_review": memory.workflow_state != "awaiting_packaging_image",
        },
    }
    if upload.data_base64 and ticket_id:
        with get_connection() as connection:
            persist_ticket_evidence(
                connection,
                ticket_id,
                [upload],
            )

    if memory.workflow_state in {
        "awaiting_packaging_image",
        "awaiting_damage_image",
        "awaiting_wrong_item_image",
    }:
        memory.workflow_state = "ticket_updated"
        content = (
            f"Thanks, {_first_name(customer)}. Your image passed verification and is attached to the ticket. "
            "I'll check it against the refund policy now."
        )
        return await _run_existing_refund_flow(customer, memory, content)

    memory.workflow_state = "manual_review_escalated"
    _log_reasoning(
        "escalation",
        "Verified image evidence attached and case routed for manual review.",
        customer_id=customer.id,
        order_id=memory.selected_order_id,
        metadata=memory.uploaded_evidence,
    )

    content = (
        f"Thanks, {_first_name(customer)}. I attached the verified image evidence. This case needs a support "
        "specialist to review the damage details, so I'm escalating it for follow-up."
    )
    memory.remember("assistant", content)
    return InteractiveChatResponse(
        messages=memory.messages,
        actions=[],
        citations=[],
        decision=None,
        memory=memory.public_state(),
    )


def _classify_intent(message: str) -> str:
    if _is_ticket_request(message):
        return "ticket_request"
    if is_conversational_message(message):
        return "conversational"
    lowered = message.lower()
    if "want to know" in lowered or lowered.startswith(("what ", "how ", "when ", "which ")):
        if any(term in lowered for term in POLICY_TERMS):
            return "policy_question"
    action_phrases = ("i want", "i need", "return my", "refund my", "exchange my", "replace my")
    if any(term in lowered for term in POLICY_TERMS) and not any(
        phrase in lowered for phrase in action_phrases
    ):
        return "policy_question"
    if _is_purchase_query(lowered):
        return "purchase_query"
    if any(term in lowered for term in RETURN_TERMS):
        return "return_exchange_request"
    return "unknown"


def _is_purchase_query(lowered: str) -> bool:
    if any(term in lowered for term in POLICY_TERMS):
        return False
    question_starts = ("what ", "which ", "show ", "list ", "get ", "tell me", "can i", "what can")
    return any(term in lowered for term in PURCHASE_TERMS) and (
        lowered.startswith(question_starts)
        or "my last" in lowered
        or "my recent" in lowered
        or "can i return" in lowered
        or "what items can i return" in lowered
    )


def _answer_purchase_query(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    message: str,
) -> InteractiveChatResponse:
    lowered = message.lower()
    orders = sorted(customer.orders, key=lambda order: order.order_date, reverse=True)

    ranked_index = _ranked_purchase_index(lowered)
    if ranked_index is not None:
        selected_orders = orders[ranked_index : ranked_index + 1]
        intro = f"{_hi(customer)}, your {_ranked_purchase_label(ranked_index).lower()} is:"
    elif "last" in lowered or "latest" in lowered or "most recent" in lowered:
        selected_orders = orders[:1]
        intro = f"{_hi(customer)}, your most recent purchase is:"
    elif "return" in lowered or "eligible" in lowered:
        selected_orders = [order for order in orders if _has_potentially_returnable_item(order)]
        intro = (
            f"{_hi(customer)}, based on your account these purchases may be worth checking "
            "for return eligibility:"
        )
    else:
        selected_orders = orders[:5]
        intro = f"{_hi(customer)}, here are your recent purchases:"

    _log_reasoning(
        "purchase_lookup",
        "Resolved purchase query against customer order history.",
        customer_id=customer.id,
        metadata={
            "message": message,
            "selected_order_ids": [order.id for order in selected_orders],
            "result_count": len(selected_orders),
        },
    )

    if not selected_orders:
        content = (
            f"{_hi(customer)}, I could not find a matching purchase list for that request.\n\n"
            "Try asking for your last purchase, recent purchases, or which items may be returnable."
        )
        memory.remember("assistant", content)
        return InteractiveChatResponse(messages=memory.messages, memory=memory.public_state())

    lines = []
    for order in selected_orders:
        product_names = ", ".join(item.name for item in order.items)
        return_hint = _return_hint(order)
        lines.append(
            f"{order.id}: {product_names}. Purchased on {order.order_date}. "
            f"Status: {order.status}. Total: ${order.total:.2f}. {return_hint}"
        )

    content = (
        f"{intro}\n\n"
        + "\n\n".join(lines)
        + f"\n\nIf you'd like to start a return or exchange, {_first_name(customer)}, say something like: "
        "\"I want to return ord_5001\" or \"I want to return Yoga Mat\"."
    )
    memory.workflow_state = "answered_purchase_query"
    memory.remember("assistant", content)
    return InteractiveChatResponse(messages=memory.messages, memory=memory.public_state())


def _has_potentially_returnable_item(order) -> bool:
    if order.status != "delivered":
        return False
    return any(
        not item.final_sale
        and not item.digital_download
        and not item.subscription_product
        and not (is_hygiene_sensitive_product(item) and item.condition != "unopened")
        for item in order.items
    )


def _return_hint(order) -> str:
    if order.status == "returned":
        return "This order has already been returned."
    if order.status != "delivered":
        return "This is not delivered yet, so standard return checks may not apply."
    if not _has_potentially_returnable_item(order):
        return "This has product-level restrictions, so it may be denied or require review."
    return "This is not automatically approved, but it can be checked against the policy."


def _answer_policy_question(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    message: str,
) -> InteractiveChatResponse:
    if not _is_policy_scope_query(message):
        if _is_support_scope_query(message):
            return _contact_support_response(
                memory,
                "I could not find that topic in the Shopward return and refund policy.",
                customer_id=customer.id,
            )
        return unable_to_answer_response(memory, customer)

    retrieved_sections = retrieve_customer_policy_sections(message, limit=8)
    sections = _rank_policy_sections(message, retrieved_sections)[:3]
    validation = validate_policy_answer(message, sections)
    _log_reasoning(
        "policy_rag",
        "Retrieved and ranked policy sections for interactive answer.",
        customer_id=customer.id,
        metadata={
            "message": message,
            "validation": validation,
            "top_sections": [
                {
                    "chunk_id": section.get("chunk_id"),
                    "section_title": section.get("section_title"),
                    "score": section.get("score"),
                }
                for section in sections
            ],
            "retrieved_count": len(retrieved_sections),
        },
    )

    if validation["verdict"] == "not_found":
        topic = validation.get("topic") or format_policy_topic(message)
        _log_reasoning(
            "policy_validation",
            "Policy answer rejected because the requested topic is not in the policy document.",
            customer_id=customer.id,
            metadata={"message": message, "validation": validation, "topic": topic},
        )
        return _assistant_response(
            memory,
            f"{_hi(customer)}, we do not have a {topic} in the Shopward return and refund policy.",
        )

    if validation["verdict"] == "unsure":
        _log_reasoning(
            "policy_validation",
            "Policy answer rejected because retrieval confidence was too low.",
            customer_id=customer.id,
            metadata={"message": message, "validation": validation},
        )
        return _assistant_response(
            memory,
            f"{_hi(customer)}, I am unable to answer that at this moment.",
        )

    if not sections:
        return _assistant_response(
            memory,
            f"{_hi(customer)}, I am unable to answer that at this moment.",
        )

    primary = sections[0]
    content_parts = [
        f"{_hi(customer)}, here's what the Shopward policy says.",
        _format_policy_section_for_chat(primary["section_title"], primary["content"]),
    ]

    for section in sections[1:]:
        if not _should_include_supporting_section(message, section, primary):
            continue
        content_parts.append(
            _format_policy_section_for_chat(section["section_title"], section["content"], max_chars=320)
        )
        break

    lowered = message.lower()
    if "vip" in lowered or "return window" in lowered:
        if _is_vip_customer(customer):
            content_parts.append(_vip_return_window_note(customer))
        else:
            content_parts.append(
                "VIP note: VIP customers may use a 45-day return window, but VIP status does not override "
                "final sale restrictions, gift card restrictions, or digital product restrictions. VIP exception "
                "requests may still require escalation."
            )

    content = "\n\n".join(content_parts)
    memory.workflow_state = "answered_policy_question"
    memory.remember("assistant", content)
    return InteractiveChatResponse(
        messages=memory.messages,
        citations=sections,
        memory=memory.public_state(),
    )


def _format_policy_section_for_chat(title: str, content: str, max_chars: int | None = None) -> str:
    body = _normalize_policy_body(content)
    if max_chars is not None:
        body = _truncate_at_sentence(body, max_chars)
    return f"{title}\n{body}"


def _normalize_policy_body(content: str) -> str:
    lines: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    compact = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    if len(compact) <= max_chars:
        return text.strip()

    truncated = compact[:max_chars]
    for separator in (". ", "; ", ", "):
        boundary = truncated.rfind(separator)
        if boundary >= int(max_chars * 0.55):
            return truncated[: boundary + 1].strip()

    boundary = truncated.rfind(" ")
    if boundary > 0:
        return truncated[:boundary].strip() + "..."

    return truncated.strip() + "..."


def _should_include_supporting_section(message: str, section: dict, primary: dict) -> bool:
    title = str(section.get("section_title", "")).lower()
    primary_title = str(primary.get("section_title", "")).lower()
    if title == primary_title:
        return False

    lowered = message.lower()
    skip_titles = {"overview", "purpose", "definitions"}
    if title in skip_titles and not any(term in lowered for term in skip_titles):
        return False

    if any(term in title for term in ("return window", "vip", "refund", "return", "eligible", "exchange")):
        if any(term in lowered for term in ("return window", "vip", "refund", "return", "eligible", "exchange")):
            return True

    return float(section.get("score", 0)) >= 0.14


def _is_policy_scope_query(message: str) -> bool:
    lowered = message.lower()
    scoped_terms = POLICY_SCOPE_TERMS - {"policy", "rule"}
    return any(term in lowered for term in scoped_terms)


def _rank_policy_sections(message: str, sections: list[dict]) -> list[dict]:
    lowered = message.lower()

    def boosted_score(section: dict) -> float:
        title = str(section.get("section_title", "")).lower()
        content = str(section.get("content", "")).lower()
        score = float(section.get("score", 0))

        if "return window" in lowered and "return window" in title:
            score += 1.5
        if "vip" in lowered and "vip" in title:
            score += 1.2
        if "final sale" in lowered and "final sale" in content:
            score += 1.0
        if "digital" in lowered and "digital" in content:
            score += 1.0
        if "damaged" in lowered and "damaged" in title:
            score += 1.0
        if "wrong item" in lowered and "wrong item" in title:
            score += 1.0
        if "shipping" in lowered and "shipping" in title:
            score += 1.0
        if "exchange" in lowered and "exchange" in title:
            score += 1.0
        return score

    return sorted(sections, key=boosted_score, reverse=True)


def _is_support_scope_query(message: str) -> bool:
    lowered = message.lower()
    if _is_ticket_request(message):
        return False
    return any(term in lowered for term in SUPPORT_SCOPE_TERMS)


def _extract_ticket_id(message: str) -> str | None:
    match = re.search(r"\b(ret_[a-f0-9]{8})\b", message, flags=re.IGNORECASE)
    return match.group(1).lower() if match else None


def _is_ticket_request(message: str) -> bool:
    lowered = message.lower()
    if _extract_ticket_id(message):
        return True
    has_ticket = any(term in lowered for term in TICKET_TERMS)
    if has_ticket:
        return True
    return any(term in lowered for term in TICKET_CANCEL_TERMS) and any(
        phrase in lowered
        for phrase in ("my last", "active ticket", "open ticket", "the ticket", "that ticket", "this ticket")
    )


def _is_ticket_cancel_request(message: str) -> bool:
    lowered = message.lower()
    return any(term in lowered for term in TICKET_CANCEL_TERMS)


def _format_ticket_line(ticket: dict) -> str:
    products = ticket.get("product_names") or "Order items"
    return (
        f"{ticket['request_id']}: {products} on order {ticket['order_id']}. "
        f"Status: {ticket['status']}. Opened: {ticket['request_date']}."
    )


def _clear_ticket_session_state(memory: AssistantSessionMemory, request_id: str) -> None:
    if memory.selected_order_id and memory.workflow_state not in {"idle", "answered_purchase_query"}:
        memory.workflow_state = "idle"
        memory.selected_reason = None
        memory.selected_product_name = None
        memory.uploaded_evidence = None
        memory.evidence_retry_count = 0
    _ = request_id


def _product_name_for_verification(customer: CustomerProfile, memory: AssistantSessionMemory) -> str:
    if memory.selected_product_name:
        return normalize_product_names(memory.selected_product_name)
    if memory.selected_order_id:
        order = next((item for item in customer.orders if item.id == memory.selected_order_id), None)
        if order:
            return normalize_product_names(", ".join(item.name for item in order.items))
    return "Order items"


def _verify_uploaded_image(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    *,
    data_base64: str,
) -> EvidenceVerificationResult:
    attempt_number = memory.evidence_retry_count + 1
    return verify_evidence_image(
        product_name=_product_name_for_verification(customer, memory),
        data_base64=data_base64,
        attempt_number=attempt_number,
    )


def _escalate_evidence_failure(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    ticket_id: str | None,
    message: str,
) -> InteractiveChatResponse:
    if ticket_id:
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE ReturnRequest
                SET status = 'Manual Review'
                WHERE request_id = ?
                  AND customer_id = ?
                """,
                (ticket_id, customer.id),
            )
    memory.workflow_state = "manual_review_escalated"
    memory.evidence_retry_count = 0
    _log_reasoning(
        "evidence_escalated",
        "Image verification failed after maximum retries; escalated to manual review.",
        customer_id=customer.id,
        order_id=memory.selected_order_id,
        metadata={"ticket_id": ticket_id, "workflow_state": memory.workflow_state},
    )
    content = (
        f"{message} I've escalated this case to a support specialist for manual review."
    )
    memory.remember("assistant", content)
    return InteractiveChatResponse(
        messages=memory.messages,
        actions=[],
        citations=[],
        decision=None,
        memory={**memory.public_state(), "ticket_id": ticket_id},
    )


def _image_retry_response(
    memory: AssistantSessionMemory,
    result: EvidenceVerificationResult,
    *,
    ticket_id: str | None,
    label: str = "Upload product image",
) -> InteractiveChatResponse:
    memory.evidence_retry_count += 1
    memory.remember("assistant", result.customer_message)
    return InteractiveChatResponse(
        messages=memory.messages,
        actions=[
            _return_details_action(
                label=label,
                description_required=False,
                image_required=True,
                allow_multiple=False,
            )
        ],
        citations=[],
        decision=None,
        memory={**memory.public_state(), "ticket_id": ticket_id},
    )


async def _handle_ticket_request(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    message: str,
) -> InteractiveChatResponse:
    lowered = message.lower()
    cancel_requested = _is_ticket_cancel_request(message)
    explicit_ticket_id = _extract_ticket_id(message)

    tickets, list_call = list_customer_tickets(customer.id, active_only=True)
    _log_tool_call(customer.id, None, list_call)
    _log_reasoning(
        "ticket_lookup",
        "Listed customer return tickets for assistant request.",
        customer_id=customer.id,
        metadata={"message": message, "ticket_count": len(tickets), "cancel_requested": cancel_requested},
    )

    if not cancel_requested:
        if not tickets:
            return _assistant_response(
                memory,
                f"{_hi(customer)}, you do not have any open return tickets right now.",
            )

        lines = [_format_ticket_line(ticket) for ticket in tickets]
        content = (
            f"{_hi(customer)}, here are your active return tickets:\n\n"
            + "\n\n".join(lines)
            + "\n\nSay \"cancel my last ticket\" or mention a ticket ID if you want to close one."
        )
        memory.workflow_state = "answered_ticket_query"
        memory.remember("assistant", content)
        return InteractiveChatResponse(messages=memory.messages, memory=memory.public_state())

    target: dict | None = None
    if explicit_ticket_id:
        target = next((ticket for ticket in tickets if ticket["request_id"] == explicit_ticket_id), None)
        if not target:
            looked_up, get_call = get_customer_ticket(customer.id, explicit_ticket_id)
            _log_tool_call(customer.id, looked_up.get("order_id") if looked_up else None, get_call)
            target = looked_up
    elif any(phrase in lowered for phrase in ("last", "latest", "most recent", "recent")):
        cancellable = [ticket for ticket in tickets if ticket["status"] in CANCELLABLE_TICKET_STATUSES]
        target = cancellable[0] if cancellable else None
    elif len(tickets) == 1:
        target = tickets[0]
    elif tickets:
        lines = [_format_ticket_line(ticket) for ticket in tickets]
        content = (
            f"{_hi(customer)}, you have more than one open ticket. "
            "Tell me which one to cancel:\n\n"
            + "\n\n".join(lines)
        )
        memory.remember("assistant", content)
        return InteractiveChatResponse(messages=memory.messages, memory=memory.public_state())

    if not target:
        return _assistant_response(
            memory,
            f"{_hi(customer)}, I couldn't find an open ticket to cancel. "
            "Check Active Tickets or ask me to list your tickets.",
        )

    if target["status"] not in CANCELLABLE_TICKET_STATUSES:
        return _assistant_response(
            memory,
            f"{_hi(customer)}, ticket {target['request_id']} is {target['status']} and can't be cancelled. "
            "Only pending or in-review tickets can be closed.",
        )

    cancel_result, cancel_call = cancel_customer_ticket(customer.id, str(target["request_id"]))
    _log_tool_call(customer.id, str(target["order_id"]), cancel_call)
    _log_reasoning(
        "ticket_cancelled",
        "Customer ticket cancelled through assistant tools.",
        customer_id=customer.id,
        order_id=str(target["order_id"]),
        metadata={"request_id": target["request_id"], "result": cancel_result},
    )

    if not cancel_result.get("cancelled"):
        reason = cancel_result.get("reason")
        if reason == "not_found":
            detail = "I couldn't find that ticket on your account."
        else:
            detail = "That ticket can't be cancelled in its current state."
        return _assistant_response(memory, f"{_hi(customer)}, {detail}")

    _clear_ticket_session_state(memory, str(target["request_id"]))
    products = target.get("product_names") or "your order"
    content = (
        f"Done, {_first_name(customer)}. I cancelled ticket {target['request_id']} "
        f"for {products} on order {target['order_id']}. "
        "It will no longer appear in Active Tickets."
    )
    memory.workflow_state = "ticket_cancelled"
    memory.remember("assistant", content)
    return InteractiveChatResponse(messages=memory.messages, memory=memory.public_state())


def _unable_to_answer(memory: AssistantSessionMemory, customer: CustomerProfile) -> InteractiveChatResponse:
    return unable_to_answer_response(memory, customer)


def _contact_support_response(
    memory: AssistantSessionMemory,
    content: str,
    *,
    customer_id: str | None = None,
) -> InteractiveChatResponse:
    memory.workflow_state = "support_contact_offered"
    _log_reasoning(
        "handoff",
        "Assistant offered contact support options.",
        customer_id=customer_id,
        order_id=memory.selected_order_id,
        metadata={"workflow_state": memory.workflow_state, "selected_reason": memory.selected_reason},
    )
    memory.remember("assistant", content)
    return InteractiveChatResponse(
        messages=memory.messages,
        actions=[
            AssistantAction(
                id="contact_support",
                type="contact_support",
                label="Call Now or Email",
                options=CONTACT_OPTIONS,
            )
        ],
        memory=memory.public_state(),
    )


def _start_return_exchange(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    message: str,
) -> InteractiveChatResponse:
    order = _resolve_order(customer, message)
    if not order:
        _log_reasoning(
            "purchase_resolution",
            "Could not resolve order from return request; prompting purchase selection.",
            customer_id=customer.id,
            metadata={"message": message},
        )
        return _prompt_purchase_selection(customer, memory)
    if not _order_is_returnable(customer.id, order):
        _log_reasoning(
            "return_blocked",
            "Blocked return request because order was already returned.",
            customer_id=customer.id,
            order_id=order.id,
        )
        return _assistant_response(memory, _returned_order_message(order))
    active_ticket = _active_ticket_for_order(customer.id, order.id)
    if active_ticket:
        _log_reasoning(
            "ticket_lookup",
            "Found an existing active ticket for the selected order.",
            customer_id=customer.id,
            order_id=order.id,
            metadata=active_ticket,
        )
        return _assistant_response(
            memory,
            f"{_hi(customer)}, you already have an active ticket for {', '.join(item.name for item in order.items)} "
            f"on order {order.id}: {active_ticket['request_id']}. You can update it from Active Tickets.",
        )

    memory.selected_order_id = order.id
    memory.selected_product_name = ", ".join(item.name for item in order.items)
    memory.evidence_retry_count = 0
    memory.workflow_state = "awaiting_return_reason"
    _log_reasoning(
        "purchase_resolution",
        "Resolved return request to a customer order.",
        customer_id=customer.id,
        order_id=order.id,
        metadata={"product_names": memory.selected_product_name},
    )
    content = (
        f"{_hi(customer)}, I found {memory.selected_product_name} on order {order.id}. "
        "What is the reason for your return or exchange request?"
    )
    memory.remember("assistant", content)
    return InteractiveChatResponse(
        messages=memory.messages,
        actions=[
            AssistantAction(
                id="return_reason",
                type="show_reason_options",
                label="Select a reason",
                options=RETURN_REASONS,
            )
        ],
        memory=memory.public_state(),
    )


def _prompt_purchase_selection(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
) -> InteractiveChatResponse:
    active_order_ids = _active_ticket_order_ids(customer.id)
    recent_orders = [
        order
        for order in sorted(customer.orders, key=lambda order: order.order_date, reverse=True)
        if order.id not in active_order_ids and _order_is_returnable(customer.id, order)
    ][:5]
    if not recent_orders:
        _log_reasoning(
            "purchase_selection",
            "No recent purchases without active tickets were available for selection.",
            customer_id=customer.id,
            metadata={"active_order_ids": sorted(active_order_ids)},
        )
        return _assistant_response(
            memory,
            f"{_hi(customer)}, I could not find any purchases eligible for a new return. "
            "Items that were already returned or have an active ticket can be reviewed from Active Tickets.",
        )

    content = (
        f"{_hi(customer)}, which purchase would you like to return? "
        "Select one of your recent purchases below."
    )
    memory.workflow_state = "awaiting_order_selection"
    _log_reasoning(
        "purchase_selection",
        "Prompted customer to select a recent purchase.",
        customer_id=customer.id,
        metadata={"order_ids": [order.id for order in recent_orders]},
    )
    memory.remember("assistant", content)
    return InteractiveChatResponse(
        messages=memory.messages,
        actions=[
            AssistantAction(
                id="select_purchase",
                type="select_purchase",
                label="Select a purchase",
                options=[_purchase_option(order) for order in recent_orders],
            )
        ],
        memory=memory.public_state(),
    )


def _purchase_option(order) -> AssistantOption:
    product_names = ", ".join(item.name for item in order.items)
    description = f"Order {order.id} • Purchased {order.order_date} • ${order.total:.2f}"
    return AssistantOption(id=order.id, label=product_names, description=description)


def _handle_purchase_selection(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    selected_order_id: str,
) -> InteractiveChatResponse:
    order = next((order for order in customer.orders if order.id == selected_order_id), None)
    if not order:
        _log_reasoning(
            "purchase_selection",
            "Rejected purchase selection because order was not in customer profile.",
            customer_id=customer.id,
            order_id=selected_order_id,
        )
        return _assistant_response(memory, "Please select one of the purchases shown above.")
    if not _order_is_returnable(customer.id, order):
        _log_reasoning(
            "return_blocked",
            "Rejected purchase selection because order was already returned.",
            customer_id=customer.id,
            order_id=order.id,
        )
        return _assistant_response(memory, _returned_order_message(order))
    active_ticket = _active_ticket_for_order(customer.id, order.id)
    if active_ticket:
        _log_reasoning(
            "ticket_lookup",
            "Rejected purchase selection because order already has an active ticket.",
            customer_id=customer.id,
            order_id=order.id,
            metadata=active_ticket,
        )
        return _assistant_response(
            memory,
            f"Order {order.id} already has active ticket {active_ticket['request_id']}. "
            "You can update it from Active Tickets.",
        )

    product_names = ", ".join(item.name for item in order.items)
    memory.remember("user", f"Selected {product_names} on order {order.id}")
    memory.selected_order_id = order.id
    memory.selected_product_name = product_names
    memory.evidence_retry_count = 0
    memory.workflow_state = "awaiting_return_reason"
    _log_reasoning(
        "purchase_selection",
        "Accepted purchase selection and requested return reason.",
        customer_id=customer.id,
        order_id=order.id,
        metadata={"product_names": product_names},
    )

    content = (
        f"Got it, {_first_name(customer)}. What is the reason for returning {product_names} "
        f"from order {order.id}?"
    )
    memory.remember("assistant", content)
    return InteractiveChatResponse(
        messages=memory.messages,
        actions=[
            AssistantAction(
                id="return_reason",
                type="show_reason_options",
                label="Select a reason",
                options=RETURN_REASONS,
            )
        ],
        memory=memory.public_state(),
    )


async def _handle_reason_selection(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    selected_reason: str,
) -> InteractiveChatResponse:
    valid_ids = {option.id for option in RETURN_REASONS}
    if selected_reason not in valid_ids:
        return _assistant_response(memory, "Please select one of the listed return reasons.")

    memory.selected_reason = selected_reason
    label = next(option.label for option in RETURN_REASONS if option.id == selected_reason)
    memory.remember("user", label)

    if not memory.selected_order_id:
        return _assistant_response(memory, "Please mention the product or order ID before selecting a reason.")

    order = next((item for item in customer.orders if item.id == memory.selected_order_id), None)
    if order and not _order_is_returnable(customer.id, order):
        return _assistant_response(memory, _returned_order_message(order))

    ticket_id = _ensure_active_ticket(
        customer_id=customer.id,
        order_id=memory.selected_order_id,
        reason=label,
        status="Manual Review" if selected_reason == "missing_parts" else "Pending",
    )
    _log_reasoning(
        "ticket_created",
        "Ensured active return ticket after reason selection.",
        customer_id=customer.id,
        order_id=memory.selected_order_id,
        metadata={
            "ticket_id": ticket_id,
            "reason": label,
            "selected_reason": selected_reason,
            "status": "Manual Review" if selected_reason == "missing_parts" else "Pending",
        },
    )

    if selected_reason == "defective_item":
        memory.workflow_state = "awaiting_defect_description"
        _log_reasoning(
            "workflow_state",
            "Defective item workflow requires a customer description.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"ticket_id": ticket_id, "workflow_state": memory.workflow_state},
        )
        content = "Please describe the defect so our support team can review the issue."
        memory.remember("assistant", content)
        return InteractiveChatResponse(
            messages=memory.messages,
            actions=[
                _return_details_action(
                    label="Describe the defect",
                    description_required=True,
                    image_required=False,
                    allow_multiple=False,
                )
            ],
            memory={**memory.public_state(), "ticket_id": ticket_id},
        )

    if selected_reason == "packaging_damaged_product_ok":
        memory.workflow_state = "awaiting_packaging_image"
        _log_reasoning(
            "workflow_state",
            "Packaging damage workflow requires packaging image evidence.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"ticket_id": ticket_id, "workflow_state": memory.workflow_state},
        )
        content = "Please upload an image showing the damaged packaging with the product inside."
        memory.remember("assistant", content)
        return InteractiveChatResponse(
            messages=memory.messages,
            actions=[
                _return_details_action(
                    label="Upload packaging image",
                    description_required=False,
                    image_required=True,
                    allow_multiple=False,
                )
            ],
            memory={**memory.public_state(), "ticket_id": ticket_id},
        )

    if selected_reason == "packaging_and_product_damaged":
        memory.workflow_state = "awaiting_damage_image"
        _log_reasoning(
            "workflow_state",
            "Damage workflow requires product or packaging image evidence.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"ticket_id": ticket_id, "workflow_state": memory.workflow_state},
        )
        content = (
            "Because both the packaging and product are damaged, please upload a photo. "
            "We’ll attach it to your request and route the case for specialist review."
        )
        memory.remember("assistant", content)
        return InteractiveChatResponse(
            messages=memory.messages,
            actions=[
                _return_details_action(
                    label="Upload damaged product image",
                    description_required=False,
                    image_required=True,
                    allow_multiple=False,
                )
            ],
            memory={**memory.public_state(), "ticket_id": ticket_id},
        )

    if selected_reason == "wrong_item_sent":
        memory.workflow_state = "awaiting_wrong_item_image"
        _log_reasoning(
            "workflow_state",
            "Wrong item workflow requires product and box images.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"ticket_id": ticket_id, "workflow_state": memory.workflow_state},
        )
        content = "For a wrong-item claim, please upload images of both the received product and the box."
        memory.remember("assistant", content)
        return InteractiveChatResponse(
            messages=memory.messages,
            actions=[
                _return_details_action(
                    label="Upload product and box images",
                    description_required=False,
                    image_required=True,
                    allow_multiple=True,
                )
            ],
            memory={**memory.public_state(), "ticket_id": ticket_id},
        )

    if selected_reason == "missing_parts":
        memory.workflow_state = "human_escalated"
        _log_reasoning(
            "escalation",
            "Missing parts request escalated to manual review.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"ticket_id": ticket_id, "workflow_state": memory.workflow_state},
        )
        return _contact_support_response(
            memory,
            "I created an active ticket and escalated this to a support specialist because parts are missing.",
            customer_id=customer.id,
        )

    if selected_reason == "changed_mind":
        memory.workflow_state = "ticket_created_policy_referenced"
        _log_reasoning(
            "policy_reference",
            "Changed-mind request created with policy reference for review.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"ticket_id": ticket_id, "workflow_state": memory.workflow_state},
        )
        content = (
            "I created an active ticket for this request.\n\n"
            "Shopward policy: changed-mind returns are checked against the standard return window, "
            "product eligibility, item condition, packaging, and proof-of-purchase requirements. "
            "Final sale, digital, subscription, and opened hygiene products may be restricted."
        )
        return await _run_existing_refund_flow(customer, memory, content)

    if selected_reason == "other":
        memory.workflow_state = "awaiting_other_details"
        _log_reasoning(
            "workflow_state",
            "Other return workflow requires a customer description.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"ticket_id": ticket_id, "workflow_state": memory.workflow_state},
        )
        content = "Please describe the reason for the return. You can also upload an image if it helps."
        memory.remember("assistant", content)
        return InteractiveChatResponse(
            messages=memory.messages,
            actions=[
                _return_details_action(
                    label="Add details",
                    description_required=True,
                    image_required=False,
                    allow_multiple=True,
                )
            ],
            memory={**memory.public_state(), "ticket_id": ticket_id},
        )

    return _assistant_response(memory, "I created an active ticket for this return request.")


def _return_details_action(
    label: str,
    description_required: bool,
    image_required: bool,
    allow_multiple: bool,
) -> AssistantAction:
    return AssistantAction(
        id="return_details",
        type="collect_return_details",
        label=label,
        accept="image/*",
        description_required=description_required,
        image_required=image_required,
        allow_multiple=allow_multiple,
    )


async def _handle_return_details(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    request: InteractiveChatRequest,
) -> InteractiveChatResponse:
    if not memory.selected_order_id or not memory.selected_reason:
        return _assistant_response(memory, "Please start a return request before adding details.")

    reason_label = next(
        (option.label for option in RETURN_REASONS if option.id == memory.selected_reason),
        memory.selected_reason,
    )
    ticket_id = _ensure_active_ticket(customer.id, memory.selected_order_id, reason_label)

    description = (request.description or "").strip()
    files = request.files

    description_required = memory.workflow_state in {"awaiting_defect_description", "awaiting_other_details"}
    image_required = memory.workflow_state in {
        "awaiting_packaging_image",
        "awaiting_damage_image",
        "awaiting_wrong_item_image",
    }

    if description_required and not description:
        _log_reasoning(
            "ticket_update_rejected",
            "Ticket update rejected because description was required.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"ticket_id": ticket_id, "workflow_state": memory.workflow_state},
        )
        return _assistant_response(memory, "Please add a description before submitting this ticket update.")
    if image_required and not files:
        _log_reasoning(
            "ticket_update_rejected",
            "Ticket update rejected because image evidence was required.",
            customer_id=customer.id,
            order_id=memory.selected_order_id,
            metadata={"ticket_id": ticket_id, "workflow_state": memory.workflow_state},
        )
        return _assistant_response(memory, "Please upload the requested image before submitting this ticket update.")

    if description:
        _update_ticket_comment(customer.id, ticket_id, description)

    upload_label = "Upload product image"
    if memory.workflow_state == "awaiting_packaging_image":
        upload_label = "Upload packaging image"
    elif memory.workflow_state == "awaiting_damage_image":
        upload_label = "Upload damaged product image"
    elif memory.workflow_state == "awaiting_wrong_item_image":
        upload_label = "Upload product and box images"

    if files:
        for file_upload in files:
            if not file_upload.data_base64:
                continue
            verification = _verify_uploaded_image(
                customer,
                memory,
                data_base64=file_upload.data_base64,
            )
            _log_reasoning(
                "evidence_verification",
                "Ran OpenCV/ViT evidence verification on return detail image.",
                customer_id=customer.id,
                order_id=memory.selected_order_id,
                metadata={
                    "ticket_id": ticket_id,
                    "passed": verification.passed,
                    "issue": verification.issue,
                    "detected_objects": verification.detected_objects,
                    "retries_remaining": verification.retries_remaining,
                },
            )
            if not verification.passed:
                if verification.retries_remaining <= 0:
                    return _escalate_evidence_failure(
                        customer,
                        memory,
                        ticket_id,
                        verification.customer_message,
                    )
                return _image_retry_response(
                    memory,
                    verification,
                    ticket_id=ticket_id,
                    label=upload_label,
                )
        memory.evidence_retry_count = 0
        _replace_ticket_evidence(ticket_id, files)

    memory.workflow_state = "ticket_updated"
    _log_reasoning(
        "ticket_updated",
        "Active ticket details were updated.",
        customer_id=customer.id,
        order_id=memory.selected_order_id,
        metadata={
            "ticket_id": ticket_id,
            "description_present": bool(description),
            "file_count": len(files),
            "workflow_state": memory.workflow_state,
        },
    )
    file_count = len(files)
    details = []
    if description:
        details.append("description")
    if file_count:
        details.append(f"{file_count} image{'s' if file_count != 1 else ''}")
    detail_text = " and ".join(details) if details else "details"
    content = (
        f"Thanks, {_first_name(customer)}. I updated active ticket {ticket_id} with your {detail_text}. "
        "I’ll check it against the refund policy now."
    )
    return await _run_existing_refund_flow(customer, memory, content)


def _order_is_returnable(customer_id: str, order) -> bool:
    if order.status == "returned":
        return False
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM ReturnRequest
            WHERE customer_id = ?
              AND order_id = ?
              AND status = 'Approved'
            LIMIT 1
            """,
            (customer_id, order.id),
        ).fetchone()
    return row is None


def _returned_order_message(order) -> str:
    product_names = ", ".join(item.name for item in order.items)
    return (
        f"{product_names} on order {order.id} has already been returned and "
        "cannot be submitted for another return request."
    )


def _active_ticket_order_ids(customer_id: str) -> set[str]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT order_id
            FROM ReturnRequest
            WHERE customer_id = ?
              AND status NOT IN ('Closed', 'Denied', 'Approved')
            """,
            (customer_id,),
        ).fetchall()
    return {row["order_id"] for row in rows}


def _active_ticket_for_order(customer_id: str, order_id: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT request_id, status
            FROM ReturnRequest
            WHERE customer_id = ?
              AND order_id = ?
              AND status NOT IN ('Closed', 'Denied', 'Approved')
            ORDER BY request_date DESC, request_id DESC
            LIMIT 1
            """,
            (customer_id, order_id),
        ).fetchone()
    return dict(row) if row else None


def _ensure_active_ticket(
    customer_id: str,
    order_id: str,
    reason: str,
    status: str = "Pending",
) -> str:
    existing = _active_ticket_for_order(customer_id, order_id)
    if existing:
        return str(existing["request_id"])

    request_id = f"ret_{uuid4().hex[:8]}"
    with get_connection() as connection:
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
                status,
            ),
        )
    return request_id


def _update_ticket_comment(customer_id: str, request_id: str, comment: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE ReturnRequest
            SET customer_comment = ?
            WHERE request_id = ?
              AND customer_id = ?
            """,
            (comment, request_id, customer_id),
        )


def _replace_ticket_evidence(request_id: str, files: list) -> None:
    with get_connection() as connection:
        persist_ticket_evidence(connection, request_id, files)


async def _run_existing_refund_flow(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    intro: str,
) -> InteractiveChatResponse:
    memory.workflow_state = "decision_completed"
    _log_reasoning(
        "policy_evaluation",
        "Interactive assistant handed off to deterministic refund policy agent.",
        customer_id=customer.id,
        order_id=memory.selected_order_id,
        metadata={"message": intro},
    )
    decision = await run_refund_agent(
        ChatRequest(customer_id=customer.id, order_id=memory.selected_order_id, message=intro)
    )
    request_id = None
    if memory.selected_order_id:
        ticket = _active_ticket_for_order(customer.id, memory.selected_order_id)
        request_id = str(ticket["request_id"]) if ticket else None
    if decision.order_id:
        request_id = await apply_refund_decision(
            decision=decision,
            customer_id=customer.id,
            order_id=decision.order_id,
            request_id=request_id,
            actor="agent",
        )
    content = intro
    memory.remember("assistant", content)
    return InteractiveChatResponse(
        messages=memory.messages,
        decision=public_refund_decision(decision),
        memory={**memory.public_state(), "ticket_id": request_id},
    )


def _assistant_response(memory: AssistantSessionMemory, content: str) -> InteractiveChatResponse:
    memory.remember("assistant", content)
    return InteractiveChatResponse(messages=memory.messages, memory=memory.public_state())


def _resolve_order(customer: CustomerProfile, message: str):
    normalized_message = message.lower()
    ranked_index = _ranked_purchase_index(normalized_message)
    if ranked_index is not None:
        orders = sorted(customer.orders, key=lambda order: order.order_date, reverse=True)
        if ranked_index < len(orders):
            return orders[ranked_index]

    normalized_compact = re.sub(r"[^a-z0-9]+", " ", normalized_message).strip()
    candidates: dict[str, float] = {}

    for order in customer.orders:
        if order.id.lower() in normalized_message:
            return order
        for item in order.items:
            labels = [item.name, item.sku, f"{order.id} {item.name}", f"{item.name} {item.sku}"]
            for label in labels:
                normalized_label = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
                if normalized_label and normalized_label in normalized_compact:
                    return order

                score = SequenceMatcher(None, normalized_label, normalized_compact).ratio()
                token_score = max(
                    (
                        SequenceMatcher(None, normalized_label, window).ratio()
                        for window in _message_windows(normalized_compact, len(normalized_label.split()))
                    ),
                    default=0,
                )
                candidates[order.id] = max(candidates.get(order.id, 0), score, token_score)

    if not candidates:
        return None

    ranked = sorted(((score, order_id) for order_id, score in candidates.items()), reverse=True)
    best_score, best_order_id = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0
    if best_score >= 0.72 and best_score - second_score >= 0.06:
        return next(order for order in customer.orders if order.id == best_order_id)
    return None


def _ranked_purchase_index(lowered: str) -> int | None:
    if any(phrase in lowered for phrase in ("second last", "second-last", "2nd last", "second most recent", "2nd most recent")):
        return 1
    if any(phrase in lowered for phrase in ("third last", "third-last", "3rd last", "third most recent", "3rd most recent")):
        return 2
    if any(phrase in lowered for phrase in ("fourth last", "fourth-last", "4th last", "fourth most recent", "4th most recent")):
        return 3
    if any(phrase in lowered for phrase in ("fifth last", "fifth-last", "5th last", "fifth most recent", "5th most recent")):
        return 4
    if any(phrase in lowered for phrase in ("last purchase", "latest purchase", "most recent purchase", "last order", "latest order", "most recent order")):
        return 0
    if re.search(r"\blast (product|item) i purchased\b", lowered):
        return 0
    return None


def _ranked_purchase_label(index: int) -> str:
    if index == 0:
        return "most recent purchase"
    labels = {1: "second most recent purchase", 2: "third most recent purchase", 3: "fourth most recent purchase"}
    return labels.get(index, f"{index + 1}th most recent purchase")


def _message_windows(message: str, token_count: int) -> list[str]:
    tokens = message.split()
    if token_count <= 0 or not tokens:
        return []
    window_size = min(max(token_count, 1), len(tokens))
    return [" ".join(tokens[index : index + window_size]) for index in range(len(tokens) - window_size + 1)]
