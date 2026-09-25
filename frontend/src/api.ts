import type { ApiErrorBody, ChatRequest, ChatResponse, UserContext } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId: string | null
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers
    }
  });

  if (!response.ok) {
    let message = "The request could not be completed.";
    try {
      const body = (await response.json()) as ApiErrorBody;
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Keep the safe generic message when the server does not return JSON.
    }
    throw new ApiError(message, response.status, response.headers.get("X-Request-ID"));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function listDemoUsers(): Promise<UserContext[]> {
  return request<UserContext[]>("/api/v1/demo/users");
}

export async function readSession(): Promise<UserContext | null> {
  try {
    return await request<UserContext>("/api/v1/demo/session");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export function createSession(userId: string): Promise<UserContext> {
  return request<UserContext>("/api/v1/demo/session", {
    method: "POST",
    body: JSON.stringify({ user_id: userId })
  });
}

export function deleteSession(): Promise<void> {
  return request<void>("/api/v1/demo/session", { method: "DELETE" });
}

export async function sendChat(payload: ChatRequest): Promise<ChatResponse> {
  const body = JSON.stringify(payload);
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      return await request<ChatResponse>("/api/v1/chat", {
        method: "POST",
        body
      });
    } catch (error) {
      const retryable =
        error instanceof ApiError && [502, 503, 504].includes(error.status);
      if (!retryable || attempt === 1) throw error;
    }
  }
  throw new Error("The analytics request could not be completed.");
}
