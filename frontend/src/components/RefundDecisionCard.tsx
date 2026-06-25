import { RefundDecision } from "../lib/api";

type Props = {
  decision: RefundDecision;
};

export default function RefundDecisionCard({ decision }: Props) {
  return (
    <div className={`decision-card ${decision.status}`}>
      <div className="decision-card-header">
        <strong>{formatDecisionStatus(decision.status)}</strong>
        <span className="decision-card-meta">Order {decision.order_id}</span>
      </div>
      {decision.status === "approved" && decision.amount > 0 ? (
        <span className="decision-card-amount">${decision.amount.toFixed(2)} refund</span>
      ) : null}
      <p className="decision-card-summary">{decisionSummary(decision)}</p>
    </div>
  );
}

function formatDecisionStatus(status: string): string {
  switch (status.toLowerCase()) {
    case "approved":
      return "Approved";
    case "denied":
      return "Denied";
    case "manual_review":
    case "manager_review":
      return "Under review";
    default:
      return status.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
  }
}

function decisionSummary(decision: RefundDecision): string {
  if (decision.status === "approved") {
    return (
      `Your refund of $${decision.amount.toFixed(2)} has been approved. ` +
      "You'll see this order marked as returned in My Purchases."
    );
  }
  if (decision.status === "denied") {
    return (
      "We couldn't approve an automatic refund for this order. " +
      "See Active Tickets for details and support options."
    );
  }
  return "Your request needs a quick review. We'll follow up with you soon.";
}
