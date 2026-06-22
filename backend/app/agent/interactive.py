from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.agent.graph import run_refund_agent
from app.agent.session_memory import AssistantSessionMemory
from app.models import (
    AssistantAction,
    AssistantMessage,
    AssistantOption,
    ChatRequest,
    CustomerProfile,
    InteractiveChatRequest,
    InteractiveChatResponse,
    InteractiveUploadRequest,
)
from app.rag.policy_index import retrieve_policy_sections

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


async def handle_interactive_chat(
    token: str,
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    request: InteractiveChatRequest,
) -> InteractiveChatResponse:
    if request.selected_option:
        return await _handle_reason_selection(customer, memory, request.selected_option)

    message = (request.message or "").strip()
    if not message:
        return _assistant_response(memory, "Tell me what you need help with.")

    memory.remember("user", message)
    if memory.workflow_state == "awaiting_order":
        memory.current_intent = "return_exchange_request"
        return _start_return_exchange(customer, memory, message)

    intent = _classify_intent(message)
    memory.current_intent = intent

    if intent == "policy_question":
        return _answer_policy_question(memory, message)

    if intent == "return_exchange_request":
        return _start_return_exchange(customer, memory, message)

    return _assistant_response(
        memory,
        "I can help with Shopward policy questions or guide a return/exchange request. "
        "For returns, mention your order ID, product name, or SKU.",
    )


def handle_interactive_upload(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    upload: InteractiveUploadRequest,
) -> InteractiveChatResponse:
    if not upload.content_type.startswith("image/"):
        return _assistant_response(memory, "Please upload an image file so I can attach it as evidence.")

    max_size = 5 * 1024 * 1024
    if upload.size > max_size:
        return _assistant_response(memory, "That image is too large for the demo. Please upload one under 5 MB.")

    memory.uploaded_evidence = {
        "file_name": upload.file_name,
        "content_type": upload.content_type,
        "size": upload.size,
        "image_engine": {
            "damage_detected": True,
            "confidence": 0.91,
            "requires_manual_review": True,
        },
    }
    memory.workflow_state = "manual_review_escalated"

    content = (
        "Thanks, I attached the image evidence. The internal image check marked this as requiring "
        "manual review, so I’m escalating this case to an admin specialist."
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
    lowered = message.lower()
    if "want to know" in lowered or lowered.startswith(("what ", "how ", "when ", "which ")):
        if any(term in lowered for term in POLICY_TERMS):
            return "policy_question"
    action_phrases = ("i want", "i need", "return my", "refund my", "exchange my", "replace my")
    if any(term in lowered for term in POLICY_TERMS) and not any(
        phrase in lowered for phrase in action_phrases
    ):
        return "policy_question"
    if any(term in lowered for term in RETURN_TERMS):
        return "return_exchange_request"
    return "unknown"


def _answer_policy_question(memory: AssistantSessionMemory, message: str) -> InteractiveChatResponse:
    sections = retrieve_policy_sections(message, limit=3)
    if not sections:
        content = (
            "I could not find a matching policy section.\n\n"
            "Try asking about return windows, final sale items, VIP rules, exchanges, or damaged items."
        )
        memory.remember("assistant", content)
        return InteractiveChatResponse(messages=memory.messages, memory=memory.public_state())

    primary = sections[0]
    supporting = sections[1:]
    content_parts = [
        "Here is what the Shopward policy says.",
        f"Primary section: {primary['section_title']}. {primary['content'][:360].replace(chr(10), ' ')}",
    ]

    if supporting:
        supporting_text = " ".join(
            f"{section['section_title']}: {section['content'][:180].replace(chr(10), ' ')}"
            for section in supporting
        )
        content_parts.append(f"Related sections: {supporting_text}")

    lowered = message.lower()
    if "vip" in lowered or "return window" in lowered:
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


def _start_return_exchange(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    message: str,
) -> InteractiveChatResponse:
    order = _resolve_order(customer, message)
    if not order:
        content = "Which purchase is this for? Please mention an order ID, product name, or SKU from your purchases."
        memory.workflow_state = "awaiting_order"
        memory.remember("assistant", content)
        return InteractiveChatResponse(messages=memory.messages, memory=memory.public_state())

    memory.selected_order_id = order.id
    memory.selected_product_name = ", ".join(item.name for item in order.items)
    memory.workflow_state = "awaiting_return_reason"
    content = (
        f"I found {memory.selected_product_name} on order {order.id}. "
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

    if selected_reason == "packaging_and_product_damaged":
        memory.workflow_state = "awaiting_damage_image"
        content = (
            "Because both the packaging and product are damaged, please upload a photo. "
            "The internal image check will attach evidence and escalate this to admin review."
        )
        memory.remember("assistant", content)
        return InteractiveChatResponse(
            messages=memory.messages,
            actions=[
                AssistantAction(
                    id="damage_image",
                    type="upload_image",
                    label="Upload damaged product image",
                    accept="image/*",
                )
            ],
            memory=memory.public_state(),
        )

    if selected_reason == "wrong_item_sent":
        memory.workflow_state = "awaiting_wrong_item_image"
        content = "For a wrong-item claim, please upload a photo of the received item and label."
        memory.remember("assistant", content)
        return InteractiveChatResponse(
            messages=memory.messages,
            actions=[
                AssistantAction(
                    id="wrong_item_image",
                    type="upload_image",
                    label="Upload wrong item evidence",
                    accept="image/*",
                )
            ],
            memory=memory.public_state(),
        )

    if selected_reason == "packaging_damaged_product_ok":
        content = (
            "Packaging-only damage usually does not qualify for a full automatic refund if the product is fine. "
            "I can still check standard return eligibility for this order."
        )
    elif selected_reason == "defective_item":
        content = "I’ll check this against the manufacturer defect and return eligibility rules."
    elif selected_reason == "missing_parts":
        content = "Missing parts may require review, but I’ll first run the standard eligibility checks."
    elif selected_reason == "changed_mind":
        content = "I’ll check the standard return window and product eligibility rules."
    else:
        content = "I’ll run the standard return eligibility checks for this order."

    decision_response = await _run_existing_refund_flow(customer, memory, content)
    return decision_response


async def _run_existing_refund_flow(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    intro: str,
) -> InteractiveChatResponse:
    memory.workflow_state = "decision_completed"
    decision = await run_refund_agent(
        ChatRequest(customer_id=customer.id, order_id=memory.selected_order_id, message=intro)
    )
    content = f"{intro}\n\n{decision.customer_message}"
    memory.remember("assistant", content)
    return InteractiveChatResponse(
        messages=memory.messages,
        decision=decision,
        memory=memory.public_state(),
    )


def _assistant_response(memory: AssistantSessionMemory, content: str) -> InteractiveChatResponse:
    memory.remember("assistant", content)
    return InteractiveChatResponse(messages=memory.messages, memory=memory.public_state())


def _resolve_order(customer: CustomerProfile, message: str):
    normalized_message = message.lower()
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


def _message_windows(message: str, token_count: int) -> list[str]:
    tokens = message.split()
    if token_count <= 0 or not tokens:
        return []
    window_size = min(max(token_count, 1), len(tokens))
    return [" ".join(tokens[index : index + window_size]) for index in range(len(tokens) - window_size + 1)]
