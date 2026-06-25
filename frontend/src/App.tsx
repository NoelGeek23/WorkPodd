import { useEffect, useState } from "react";
import ChatPanel from "./components/ChatPanel";
import AdminDashboard from "./components/AdminDashboard";
import BrandLogo from "./components/BrandLogo";
import LoginPage from "./components/LoginPage";
import PolicySectionContent from "./components/PolicySectionContent";
import TicketEvidenceGallery from "./components/TicketEvidenceGallery";
import TicketSupportFallback from "./components/TicketSupportFallback";
import VoicePanel from "./components/VoicePanel";
import {
  ActiveTicket,
  AssistantAction,
  AssistantMessage,
  CurrentUser,
  Customer,
  EvidenceUpload,
  PolicySection,
  RefundDecision,
  cancelActiveTicket,
  getActiveTickets,
  getAssistantSession,
  getMe,
  getPolicySections,
  logout as logoutSession,
  splitCustomerTickets,
  updateActiveTicket,
} from "./lib/api";
import { fileToEvidenceUpload } from "./lib/evidence";
import { getPolicySectionTitle, policyPreviewText } from "./lib/policyContent";

const TOKEN_STORAGE_KEY = "shopward_demo_token";
const navItems = ["Dashboard", "Products", "ActiveTickets", "PolicySections"] as const;

type Page = (typeof navItems)[number];

function navLabel(page: Page): string {
  if (page === "ActiveTickets") {
    return "Active Tickets";
  }
  if (page === "PolicySections") {
    return "Shopward Policies";
  }
  return page;
}

function pageTitle(page: Page): string {
  if (page === "Dashboard") {
    return "Support Dashboard";
  }
  if (page === "Products") {
    return "My Purchases";
  }
  if (page === "ActiveTickets") {
    return "Active Tickets";
  }
  return "Shopward Policies";
}

function pageSubtitle(page: Page): string {
  if (page === "Dashboard") {
    return "Chat with support, start returns, and review account activity.";
  }
  if (page === "Products") {
    return "View everything you have purchased from Shopward.";
  }
  if (page === "ActiveTickets") {
    return "Track open return requests or review past refund outcomes.";
  }
  return "Browse Shopward customer policies for returns, refunds, and more.";
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? "");
  const [customer, setCustomer] = useState<CurrentUser | null>(null);
  const [activePage, setActivePage] = useState<Page>("Dashboard");
  const [policySections, setPolicySections] = useState<PolicySection[]>([]);
  const [activeTickets, setActiveTickets] = useState<ActiveTicket[]>([]);
  const [chatMessages, setChatMessages] = useState<AssistantMessage[]>([]);
  const [chatActions, setChatActions] = useState<AssistantAction[]>([]);
  const [chatDecision, setChatDecision] = useState<RefundDecision | null>(null);
  const [error, setError] = useState("");
  const isUnderDevelopmentPage = window.location.pathname === "/under-development";

  useEffect(() => {
    if (!token) {
      return;
    }

    getMe(token)
      .then((profile) => {
        setCustomer(profile);
        setError("");
      })
      .catch((err) => {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        setToken("");
        setCustomer(null);
        setError(err instanceof Error ? err.message : "Session expired. Please sign in again.");
      });
  }, [token]);

  useEffect(() => {
    if (activePage !== "PolicySections" || policySections.length > 0) {
      return;
    }
    getPolicySections().then(setPolicySections).catch(() => setPolicySections([]));
  }, [activePage, policySections.length]);

  useEffect(() => {
    if (!token || activePage !== "ActiveTickets") {
      return;
    }
    getActiveTickets(token).then(setActiveTickets).catch(() => setActiveTickets([]));
  }, [activePage, token]);

  useEffect(() => {
    if (!token || customer?.role === "admin") {
      return;
    }
    if (activePage === "Products" || activePage === "ActiveTickets") {
      getMe(token)
        .then((profile) => {
          if (profile.role === "customer") {
            setCustomer(profile);
          }
        })
        .catch(() => undefined);
    }
  }, [activePage, token, customer?.role]);

  function handleLogin(nextToken: string, profile: CurrentUser) {
    localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
    setToken(nextToken);
    setCustomer(profile);
    setChatMessages([]);
    setChatActions([]);
    setChatDecision(null);
    setError("");
  }

  function updateChatState(state: {
    messages: AssistantMessage[];
    actions: AssistantAction[];
    decision: RefundDecision | null;
  }) {
    setChatMessages(state.messages);
    setChatActions(state.actions);
    setChatDecision(state.decision);
  }

  async function restoreAssistantSession() {
    if (!token) {
      return;
    }
    const session = await getAssistantSession(token);
    updateChatState({
      messages: session.messages,
      actions: session.actions,
      decision: session.decision,
    });
  }

  function refreshActiveTickets() {
    if (!token) {
      return;
    }
    getActiveTickets(token).then(setActiveTickets).catch(() => setActiveTickets([]));
    getMe(token)
      .then((profile) => {
        if (profile.role === "customer") {
          setCustomer(profile);
        }
      })
      .catch(() => undefined);
  }

  async function logout() {
    if (token) {
      await logoutSession(token).catch(() => undefined);
    }
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken("");
    setCustomer(null);
    setChatMessages([]);
    setChatActions([]);
    setChatDecision(null);
  }

  if (isUnderDevelopmentPage) {
    return <UnderDevelopmentPage />;
  }

  if (!token || !customer) {
    return <LoginPage onLogin={handleLogin} />;
  }

  if (customer.role === "admin") {
    return <AdminDashboard token={token} admin={customer} onLogout={logout} />;
  }

  const purchasedItems = customer.orders.flatMap((order) =>
    order.items.map((item) => ({
      ...item,
      orderId: order.id,
      orderTotal: order.total,
      orderStatus: order.status,
    })),
  );
  const totalOrderValue = customer.orders.reduce((sum, order) => sum + order.total, 0);
  const refundableProducts = purchasedItems.filter(
    (item) =>
      !item.final_sale &&
      !item.digital_download &&
      !item.subscription_product &&
      item.orderStatus !== "returned",
  );
  const returnedProducts = purchasedItems.filter((item) => item.orderStatus === "returned");
  const deliveredOrders = customer.orders.filter((order) => order.status === "delivered");

  return (
    <main className="support-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <BrandLogo compact />
        </div>

        <p className="sidebar-section-label">Menu</p>
        <nav className="side-nav">
          {navItems.map((item) => (
            <button
              key={item}
              type="button"
              className={activePage === item ? "active" : ""}
              onClick={() => setActivePage(item)}
            >
              {navLabel(item)}
            </button>
          ))}
        </nav>

        <div className="sidebar-profile">
          <div className="profile-card">
            <strong>{customer.name}</strong>
            <span>{customer.email}</span>
            <span className="profile-tier">{customer.loyalty_tier} member</span>
          </div>
          <button type="button" className="secondary-button" onClick={logout}>
            Sign out
          </button>
        </div>
      </aside>

      <section className="support-main">
        <header className="topbar">
          <div>
            <p className="eyebrow">Customer Portal</p>
            <h1>{pageTitle(activePage)}</h1>
            <p className="topbar-subtitle">{pageSubtitle(activePage)}</p>
          </div>
          <div className="topbar-badge">
            <span className="status-dot" />
            Signed in as {customer.name.split(" ")[0]}
          </div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        {activePage === "Dashboard" ? (
          <DashboardPage
            customer={customer}
            purchasedItems={purchasedItems}
            deliveredOrders={deliveredOrders.length}
            token={token}
            chatMessages={chatMessages}
            chatActions={chatActions}
            chatDecision={chatDecision}
            onChatStateChange={updateChatState}
            onSessionRestore={restoreAssistantSession}
            onDecision={refreshActiveTickets}
          />
        ) : null}

        {activePage === "Products" ? (
          <ProductsPage
            purchasedItems={purchasedItems}
            refundableCount={refundableProducts.length}
            returnedCount={returnedProducts.length}
            totalOrderValue={totalOrderValue}
          />
        ) : null}

        {activePage === "ActiveTickets" ? (
          <ActiveTicketsPage tickets={activeTickets} token={token} onUpdated={refreshActiveTickets} />
        ) : null}

        {activePage === "PolicySections" ? (
          <PolicySectionsPage sections={policySections} />
        ) : null}
      </section>
    </main>
  );
}

function UnderDevelopmentPage() {
  return (
    <main className="under-development-shell">
      <section className="panel under-development-card">
        <BrandLogo compact />
        <p className="eyebrow">Shopward Support</p>
        <h1>Currently under development</h1>
        <p className="muted">
          This contact option is not available in the demo yet. Please return to the customer portal
          and continue with policy questions or refund requests.
        </p>
        <a className="secondary-button under-development-link" href="/">
          Back to portal
        </a>
      </section>
    </main>
  );
}

function DashboardPage({
  customer,
  purchasedItems,
  deliveredOrders,
  token,
  chatMessages,
  chatActions,
  chatDecision,
  onChatStateChange,
  onSessionRestore,
  onDecision,
}: {
  customer: Customer;
  purchasedItems: Array<Customer["orders"][number]["items"][number] & { orderId: string; orderTotal: number }>;
  deliveredOrders: number;
  token: string;
  chatMessages: AssistantMessage[];
  chatActions: AssistantAction[];
  chatDecision: RefundDecision | null;
  onChatStateChange: (state: {
    messages: AssistantMessage[];
    actions: AssistantAction[];
    decision: RefundDecision | null;
  }) => void;
  onSessionRestore: () => Promise<void>;
  onDecision: () => void;
}) {
  return (
    <div className="dashboard-grid">
      <section className="metric-row">
        <Metric label="Products" value={purchasedItems.length.toString()} detail="Purchased by you" />
        <Metric label="Delivered Orders" value={deliveredOrders.toString()} detail="Completed deliveries" />
        <Metric label="Refunds" value={customer.refund_count_last_12_months.toString()} detail="Last 12 months" />
      </section>

      <div className="dashboard-support-grid">
        <ChatPanel
          token={token}
          customerName={customer.name}
          messages={chatMessages}
          actions={chatActions}
          decision={chatDecision}
          onStateChange={onChatStateChange}
          onSessionRestore={onSessionRestore}
          onDecision={onDecision}
        />
        <VoicePanel token={token} onDecision={onDecision} />
      </div>
    </div>
  );
}

function ProductsPage({
  purchasedItems,
  refundableCount,
  returnedCount,
  totalOrderValue,
}: {
  purchasedItems: Array<
    Customer["orders"][number]["items"][number] & {
      orderId: string;
      orderTotal: number;
      orderStatus: string;
    }
  >;
  refundableCount: number;
  returnedCount: number;
  totalOrderValue: number;
}) {
  return (
    <div className="page-stack">
      <section className="metric-row">
        <Metric label="Purchased" value={purchasedItems.length.toString()} detail="Products on your account" />
        <Metric label="Return Eligible" value={refundableCount.toString()} detail="Available for return" />
        <Metric label="Returned" value={returnedCount.toString()} detail="Refund completed" />
        <Metric label="Total Value" value={`$${totalOrderValue.toFixed(2)}`} detail="Across your orders" />
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Products</p>
            <h2>Your purchased products</h2>
          </div>
        </div>
        <div className="product-grid">
          {purchasedItems.map((item) => (
            <article
              key={`${item.orderId}-${item.sku}`}
              className={`product-card static${item.orderStatus === "returned" ? " returned" : ""}`}
            >
              <div className="product-card-header">
                <strong>{item.name}</strong>
                {item.orderStatus === "returned" ? (
                  <span className="product-status returned">Returned</span>
                ) : null}
              </div>
              <span>{item.sku}</span>
              <span>Order: {item.orderId}</span>
              <span>${item.price.toFixed(2)} · {item.condition}</span>
              {item.orderStatus === "returned" ? (
                <small className="muted">This item was returned and is no longer eligible for a new request.</small>
              ) : null}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function ActiveTicketsPage({
  tickets,
  token,
  onUpdated,
}: {
  tickets: ActiveTicket[];
  token: string;
  onUpdated: () => void;
}) {
  const { open: openTickets, past: pastTickets } = splitCustomerTickets(tickets);
  const pendingCount = openTickets.filter((ticket) => ticket.status === "Pending").length;
  const reviewCount = openTickets.filter((ticket) =>
    ["Manual Review", "Manager Review"].includes(ticket.status),
  ).length;
  const approvedCount = pastTickets.filter((ticket) => ticket.status === "Approved").length;
  const deniedCount = pastTickets.filter((ticket) => ticket.status === "Denied").length;
  const [savingTicketId, setSavingTicketId] = useState("");
  const [cancellingTicketId, setCancellingTicketId] = useState("");
  const [draftDescriptions, setDraftDescriptions] = useState<Record<string, string>>({});
  const [draftFiles, setDraftFiles] = useState<Record<string, EvidenceUpload[]>>({});

  function descriptionFor(ticket: ActiveTicket): string {
    return draftDescriptions[ticket.request_id] ?? ticket.customer_comment ?? "";
  }

  function filesFor(ticket: ActiveTicket): EvidenceUpload[] {
    return draftFiles[ticket.request_id] ?? [];
  }

  async function saveTicket(ticket: ActiveTicket) {
    setSavingTicketId(ticket.request_id);
    await updateActiveTicket(token, ticket.request_id, {
      description: descriptionFor(ticket),
      files: filesFor(ticket),
    }).finally(() => setSavingTicketId(""));
    setDraftFiles((current) => ({ ...current, [ticket.request_id]: [] }));
    onUpdated();
  }

  async function cancelTicket(ticket: ActiveTicket) {
    setCancellingTicketId(ticket.request_id);
    await cancelActiveTicket(token, ticket.request_id).finally(() => setCancellingTicketId(""));
    onUpdated();
  }

  return (
    <div className="page-stack">
      <section className="metric-row">
        <Metric label="Active Tickets" value={openTickets.length.toString()} detail="Open requests" />
        <Metric label="Pending" value={pendingCount.toString()} detail="Awaiting review" />
        <Metric label="In Review" value={reviewCount.toString()} detail="Needs specialist review" />
        <Metric label="Past Tickets" value={pastTickets.length.toString()} detail="Accepted or rejected" />
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Support</p>
            <h2>Your active tickets</h2>
          </div>
        </div>
        {openTickets.length === 0 ? (
          <p className="muted">You do not have any active return or refund tickets right now.</p>
        ) : (
          <div className="ticket-grid">
            {openTickets.map((ticket) => (
              <CustomerTicketCard
                key={ticket.request_id}
                ticket={ticket}
                token={token}
                editable
                description={descriptionFor(ticket)}
                pendingFiles={filesFor(ticket)}
                saving={savingTicketId === ticket.request_id}
                cancelling={cancellingTicketId === ticket.request_id}
                onDescriptionChange={(value) =>
                  setDraftDescriptions((current) => ({
                    ...current,
                    [ticket.request_id]: value,
                  }))
                }
                onFilesSelected={(files) =>
                  setDraftFiles((current) => ({ ...current, [ticket.request_id]: files }))
                }
                onSave={() => void saveTicket(ticket)}
                onCancel={() => void cancelTicket(ticket)}
              />
            ))}
          </div>
        )}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">History</p>
            <h2>Past tickets</h2>
          </div>
        </div>
        {pastTickets.length === 0 ? (
          <p className="muted">Accepted and rejected refund requests will appear here.</p>
        ) : (
          <>
            {(approvedCount > 0 || deniedCount > 0) ? (
              <p className="muted ticket-history-summary">
                {approvedCount > 0 ? `${approvedCount} accepted` : null}
                {approvedCount > 0 && deniedCount > 0 ? " · " : null}
                {deniedCount > 0 ? `${deniedCount} rejected` : null}
              </p>
            ) : null}
            <div className="ticket-grid">
              {pastTickets.map((ticket) => (
                <CustomerTicketCard key={ticket.request_id} ticket={ticket} token={token} />
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function CustomerTicketCard({
  ticket,
  token,
  editable = false,
  description = "",
  pendingFiles = [],
  saving = false,
  cancelling = false,
  onDescriptionChange,
  onFilesSelected,
  onSave,
  onCancel,
}: {
  ticket: ActiveTicket;
  token: string;
  editable?: boolean;
  description?: string;
  pendingFiles?: EvidenceUpload[];
  saving?: boolean;
  cancelling?: boolean;
  onDescriptionChange?: (value: string) => void;
  onFilesSelected?: (files: EvidenceUpload[]) => void;
  onSave?: () => void;
  onCancel?: () => void;
}) {
  return (
    <article key={ticket.request_id} className="ticket-card">
      <div className="ticket-card-header">
        <strong>{ticket.request_id}</strong>
        <span className={`ticket-status ${ticket.status.toLowerCase().replace(/\s+/g, "-")}`}>
          {ticket.status}
        </span>
      </div>
      {ticket.status === "Approved" ? (
        <div className="ticket-decision-banner approved">
          <strong>Refund Accepted</strong>
          <p>
            {ticket.admin_message ??
              `Refund of $${ticket.total_amount.toFixed(2)} will be transferred to your original bank account within 5-7 business days.`}
          </p>
        </div>
      ) : null}
      {ticket.status === "Denied" ? (
        <div className="ticket-decision-banner denied">
          <strong>Refund Rejected</strong>
          <p>{ticket.admin_message ?? "Your return request was not approved."}</p>
          <TicketSupportFallback />
        </div>
      ) : null}
      <span>{ticket.product_names || "Order items"}</span>
      <span>Order: {ticket.order_id}</span>
      <span>Requested: {ticket.request_date}</span>
      <span>Reason: {ticket.reason}</span>
      <span>Resolution: {ticket.requested_resolution}</span>
      {editable ? (
        <>
          <label className="ticket-edit-field">
            Description
            <textarea
              value={description}
              onChange={(event) => onDescriptionChange?.(event.target.value)}
              rows={3}
              placeholder="Add or update ticket details..."
            />
          </label>
          <TicketEvidenceGallery evidence={ticket.evidence} token={token} />
          {pendingFiles.length > 0 ? (
            <small className="muted">
              New selection: {pendingFiles.map((file) => file.file_name).join(", ")}
            </small>
          ) : null}
          <input
            type="file"
            accept="image/*"
            multiple
            onChange={(event) => {
              void (async () => {
                const files = await Promise.all(
                  Array.from(event.target.files ?? []).map(fileToEvidenceUpload),
                );
                onFilesSelected?.(files);
              })();
            }}
          />
          <div className="ticket-actions">
            <button
              type="button"
              className="secondary-button ticket-save-button"
              disabled={saving || cancelling}
              onClick={onSave}
            >
              {saving ? "Saving..." : "Save changes"}
            </button>
            <button
              type="button"
              className="ghost-button ticket-cancel-button"
              disabled={saving || cancelling}
              onClick={onCancel}
            >
              {cancelling ? "Cancelling..." : "Cancel ticket"}
            </button>
          </div>
        </>
      ) : (
        <>
          {ticket.customer_comment ? <p className="ticket-comment">{ticket.customer_comment}</p> : null}
          <TicketEvidenceGallery evidence={ticket.evidence} token={token} />
        </>
      )}
    </article>
  );
}

function PolicySectionsPage({ sections }: { sections: PolicySection[] }) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());

  function toggleSection(chunkId: string) {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(chunkId)) {
        next.delete(chunkId);
      } else {
        next.add(chunkId);
      }
      return next;
    });
  }

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Knowledge Base</p>
            <h2>Shopward Policies</h2>
          </div>
        </div>
        <div className="policy-section-list">
          {sections.map((section) => {
            const expanded = expandedIds.has(section.chunk_id);
            const displayTitle = getPolicySectionTitle(section.section_title);
            const hasMore = policyPreviewText(section.content, displayTitle).endsWith("…");

            return (
              <article
                key={section.chunk_id}
                className={`policy-section-card ${expanded ? "expanded" : ""}`}
                role="button"
                tabIndex={0}
                aria-expanded={expanded}
                onClick={() => toggleSection(section.chunk_id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    toggleSection(section.chunk_id);
                  }
                }}
              >
                <div className="policy-section-card-header">
                  <strong>{displayTitle}</strong>
                  <span className="policy-section-toggle" aria-hidden="true">
                    {expanded ? "−" : "+"}
                  </span>
                </div>
                <PolicySectionContent
                  sectionTitle={section.section_title}
                  content={section.content}
                  expanded={expanded}
                />
                {!expanded && hasMore ? (
                  <span className="policy-section-hint">Click to read full section</span>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}
