import { FormEvent, useEffect, useRef, useState } from "react";
import ContactSupportOptions from "./ContactSupportOptions";
import ImageUploadPrompt from "./ImageUploadPrompt";
import PurchaseSelector from "./PurchaseSelector";
import ReasonOptions from "./ReasonOptions";
import RefundDecisionCard from "./RefundDecisionCard";
import ReturnDetailsPrompt from "./ReturnDetailsPrompt";
import {
  AssistantAction,
  AssistantMessage,
  EvidenceUpload,
  InteractiveChatResponse,
  RefundDecision,
  restartAssistantChat,
  sendAssistantChat,
  uploadAssistantImage,
} from "../lib/api";
import { readFileAsBase64 } from "../lib/evidence";
import {
  chatEmptyStateHint,
  chatGreeting,
  chatInputPlaceholder,
} from "../lib/customerPersonalization";

type Props = {
  token: string;
  customerName: string;
  messages: AssistantMessage[];
  actions: AssistantAction[];
  decision: RefundDecision | null;
  onStateChange: (state: {
    messages: AssistantMessage[];
    actions: AssistantAction[];
    decision: RefundDecision | null;
  }) => void;
  onSessionRestore?: () => Promise<void>;
  onDecision?: () => void;
};

const samplePrompt = "What is the return window for VIP customers?";

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionEventLike = {
  results: ArrayLike<{ 0: { transcript: string } }>;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

export default function ChatPanel({
  token,
  customerName,
  messages,
  actions,
  decision,
  onStateChange,
  onSessionRestore,
  onDecision,
}: Props) {
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const restoredRef = useRef(false);

  useEffect(() => {
    if (!token || !onSessionRestore || restoredRef.current || messages.length > 0) {
      return;
    }
    restoredRef.current = true;
    void onSessionRestore();
  }, [token, onSessionRestore, messages.length]);

  function applyResponse(response: InteractiveChatResponse) {
    onStateChange({
      messages: response.messages,
      actions: response.actions,
      decision: response.decision,
    });
    if (response.decision) {
      onDecision?.();
    }
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

  async function selectPurchase(orderId: string) {
    setLoading(true);
    setError("");
    try {
      const response = await sendAssistantChat(token, {
        action_id: "select_purchase",
        selected_option: orderId,
      });
      applyResponse(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Purchase selection failed");
    } finally {
      setLoading(false);
    }
  }

  async function uploadImage(file: File) {
    setLoading(true);
    setError("");
    try {
      const dataBase64 = await readFileAsBase64(file);
      const response = await uploadAssistantImage(token, file, dataBase64);
      applyResponse(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Image upload failed");
    } finally {
      setLoading(false);
    }
  }

  async function submitReturnDetails(payload: { description?: string; files?: EvidenceUpload[] }) {
    setLoading(true);
    setError("");
    try {
      const response = await sendAssistantChat(token, {
        action_id: "return_details",
        description: payload.description,
        files: payload.files,
      });
      applyResponse(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Details submission failed");
    } finally {
      setLoading(false);
    }
  }

  async function restartChat() {
    setLoading(true);
    setError("");
    try {
      await restartAssistantChat(token);
      onStateChange({ messages: [], actions: [], decision: null });
      restoredRef.current = false;
      setMessage("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not restart chat");
    } finally {
      setLoading(false);
    }
  }

  function toggleMicrophone() {
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }

    const SpeechRecognition =
      (window as unknown as { SpeechRecognition?: SpeechRecognitionConstructor }).SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: SpeechRecognitionConstructor }).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setError("Speech input is not supported in this browser. You can still type your message.");
      return;
    }

    const recognition = new SpeechRecognition();
    recognitionRef.current = recognition;
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";
    recognition.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript ?? "";
      if (transcript) {
        setMessage((current) => `${current ? `${current} ` : ""}${transcript}`.trim());
      }
    };
    recognition.onerror = () => {
      setError("I could not capture audio. Please try again or type your message.");
      setListening(false);
    };
    recognition.onend = () => setListening(false);
    recognition.start();
    setListening(true);
    setError("");
  }

  return (
    <section className="panel chat-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Customer Chat</p>
          <h2>Interactive AI Assistant</h2>
          <p className="muted">
            I can help with returns, exchanges, order questions, and Shopward policy.
          </p>
        </div>
        <div className="chat-heading-actions">
          <button type="button" className="ghost-button" onClick={() => setMessage(samplePrompt)}>
            Sample question
          </button>
          <button type="button" className="ghost-button" disabled={loading} onClick={() => void restartChat()}>
            Restart chat
          </button>
        </div>
      </div>

      <div className="chat-history">
        {messages.length === 0 ? (
          <div className="empty-state chat-welcome">
            <strong>{chatGreeting(customerName)}</strong>
            <p className="muted">{chatEmptyStateHint(customerName)}</p>
          </div>
        ) : (
          messages.map((item, index) => (
            <article key={`${item.role}-${index}`} className={`chat-bubble ${item.role}`}>
              <MessageContent content={item.content} />
            </article>
          ))
        )}
      </div>

      {actions.map((action) => {
        if (action.type === "show_reason_options") {
          return <ReasonOptions key={action.id} action={action} disabled={loading} onSelect={selectReason} />;
        }

        if (action.type === "select_purchase") {
          return <PurchaseSelector key={action.id} action={action} disabled={loading} onSubmit={selectPurchase} />;
        }

        if (action.type === "contact_support") {
          return <ContactSupportOptions key={action.id} action={action} />;
        }

        if (action.type === "collect_return_details") {
          return (
            <ReturnDetailsPrompt
              key={action.id}
              action={action}
              disabled={loading}
              onSubmit={submitReturnDetails}
            />
          );
        }

        return <ImageUploadPrompt key={action.id} action={action} disabled={loading} onUpload={uploadImage} />;
      })}

      {decision ? <RefundDecisionCard decision={decision} /> : null}

      {error ? <div className="error-banner">{error}</div> : null}

      <form onSubmit={submit} className="chat-form chat-composer">
        <button
          type="button"
          className={`mic-button ${listening ? "recording" : ""}`}
          onClick={toggleMicrophone}
          aria-label={listening ? "Stop microphone" : "Start microphone"}
          title={listening ? "Stop microphone" : "Start microphone"}
        >
          {listening ? "Stop" : "Mic"}
        </button>
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder={chatInputPlaceholder(customerName)}
          rows={1}
        />
        <button type="submit" className="send-button" disabled={loading || !token}>
          {loading ? "..." : "Send"}
        </button>
      </form>
    </section>
  );
}

function MessageContent({ content }: { content: string }) {
  const blocks = content
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);

  return (
    <>
      {blocks.map((block, index) => {
        const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
        const bulletLines = lines.filter((line) => line.startsWith("- "));
        const titleLine = lines.length > 1 && !lines[0].startsWith("- ") ? lines[0] : null;
        const proseLines = lines.filter((line) => !line.startsWith("- ") && line !== titleLine);

        if (bulletLines.length > 0) {
          return (
            <div key={index} className="chat-block">
              {titleLine ? <p className="chat-block-title">{titleLine}</p> : null}
              {proseLines.map((line, lineIndex) => (
                <p key={`${index}-prose-${lineIndex}`}>{line}</p>
              ))}
              <ul className="chat-bullet-list">
                {bulletLines.map((line) => (
                  <li key={`${index}-${line}`}>{line.slice(2)}</li>
                ))}
              </ul>
            </div>
          );
        }

        return (
          <p key={index} className="chat-paragraph">
            {block}
          </p>
        );
      })}
    </>
  );
}
