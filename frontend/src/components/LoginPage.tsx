import { FormEvent, useState } from "react";
import { Customer, login } from "../lib/api";

type Props = {
  onLogin: (token: string, customer: Customer) => void;
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
      <section className="panel login-card">
        <p className="eyebrow">Shopward Customer Portal</p>
        <h1>Sign in to your refunds dashboard</h1>
        <p className="muted">
          Use any seeded customer email with the demo password <code>12345678</code>.
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
          <button type="submit" disabled={loading}>
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>

        {error ? <div className="error-banner">{error}</div> : null}
      </section>
    </main>
  );
}
