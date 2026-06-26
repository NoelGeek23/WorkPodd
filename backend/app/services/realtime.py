from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

from app.models import RealtimeSessionResponse

REALTIME_INSTRUCTIONS = """
You are WorkPodd's customer support voice agent. Be concise, warm, and transparent.
Collect the customer ID, order ID, and refund reason. When the customer wants a refund,
summarize the request and ask the web app to submit it to the refund policy backend.
Never approve, deny, or claim to process a refund by voice alone.
""".strip()

REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls"
CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"


@dataclass
class RealtimeCallResult:
    sdp: str | None
    model: str
    voice: str
    error: str | None = None


def _realtime_model() -> str:
    return os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime")


def _realtime_voice() -> str:
    return os.getenv("OPENAI_REALTIME_VOICE", "alloy")


def _session_payload() -> dict:
    return {
        "type": "realtime",
        "model": _realtime_model(),
        "instructions": REALTIME_INSTRUCTIONS,
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                "transcription": {
                    "model": "gpt-4o-mini-transcribe",
                },
            },
            "output": {
                "voice": _realtime_voice(),
            },
        },
    }


async def connect_realtime_call(sdp: str) -> RealtimeCallResult:
    """Proxy WebRTC SDP negotiation through the backend using the Realtime unified interface."""
    model = _realtime_model()
    voice = _realtime_voice()
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return RealtimeCallResult(
            sdp=None,
            model=model,
            voice=voice,
            error="OPENAI_API_KEY is not configured.",
        )

    if not sdp.strip():
        return RealtimeCallResult(
            sdp=None,
            model=model,
            voice=voice,
            error="Missing SDP offer.",
        )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                REALTIME_CALLS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={
                    "sdp": (None, sdp, "application/sdp"),
                    "session": (None, json.dumps(_session_payload()), "application/json"),
                },
            )
            response.raise_for_status()
            answer_sdp = response.text
    except httpx.HTTPStatusError as exc:
        return RealtimeCallResult(
            sdp=None,
            model=model,
            voice=voice,
            error=f"OpenAI Realtime API error ({exc.response.status_code}): {exc.response.text[:300]}",
        )
    except httpx.HTTPError as exc:
        return RealtimeCallResult(
            sdp=None,
            model=model,
            voice=voice,
            error=f"OpenAI Realtime API request failed: {exc}",
        )

    return RealtimeCallResult(sdp=answer_sdp, model=model, voice=voice)


async def create_realtime_session() -> RealtimeSessionResponse:
    model = _realtime_model()
    voice = _realtime_voice()
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return RealtimeSessionResponse(
            model=model,
            voice=voice,
            instructions=REALTIME_INSTRUCTIONS,
            note="OPENAI_API_KEY is not configured. Voice UI will show setup guidance.",
        )

    payload = {"session": _session_payload()}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                CLIENT_SECRETS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        return RealtimeSessionResponse(
            model=model,
            voice=voice,
            instructions=REALTIME_INSTRUCTIONS,
            note=f"OpenAI Realtime API error ({exc.response.status_code}): {detail}",
        )
    except httpx.HTTPError as exc:
        return RealtimeSessionResponse(
            model=model,
            voice=voice,
            instructions=REALTIME_INSTRUCTIONS,
            note=f"OpenAI Realtime API request failed: {exc}",
        )

    session_config = data.get("session") or {}
    return RealtimeSessionResponse(
        client_secret={"value": data.get("value")},
        model=str(session_config.get("model") or model),
        voice=voice,
        instructions=REALTIME_INSTRUCTIONS,
        calls_url=REALTIME_CALLS_URL,
    )
