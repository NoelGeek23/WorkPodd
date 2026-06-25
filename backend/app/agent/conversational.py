from __future__ import annotations

import os
import re

import httpx

from app.agent.session_memory import AssistantSessionMemory
from app.agent.system_prompt import (
    ASSISTANT_SYSTEM_PROMPT,
    OUT_OF_SCOPE_TOKEN,
    customer_context_line,
    out_of_scope_reply,
)
from app.models import CustomerProfile, InteractiveChatResponse


_THANKS = re.compile(
    r"^(thanks?|thank you|thx|much appreciated|appreciate it|appreciated)[!.?\s]*$",
    re.IGNORECASE,
)
_HOW_ARE_YOU = re.compile(
    r"^how(\s*are|\s*\'re|\s*r)\s*you(\s*doing|\s*today)?[!.?\s]*$",
    re.IGNORECASE,
)
_GREETING = re.compile(
    r"^(hi|hello|hey|good morning|good afternoon|good evening|howdy)[!.?\s]*$",
    re.IGNORECASE,
)
_GOODBYE = re.compile(
    r"^(bye|goodbye|good bye|see you|see ya|take care|have a (good|great|nice) (day|one))[!.?\s]*$",
    re.IGNORECASE,
)
_YOU_WELCOME = re.compile(
    r"^(you(\'re| are) welcome|no problem|anytime|my pleasure)[!.?\s]*$",
    re.IGNORECASE,
)


def _first_name(customer: CustomerProfile) -> str:
    name = customer.name.strip()
    return name.split()[0] if name else "there"


def detect_conversational_kind(message: str) -> str | None:
    normalized = re.sub(r"\s+", " ", message.strip())
    if not normalized:
        return None
    if _THANKS.match(normalized):
        return "thanks"
    if _HOW_ARE_YOU.match(normalized):
        return "how_are_you"
    if _GREETING.match(normalized):
        return "greeting"
    if _GOODBYE.match(normalized):
        return "goodbye"
    if _YOU_WELCOME.match(normalized):
        return "you_welcome"
    return None


def conversational_reply(kind: str, customer: CustomerProfile) -> str:
    name = _first_name(customer)
    replies = {
        "thanks": f"Glad I was able to help you, {name}! Let me know if you need anything else.",
        "how_are_you": (
            f"I'm doing well, thanks for asking, {name}! "
            "How can I help you with your orders or returns today?"
        ),
        "greeting": f"Hi {name}! How can I help you with returns, orders, or Shopward policy today?",
        "goodbye": f"Take care, {name}! Come back anytime you need help with an order.",
        "you_welcome": f"Happy to help, {name}!",
    }
    return replies[kind]


def is_conversational_message(message: str) -> bool:
    return detect_conversational_kind(message) is not None


async def _llm_conversational_reply(customer: CustomerProfile, message: str) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "temperature": 0.4,
        "max_tokens": 120,
        "messages": [
            {"role": "system", "content": ASSISTANT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{customer_context_line(customer)}\n\n"
                    f"Customer message: {message}\n\n"
                    "If this is a brief social message, reply naturally. "
                    f"Otherwise respond with exactly {OUT_OF_SCOPE_TOKEN}."
                ),
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None

    content = str(data["choices"][0]["message"]["content"]).strip()
    if not content or OUT_OF_SCOPE_TOKEN in content:
        return None
    return content


async def try_conversational_response(
    customer: CustomerProfile,
    memory: AssistantSessionMemory,
    message: str,
) -> InteractiveChatResponse | None:
    kind = detect_conversational_kind(message)
    if kind:
        content = conversational_reply(kind, customer)
    else:
        content = await _llm_conversational_reply(customer, message)
        if not content:
            return None

    memory.workflow_state = "conversational"
    memory.remember("assistant", content)
    return InteractiveChatResponse(messages=memory.messages, memory=memory.public_state())


def unable_to_answer_response(
    memory: AssistantSessionMemory,
    customer: CustomerProfile,
) -> InteractiveChatResponse:
    content = out_of_scope_reply(_first_name(customer))
    return _assistant_response(memory, content)


def _assistant_response(
    memory: AssistantSessionMemory,
    content: str,
) -> InteractiveChatResponse:
    memory.remember("assistant", content)
    return InteractiveChatResponse(messages=memory.messages, memory=memory.public_state())
