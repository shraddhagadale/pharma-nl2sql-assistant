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
  rows: [{ drug_name: "ZENOVAX", pack_units: 1240 }],
  assumptions: ["Results are limited by database RLS to New York Metro."],
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

    fireEvent.click(screen.getByRole("switch", { name: "Diagnostic SQL" }));
    const input = screen.getByLabelText("Ask a pharmaceutical sales question");
    fireEvent.change(input, { target: { value: "Show Zenovax paid demand" } });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));

    expect(await screen.findByText("Paid demand is 1,240 pack units.")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Drug Name" })).toBeInTheDocument();
    expect(screen.getByText("ZENOVAX")).toBeInTheDocument();
    expect(screen.getByText("1,240")).toBeInTheDocument();
    expect(screen.getByText("Validated SQL")).toBeInTheDocument();

    const chatCall = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/chat"));
    expect(chatCall).toBeDefined();
    expect(JSON.parse(String(chatCall?.[1]?.body))).toMatchObject({
      question: "Show Zenovax paid demand",
      conversation: [],
      include_sql: true
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
        "The analytics model is not configured yet. Add the server-side model key and try again."
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/temporarily unavailable/i)).not.toBeInTheDocument();
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
});
