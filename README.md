# AI Customer Support Refund Agent

This project is a full-stack demo for an AI customer support agent that evaluates e-commerce refund requests. It uses deterministic policy tools for the actual approve, deny, or escalate decision, optional LLM wording for customer-facing replies, customer-scoped login, and live reasoning logs.

## Stack

- Backend: FastAPI, Pydantic, LangGraph-ready workflow, optional LangChain OpenAI
- Frontend: Vite, React, TypeScript
- Data: multi-table SQLite CRM database plus a strict refund policy document indexed for RAG
- Voice: OpenAI Realtime session endpoint plus browser microphone/WebRTC UI

## Project Structure

```text
backend/
  app/
    agent/          # refund workflow and deterministic tools
    data/           # generated SQLite DB, policy document, and local policy index
    db/             # schema, connection helpers, and seed data
    rag/            # policy chunking and retrieval
    services/       # reasoning log bus and OpenAI Realtime helper
    main.py         # FastAPI entry point
frontend/
  src/
    components/     # chat, voice, and admin dashboard
    lib/api.ts      # API client and SSE subscription
```

## Backend Setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
python -m app.db.seed
uvicorn app.main:app --reload
```

The API will run on `http://localhost:8000`. The app also initializes and seeds SQLite on startup when the configured database is empty.

## Database Architecture

SQLite stores customer and transaction facts in normalized tables:

```text
Customer
   |-- Orders
   |     |-- OrderItem
   |           |-- Product
   |-- ReturnRequest
   |     |-- Evidence
   |-- RefundHistory
   |-- FraudAssessment
   |-- AgentDecisionLog
```

The seed dataset includes:

- 15 customers
- 25 products
- 40 orders
- 15 return requests
- 20 refund history records
- 15 fraud assessments

The runtime SQLite database is generated at `backend/app/data/refund_agent.sqlite` by default. Set `SQLITE_DB_PATH` in `backend/.env` to override it.

## Frontend Setup

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

The app will run on `http://localhost:5173`.

## Demo Login

Customers sign in with their seeded email address and the shared demo password:

```text
12345678
```

Example account:

```text
avery.stone@mailinator.com
```

Admin dashboard account:

```text
admin@mailinator.com
```

After login, the customer portal only requests and renders that customer's profile, purchased products, KPIs, and scoped AI chat context. The backend validates every scoped chat request against the logged-in customer's token, so an order belonging to another customer is rejected. Policy document retrieval remains global and shared for all customers.

After login with `admin@mailinator.com`, the frontend routes to the admin dashboard instead of the customer portal. Admin sessions can subscribe to the global real-time agent reasoning stream, while customer sessions only receive log events scoped to their own customer ID. Admins can also review open return requests on the **Active Tickets** tab and approve or reject refunds; customers see the decision on their Active Tickets page.

## OpenAI Configuration

The text refund decision works without an API key because policy enforcement is deterministic. Customer facts come from SQLite, and policy context comes from the local RAG index over `backend/app/data/refund_policy.md`.

Add `OPENAI_API_KEY` in `backend/.env` to enable:

- LLM rewriting of customer-facing refund replies.
- OpenAI Realtime voice sessions through `POST /api/voice/session`.

The voice component uses an ephemeral Realtime client secret from the backend, connects the browser microphone to OpenAI over WebRTC, and submits the transcript to the same refund policy agent.

## Demo Scenarios

- `cus_1001` / `ord_5001`: opened apparel, gold customer, inside window, should approve.
- `cus_1002` / `ord_5002`: unopened item outside standard 30 day window, should deny.
- `cus_1003` / `ord_5003`: fraud flag, should escalate.
- `cus_1005` / `ord_5005`: final sale item, should deny.
- `cus_1009` / `ord_5009`: amount above $500, should escalate.
- `cus_1012` / `ord_5012`: carrier-damaged item, should approve.

## Key Endpoints

- `GET /api/health`
- `POST /api/auth/login`
- `GET /api/me`
- `GET /api/customers`
- `GET /api/customers/{customer_id}`
- `GET /api/policy`
- `GET /api/policy/search?q=refund`
- `GET /api/return-requests`
- `GET /api/decisions`
- `POST /api/chat`
- `POST /api/me/chat`
- `GET /api/agent/logs`
- `POST /api/voice/session`

Example chat request:

```json
{
  "order_id": "ord_5001",
  "message": "I would like a refund for this order."
}
```

## Notes

The refund decision is deliberately not left to the LLM. The agent calls tools for customer lookup, order lookup, order items, refund history, fraud assessment, policy retrieval, return-window validation, item condition validation, loyalty checks, fraud checks, and refund-limit checks. The admin dashboard streams those tool calls, retrieved policy sections, and the final decision in real time. Final decisions are persisted in `AgentDecisionLog` for audit.
