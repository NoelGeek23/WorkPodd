from __future__ import annotations

import os

import httpx

from app.models import RealtimeSessionResponse

REALTIME_INSTRUCTIONS = """
You are WorkPodd's customer support voice agent. Be concise, warm, and transparent.
Collect the customer ID, order ID, and refund reason. When the customer wants a refund,
summarize the request and ask the web app to submit it to the refund policy backend.
Never approve, deny, or claim to process a refund by voice alone.
""".strip()


async def create_realtime_session() -> RealtimeSessionResponse:
    model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview")
    voice = os.getenv("OPENAI_REALTIME_VOICE", "alloy")
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return RealtimeSessionResponse(
            model=model,
            voice=voice,
            instructions=REALTIME_INSTRUCTIONS,
            note="OPENAI_API_KEY is not configured. Voice UI will show setup guidance.",
        )

    payload = {
        "model": model,
        "voice": voice,
        "instructions": REALTIME_INSTRUCTIONS,
        "modalities": ["audio", "text"],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://api.openai.com/v1/realtime/sessions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    return RealtimeSessionResponse(
        client_secret=data.get("client_secret"),
        model=model,
        voice=voice,
        instructions=REALTIME_INSTRUCTIONS,
    )
