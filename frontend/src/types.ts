export type UserRole = "exec" | "director" | "ram";

export interface UserContext {
  user_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  territory_name: string | null;
  region_name: string | null;
  can_view_wac: boolean;
}

export type ConversationRole = "user" | "assistant";

export interface ConversationTurn {
  role: ConversationRole;
  content: string;
}

export type ChatStatus =
  | "answered"
  | "clarification"
  | "no_data"
  | "denied"
  | "error"
  | "rejected";
export type JsonScalar = string | number | boolean | null;

export interface ChatResponse {
  status: ChatStatus;
  answer: string;
  columns: string[];
  rows: Array<Record<string, JsonScalar>>;
  assumptions: string[];
  sql: string | null;
  request_id: string;
}

export interface ChatRequest {
  question: string;
  conversation: ConversationTurn[];
  include_sql: boolean;
}

export interface ApiErrorBody {
  detail?: string;
}

export interface UserMessage {
  id: string;
  role: "user";
  content: string;
}

export interface AssistantMessage {
  id: string;
  role: "assistant";
  content: string;
  response?: ChatResponse;
  error?: boolean;
}

export type ChatMessage = UserMessage | AssistantMessage;
