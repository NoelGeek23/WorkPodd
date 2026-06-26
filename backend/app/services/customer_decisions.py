from __future__ import annotations

from app.models import RefundDecision

GENERIC_DENIAL = (
    "This order does not qualify for an automatic refund under Shopward policy."
)

SUPPORT_FOLLOW_UP = (
    " If you have questions or believe this was decided in error, contact Shopward Support."
)


def customer_denial_summary(decision: RefundDecision) -> str:
    """Map internal policy outcomes to a short customer-safe explanation."""
    # Use the actual denial reason only. Policy rule citations from RAG can mention
    # unrelated sections (e.g. "Personal Hygiene Products") and must not drive UX copy.
    text = decision.internal_reason.lower()

    if (
        "return window" in text
        or "outside the eligible return window" in text
        or "must be returned within" in text
        or ("days" in text and "delivery" in text and "within" in text)
    ):
        return "This return falls outside the eligible return window for this order." + SUPPORT_FOLLOW_UP
    if "final sale" in text:
        return "This item is marked as final sale and is not eligible for a refund." + SUPPORT_FOLLOW_UP
    if "digital" in text:
        return "Digital products are not eligible for automatic refunds after delivery." + SUPPORT_FOLLOW_UP
    if "subscription" in text:
        return "Subscription products must be reviewed by our subscription support team." + SUPPORT_FOLLOW_UP
    if (
        "hygiene-sensitive" in text
        or "opened hygiene" in text
        or "personal hygiene" in text
        or "hygiene product" in text
    ):
        return "Opened hygiene-sensitive items cannot be refunded automatically." + SUPPORT_FOLLOW_UP
    if "used item" in text or ("condition" in text and "used" in text):
        return "Used items are not eligible for an automatic refund." + SUPPORT_FOLLOW_UP
    if "original packaging" in text or "packaging is required" in text:
        return "Original packaging is required for an automatic refund on this item." + SUPPORT_FOLLOW_UP
    if "carrier damage" not in text and "damaged" in text and "customer-caused" in text:
        return "Customer-caused damage is not covered by our automatic refund policy." + SUPPORT_FOLLOW_UP
    if "opened item" in text and "loyalty" in text:
        return "Opened items require an eligible membership tier for automatic refunds." + SUPPORT_FOLLOW_UP
    if "lost" in text or "not delivered" in text:
        return "This order is not eligible for a standard return refund in its current delivery state." + SUPPORT_FOLLOW_UP
    if "fraud" in text or "anti-fraud" in text or "manual review" in text:
        return (
            "Your request could not be approved automatically and needs a support review."
            + SUPPORT_FOLLOW_UP
        )

    return GENERIC_DENIAL + SUPPORT_FOLLOW_UP


def customer_facing_message(decision: RefundDecision) -> str:
    if decision.status == "approved":
        return (
            f"Your refund of ${decision.amount:.2f} has been approved. "
            "You'll receive confirmation once it's processed."
        )
    if decision.status == "denied":
        return customer_denial_summary(decision)
    if "awaiting admin approval" in decision.internal_reason.lower():
        return (
            "Your return request has been submitted and is pending admin review. "
            "Check Active Tickets for updates once a decision is made."
        )
    return (
        "Your return request needs additional review. "
        "A support specialist will follow up with you soon."
    )


def ticket_denial_message(decision: RefundDecision, *, actor: str = "agent") -> str:
    """Message stored on the ticket for customer-visible denial outcomes."""
    if actor == "admin":
        admin_text = (decision.customer_message or "").strip()
        if admin_text:
            return admin_text if "support" in admin_text.lower() else admin_text + SUPPORT_FOLLOW_UP
    return customer_denial_summary(decision)


def public_refund_decision(decision: RefundDecision) -> RefundDecision:
    """Return a customer-safe view without internal policy or tool details."""
    summary = (
        customer_denial_summary(decision)
        if decision.status == "denied"
        else customer_facing_message(decision)
    )
    return RefundDecision(
        status=decision.status,
        customer_message=summary,
        internal_reason="",
        amount=decision.amount,
        order_id=decision.order_id,
        policy_rules=[],
        tool_calls=[],
    )
