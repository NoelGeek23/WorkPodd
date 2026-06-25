import { useEffect, useMemo, useRef, useState } from "react";
import BrandLogo from "./BrandLogo";
import AdminActiveTickets from "./AdminActiveTickets";
import { AdminProfile, AgentLogEvent, subscribeToAgentLogs } from "../lib/api";

type Props = {
  token: string;
  admin: AdminProfile;
  onLogout: () => void | Promise<void>;
};

function stageLabel(stage: string): string {
  return stage
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function stageClass(stage: string): string {
  return stage.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

type AdminTab = "reasoning" | "tickets";

export default function AdminDashboard({ token, admin, onLogout }: Props) {
  const [activeTab, setActiveTab] = useState<AdminTab>("reasoning");
  const [logs, setLogs] = useState<AgentLogEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const [stageFilter, setStageFilter] = useState("all");
  const [customerFilter, setCustomerFilter] = useState("");
  const [orderFilter, setOrderFilter] = useState("");
  const pausedRef = useRef(false);

  const stageOptions = useMemo(
    () => Array.from(new Set(logs.map((log) => log.stage))).sort(),
    [logs],
  );

  const filteredLogs = useMemo(
    () =>
      logs.filter((log) => {
        const customerMatch =
          !customerFilter ||
          (log.customer_id ?? "").toLowerCase().includes(customerFilter.toLowerCase());
        const orderMatch =
          !orderFilter || (log.order_id ?? "").toLowerCase().includes(orderFilter.toLowerCase());
        const stageMatch = stageFilter === "all" || log.stage === stageFilter;
        return customerMatch && orderMatch && stageMatch;
      }),
    [customerFilter, logs, orderFilter, stageFilter],
  );

  const toolCallCount = logs.filter((log) => log.stage === "tool_call").length;
  const decisionCount = logs.filter((log) => log.stage === "decision").length;
  const uniqueCustomerCount = new Set(logs.map((log) => log.customer_id).filter(Boolean)).size;

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    if (!token) {
      return undefined;
    }

    const source = subscribeToAgentLogs((event) => {
      if (!pausedRef.current) {
        setLogs((current) => [event, ...current].slice(0, 120));
      }
    }, token);

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);

    return () => source.close();
  }, [token]);

  return (
    <main className="admin-shell">
      <header className="admin-hero panel">
        <div className="admin-brand-block">
          <BrandLogo compact />
          <div>
            <p className="eyebrow">Admin Dashboard</p>
            <h1>{activeTab === "reasoning" ? "Real-Time Agent Reasoning" : "Return Request Review"}</h1>
            <p className="topbar-subtitle">
              {activeTab === "reasoning"
                ? "Monitor interactive support intent routing, ticket workflows, policy retrieval, tool calls, and final refund decisions as they happen."
                : "Review open customer return requests and approve or reject refunds with clear customer-facing messaging."}
            </p>
          </div>
        </div>

        <div className="admin-session-card">
          <nav className="admin-tabs" aria-label="Admin sections">
            <button
              type="button"
              className={activeTab === "reasoning" ? "active" : ""}
              onClick={() => setActiveTab("reasoning")}
            >
              Agent Logs
            </button>
            <button
              type="button"
              className={activeTab === "tickets" ? "active" : ""}
              onClick={() => setActiveTab("tickets")}
            >
              Active Tickets
            </button>
          </nav>
          <span className={`connection-pill ${connected ? "connected" : ""}`}>
            {connected ? "Live stream connected" : "Waiting for stream"}
          </span>
          <strong>{admin.name}</strong>
          <span>{admin.email}</span>
          <button type="button" className="secondary-button" onClick={() => void onLogout()}>
            Sign out
          </button>
        </div>
      </header>

      {activeTab === "tickets" ? (
        <AdminActiveTickets token={token} />
      ) : (
        <>
      <section className="metric-row">
        <article className="metric-card">
          <span>Total Events</span>
          <strong>{logs.length}</strong>
          <small>Recent in-memory stream</small>
        </article>
        <article className="metric-card">
          <span>Tool Calls</span>
          <strong>{toolCallCount}</strong>
          <small>Policy and CRM tools</small>
        </article>
        <article className="metric-card">
          <span>Decisions</span>
          <strong>{decisionCount}</strong>
          <small>Final refund outcomes</small>
        </article>
        <article className="metric-card">
          <span>Customers</span>
          <strong>{uniqueCustomerCount}</strong>
          <small>Seen in this session</small>
        </article>
      </section>

      <section className="panel admin-log-panel">
        <div className="panel-heading admin-log-heading">
        <div>
            <p className="eyebrow">Reasoning Stream</p>
            <h2>Live agent events</h2>
            <p className="muted">
              Showing {filteredLogs.length} of {logs.length} events.
            </p>
        </div>
          <div className="admin-log-actions">
            <button type="button" className="secondary-button" onClick={() => setPaused((value) => !value)}>
              {paused ? "Resume stream" : "Pause stream"}
            </button>
            <button type="button" className="ghost-button" onClick={() => setLogs([])}>
              Clear
            </button>
          </div>
      </div>

        <div className="admin-filters">
          <label>
            Stage
            <select value={stageFilter} onChange={(event) => setStageFilter(event.target.value)}>
              <option value="all">All stages</option>
              {stageOptions.map((stage) => (
                <option key={stage} value={stage}>
                  {stageLabel(stage)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Customer
            <input
              value={customerFilter}
              onChange={(event) => setCustomerFilter(event.target.value)}
              placeholder="cus_1001"
            />
          </label>
          <label>
            Order
            <input
              value={orderFilter}
              onChange={(event) => setOrderFilter(event.target.value)}
              placeholder="ord_5001"
            />
          </label>
        </div>

        <div className="log-stream">
          {filteredLogs.length === 0 ? (
          <div className="empty-state">
              Reasoning logs will appear here when customers use the assistant.
          </div>
        ) : (
            filteredLogs.map((log) => (
              <article key={log.id} className={`log-card stage-${stageClass(log.stage)}`}>
              <div className="log-header">
                  <strong>{stageLabel(log.stage)}</strong>
                <time>{new Date(log.timestamp).toLocaleTimeString()}</time>
              </div>
              <p>{log.message}</p>
              <div className="log-meta">
                  <span>Customer: {log.customer_id ?? "Global"}</span>
                  <span>Order: {log.order_id ?? "None"}</span>
              </div>
              {Object.keys(log.metadata).length > 0 ? (
                <details>
                  <summary>Metadata</summary>
                  <pre>{JSON.stringify(log.metadata, null, 2)}</pre>
                </details>
              ) : null}
            </article>
          ))
        )}
      </div>
      </section>
        </>
      )}
    </main>
  );
}
