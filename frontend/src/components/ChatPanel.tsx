import { FormEvent, useState } from "react";
import ImageUploadPrompt from "./ImageUploadPrompt";
import PolicyAnswer from "./PolicyAnswer";
import ReasonOptions from "./ReasonOptions";
import {
  AssistantAction,
  AssistantMessage,
  InteractiveChatResponse,
  RefundDecision,
  sendAssistantChat,
  uploadAssistantImage,
} from "../lib/api";

type Props = {
  token: string;
};

const samplePrompt = "What is the return window for VIP customers?";

export default function ChatPanel({ token }: Props) {
  const [message, setMessage] = useState(samplePrompt);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [actions, setActions] = useState<AssistantAction[]>([]);
  const [citations, setCitations] = useState<Array<Record<string, unknown>>>([]);
  const [decision, setDecision] = useState<RefundDecision | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function applyResponse(response: InteractiveChatResponse) {
    setMessages(response.messages);
    setActions(response.actions);
    setCitations(response.citations);
    setDecision(response.decision);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !message.trim()) {
      return;
    }

    const outgoing = message.trim();
    setMessage("");
    setLoading(true);
    setError("");

    try {
      const response = await sendAssistantChat(token, { message: outgoing });
      applyResponse(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Assistant request failed");
    } finally {
      setLoading(false);
    }
  }

  async function selectReason(optionId: string) {
    setLoading(true);
    setError("");
    try {
      const response = await sendAssistantChat(token, {
        action_id: "return_reason",
        selected_option: optionId,
      });
      applyResponse(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reason selection failed");
    } finally {
      setLoading(false);
    }
  }

  async function uploadImage(file: File) {
    setLoading(true);
    setError("");
    try {
      const response = await uploadAssistantImage(token, file);
      applyResponse(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Image upload failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel chat-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Customer Chat</p>
          <h2>Interactive AI Assistant</h2>
          <p className="muted">
            Ask about policy, or start a return/exchange by mentioning an order ID, product name, or
            SKU.
          </p>
        </div>
        <button type="button" className="ghost-button" onClick={() => setMessage(samplePrompt)}>
          Policy sample
        </button>
      </div>

      <div className="chat-history">
        {messages.length === 0 ? (
          <div className="empty-state">
            Try “What is the return window for VIP customers?” or “I want to return Yoga Mat”.
          </div>
        ) : (
          messages.map((item, index) => (
            <article key={`${item.role}-${index}`} className={`chat-bubble ${item.role}`}>
              <MessageContent content={item.content} />
            </article>
          ))
        )}
      </div>

      <PolicyAnswer citations={citations} />

      {actions.map((action) =>
        action.type === "show_reason_options" ? (
          <ReasonOptions key={action.id} action={action} disabled={loading} onSelect={selectReason} />
        ) : (
          <ImageUploadPrompt key={action.id} action={action} disabled={loading} onUpload={uploadImage} />
        ),
      )}

      {decision ? (
        <div className={`decision-card ${decision.status}`}>
          <strong>{decision.status.toUpperCase()}</strong>
          <span>Order: {decision.order_id}</span>
          <span>Amount: {decision.amount > 0 ? `$${decision.amount.toFixed(2)}` : "$0.00"}</span>
          <span>{decision.internal_reason}</span>
        </div>
      ) : null}

      {error ? <div className="error-banner">{error}</div> : null}

      <form onSubmit={submit} className="chat-form">
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="Ask about policy, returns, exchanges, or a product..."
          rows={3}
        />
        <button type="submit" disabled={loading || !token}>
          {loading ? "Thinking..." : "Send"}
        </button>
      </form>
    </section>
  );
}

function MessageContent({ content }: { content: string }) {
  const paragraphs = content
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);

  return (
    <>
      {paragraphs.map((paragraph, index) => (
        <p key={index}>{paragraph}</p>
      ))}
    </>
  );
}
