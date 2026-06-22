import { useEffect, useState } from "react";
import { AgentLogEvent, subscribeToAgentLogs } from "../lib/api";

export default function AdminDashboard() {
  const [logs, setLogs] = useState<AgentLogEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const source = subscribeToAgentLogs((event) => {
      setLogs((current) => [event, ...current].slice(0, 80));
    });

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);

    return () => source.close();
  }, []);

  return (
    <aside className="panel admin-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Admin Dashboard</p>
          <h2>Real-Time Agent Reasoning</h2>
        </div>
        <span className={`connection-pill ${connected ? "connected" : ""}`}>
          {connected ? "Live" : "Waiting"}
        </span>
      </div>

      <div className="log-stream">
        {logs.length === 0 ? (
          <div className="empty-state">
            Reasoning logs will appear here as the agent calls refund policy tools.
          </div>
        ) : (
          logs.map((log) => (
            <article key={log.id} className={`log-card stage-${log.stage}`}>
              <div className="log-header">
                <strong>{log.stage}</strong>
                <time>{new Date(log.timestamp).toLocaleTimeString()}</time>
              </div>
              <p>{log.message}</p>
              <div className="log-meta">
                {log.customer_id ? <span>Customer: {log.customer_id}</span> : null}
                {log.order_id ? <span>Order: {log.order_id}</span> : null}
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
    </aside>
  );
}
