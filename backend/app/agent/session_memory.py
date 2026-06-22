from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models import AssistantMessage


class AssistantSessionMemory(BaseModel):
    messages: list[AssistantMessage] = Field(default_factory=list)
    current_intent: str | None = None
    workflow_state: str = "idle"
    selected_order_id: str | None = None
    selected_product_name: str | None = None
    selected_reason: str | None = None
    uploaded_evidence: dict[str, Any] | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def remember(self, role: str, content: str) -> None:
        self.messages.append(AssistantMessage(role=role, content=content))  # type: ignore[arg-type]
        self.messages = self.messages[-20:]
        self.updated_at = datetime.utcnow()

    def public_state(self) -> dict[str, Any]:
        return {
            "current_intent": self.current_intent,
            "workflow_state": self.workflow_state,
            "selected_order_id": self.selected_order_id,
            "selected_product_name": self.selected_product_name,
            "selected_reason": self.selected_reason,
            "uploaded_evidence": self.uploaded_evidence,
        }


_SESSION_MEMORY: dict[str, AssistantSessionMemory] = {}


def get_session_memory(token: str) -> AssistantSessionMemory:
    if token not in _SESSION_MEMORY:
        _SESSION_MEMORY[token] = AssistantSessionMemory()
    return _SESSION_MEMORY[token]


def clear_session_memory(token: str) -> None:
    _SESSION_MEMORY.pop(token, None)
