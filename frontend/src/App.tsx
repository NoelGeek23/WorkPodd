import { useEffect, useState } from "react";
import ChatPanel from "./components/ChatPanel";
import LoginPage from "./components/LoginPage";
import VoicePanel from "./components/VoicePanel";
import { Customer, PolicySection, getMe, getPolicySections, logout as logoutSession } from "./lib/api";

const TOKEN_STORAGE_KEY = "shopward_demo_token";
const navItems = ["Dashboard", "Products", "Refunds", "PolicySections"] as const;

type Page = (typeof navItems)[number];

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? "");
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [activePage, setActivePage] = useState<Page>("Dashboard");
  const [policySections, setPolicySections] = useState<PolicySection[]>([]);
  const [error, setError] = useState("");

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

  function handleLogin(nextToken: string, profile: Customer) {
    localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
    setToken(nextToken);
    setCustomer(profile);
    setError("");
  }

  async function logout() {
    if (token) {
      await logoutSession(token).catch(() => undefined);
    }
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken("");
    setCustomer(null);
  }

  if (!token || !customer) {
    return <LoginPage onLogin={handleLogin} />;
  }

  const purchasedItems = customer.orders.flatMap((order) =>
    order.items.map((item) => ({ ...item, orderId: order.id, orderTotal: order.total })),
  );
  const totalOrderValue = customer.orders.reduce((sum, order) => sum + order.total, 0);
  const refundableProducts = purchasedItems.filter(
    (item) => !item.final_sale && !item.digital_download && !item.subscription_product,
  );
  const deliveredOrders = customer.orders.filter((order) => order.status === "delivered");
  const riskyOrders = customer.orders.filter((order) => order.total > 500 || order.status === "lost");

  const pageTitle =
    activePage === "Dashboard"
      ? "AI Refund Dashboard"
      : activePage === "Products"
        ? "Purchased Products"
        : activePage === "Refunds"
          ? "Refund Center"
          : "Policy Sections";

  return (
    <main className="support-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark">S</div>
          <div>
            <strong>Shopward</strong>
            <span>Support Portal</span>
          </div>
        </div>

        <nav className="side-nav">
          {navItems.map((item) => (
            <button
              key={item}
              type="button"
              className={activePage === item ? "active" : ""}
              onClick={() => setActivePage(item)}
            >
              {item}
            </button>
          ))}
        </nav>

        <div className="sidebar-profile">
          <strong>{customer.name}</strong>
          <span>{customer.email}</span>
          <button type="button" className="secondary-button" onClick={logout}>
            Sign out
          </button>
        </div>
      </aside>

      <section className="support-main">
        <header className="topbar">
          <div>
            <p className="eyebrow">Customer Workspace</p>
            <h1>{pageTitle}</h1>
          </div>
          <div className="search-shell">
            Search is powered by the AI chat. Mention an order ID, product name, or SKU.
          </div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        {activePage === "Dashboard" ? (
          <DashboardPage
            customer={customer}
            purchasedItems={purchasedItems}
            deliveredOrders={deliveredOrders.length}
            riskyOrders={riskyOrders.length}
            token={token}
          />
        ) : null}

        {activePage === "Products" ? (
          <ProductsPage
            purchasedItems={purchasedItems}
            refundableCount={refundableProducts.length}
            totalOrderValue={totalOrderValue}
          />
        ) : null}

        {activePage === "Refunds" ? (
          <RefundsPage
            customer={customer}
            riskyOrders={riskyOrders.length}
            deliveredOrders={deliveredOrders.length}
          />
        ) : null}

        {activePage === "PolicySections" ? (
          <PolicySectionsPage sections={policySections} />
        ) : null}
      </section>
    </main>
  );
}

function DashboardPage({
  customer,
  purchasedItems,
  deliveredOrders,
  riskyOrders,
  token,
}: {
  customer: Customer;
  purchasedItems: Array<Customer["orders"][number]["items"][number] & { orderId: string; orderTotal: number }>;
  deliveredOrders: number;
  riskyOrders: number;
  token: string;
}) {
  return (
    <div className="dashboard-grid">
      <section className="metric-row">
        <Metric label="Products" value={purchasedItems.length.toString()} detail="Purchased by you" />
        <Metric label="Delivered Orders" value={deliveredOrders.toString()} detail="Eligible for checks" />
        <Metric label="Refunds" value={customer.refund_count_last_12_months.toString()} detail="Last 12 months" />
        <Metric label="Review Risk" value={riskyOrders.toString()} detail="High value or lost" />
      </section>

      <ChatPanel token={token} />

      <VoicePanel token={token} />
    </div>
  );
}

function ProductsPage({
  purchasedItems,
  refundableCount,
  totalOrderValue,
}: {
  purchasedItems: Array<Customer["orders"][number]["items"][number] & { orderId: string; orderTotal: number }>;
  refundableCount: number;
  totalOrderValue: number;
}) {
  return (
    <div className="page-stack">
      <section className="metric-row">
        <Metric label="Purchased" value={purchasedItems.length.toString()} detail="Products on your account" />
        <Metric label="Potentially Refundable" value={refundableCount.toString()} detail="Before policy checks" />
        <Metric label="Total Value" value={`$${totalOrderValue.toFixed(2)}`} detail="Across visible orders" />
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
            <article key={`${item.orderId}-${item.sku}`} className="product-card static">
              <strong>{item.name}</strong>
              <span>{item.sku}</span>
              <span>Order: {item.orderId}</span>
              <span>${item.price.toFixed(2)} · {item.condition}</span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function RefundsPage({
  customer,
  riskyOrders,
  deliveredOrders,
}: {
  customer: Customer;
  riskyOrders: number;
  deliveredOrders: number;
}) {
  return (
    <div className="page-stack">
      <section className="metric-row">
        <Metric label="Refund Count" value={customer.refund_count_last_12_months.toString()} detail="Last 12 months" />
        <Metric label="Chargebacks" value={customer.chargeback_count.toString()} detail="Customer record" />
        <Metric label="Delivered Orders" value={deliveredOrders.toString()} detail="Can be evaluated" />
        <Metric label="Needs Review" value={riskyOrders.toString()} detail="High value or lost" />
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Refunds</p>
            <h2>How to request</h2>
          </div>
        </div>
        <p className="muted">
          Open Dashboard and tell the AI assistant the order ID or product name. It will fuzzy-match
          against your purchases and apply Shopward policy sections globally.
        </p>
      </section>
    </div>
  );
}

function PolicySectionsPage({ sections }: { sections: PolicySection[] }) {
  return (
    <div className="page-stack">
      <section className="metric-row">
        <Metric label="Policy Sections" value={sections.length.toString()} detail="Global policy chunks" />
        <Metric label="Scope" value="Global" detail="Same for all customers" />
        <Metric label="Decision Source" value="RAG + Tools" detail="Policy plus SQLite facts" />
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Knowledge Base</p>
            <h2>Policy sections used by the agent</h2>
          </div>
        </div>
        <div className="policy-section-list">
          {sections.map((section) => (
            <article key={section.chunk_id} className="policy-section-card">
              <strong>{section.section_title}</strong>
              <p>{section.content.slice(0, 260)}...</p>
            </article>
          ))}
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
