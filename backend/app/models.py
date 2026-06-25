from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class LoyaltyTier(str, Enum):
    standard = "standard"
    silver = "silver"
    gold = "gold"
    platinum = "platinum"


class OrderItem(BaseModel):
    sku: str
    name: str
    category: str
    product_type: str = "physical"
    price: float
    quantity: int = 1
    condition: Literal["unopened", "opened", "damaged", "used", "digital_delivered"]
    final_sale: bool = False
    digital_download: bool = False
    subscription_product: bool = False
    hygiene_sensitive: bool = False
    serial_number_present: bool = True
    original_packaging_present: bool = True
    original_accessories_present: bool = True


class Order(BaseModel):
    id: str
    order_date: str
    delivered_date: str | None = None
    status: Literal["processing", "shipped", "delivered", "returned", "lost"]
    total: float
    currency: str = "USD"
    items: list[OrderItem]
    payment_method: str
    shipping_country: str
    tracking_status: str


class CustomerProfile(BaseModel):
    id: str
    name: str
    email: str
    loyalty_tier: LoyaltyTier
    account_created: str
    fraud_flag: bool = False
    chargeback_count: int = 0
    refund_count_last_12_months: int = 0
    lifetime_value: float
    notes: str
    orders: list[Order]


class ChatRequest(BaseModel):
    customer_id: str
    message: str
    order_id: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class ScopedChatRequest(BaseModel):
    message: str
    order_id: str | None = None


class LoginResponse(BaseModel):
    token: str
    role: Literal["customer", "admin"]
    customer: dict[str, Any]


class AssistantOption(BaseModel):
    id: str
    label: str
    description: str | None = None


class AssistantAction(BaseModel):
    id: str
    type: Literal[
        "show_reason_options",
        "upload_image",
        "select_purchase",
        "contact_support",
        "collect_return_details",
    ]
    label: str
    options: list[AssistantOption] = Field(default_factory=list)
    accept: str | None = None
    description_required: bool = False
    image_required: bool = False
    allow_multiple: bool = False


class EvidenceUpload(BaseModel):
    file_name: str
    content_type: str
    size: int
    data_base64: str | None = None


class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class InteractiveChatRequest(BaseModel):
    message: str | None = None
    selected_option: str | None = None
    action_id: str | None = None
    description: str | None = None
    files: list[EvidenceUpload] = Field(default_factory=list)


class InteractiveUploadRequest(BaseModel):
    file_name: str
    content_type: str
    size: int
    data_base64: str | None = None


class TicketUpdateRequest(BaseModel):
    description: str | None = None
    files: list[EvidenceUpload] = Field(default_factory=list)


class AdminTicketRejectRequest(BaseModel):
    reason: str


class InteractiveChatResponse(BaseModel):
    messages: list[AssistantMessage]
    actions: list[AssistantAction] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    decision: RefundDecision | None = None
    memory: dict[str, Any] = Field(default_factory=dict)


class ToolCallLog(BaseModel):
    tool: str
    input: dict[str, Any]
    output: dict[str, Any]


class AgentLogEvent(BaseModel):
    id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    customer_id: str | None = None
    order_id: str | None = None
    stage: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RefundDecision(BaseModel):
    status: Literal["approved", "denied", "escalated"]
    customer_message: str
    internal_reason: str
    amount: float = 0
    order_id: str | None = None
    policy_rules: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallLog] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    decision: RefundDecision


class RealtimeSessionResponse(BaseModel):
    client_secret: dict[str, Any] | None = None
    model: str
    voice: str
    instructions: str
    note: str | None = None
