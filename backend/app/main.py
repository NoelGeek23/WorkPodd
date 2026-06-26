from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from app.agent.graph import build_langgraph_definition, run_refund_agent
from app.agent.prescreen_graph import build_prescreen_langgraph_definition
from app.agent.interactive import handle_interactive_chat, handle_interactive_upload
from app.agent.session_memory import clear_session_memory, get_session_memory
from app.agent.tools import find_customer, load_policy
from app.db.database import get_connection, has_seed_data, initialize_schema, rows_to_dicts
from app.db.seed import seed_demo_data
from app.models import (
    AdminTicketRejectRequest,
    ChatRequest,
    ChatResponse,
    CustomerProfile,
    InteractiveChatRequest,
    InteractiveChatResponse,
    InteractiveUploadRequest,
    LoginRequest,
    LoginResponse,
    RefundDecision,
    ScopedChatRequest,
    TicketUpdateRequest,
    VoiceConnectRequest,
    VoiceConnectResponse,
)
from app.rag.fraud_index import ensure_fraud_index
from app.rag.policy_index import ensure_policy_index
from app.rag.refund_policy_index import ensure_refund_policy_index
from app.services.customer_decisions import public_refund_decision
from app.services.evidence_store import get_evidence_file, persist_ticket_evidence
from app.services.log_bus import log_bus
from app.services.refund_decisions import apply_refund_decision, approval_message
from app.services.realtime import connect_realtime_call, create_realtime_session

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
ensure_fraud_index()
ensure_refund_policy_index()

_compiled_langgraph = build_langgraph_definition()
_compiled_prescreen_langgraph = build_prescreen_langgraph_definition()
DEMO_PASSWORD = "12345678"
ADMIN_EMAIL = "admin@mailinator.com"
SESSIONS: dict[str, dict[str, str]] = {}


def _customer_response(customer: CustomerProfile) -> dict:
    return {
        "id": customer.id,
        "role": "customer",
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
                "shipping_country": order.shipping_country,
                "items": [item.model_dump() for item in order.items],
            }
            for order in customer.orders
        ],
    }


def _admin_response() -> dict:
    return {
        "id": "admin",
        "role": "admin",
        "name": "Shopward Admin",
        "email": ADMIN_EMAIL,
        "loyalty_tier": "admin",
        "fraud_flag": False,
        "chargeback_count": 0,
        "refund_count_last_12_months": 0,
        "lifetime_value": 0,
        "notes": "Real-time support operations dashboard.",
        "orders": [],
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


def get_current_session_record(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> tuple[str, dict[str, str]]:
    session_token = _extract_session_token(authorization, token)
    session_record = SESSIONS.get(session_token)
    if not session_record:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return session_token, session_record


def get_current_customer(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> CustomerProfile:
    _session_token, session_record = get_current_session_record(authorization, token)
    if session_record.get("role") != "customer":
        raise HTTPException(status_code=403, detail="Customer session required")

    customer_id = session_record["id"]
    customer = find_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=401, detail="Session customer no longer exists")
    return customer


def get_current_session(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> tuple[str, CustomerProfile]:
    session_token, session_record = get_current_session_record(authorization, token)
    if session_record.get("role") != "customer":
        raise HTTPException(status_code=403, detail="Customer session required")

    customer_id = session_record["id"]
    customer = find_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=401, detail="Session customer no longer exists")
    return session_token, customer


def get_current_admin(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, str]:
    _session_token, session_record = get_current_session_record(authorization, token)
    if session_record.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin session required")
    return session_record


def _attach_ticket_evidence(connection, tickets: list[dict]) -> None:
    for ticket in tickets:
        evidence_rows = connection.execute(
            """
            SELECT evidence_id, type, file_path, content_type, verified, uploaded_date
            FROM Evidence
            WHERE request_id = ?
            ORDER BY uploaded_date DESC, evidence_id
            """,
            (ticket["request_id"],),
        ).fetchall()
        ticket["evidence"] = rows_to_dicts(evidence_rows)


def _attach_fraud_assessments(connection, tickets: list[dict]) -> None:
    import json

    for ticket in tickets:
        row = connection.execute(
            """
            SELECT fraud_score, risk_level, is_fraud_flagged, signals_json, reasoning, policy_sections_json
            FROM FraudDetectionRun
            WHERE request_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (ticket["request_id"],),
        ).fetchone()
        if not row:
            ticket["fraud_flagged"] = False
            ticket["fraud_score"] = None
            ticket["fraud_risk_level"] = None
            ticket["fraud_reasoning"] = None
            ticket["fraud_signals"] = []
            ticket["fraud_policy_citations"] = []
            continue
        ticket["fraud_flagged"] = bool(row["is_fraud_flagged"])
        ticket["fraud_score"] = int(row["fraud_score"])
        ticket["fraud_risk_level"] = row["risk_level"]
        ticket["fraud_reasoning"] = row["reasoning"]
        ticket["fraud_signals"] = json.loads(row["signals_json"] or "[]")
        ticket["fraud_policy_citations"] = json.loads(row["policy_sections_json"] or "[]")


def _attach_refund_evaluations(connection, tickets: list[dict]) -> None:
    import json

    for ticket in tickets:
        row = connection.execute(
            """
            SELECT outcome, reasoning, signals_json, policy_sections_json,
                   customer_reason, customer_description
            FROM RefundEvaluationRun
            WHERE request_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (ticket["request_id"],),
        ).fetchone()
        if not row:
            ticket["refund_evaluated"] = False
            ticket["refund_outcome"] = None
            ticket["refund_reasoning"] = None
            ticket["refund_signals"] = []
            ticket["refund_policy_citations"] = []
            continue
        ticket["refund_evaluated"] = True
        ticket["refund_outcome"] = row["outcome"]
        ticket["refund_reasoning"] = row["reasoning"]
        ticket["refund_signals"] = json.loads(row["signals_json"] or "[]")
        ticket["refund_policy_citations"] = json.loads(row["policy_sections_json"] or "[]")


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "langgraph_available": _compiled_langgraph is not None,
        "prescreen_langgraph_available": _compiled_prescreen_langgraph is not None,
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "database_ready": has_seed_data(),
    }


@app.post("/api/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    if request.password != DEMO_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    email = request.email.strip().lower()
    if email == ADMIN_EMAIL:
        token = uuid4().hex
        SESSIONS[token] = {"role": "admin", "id": "admin"}
        return LoginResponse(token=token, role="admin", customer=_admin_response())

    customer = _find_customer_by_email(request.email)
    if not customer:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = uuid4().hex
    SESSIONS[token] = {"role": "customer", "id": customer.id}
    return LoginResponse(token=token, role="customer", customer=_customer_response(customer))


@app.post("/api/auth/logout")
async def logout(session: tuple[str, dict[str, str]] = Depends(get_current_session_record)) -> dict:
    session_token, _session_record = session
    clear_session_memory(session_token)
    SESSIONS.pop(session_token, None)
    return {"status": "ok"}


@app.get("/api/me")
async def me(session: tuple[str, dict[str, str]] = Depends(get_current_session_record)) -> dict:
    _session_token, session_record = session
    if session_record.get("role") == "admin":
        return _admin_response()

    customer = find_customer(session_record["id"])
    if not customer:
        raise HTTPException(status_code=401, detail="Session customer no longer exists")
    return _customer_response(customer)


@app.get("/api/me/tickets")
async def my_tickets(customer: CustomerProfile = Depends(get_current_customer)) -> dict:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                rr.request_id,
                rr.order_id,
                rr.request_date,
                rr.reason,
                rr.customer_comment,
                rr.requested_resolution,
                rr.status,
                rr.admin_message,
                o.total_amount,
                GROUP_CONCAT(p.name, ', ') AS product_names
            FROM ReturnRequest rr
            JOIN Orders o ON rr.order_id = o.order_id
            LEFT JOIN OrderItem oi ON oi.order_id = o.order_id
            LEFT JOIN Product p ON p.product_id = oi.product_id
            WHERE rr.customer_id = ?
              AND rr.status NOT IN ('Closed')
            GROUP BY rr.request_id
            ORDER BY rr.request_date DESC, rr.request_id DESC
            """,
            (customer.id,),
        ).fetchall()
        tickets = rows_to_dicts(rows)
        _attach_ticket_evidence(connection, tickets)
    return {"tickets": tickets}


@app.put("/api/me/tickets/{request_id}")
async def update_my_ticket(
    request_id: str,
    request: TicketUpdateRequest,
    customer: CustomerProfile = Depends(get_current_customer),
) -> dict:
    with get_connection() as connection:
        ticket = connection.execute(
            """
            SELECT request_id
            FROM ReturnRequest
            WHERE request_id = ?
              AND customer_id = ?
              AND status IN ('Pending', 'Manual Review', 'Manager Review')
            """,
            (request_id, customer.id),
        ).fetchone()
        if not ticket:
            raise HTTPException(status_code=404, detail="Active ticket not found")

        if request.description is not None:
            connection.execute(
                """
                UPDATE ReturnRequest
                SET customer_comment = ?
                WHERE request_id = ?
                  AND customer_id = ?
                """,
                (request.description.strip(), request_id, customer.id),
            )

        if request.files:
            persist_ticket_evidence(connection, request_id, request.files)
    return {"status": "ok"}


@app.get("/api/evidence/{evidence_id}")
async def get_evidence_file_endpoint(
    evidence_id: str,
    session: tuple[str, dict[str, str]] = Depends(get_current_session_record),
) -> FileResponse:
    _session_token, session_record = session
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT e.evidence_id, e.content_type, rr.customer_id
            FROM Evidence e
            JOIN ReturnRequest rr ON e.request_id = rr.request_id
            WHERE e.evidence_id = ?
            """,
            (evidence_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Evidence not found")

    if session_record.get("role") != "admin" and row["customer_id"] != session_record["id"]:
        raise HTTPException(status_code=403, detail="Cannot access another customer's evidence")

    stored = get_evidence_file(evidence_id)
    if not stored:
        raise HTTPException(status_code=404, detail="Evidence file not found")

    path, guessed_type = stored
    media_type = row["content_type"] or guessed_type
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.post("/api/me/tickets/{request_id}/cancel")
async def cancel_my_ticket(
    request_id: str,
    customer: CustomerProfile = Depends(get_current_customer),
) -> dict:
    with get_connection() as connection:
        ticket = connection.execute(
            """
            SELECT request_id
            FROM ReturnRequest
            WHERE request_id = ?
              AND customer_id = ?
              AND status IN ('Pending', 'Manual Review', 'Manager Review')
            """,
            (request_id, customer.id),
        ).fetchone()
        if not ticket:
            raise HTTPException(status_code=404, detail="Active ticket not found")

        connection.execute(
            """
            UPDATE ReturnRequest
            SET status = 'Closed'
            WHERE request_id = ?
              AND customer_id = ?
            """,
            (request_id, customer.id),
        )
    return {"status": "ok"}


@app.get("/api/admin/tickets")
async def admin_tickets(_admin: dict[str, str] = Depends(get_current_admin)) -> dict:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                rr.request_id,
                rr.customer_id,
                rr.order_id,
                rr.request_date,
                rr.reason,
                rr.customer_comment,
                rr.requested_resolution,
                rr.status,
                rr.admin_message,
                o.total_amount,
                c.name AS customer_name,
                c.email AS customer_email,
                GROUP_CONCAT(p.name, ', ') AS product_names
            FROM ReturnRequest rr
            JOIN Customer c ON rr.customer_id = c.customer_id
            JOIN Orders o ON rr.order_id = o.order_id
            LEFT JOIN OrderItem oi ON oi.order_id = o.order_id
            LEFT JOIN Product p ON p.product_id = oi.product_id
            WHERE rr.status IN ('Pending', 'Manual Review', 'Manager Review')
            GROUP BY rr.request_id
            ORDER BY rr.request_date DESC, rr.request_id DESC
            """
        ).fetchall()
        tickets = rows_to_dicts(rows)
        _attach_ticket_evidence(connection, tickets)
        _attach_fraud_assessments(connection, tickets)
        _attach_refund_evaluations(connection, tickets)
    return {"tickets": tickets}


@app.post("/api/admin/tickets/{request_id}/approve")
async def approve_admin_ticket(
    request_id: str,
    _admin: dict[str, str] = Depends(get_current_admin),
) -> dict:
    with get_connection() as connection:
        ticket = connection.execute(
            """
            SELECT rr.request_id, rr.customer_id, rr.order_id, rr.reason, o.total_amount
            FROM ReturnRequest rr
            JOIN Orders o ON rr.order_id = o.order_id
            WHERE rr.request_id = ?
              AND rr.status IN ('Pending', 'Manual Review', 'Manager Review')
            """,
            (request_id,),
        ).fetchone()
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found or already decided")

    refund_amount = float(ticket["total_amount"])
    decision = RefundDecision(
        status="approved",
        customer_message=approval_message(refund_amount),
        internal_reason="Admin approved the return request.",
        amount=refund_amount,
        order_id=ticket["order_id"],
        policy_rules=["Admin manual approval"],
    )
    await apply_refund_decision(
        decision=decision,
        customer_id=ticket["customer_id"],
        order_id=ticket["order_id"],
        request_id=request_id,
        actor="admin",
    )

    await log_bus.publish(
        "admin_decision",
        f"Admin approved return request {request_id}.",
        customer_id=ticket["customer_id"],
        order_id=ticket["order_id"],
        metadata={"request_id": request_id, "status": "Approved", "refund_amount": refund_amount},
    )
    return {"status": "ok", "request_id": request_id}


@app.post("/api/admin/tickets/{request_id}/reject")
async def reject_admin_ticket(
    request_id: str,
    request: AdminTicketRejectRequest,
    _admin: dict[str, str] = Depends(get_current_admin),
) -> dict:
    reason = request.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Rejection reason is required")

    with get_connection() as connection:
        ticket = connection.execute(
            """
            SELECT request_id, customer_id, order_id
            FROM ReturnRequest
            WHERE request_id = ?
              AND status IN ('Pending', 'Manual Review', 'Manager Review')
            """,
            (request_id,),
        ).fetchone()
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found or already decided")

    decision = RefundDecision(
        status="denied",
        customer_message=reason,
        internal_reason=reason,
        amount=0,
        order_id=ticket["order_id"],
        policy_rules=["Admin manual rejection"],
    )
    await apply_refund_decision(
        decision=decision,
        customer_id=ticket["customer_id"],
        order_id=ticket["order_id"],
        request_id=request_id,
        actor="admin",
    )

    await log_bus.publish(
        "admin_decision",
        f"Admin rejected return request {request_id}.",
        customer_id=ticket["customer_id"],
        order_id=ticket["order_id"],
        metadata={"request_id": request_id, "status": "Denied", "reason": reason},
    )
    return {"status": "ok", "request_id": request_id}


@app.post("/api/me/assistant/restart")
async def restart_assistant(
    session: tuple[str, CustomerProfile] = Depends(get_current_session),
) -> dict:
    session_token, _customer = session
    clear_session_memory(session_token)
    return {"status": "ok"}


@app.get("/api/me/assistant/session")
async def assistant_session(
    session: tuple[str, CustomerProfile] = Depends(get_current_session),
) -> dict:
    session_token, _customer = session
    memory = get_session_memory(session_token)
    return {
        "messages": [{"role": message.role, "content": message.content} for message in memory.messages],
        "actions": [],
        "decision": None,
    }


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
    from app.rag.policy_index import filter_customer_policy_sections, load_policy, chunk_policy

    visible_chunks = filter_customer_policy_sections(
        [{"section_title": chunk["section_title"], "content": chunk["content"]} for chunk in chunk_policy(load_policy())]
    )
    policy_text = "\n\n".join(
        f"## {chunk['section_title']}\n{chunk['content']}" for chunk in visible_chunks
    )
    return {"policy": policy_text}


@app.get("/api/policy/search")
async def policy_search(q: str) -> dict:
    from app.rag.policy_index import retrieve_customer_policy_sections

    return {"query": q, "sections": retrieve_customer_policy_sections(q)}


@app.get("/api/policy/sections")
async def policy_sections() -> dict:
    from app.rag.policy_index import is_customer_visible_policy_section

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT chunk_id, section_title, content
            FROM PolicyChunk
            ORDER BY chunk_id
            """
        ).fetchall()
    sections = [
        row
        for row in rows_to_dicts(rows)
        if is_customer_visible_policy_section(str(row.get("section_title", "")))
    ]
    return {"sections": sections}


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
    _, decision = await apply_refund_decision(
        decision=decision,
        customer_id=current_customer.id,
        order_id=resolved_order_id,
        actor="agent",
    )
    public = public_refund_decision(decision)
    return ChatResponse(reply=public.customer_message, decision=public)


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
    _, decision = await apply_refund_decision(
        decision=decision,
        customer_id=current_customer.id,
        order_id=resolved_order_id,
        actor="agent",
    )
    public = public_refund_decision(decision)
    return ChatResponse(reply=public.customer_message, decision=public)


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
    return await handle_interactive_upload(current_customer, memory, request)


@app.get("/api/agent/logs")
async def agent_logs(session: tuple[str, dict[str, str]] = Depends(get_current_session_record)) -> StreamingResponse:
    _session_token, session_record = session
    if session_record.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin session required")
    return StreamingResponse(log_bus.stream(None), media_type="text/event-stream")


@app.post("/api/voice/session")
async def voice_session() -> dict:
    session = await create_realtime_session()
    return session.model_dump(mode="json")


@app.post("/api/voice/connect")
async def voice_connect(body: VoiceConnectRequest) -> VoiceConnectResponse:
    result = await connect_realtime_call(body.sdp)
    if not result.sdp:
        raise HTTPException(status_code=502, detail=result.error or "Realtime connection failed.")
    return VoiceConnectResponse(sdp=result.sdp, model=result.model, voice=result.voice)
