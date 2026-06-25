export function customerFirstName(fullName: string): string {
  const trimmed = fullName.trim();
  if (!trimmed) {
    return "there";
  }
  return trimmed.split(/\s+/)[0] ?? "there";
}

export function chatGreeting(fullName: string): string {
  return `Hi ${customerFirstName(fullName)}, how can I help you today?`;
}

export function chatInputPlaceholder(fullName: string): string {
  return chatGreeting(fullName);
}

export function chatEmptyStateHint(fullName: string): string {
  const firstName = customerFirstName(fullName);
  return `Ask about returns, exchanges, your orders, or Shopward policy, ${firstName}.`;
}
