export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type OrderItem = {
  sku: string;
  name: string;
  category: string;
  product_type: string;
  price: number;
  quantity: number;
  condition: string;
  final_sale: boolean;
  digital_download: boolean;
  subscription_product: boolean;
  hygiene_sensitive: boolean;
};

export type Order = {
  id: string;
  status: string;
  total: number;
  delivered_date: string | null;
  tracking_status: string;
  items: OrderItem[];
};

export type Customer = {
  id: string;
  name: string;
  email: string;
  loyalty_tier: string;
  fraud_flag: boolean;
  chargeback_count: number;
  refund_count_last_12_months: number;
  lifetime_value: number;
  notes: string;
  orders: Order[];
};

export type LoginResponse = {
  token: string;
  customer: Customer;
};

export type RefundDecision = {
  status: "approved" | "denied" | "escalated";
  customer_message: string;
  internal_reason: string;
  amount: number;
  order_id: string | null;
  policy_rules: string[];
  tool_calls: Array<{
    tool: string;
    input: Record<string, unknown>;
    output: Record<string, unknown>;
  }>;
};

export type ChatResponse = {
  reply: string;
  decision: RefundDecision;
};

export type AgentLogEvent = {
  id: string;
  timestamp: string;
  customer_id: string | null;
  order_id: string | null;
  stage: string;
  message: string;
  metadata: Record<string, unknown>;
};

export type RealtimeSession = {
  client_secret: { value?: string } | null;
  model: string;
  voice: string;
  instructions: string;
  note?: string | null;
};

export type PolicySection = {
  chunk_id: string;
  section_title: string;
  content: string;
};

export type AssistantOption = {
  id: string;
  label: string;
  description?: string | null;
};

export type AssistantAction = {
  id: string;
  type: "show_reason_options" | "upload_image";
  label: string;
  options: AssistantOption[];
  accept?: string | null;
};

export type AssistantMessage = {
  role: "user" | "assistant";
  content: string;
};

export type InteractiveChatResponse = {
  messages: AssistantMessage[];
  actions: AssistantAction[];
  citations: Array<Record<string, unknown>>;
  decision: RefundDecision | null;
  memory: Record<string, unknown>;
};

async function request<T>(path: string, options?: RequestInit, token?: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function getMe(token: string): Promise<Customer> {
  return request<Customer>("/api/me", undefined, token);
}

export function logout(token: string): Promise<{ status: string }> {
  return request<{ status: string }>("/api/auth/logout", { method: "POST" }, token);
}

export function getCustomers(token: string): Promise<Customer[]> {
  return request<Customer[]>("/api/customers", undefined, token);
}

export function sendChat(
  token: string,
  message: string,
  orderId?: string | null,
): Promise<ChatResponse> {
  return request<ChatResponse>("/api/me/chat", {
    method: "POST",
    body: JSON.stringify({ order_id: orderId, message }),
  }, token);
}

export function sendAssistantChat(
  token: string,
  payload: { message?: string; selected_option?: string; action_id?: string },
): Promise<InteractiveChatResponse> {
  return request<InteractiveChatResponse>("/api/me/assistant/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export function uploadAssistantImage(token: string, file: File): Promise<InteractiveChatResponse> {
  return request<InteractiveChatResponse>("/api/me/assistant/upload", {
    method: "POST",
    body: JSON.stringify({
      file_name: file.name,
      content_type: file.type,
      size: file.size,
    }),
  }, token);
}

export function getPolicySections(): Promise<PolicySection[]> {
  return request<{ sections: PolicySection[] }>("/api/policy/sections").then(
    (response) => response.sections,
  );
}

export function createRealtimeSession(): Promise<RealtimeSession> {
  return request<RealtimeSession>("/api/voice/session", { method: "POST" });
}

export function subscribeToAgentLogs(
  onLog: (event: AgentLogEvent) => void,
  token?: string,
): EventSource {
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  const source = new EventSource(`${API_BASE_URL}/api/agent/logs${query}`);
  source.onmessage = (event) => onLog(JSON.parse(event.data) as AgentLogEvent);
  return source;
}
