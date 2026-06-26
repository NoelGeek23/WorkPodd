# WorkPodd — Feature List

Shopward AI customer support and refund agent demo. Full-stack app with a customer portal, admin dashboard, deterministic policy engine, and LangGraph-ready agent workflows.

---

## Authentication & Access

- Email + password login for seeded demo customers (`12345678`)
- Separate **admin** login (`admin@mailinator.com`) routing to the operations dashboard
- Session tokens with scoped API access — customers only see their own profile, orders, tickets, and logs
- Logout and session restore for the interactive assistant

---

## Customer Portal

### Dashboard

- Personalized greeting and account KPIs (products, delivered orders, refund count)
- Interactive AI chat assistant on the home dashboard
- Sample policy prompt shortcut and **Restart chat** to reset the assistant session

### My Purchases

- Grid of all purchased products with SKU, order ID, price, and condition
- **Return window countdown** per item (days left, expired, or not eligible)
- VIP-aware windows (45-day vs 30-day standard)
- Visual status for returned items

### Active Tickets

- Open vs past ticket views with status metrics (Pending, In Review, Approved, Denied)
- Update ticket description and upload evidence on open requests
- Cancel eligible pending tickets from the portal
- Customer-facing decision banners (approved, denied, pending admin review)
- Evidence gallery for uploaded images

### Shopward Policies

- Browse indexed refund and return policy sections
- Expandable policy cards with section previews

---

## Interactive AI Assistant

### Conversation

- Natural-language chat for returns, orders, policy questions, and ticket management
- Intent routing: policy Q&A, purchase lookup, return flow, ticket cancel/list, conversational replies
- Optional OpenAI-powered small-talk when an API key is configured
- **Browser speech-to-text** microphone input for dictating messages
- Session memory across turns (selected order, reason, workflow state)

### Guided return flow

- Purchase picker for recent eligible orders
- **Pre-return prescreen** (LangGraph) before reason collection — blocks ineligible orders early
- Structured return reason options (defective, damaged packaging, wrong item, changed mind, missing parts, other)
- Conditional follow-ups: defect description, packaging/damage photos, wrong-item images
- **Refund decision card** with customer-safe outcome summary

### Policy answers (no return required)

- RAG-backed answers from `refund_policy.md` with citations
- Personalized **return-window countdown** by order when asked “how many days…”
- **VIP membership** answers using live account context
- VIP / return-window notes tailored to loyalty tier

---

## Refund & Return Processing

### LangGraph workflows

- **Refund Policy Agent** — full pipeline: CRM lookup → RAG → policy checks → decision → audit log
- **Return Prescreen Agent** — lightweight eligibility gate before a return is submitted
- Conditional routing when customer or order is missing (short-circuit to decision)
- Sequential fallback runner when LangGraph is not installed

### Deterministic policy tools

- Return window validation (30 / 45 VIP / 15 business / 20 international days)
- Item condition checks (final sale, digital, subscription, hygiene-sensitive, packaging, used items)
- Opened-item loyalty tier rules (Gold / Platinum / VIP)
- Refund frequency and dollar-volume limits
- Fraud flag and fraud-assessment escalation rules

### Decision outcomes

- **Approved** — passes all checks (agents escalate to admin; only admins finalize payment)
- **Denied** — policy violation with customer-safe messaging (no internal rule leakage)
- **Escalated** — manual or manager review (fraud, high value, lost shipments, etc.)

### Anti-fraud & refund engines

- Pre-graph **fraud scoring** (0–100) with risk levels (Low / Medium / High / Critical)
- RAG over `fraud_policy.md` for fraud reasoning and citations
- Separate **refund rule evaluation** engine with auditable signals
- Fraud-flagged requests blocked from automatic approval

### Evidence handling

- Image upload on tickets and in-chat (JPEG, PNG, etc., up to 5 MB)
- **OpenCV** blur and size checks
- Optional **OpenAI Vision** product/damage verification
- Retry flow with escalation to manual review after max failures

---

## Admin Dashboard

### Real-time reasoning stream

- Server-Sent Events (SSE) log feed for all agent activity
- Filter by stage, customer ID, and order ID
- Pause / resume stream; stage and decision counts
- Events include: `tool_call`, `policy_rag`, `fraud_scored`, `decision`, `prescreen`, `evidence_verification`, and more

### Active return tickets

- Queue of open return requests awaiting review
- **Approve** refunds — updates ticket, order status, and refund history
- **Reject** with required customer-facing rejection reason
- **AI Reasoning for Refund** panel (rule engine outcome, signals, policy citations)
- **Anti-Fraud Assessment** panel (score, risk level, triggered rules, policy citations)
- Evidence gallery per ticket

---

## Data & CRM

- Normalized **SQLite** database (customers, orders, products, return requests, evidence, refund history, fraud assessments, agent decision log)
- Seed script with 18 demo customers, 46 orders, and Loom-ready scenario accounts
- Chroma vector indexes for refund policy and fraud policy documents
- Audit trail via `AgentDecisionLog` and persisted fraud/refund evaluation runs

---

## API & Integrations

- REST API (FastAPI) for auth, chat, tickets, policy search, evidence, and admin actions
- Scoped endpoints: `/api/me/*` for customers, `/api/admin/*` for operators
- Direct refund chat: `POST /api/chat` and `POST /api/me/chat`
- Interactive assistant: `/api/me/assistant/chat`, `/api/me/assistant/upload`, session restore/restart
- Policy: `/api/policy`, `/api/policy/search`, `/api/policy/sections`
- Live logs: `GET /api/agent/logs` (SSE)
- **OpenAI Realtime voice** backend endpoints (`/api/voice/session`, `/api/voice/connect`) — WebRTC; requires API key
- Optional OpenAI for customer-facing reply polish and conversational fallback

---

## Developer & Demo Experience

- Hot-reload backend (Uvicorn) and frontend (Vite)
- Auto-seed on first startup when the database is empty
- Documented demo accounts for standard refund, policy denial, and fraud escalation
- Architecture docs: `LANGGRAPH_WORKFLOW.md`, `README.md`
