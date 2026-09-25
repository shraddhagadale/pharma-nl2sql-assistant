import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { ChatResponse, UserContext } from "./types";

const ram: UserContext = {
  user_id: "U009",
  email: "amy.nguyen@novapharma.com",
  full_name: "Amy Nguyen",
  role: "ram",
  territory_name: "New York Metro",
  region_name: "Northeast",
  can_view_wac: false
};

const executive: UserContext = {
  user_id: "U001",
  email: "elena.vasquez@novapharma.com",
  full_name: "Elena Vasquez",
  role: "exec",
  territory_name: null,
  region_name: null,
  can_view_wac: true
};

const answer: ChatResponse = {
  status: "answered",
  answer: "Paid demand is 1,240 pack units.",
  columns: ["drug_name", "pack_units"],
  rows: [{ drug_name: "ZENOVAX", pack_units: "1240.000" }],
  assumptions: ["Showing results for your assigned territory: New York Metro."],
  sql: "SELECT SUM(pack_units) FROM sales LIMIT 100",
  request_id: "12345678-abcd"
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function mockApplicationApi(chatResponse: Response = jsonResponse(answer)) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/demo/users")) return jsonResponse([ram, executive]);
    if (path.endsWith("/demo/session") && (!init?.method || init.method === "GET")) {
      return jsonResponse({ detail: "Not authenticated" }, 401);
    }
    if (path.endsWith("/demo/session") && init?.method === "POST") return jsonResponse(ram);
    if (path.endsWith("/chat")) return chatResponse;
    throw new Error(`Unexpected request: ${path}`);
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("analytics chat", () => {
  it("selects a database-backed user and renders a structured answer", async () => {
    const fetchMock = mockApplicationApi();
    render(<App />);

    const userSelect = await screen.findByLabelText("View as");
    fireEvent.change(userSelect, { target: { value: "U009" } });

    expect(await screen.findByText("New York Metro")).toBeInTheDocument();
    expect(screen.getByText("Restricted")).toBeInTheDocument();

    const input = screen.getByLabelText("Ask a pharmaceutical sales question");
    fireEvent.change(input, { target: { value: "Show Zenovax paid demand" } });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));

    expect(await screen.findByText("Paid demand is 1,240 pack units.")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Drug Name" })).toBeInTheDocument();
    expect(screen.getByText("ZENOVAX")).toBeInTheDocument();
    expect(screen.getByText("1,240")).toBeInTheDocument();
    expect(screen.queryByText(/scope and assumptions/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/request 12345678/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Validated SQL")).not.toBeInTheDocument();
    expect(screen.queryByText("Diagnostic SQL")).not.toBeInTheDocument();

    const chatCall = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/chat"));
    expect(chatCall).toBeDefined();
    expect(JSON.parse(String(chatCall?.[1]?.body))).toMatchObject({
      question: "Show Zenovax paid demand",
      conversation: [],
      include_sql: false
    });
  });

  it("shows a safe model-configuration message without exposing server details", async () => {
    mockApplicationApi(
      jsonResponse(
        { detail: "The analytics model is not configured or temporarily unavailable." },
        503
      )
    );
    render(<App />);

    fireEvent.change(await screen.findByLabelText("View as"), { target: { value: "U009" } });
    await screen.findByText("New York Metro");
    fireEvent.click(screen.getByRole("button", { name: /show paid demand for the last 3 months/i }));

    expect(
      await screen.findByText(
        "The analytics assistant is temporarily unavailable. Please try again later."
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/server-side model key/i)).not.toBeInTheDocument();
  });

  it("carries only the bounded prior conversation into a follow-up", async () => {
    const fetchMock = mockApplicationApi();
    render(<App />);

    fireEvent.change(await screen.findByLabelText("View as"), { target: { value: "U009" } });
    await screen.findByText("New York Metro");
    fireEvent.click(screen.getByRole("button", { name: /show paid demand for the last 3 months/i }));
    await screen.findByText("Paid demand is 1,240 pack units.");

    const input = screen.getByLabelText("Ask a pharmaceutical sales question");
    fireEvent.change(input, { target: { value: "What about last month?" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });

    await waitFor(() => {
      const chatCalls = fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/chat"));
      expect(chatCalls).toHaveLength(2);
      const followUp = JSON.parse(String(chatCalls[1][1]?.body));
      expect(followUp.conversation).toEqual([
        { role: "user", content: "Show paid demand for the last 3 months" },
        { role: "assistant", content: "Paid demand is 1,240 pack units." }
      ]);
    });
  });

  it("retries the exact failed request without adding error text to the conversation", async () => {
    let chatAttempts = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.endsWith("/demo/users")) return jsonResponse([ram]);
      if (path.endsWith("/demo/session") && (!init?.method || init.method === "GET")) {
        return jsonResponse({ detail: "Not authenticated" }, 401);
      }
      if (path.endsWith("/demo/session") && init?.method === "POST") {
        return jsonResponse(ram);
      }
      if (path.endsWith("/chat")) {
        chatAttempts += 1;
        if (chatAttempts <= 3) {
          return new Response(
            JSON.stringify({ detail: "This analysis is taking longer than expected." }),
            {
              status: 504,
              headers: {
                "Content-Type": "application/json",
                "X-Request-ID": "gateway-timeout-1"
              }
            }
          );
        }
        return jsonResponse(answer);
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<App />);
    fireEvent.change(await screen.findByLabelText("View as"), { target: { value: "U009" } });
    await screen.findByText("New York Metro");
    fireEvent.click(screen.getByRole("button", { name: /show paid demand for the last 3 months/i }));

    expect(
      await screen.findByText(
        "That analysis took longer than expected. Retry the same request when you're ready."
      )
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry analysis" }));
    expect(await screen.findByText("Paid demand is 1,240 pack units.")).toBeInTheDocument();

    const chatCalls = fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/chat"));
    expect(chatCalls).toHaveLength(4);
    expect(String(chatCalls[1][1]?.body)).toEqual(String(chatCalls[0][1]?.body));
    expect(String(chatCalls[2][1]?.body)).toEqual(String(chatCalls[0][1]?.body));
    expect(String(chatCalls[3][1]?.body)).toEqual(String(chatCalls[0][1]?.body));
    expect(JSON.parse(String(chatCalls[3][1]?.body)).conversation).toEqual([]);
  });

  it("recovers from one transient chat failure before showing an error", async () => {
    let chatAttempts = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.endsWith("/demo/users")) return jsonResponse([ram]);
      if (path.endsWith("/demo/session") && (!init?.method || init.method === "GET")) {
        return jsonResponse({ detail: "Not authenticated" }, 401);
      }
      if (path.endsWith("/demo/session") && init?.method === "POST") {
        return jsonResponse(ram);
      }
      if (path.endsWith("/chat")) {
        chatAttempts += 1;
        return chatAttempts === 1
          ? jsonResponse({ detail: "The analytics model is temporarily unavailable." }, 503)
          : jsonResponse(answer);
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<App />);
    fireEvent.change(await screen.findByLabelText("View as"), { target: { value: "U009" } });
    await screen.findByText("New York Metro");
    fireEvent.click(screen.getByRole("button", { name: /show paid demand for the last 3 months/i }));

    expect(await screen.findByText("Paid demand is 1,240 pack units.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry analysis" })).not.toBeInTheDocument();
    const chatCalls = fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/chat"));
    expect(chatCalls).toHaveLength(2);
    expect(String(chatCalls[1][1]?.body)).toEqual(String(chatCalls[0][1]?.body));
  });

  it("retries a validator-rejected plan without weakening the validator", async () => {
    let chatAttempts = 0;
    const rejected: ChatResponse = {
      status: "rejected",
      answer: "I couldn't complete that analysis as asked. Please rephrase it.",
      columns: [],
      rows: [],
      assumptions: [],
      sql: null,
      request_id: "rejected-plan-1"
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.endsWith("/demo/users")) return jsonResponse([ram]);
      if (path.endsWith("/demo/session") && (!init?.method || init.method === "GET")) {
        return jsonResponse({ detail: "Not authenticated" }, 401);
      }
      if (path.endsWith("/demo/session") && init?.method === "POST") {
        return jsonResponse(ram);
      }
      if (path.endsWith("/chat")) {
        chatAttempts += 1;
        return jsonResponse(chatAttempts === 1 ? rejected : answer);
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<App />);
    fireEvent.change(await screen.findByLabelText("View as"), { target: { value: "U009" } });
    await screen.findByText("New York Metro");
    fireEvent.click(screen.getByRole("button", { name: /show paid demand for the last 3 months/i }));

    expect(await screen.findByText("Paid demand is 1,240 pack units.")).toBeInTheDocument();
    expect(screen.queryByText(/rephrase it/i)).not.toBeInTheDocument();
    const chatCalls = fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/chat"));
    expect(chatCalls).toHaveLength(2);
    expect(String(chatCalls[1][1]?.body)).toEqual(String(chatCalls[0][1]?.body));
  });
});
