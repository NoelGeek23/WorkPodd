import { useState } from "react";
import { AssistantAction } from "../lib/api";

type Props = {
  action: AssistantAction;
  disabled?: boolean;
  onSubmit: (orderId: string) => void;
};

export default function PurchaseSelector({ action, disabled, onSubmit }: Props) {
  const [selectedOrderId, setSelectedOrderId] = useState("");

  return (
    <div className="assistant-action-card">
      <strong>{action.label}</strong>
      <div className="purchase-options">
        {action.options.map((option) => (
          <label key={option.id} className={`purchase-option ${selectedOrderId === option.id ? "selected" : ""}`}>
            <input
              type="checkbox"
              name={action.id}
              checked={selectedOrderId === option.id}
              disabled={disabled}
              onChange={() => setSelectedOrderId((current) => (current === option.id ? "" : option.id))}
            />
            <span>
              <strong>{option.label}</strong>
              {option.description ? <small>{option.description}</small> : null}
            </span>
          </label>
        ))}
      </div>
      <button
        type="button"
        className="secondary-button purchase-submit-button"
        disabled={disabled || !selectedOrderId}
        onClick={() => onSubmit(selectedOrderId)}
      >
        Continue with selected purchase
      </button>
    </div>
  );
}
