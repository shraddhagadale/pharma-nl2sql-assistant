import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, createSession, listDemoUsers, readSession, sendChat } from "./api";
import { ChatMessage } from "./components/ChatMessage";
import { UserPanel } from "./components/UserPanel";
import type {
  ChatMessage as Message,
  ConversationTurn,
  UserContext,
  UserRole
} from "./types";

const SUGGESTIONS: Record<UserRole, string[]> = {
  ram: [
    "Show paid demand for the last 3 months",
    "What is market share by territory for R3M?",
    "How much free drug did we provide in the last 4 weeks?",
    "Show pricing for last month"
  ],
  director: [
    "Rank the top accounts by pack units last quarter",
    "Show monthly equivalents for the last 6 months",
    "Compare paid demand for R3M versus prior R3M",
    "Show market share by region for the last 3 months"
  ],
  exec: [
    "What was gross revenue last month?",
    "Show market share by product for the last 3 months",
    "Rank the top accounts by paid demand last quarter",
    "Compare paid demand for R3M versus prior R3M"
  ]
};

let messageSequence = 0;

function nextMessageId(): string {
  messageSequence += 1;
  return `message-${messageSequence}`;
}

function safeErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 503) {
      return "The analytics model is not configured yet. Add the server-side model key and try again.";
    }
    if (error.status === 401) return "Your demo session expired. Select a user and try again.";
    return error.message;
  }
  return "The analytics service could not be reached. Please try again.";
}

function conversationFrom(messages: Message[]): ConversationTurn[] {
  return messages
    .map((message): ConversationTurn => ({
      role: message.role,
      content: message.content.slice(0, 1_000)
    }))
    .slice(-6);
}

export function App() {
  const [users, setUsers] = useState<UserContext[]>([]);
  const [currentUser, setCurrentUser] = useState<UserContext | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [diagnosticSql, setDiagnosticSql] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [selectingUser, setSelectingUser] = useState(false);
  const [sending, setSending] = useState(false);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const endOfConversation = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    void Promise.all([listDemoUsers(), readSession()])
      .then(([availableUsers, session]) => {
        if (!active) return;
        setUsers(availableUsers);
        setCurrentUser(session);
      })
      .catch((error: unknown) => {
        if (active) setBannerError(safeErrorMessage(error));
      })
      .finally(() => {
        if (active) setInitializing(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    endOfConversation.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, sending]);

  const suggestions = useMemo(
    () => (currentUser ? SUGGESTIONS[currentUser.role] : []),
    [currentUser]
  );

  async function selectUser(userId: string) {
    if (!userId || userId === currentUser?.user_id) return;
    setSelectingUser(true);
    setBannerError(null);
    try {
      const user = await createSession(userId);
      setCurrentUser(user);
      setMessages([]);
      setQuestion("");
    } catch (error) {
      setBannerError(safeErrorMessage(error));
    } finally {
      setSelectingUser(false);
    }
  }

  async function submitQuestion(rawQuestion: string) {
    const content = rawQuestion.trim();
    if (!content || !currentUser || sending) return;

    const userMessage: Message = { id: nextMessageId(), role: "user", content };
    const priorConversation = conversationFrom(messages);
    setMessages((current) => [...current, userMessage]);
    setQuestion("");
    setSending(true);
    setBannerError(null);

    try {
      const response = await sendChat({
        question: content,
        conversation: priorConversation,
        include_sql: diagnosticSql
      });
      setMessages((current) => [
        ...current,
        {
          id: nextMessageId(),
          role: "assistant",
          content: response.answer,
          response
        }
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: nextMessageId(),
          role: "assistant",
          content: safeErrorMessage(error),
          error: true
        }
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="app-shell">
      <UserPanel
        users={users}
        currentUser={currentUser}
        disabled={initializing || selectingUser || sending}
        diagnosticSql={diagnosticSql}
        onSelect={(userId) => void selectUser(userId)}
        onDiagnosticChange={setDiagnosticSql}
      />

      <main className="workspace">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">Conversational intelligence</p>
            <h1>Ask your commercial data</h1>
          </div>
          <div className="connection-state">
            <span aria-hidden="true" />
            RLS protected
          </div>
        </header>

        {bannerError ? (
          <div className="banner-error" role="alert">
            {bannerError}
          </div>
        ) : null}

        <section className="conversation" aria-label="Analytics conversation">
          {initializing ? (
            <div className="center-state" role="status">
              <div className="loading-ring" aria-hidden="true" />
              <p>Connecting to secure analytics…</p>
            </div>
          ) : !currentUser ? (
            <div className="welcome-state">
              <span className="welcome-kicker">Database-enforced permissions</span>
              <h2>Start with a demo role</h2>
              <p>
                Choose a user to see how the same question is answered within executive,
                regional, or territory access.
              </p>
              <div className="welcome-flow" aria-label="Request flow">
                <span>Question</span><i aria-hidden="true">→</i>
                <span>Validated SQL</span><i aria-hidden="true">→</i>
                <span>RLS-scoped answer</span>
              </div>
            </div>
          ) : messages.length === 0 ? (
            <div className="starter-state">
              <div className="starter-icon" aria-hidden="true">N</div>
              <p className="eyebrow">Ready for {currentUser.full_name}</p>
              <h2>What would you like to understand?</h2>
              <p className="starter-copy">
                Ask about demand, accounts, products, market share, or reporting periods.
                Your database scope is applied automatically.
              </p>
              <div className="suggestion-grid">
                {suggestions.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    className="suggestion-card"
                    onClick={() => void submitQuestion(suggestion)}
                  >
                    <span>{suggestion}</span>
                    <b aria-hidden="true">↗</b>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="message-list" aria-live="polite">
              {messages.map((message) => <ChatMessage key={message.id} message={message} />)}
              {sending ? (
                <div className="thinking" role="status">
                  <span /><span /><span />
                  <p>Planning and validating the query…</p>
                </div>
              ) : null}
              <div ref={endOfConversation} />
            </div>
          )}
        </section>

        <footer className="composer-wrap">
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              void submitQuestion(question);
            }}
          >
            <label htmlFor="question" className="sr-only">Ask a pharmaceutical sales question</label>
            <textarea
              id="question"
              rows={1}
              maxLength={2_000}
              value={question}
              disabled={!currentUser || sending}
              placeholder={currentUser ? "Ask a follow-up or start a new analysis…" : "Select a demo user to begin"}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void submitQuestion(question);
                }
              }}
            />
            <button
              type="submit"
              className="send-button"
              disabled={!currentUser || !question.trim() || sending}
              aria-label="Send question"
            >
              <span aria-hidden="true">↑</span>
            </button>
          </form>
          <p className="composer-caption">
            AI-generated analysis is validated before execution. Verify important decisions.
          </p>
        </footer>
      </main>
    </div>
  );
}
