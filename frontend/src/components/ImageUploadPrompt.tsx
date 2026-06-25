import { ChangeEvent, useState } from "react";
import { AssistantAction } from "../lib/api";

type Props = {
  action: AssistantAction;
  disabled?: boolean;
  onUpload: (file: File) => Promise<void>;
};

export default function ImageUploadPrompt({ action, disabled, onUpload }: Props) {
  const [status, setStatus] = useState("");

  async function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setStatus(`Uploading ${file.name}...`);
    await onUpload(file);
    setStatus(`Attached ${file.name}`);
  }

  return (
    <div className="assistant-action-card">
      <strong>{action.label}</strong>
      <p className="muted">Upload a photo so we can review your return request.</p>
      <input type="file" accept={action.accept ?? "image/*"} disabled={disabled} onChange={handleChange} />
      {status ? <small className="muted">{status}</small> : null}
    </div>
  );
}
