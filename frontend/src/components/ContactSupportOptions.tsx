import { AssistantAction } from "../lib/api";

type Props = {
  action: AssistantAction;
};

export default function ContactSupportOptions({ action }: Props) {
  return (
    <div className="assistant-action-card contact-support-card">
      <strong>{action.label}</strong>
      <div className="contact-support-actions">
        {action.options.map((option) => (
          <a key={option.id} className="contact-support-button" href={`/under-development?source=${option.id}`}>
            <span>{option.label}</span>
            {option.description ? <small>{option.description}</small> : null}
          </a>
        ))}
      </div>
    </div>
  );
}
