import { AssistantAction } from "../lib/api";

type Props = {
  action: AssistantAction;
  disabled?: boolean;
  onSelect: (optionId: string) => void;
};

export default function ReasonOptions({ action, disabled, onSelect }: Props) {
  return (
    <div className="assistant-action-card">
      <strong>{action.label}</strong>
      <div className="reason-options">
        {action.options.map((option) => (
          <label key={option.id} className="radio-option">
            <input
              type="radio"
              name={action.id}
              disabled={disabled}
              onChange={() => onSelect(option.id)}
            />
            <span>
              <strong>{option.label}</strong>
              {option.description ? <small>{option.description}</small> : null}
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}
