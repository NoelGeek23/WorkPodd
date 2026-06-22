import { useRef, useState } from "react";
import { API_BASE_URL, createRealtimeSession, sendChat } from "../lib/api";

type Props = {
  token: string;
};

export default function VoicePanel({ token }: Props) {
  const [status, setStatus] = useState("Idle");
  const [transcript, setTranscript] = useState("");
  const [reply, setReply] = useState("");
  const [error, setError] = useState("");
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  async function startVoice() {
    setError("");
    setReply("");
    setStatus("Creating Realtime session...");

    try {
      const session = await createRealtimeSession();
      if (!session.client_secret?.value) {
        setStatus("Voice setup needed");
        setError(session.note ?? "No OpenAI Realtime client secret returned.");
        return;
      }

      const peer = new RTCPeerConnection();
      peerRef.current = peer;

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      stream.getTracks().forEach((track) => peer.addTrack(track, stream));

      const dataChannel = peer.createDataChannel("oai-events");
      dataChannel.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        const delta =
          payload.type === "response.audio_transcript.delta" ||
          payload.type === "conversation.item.input_audio_transcription.completed"
            ? payload.delta ?? payload.transcript
            : "";
        if (delta) {
          setTranscript((current) => `${current}${delta}`);
        }
      };

      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);

      const response = await fetch(
        `https://api.openai.com/v1/realtime?model=${encodeURIComponent(session.model)}`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${session.client_secret.value}`,
            "Content-Type": "application/sdp",
          },
          body: offer.sdp,
        },
      );

      if (!response.ok) {
        throw new Error(`Realtime connection failed: ${response.status}`);
      }

      const answer = await response.text();
      await peer.setRemoteDescription({ type: "answer", sdp: answer });
      setStatus(`Live with ${session.model} (${session.voice})`);
    } catch (err) {
      setStatus("Voice failed");
      setError(err instanceof Error ? err.message : "Unable to start voice session");
      stopVoice();
    }
  }

  function stopVoice() {
    peerRef.current?.close();
    peerRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setStatus("Idle");
  }

  async function submitTranscript() {
    if (!transcript.trim()) {
      setError("Add or record a transcript before submitting.");
      return;
    }

    setError("");
    setReply("Checking refund policy...");
    try {
      const response = await sendChat(token, transcript);
      setReply(`${response.decision.status.toUpperCase()}: ${response.reply}`);
    } catch (err) {
      setReply("");
      setError(err instanceof Error ? err.message : "Transcript submission failed");
    }
  }

  return (
    <section className="panel voice-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Voice</p>
          <h2>OpenAI Realtime Pipeline</h2>
        </div>
        <span className="connection-pill">{status}</span>
      </div>

      <p className="muted">
        The browser requests an ephemeral Realtime session from <code>{API_BASE_URL}</code>, opens
        the microphone, then submits the captured transcript to the same customer-scoped refund
        policy agent. Mention an order ID or product name in the transcript.
      </p>

      <div className="voice-actions">
        <button type="button" onClick={startVoice}>
          Start microphone
        </button>
        <button type="button" className="secondary-button" onClick={stopVoice}>
          Stop
        </button>
      </div>

      <label>
        Transcript / voice summary
        <textarea
          rows={4}
          value={transcript}
          onChange={(event) => setTranscript(event.target.value)}
          placeholder="Voice transcript appears here, or type a spoken refund request summary..."
        />
      </label>

      <button type="button" onClick={submitTranscript} disabled={!token}>
        Submit transcript to refund agent
      </button>

      {reply ? <div className="success-banner">{reply}</div> : null}
      {error ? <div className="error-banner">{error}</div> : null}
    </section>
  );
}
