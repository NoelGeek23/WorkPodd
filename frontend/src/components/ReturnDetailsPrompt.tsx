import { ChangeEvent, FormEvent, useState } from "react";
import { AssistantAction, EvidenceUpload } from "../lib/api";
import { fileToEvidenceUpload } from "../lib/evidence";

type Props = {
  action: AssistantAction;
  disabled?: boolean;
  onSubmit: (payload: { description?: string; files?: EvidenceUpload[] }) => Promise<void>;
};

export default function ReturnDetailsPrompt({ action, disabled, onSubmit }: Props) {
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<EvidenceUpload[]>([]);
  const [status, setStatus] = useState("");

  async function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    const selectedFiles = Array.from(event.target.files ?? []);
    const selected = await Promise.all(selectedFiles.map(fileToEvidenceUpload));
    setFiles(selected);
    setStatus(selected.length ? `${selected.length} image${selected.length === 1 ? "" : "s"} selected` : "");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Submitting...");
    await onSubmit({ description, files });
    setStatus("Submitted");
  }

  return (
    <form className="assistant-action-card return-details-card" onSubmit={submit}>
      <strong>{action.label}</strong>

      {(action.description_required || !action.image_required) ? (
        <label className="return-details-field">
          Description {action.description_required ? <span>*</span> : <small>(optional)</small>}
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Add details for the support team..."
            rows={4}
            required={action.description_required}
            disabled={disabled}
          />
        </label>
      ) : null}

      {(action.image_required || action.allow_multiple) ? (
        <label className="return-details-field">
          Images {action.image_required ? <span>*</span> : <small>(optional)</small>}
          <input
            type="file"
            accept={action.accept ?? "image/*"}
            multiple={action.allow_multiple}
            required={action.image_required}
            disabled={disabled}
            onChange={handleFiles}
          />
        </label>
      ) : null}

      {files.length > 0 ? (
        <ul className="selected-file-list">
          {files.map((file) => (
            <li key={`${file.file_name}-${file.size}`}>{file.file_name}</li>
          ))}
        </ul>
      ) : null}

      <button type="submit" className="secondary-button return-details-submit" disabled={disabled}>
        Submit details
      </button>
      {status ? <small className="muted">{status}</small> : null}
    </form>
  );
}
