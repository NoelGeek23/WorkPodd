from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agent.graph import build_langgraph_definition, run_refund_agent
from app.agent.interactive import handle_interactive_chat, handle_interactive_upload
from app.agent.session_memory import clear_session_memory, get_session_memory
from app.agent.tools import find_customer, load_policy
from app.db.database import get_connection, has_seed_data, initialize_schema, rows_to_dicts
from app.db.seed import seed_demo_data
from app.models import (
    ChatRequest,
    ChatResponse,
    CustomerProfile,
    InteractiveChatRequest,
    InteractiveChatResponse,
    InteractiveUploadRequest,
    LoginRequest,
    LoginResponse,
    ScopedChatRequest,
)
from app.rag.policy_index import ensure_policy_index, retrieve_policy_sections
from app.services.log_bus import log_bus
from app.services.realtime import create_realtime_session

load_dotenv()

app = FastAPI(title="AI Customer Support Refund Agent", version="0.1.0")

allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

initialize_schema()
if not has_seed_data():
    seed_demo_data(reset=True)
ensure_policy_index()

_compiled_langgraph = build_langgraph_definition()
DEMO_PASSWORD = "12345678"
SESSIONS: dict[str, str] = {}


def _customer_response(customer: CustomerProfile) -> dict:
    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "loyalty_tier": customer.loyalty_tier.value,
        "fraud_flag": customer.fraud_flag,
        "chargeback_count": customer.chargeback_count,
        "refund_count_last_12_months": customer.refund_count_last_12_months,
        "lifetime_value": customer.lifetime_value,
        "notes": customer.notes,
        "orders": [
            {
                "id": order.id,
                "status": order.status,
                "total": order.total,
                "delivered_date": order.delivered_date,
                "tracking_status": order.tracking_status,
                "items": [item.model_dump() for item in order.items],
            }
            for order in customer.orders
        ],
    }


def _find_customer_by_email(email: str) -> CustomerProfile | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT customer_id FROM Customer WHERE lower(email) = lower(?)",
            (email.strip(),),
        ).fetchone()
    return find_customer(row["customer_id"]) if row else None


def _resolve_order_id_from_message(customer: CustomerProfile, message: str) -> str | None:
    normalized_message = message.lower()
    normalized_compact = re.sub(r"[^a-z0-9]+", " ", normalized_message).strip()
    candidates: dict[str, float] = {}

    for order in customer.orders:
        if order.id.lower() in normalized_message:
            return order.id

        for item in order.items:
            labels = [item.name, item.sku, f"{order.id} {item.name}", f"{item.name} {item.sku}"]
            for label in labels:
                normalized_label = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
                if normalized_label and normalized_label in normalized_compact:
                    return order.id

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
        return best_order_id
    return None


def _message_windows(message: str, token_count: int) -> list[str]:
    tokens = message.split()
    if token_count <= 0 or not tokens:
        return []
    window_size = min(max(token_count, 1), len(tokens))
    return [" ".join(tokens[index : index + window_size]) for index in range(len(tokens) - window_size + 1)]


def _resolve_scoped_order_id(customer: CustomerProfile, order_id: str | None, message: str) -> str | None:
    mentioned_order_id = _resolve_order_id_from_message(customer, message)
    if mentioned_order_id and mentioned_order_id != order_id:
        return mentioned_order_id
    return order_id


def _extract_session_token(authorization: str | None, token: str | None) -> str:
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip()
    if token:
        return token.strip()
    raise HTTPException(status_code=401, detail="Login required")


def get_current_customer(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> CustomerProfile:
    session_token = _extract_session_token(authorization, token)
    customer_id = SESSIONS.get(session_token)
    if not customer_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    customer = find_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=401, detail="Session customer no longer exists")
    return customer


def get_current_session(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> tuple[str, CustomerProfile]:
    session_token = _extract_session_token(authorization, token)
    customer_id = SESSIONS.get(session_token)
    if not customer_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    customer = find_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=401, detail="Session customer no longer exists")
    return session_token, customer


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "langgraph_available": _compiled_langgraph is not None,
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "database_ready": has_seed_data(),
    }


@app.post("/api/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    if request.password != DEMO_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    customer = _find_customer_by_email(request.email)
    if not customer:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = uuid4().hex
    SESSIONS[token] = customer.id
    return LoginResponse(token=token, customer=_customer_response(customer))


@app.post("/api/auth/logout")
async def logout(session: tuple[str, CustomerProfile] = Depends(get_current_session)) -> dict:
    session_token, _customer = session
    clear_session_memory(session_token)
    SESSIONS.pop(session_token, None)
    return {"status": "ok"}


@app.get("/api/me")
async def me(customer: CustomerProfile = Depends(get_current_customer)) -> dict:
    return _customer_response(customer)


@app.get("/api/customers")
async def customers(customer: CustomerProfile = Depends(get_current_customer)) -> list[dict]:
    return [_customer_response(customer)]


@app.get("/api/customers/{customer_id}")
async def customer(customer_id: str, current_customer: CustomerProfile = Depends(get_current_customer)) -> dict:
    if customer_id != current_customer.id:
        raise HTTPException(status_code=403, detail="Cannot access another customer's data")
    profile = find_customer(current_customer.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Customer not found")
    return _customer_response(profile)


@app.get("/api/policy")
async def policy() -> dict:
    return {"policy": load_policy()}


@app.get("/api/policy/search")
async def policy_search(q: str) -> dict:
    return {"query": q, "sections": retrieve_policy_sections(q)}


@app.get("/api/policy/sections")
async def policy_sections() -> dict:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT chunk_id, section_title, content
            FROM PolicyChunk
            ORDER BY chunk_id
            """
        ).fetchall()
    return {"sections": rows_to_dicts(rows)}


@app.get("/api/return-requests")
async def return_requests() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT rr.*, c.name AS customer_name, o.total_amount
            FROM ReturnRequest rr
            JOIN Customer c ON rr.customer_id = c.customer_id
            JOIN Orders o ON rr.order_id = o.order_id
            ORDER BY rr.request_date DESC, rr.request_id
            """
        ).fetchall()
    return rows_to_dicts(rows)


@app.get("/api/decisions")
async def decisions() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT adl.*, rr.customer_id, rr.order_id
            FROM AgentDecisionLog adl
            LEFT JOIN ReturnRequest rr ON adl.request_id = rr.request_id
            ORDER BY adl.created_at DESC
            LIMIT 100
            """
        ).fetchall()
    return rows_to_dicts(rows)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_customer: CustomerProfile = Depends(get_current_customer),
) -> ChatResponse:
    if request.customer_id != current_customer.id:
        raise HTTPException(status_code=403, detail="Cannot chat with another customer's context")
    resolved_order_id = _resolve_scoped_order_id(current_customer, request.order_id, request.message)
    if not resolved_order_id:
        raise HTTPException(
            status_code=400,
            detail="Mention one of your order IDs or product names so I can evaluate the correct purchase.",
        )
    if resolved_order_id and all(order.id != resolved_order_id for order in current_customer.orders):
        raise HTTPException(status_code=403, detail="Order does not belong to logged-in customer")
    decision = await run_refund_agent(request.model_copy(update={"order_id": resolved_order_id}))
    return ChatResponse(reply=decision.customer_message, decision=decision)


@app.post("/api/me/chat", response_model=ChatResponse)
async def scoped_chat(
    request: ScopedChatRequest,
    current_customer: CustomerProfile = Depends(get_current_customer),
) -> ChatResponse:
    resolved_order_id = _resolve_scoped_order_id(current_customer, request.order_id, request.message)
    if not resolved_order_id:
        raise HTTPException(
            status_code=400,
            detail="Mention one of your order IDs or product names so I can evaluate the correct purchase.",
        )
    if resolved_order_id and all(order.id != resolved_order_id for order in current_customer.orders):
        raise HTTPException(status_code=403, detail="Order does not belong to logged-in customer")
    decision = await run_refund_agent(
        ChatRequest(
            customer_id=current_customer.id,
            order_id=resolved_order_id,
            message=request.message,
        )
    )
    return ChatResponse(reply=decision.customer_message, decision=decision)


@app.post("/api/me/assistant/chat", response_model=InteractiveChatResponse)
async def assistant_chat(
    request: InteractiveChatRequest,
    session: tuple[str, CustomerProfile] = Depends(get_current_session),
) -> InteractiveChatResponse:
    session_token, current_customer = session
    memory = get_session_memory(session_token)
    return await handle_interactive_chat(session_token, current_customer, memory, request)


@app.post("/api/me/assistant/upload", response_model=InteractiveChatResponse)
async def assistant_upload(
    request: InteractiveUploadRequest,
    session: tuple[str, CustomerProfile] = Depends(get_current_session),
) -> InteractiveChatResponse:
    session_token, current_customer = session
    memory = get_session_memory(session_token)
    return handle_interactive_upload(current_customer, memory, request)


@app.get("/api/agent/logs")
async def agent_logs(current_customer: CustomerProfile = Depends(get_current_customer)) -> StreamingResponse:
    return StreamingResponse(log_bus.stream(current_customer.id), media_type="text/event-stream")


@app.post("/api/voice/session")
async def voice_session() -> dict:
    session = await create_realtime_session()
    return session.model_dump(mode="json")
