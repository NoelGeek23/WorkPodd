import { FormEvent, useState } from "react";
import BrandLogo from "./BrandLogo";
import { CurrentUser, login } from "../lib/api";

type Props = {
  onLogin: (token: string, customer: CurrentUser) => void;
};

export default function LoginPage({ onLogin }: Props) {
  const [email, setEmail] = useState("avery.stone@mailinator.com");
  const [password, setPassword] = useState("12345678");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      const response = await login(email, password);
      onLogin(response.token, response.customer);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-brand-panel">
        <BrandLogo />
        <h1>Welcome back</h1>
        <p className="login-brand-copy">
          Manage returns, review active tickets, and get instant policy guidance from your
          Shopward customer portal.
        </p>
        <ul className="login-feature-list">
          <li>Track return requests in real time</li>
          <li>Upload evidence and update tickets anytime</li>
          <li>Chat with the AI support assistant</li>
        </ul>
      </section>

      <section className="panel login-card">
        <p className="eyebrow">Sign in</p>
        <h2>Access your account</h2>
        <p className="muted">
          Demo account: <code>avery.stone@mailinator.com</code> · password <code>12345678</code>
          <br />
          Admin dashboard: <code>admin@mailinator.com</code> · password <code>12345678</code>
        </p>

        <form onSubmit={submit} className="login-form">
          <label>
            Email
            <input
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="customer@mailinator.com"
              type="email"
              required
            />
          </label>
          <label>
            Password
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="12345678"
              type="password"
              required
            />
          </label>
          <button type="submit" className="primary-button" disabled={loading}>
            {loading ? "Signing in..." : "Sign in to portal"}
          </button>
        </form>

        {error ? <div className="error-banner">{error}</div> : null}
      </section>
    </main>
  );
}
