import type { AssistantMessage, ChatMessage as Message } from "../types";

const STATUS_LABELS = {
  answered: "Answered",
  clarification: "Needs clarification",
  no_data: "No matching data",
  denied: "Access limited",
  error: "Please try again",
  rejected: "Couldn't answer"
} as const;

function columnLabel(column: string): string {
  return column.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function displayValue(column: string, value: string | number | boolean | null): string {
  if (value === null) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString();
  if (
    /^-?\d+(?:\.\d+)?$/.test(value) &&
    !/(^|_)(id|zip|ndc|period)($|_)/i.test(column)
  ) {
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });
  }
  return value;
}

function ResultTable({ message }: { message: AssistantMessage }) {
  const response = message.response;
  if (!response || response.columns.length === 0 || response.rows.length === 0) return null;

  return (
    <div className="result-table-wrap" tabIndex={0} aria-label="Query results">
      <table>
        <thead>
          <tr>
            {response.columns.map((column) => (
              <th key={column} scope="col">
                {columnLabel(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {response.rows.map((row, rowIndex) => (
            <tr key={`${message.id}-${rowIndex}`}>
              {response.columns.map((column) => (
                <td key={column}>{displayValue(column, row[column] ?? null)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ChatMessage({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <article className="message message-user">
        <div className="message-label">You</div>
        <div className="user-bubble">{message.content}</div>
      </article>
    );
  }

  const status = message.response?.status;
  return (
    <article className={`message message-assistant${message.error ? " message-error" : ""}`}>
      <div className="assistant-heading">
        <div className="assistant-avatar" aria-hidden="true">N</div>
        <div>
          <div className="message-label">Nova analyst</div>
          {status ? <span className={`status-badge status-${status}`}>{STATUS_LABELS[status]}</span> : null}
        </div>
      </div>
      <div className="assistant-body">
        <p className="answer-text">{message.content}</p>
        <ResultTable message={message} />

        {message.response?.assumptions.length ? (
          <details className="answer-details">
            <summary>Scope and assumptions ({message.response.assumptions.length})</summary>
            <ul>
              {message.response.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          </details>
        ) : null}

        {message.response?.sql ? (
          <details className="answer-details sql-details">
            <summary>Validated SQL</summary>
            <pre><code>{message.response.sql}</code></pre>
          </details>
        ) : null}

        {message.response ? (
          <span className="request-id">Request {message.response.request_id.slice(0, 8)}</span>
        ) : null}
      </div>
    </article>
  );
}
