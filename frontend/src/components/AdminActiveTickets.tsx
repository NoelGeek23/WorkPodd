import { useEffect, useState } from "react";
import {
  AdminTicket,
  approveAdminTicket,
  getAdminTickets,
  rejectAdminTicket,
} from "../lib/api";
import TicketEvidenceGallery from "./TicketEvidenceGallery";

type Props = {
  token: string;
};

function formatRiskLevel(level: string | null | undefined): string {
  if (!level) {
    return "Unknown";
  }
  return level.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatRefundOutcome(outcome: string | null | undefined): string {
  if (!outcome) {
    return "Unknown";
  }
  return outcome.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function AdminActiveTickets({ token }: Props) {
  const [tickets, setTickets] = useState<AdminTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actingOn, setActingOn] = useState("");
  const [rejectReasons, setRejectReasons] = useState<Record<string, string>>({});

  async function loadTickets() {
    setLoading(true);
    setError("");
    try {
      setTickets(await getAdminTickets(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load tickets");
      setTickets([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadTickets();
  }, [token]);

  async function approve(ticket: AdminTicket) {
    setActingOn(ticket.request_id);
    setError("");
    try {
      await approveAdminTicket(token, ticket.request_id);
      await loadTickets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not approve ticket");
    } finally {
      setActingOn("");
    }
  }

  async function reject(ticket: AdminTicket) {
    const reason = (rejectReasons[ticket.request_id] ?? "").trim();
    if (!reason) {
      setError("Enter a rejection reason before denying a return request.");
      return;
    }

    setActingOn(ticket.request_id);
    setError("");
    try {
      await rejectAdminTicket(token, ticket.request_id, reason);
      setRejectReasons((current) => {
        const next = { ...current };
        delete next[ticket.request_id];
        return next;
      });
      await loadTickets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reject ticket");
    } finally {
      setActingOn("");
    }
  }

  const pendingCount = tickets.filter((ticket) => ticket.status === "Pending").length;
  const reviewCount = tickets.filter((ticket) =>
    ["Manual Review", "Manager Review"].includes(ticket.status),
  ).length;
  const fraudCount = tickets.filter((ticket) => ticket.fraud_flagged).length;

  return (
    <div className="page-stack">
      <section className="metric-row">
        <article className="metric-card">
          <span>Awaiting Decision</span>
          <strong>{tickets.length}</strong>
          <small>Open return requests</small>
        </article>
        <article className="metric-card">
          <span>Pending</span>
          <strong>{pendingCount}</strong>
          <small>Standard queue</small>
        </article>
        <article className="metric-card">
          <span>In Review</span>
          <strong>{reviewCount}</strong>
          <small>Needs specialist review</small>
        </article>
        <article className="metric-card">
          <span>Fraud Flagged</span>
          <strong>{fraudCount}</strong>
          <small>High or critical risk</small>
        </article>
      </section>

      <section className="panel admin-tickets-panel">
        <div className="panel-heading admin-log-heading">
          <div>
            <p className="eyebrow">Returns Queue</p>
            <h2>Active return requests</h2>
            <p className="muted">
              Approve or reject customer return tickets. Each ticket includes AI reasoning from the refund rule
              engine and anti-fraud policy engine when available.
            </p>
          </div>
          <button type="button" className="secondary-button" onClick={() => void loadTickets()} disabled={loading}>
            Refresh
          </button>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}

        {loading ? (
          <p className="muted">Loading tickets...</p>
        ) : tickets.length === 0 ? (
          <div className="empty-state">No return requests are waiting for admin review.</div>
        ) : (
          <div className="ticket-grid">
            {tickets.map((ticket) => (
              <article
                key={ticket.request_id}
                className={`ticket-card admin-ticket-card ${ticket.fraud_flagged ? "fraud-flagged" : ""}`}
              >
                <div className="ticket-card-header">
                  <strong>{ticket.request_id}</strong>
                  <div className="ticket-header-badges">
                    {ticket.fraud_flagged ? (
                      <span className={`fraud-risk-badge ${(ticket.fraud_risk_level ?? "high").toLowerCase()}`}>
                        Fraud · {formatRiskLevel(ticket.fraud_risk_level)}
                      </span>
                    ) : null}
                    <span className={`ticket-status ${ticket.status.toLowerCase().replace(/\s+/g, "-")}`}>
                      {ticket.status}
                    </span>
                  </div>
                </div>
                <span>{ticket.customer_name} · {ticket.customer_email}</span>
                <span>{ticket.product_names || "Order items"}</span>
                <span>Customer: {ticket.customer_id}</span>
                <span>Order: {ticket.order_id}</span>
                <span>Requested: {ticket.request_date}</span>
                <span>Reason: {ticket.reason}</span>
                <span>Order value: ${ticket.total_amount.toFixed(2)}</span>
                {ticket.refund_evaluated ? (
                  <div className="refund-assessment-panel">
                    <div className="refund-assessment-header">
                      <strong>AI Reasoning for Refund</strong>
                      <span>{formatRefundOutcome(ticket.refund_outcome)}</span>
                    </div>
                    {ticket.refund_reasoning ? (
                      <pre className="refund-reasoning">{ticket.refund_reasoning}</pre>
                    ) : null}
                    {ticket.refund_signals && ticket.refund_signals.length > 0 ? (
                      <details className="refund-signals-details">
                        <summary>Triggered refund rules ({ticket.refund_signals.length})</summary>
                        <ul>
                          {ticket.refund_signals.map((signal) => (
                            <li key={signal.rule_id}>
                              <strong>{signal.category}</strong>: {signal.description} ({signal.outcome})
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                    {ticket.refund_policy_citations && ticket.refund_policy_citations.length > 0 ? (
                      <details className="refund-policy-details">
                        <summary>Refund policy citations</summary>
                        {ticket.refund_policy_citations.map((section) => (
                          <article
                            key={String(section.chunk_id ?? section.section_title)}
                            className="refund-policy-citation"
                          >
                            <strong>{section.section_title}</strong>
                            <p>{section.content.split("\n")[0]}</p>
                          </article>
                        ))}
                      </details>
                    ) : null}
                  </div>
                ) : null}
                {ticket.fraud_flagged ? (
                  <div className="fraud-assessment-panel">
                    <div className="fraud-assessment-header">
                      <strong>Anti-Fraud Assessment</strong>
                      <span>
                        Score {ticket.fraud_score ?? 0}/100 · {formatRiskLevel(ticket.fraud_risk_level)}
                      </span>
                    </div>
                    {ticket.fraud_reasoning ? (
                      <pre className="fraud-reasoning">{ticket.fraud_reasoning}</pre>
                    ) : null}
                    {ticket.fraud_signals && ticket.fraud_signals.length > 0 ? (
                      <details className="fraud-signals-details">
                        <summary>Triggered rules ({ticket.fraud_signals.length})</summary>
                        <ul>
                          {ticket.fraud_signals.map((signal) => (
                            <li key={signal.rule_id}>
                              <strong>{signal.category}</strong>: {signal.description} (+{signal.score_delta})
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                    {ticket.fraud_policy_citations && ticket.fraud_policy_citations.length > 0 ? (
                      <details className="fraud-policy-details">
                        <summary>Policy citations</summary>
                        {ticket.fraud_policy_citations.map((section) => (
                          <article key={String(section.chunk_id ?? section.section_title)} className="fraud-policy-citation">
                            <strong>{section.section_title}</strong>
                            <p>{section.content.split("\n")[0]}</p>
                          </article>
                        ))}
                      </details>
                    ) : null}
                  </div>
                ) : null}
                {ticket.customer_comment ? (
                  <p className="ticket-comment">{ticket.customer_comment}</p>
                ) : (
                  <small className="muted">No customer description provided.</small>
                )}
                {ticket.evidence.length > 0 ? (
                  <TicketEvidenceGallery evidence={ticket.evidence} token={token} title="Evidence" />
                ) : null}
                <label className="ticket-edit-field">
                  Rejection reason
                  <textarea
                    value={rejectReasons[ticket.request_id] ?? ""}
                    onChange={(event) =>
                      setRejectReasons((current) => ({
                        ...current,
                        [ticket.request_id]: event.target.value,
                      }))
                    }
                    rows={3}
                    placeholder="Required if rejecting. Example: Item is outside the 30-day return window."
                  />
                </label>
                <div className="ticket-actions">
                  <button
                    type="button"
                    className="primary-button ticket-save-button"
                    disabled={actingOn === ticket.request_id}
                    onClick={() => void approve(ticket)}
                  >
                    {actingOn === ticket.request_id ? "Processing..." : "Accept refund"}
                  </button>
                  <button
                    type="button"
                    className="ghost-button ticket-cancel-button"
                    disabled={actingOn === ticket.request_id}
                    onClick={() => void reject(ticket)}
                  >
                    Reject refund
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
