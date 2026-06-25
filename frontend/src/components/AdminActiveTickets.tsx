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
      </section>

      <section className="panel admin-tickets-panel">
        <div className="panel-heading admin-log-heading">
          <div>
            <p className="eyebrow">Returns Queue</p>
            <h2>Active return requests</h2>
            <p className="muted">Approve or reject customer return tickets. Customers see your decision on their Active Tickets page.</p>
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
              <article key={ticket.request_id} className="ticket-card admin-ticket-card">
                <div className="ticket-card-header">
                  <strong>{ticket.request_id}</strong>
                  <span className={`ticket-status ${ticket.status.toLowerCase().replace(/\s+/g, "-")}`}>
                    {ticket.status}
                  </span>
                </div>
                <span>{ticket.customer_name} · {ticket.customer_email}</span>
                <span>{ticket.product_names || "Order items"}</span>
                <span>Customer: {ticket.customer_id}</span>
                <span>Order: {ticket.order_id}</span>
                <span>Requested: {ticket.request_date}</span>
                <span>Reason: {ticket.reason}</span>
                <span>Order value: ${ticket.total_amount.toFixed(2)}</span>
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
