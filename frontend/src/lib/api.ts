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
  role: "customer";
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

export type AdminProfile = {
  id: string;
  role: "admin";
  name: string;
  email: string;
  loyalty_tier: string;
  fraud_flag: boolean;
  chargeback_count: number;
  refund_count_last_12_months: number;
  lifetime_value: number;
  notes: string;
  orders: [];
};

export type CurrentUser = Customer | AdminProfile;

export type LoginResponse = {
  token: string;
  role: CurrentUser["role"];
  customer: CurrentUser;
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

export type EvidenceUpload = {
  file_name: string;
  content_type: string;
  size: number;
  data_base64?: string;
};

export type TicketEvidence = {
  evidence_id: string;
  type: string;
  file_path: string;
  content_type?: string | null;
  verified: boolean;
  uploaded_date: string;
};

export type ActiveTicket = {
  request_id: string;
  order_id: string;
  request_date: string;
  reason: string;
  customer_comment: string;
  requested_resolution: string;
  status: string;
  admin_message: string | null;
  total_amount: number;
  product_names: string;
  evidence: TicketEvidence[];
};

export type AdminTicket = ActiveTicket & {
  customer_id: string;
  customer_name: string;
  customer_email: string;
};

export type AssistantOption = {
  id: string;
  label: string;
  description?: string | null;
};

export type AssistantAction = {
  id: string;
  type:
    | "show_reason_options"
    | "upload_image"
    | "select_purchase"
    | "contact_support"
    | "collect_return_details";
  label: string;
  options: AssistantOption[];
  accept?: string | null;
  description_required: boolean;
  image_required: boolean;
  allow_multiple: boolean;
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

export function getMe(token: string): Promise<CurrentUser> {
  return request<CurrentUser>("/api/me", undefined, token);
}

export function getActiveTickets(token: string): Promise<ActiveTicket[]> {
  return request<{ tickets: ActiveTicket[] }>("/api/me/tickets", undefined, token).then(
    (response) => response.tickets,
  );
}

export function updateActiveTicket(
  token: string,
  requestId: string,
  payload: { description?: string; files?: EvidenceUpload[] },
): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/me/tickets/${requestId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  }, token);
}

export function cancelActiveTicket(token: string, requestId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/me/tickets/${requestId}/cancel`, {
    method: "POST",
  }, token);
}

export function getAdminTickets(token: string): Promise<AdminTicket[]> {
  return request<{ tickets: AdminTicket[] }>("/api/admin/tickets", undefined, token).then(
    (response) => response.tickets,
  );
}

export function approveAdminTicket(token: string, requestId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/admin/tickets/${requestId}/approve`, {
    method: "POST",
  }, token);
}

export function rejectAdminTicket(
  token: string,
  requestId: string,
  reason: string,
): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/admin/tickets/${requestId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  }, token);
}

export function getAssistantSession(token: string): Promise<Pick<InteractiveChatResponse, "messages" | "actions" | "decision">> {
  return request<Pick<InteractiveChatResponse, "messages" | "actions" | "decision">>(
    "/api/me/assistant/session",
    undefined,
    token,
  );
}

export function restartAssistantChat(token: string): Promise<{ status: string }> {
  return request<{ status: string }>("/api/me/assistant/restart", {
    method: "POST",
  }, token);
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
  payload: {
    message?: string;
    selected_option?: string;
    action_id?: string;
    description?: string;
    files?: EvidenceUpload[];
  },
): Promise<InteractiveChatResponse> {
  return request<InteractiveChatResponse>("/api/me/assistant/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export function uploadAssistantImage(token: string, file: File, dataBase64: string): Promise<InteractiveChatResponse> {
  return request<InteractiveChatResponse>("/api/me/assistant/upload", {
    method: "POST",
    body: JSON.stringify({
      file_name: file.name,
      content_type: file.type,
      size: file.size,
      data_base64: dataBase64,
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
