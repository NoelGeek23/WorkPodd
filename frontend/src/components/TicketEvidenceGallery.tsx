import { TicketEvidence } from "../lib/api";
import { evidenceImageUrl, isImageEvidence } from "../lib/evidence";

type Props = {
  evidence: TicketEvidence[];
  token: string;
  title?: string;
};

export default function TicketEvidenceGallery({ evidence, token, title = "Images" }: Props) {
  if (evidence.length === 0) {
    return null;
  }

  return (
    <div className="ticket-evidence">
      <strong>{title}</strong>
      <div className="ticket-evidence-grid">
        {evidence.map((item) => (
          <figure key={item.evidence_id} className="ticket-evidence-item">
            {isImageEvidence(item.content_type, item.file_path) ? (
              <a href={evidenceImageUrl(item.evidence_id, token)} target="_blank" rel="noreferrer">
                <img
                  src={evidenceImageUrl(item.evidence_id, token)}
                  alt={item.file_path}
                  loading="lazy"
                />
              </a>
            ) : (
              <div className="ticket-evidence-fallback">{item.file_path}</div>
            )}
            <figcaption>{item.file_path}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}
