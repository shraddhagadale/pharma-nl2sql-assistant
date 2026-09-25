# Analytics chat frontend

Phase 8 adds a React and TypeScript interface for the existing session and chat
APIs. The browser remains an untrusted presentation layer: it selects a demo
identity and sends natural language, while the backend reloads authorization
context and PostgreSQL enforces row and column access.

## Product flow

1. On startup, the UI loads the database-backed demo-user list and attempts to
   restore the signed session cookie.
2. Selecting a user creates a backend session using only `user_id`. Role, scope,
   and WAC access displayed in the UI come from the server response.
3. Role-aware starter questions make demand, market-share, comparison, account,
   and pricing behavior easy to demonstrate.
4. The composer sends the question and at most twelve prior user/assistant turns.
5. Answers render as plain text plus an optional bounded table. Model output is
   never inserted as HTML.
6. Assumptions and database scope are visible in a disclosure. Validated SQL is
   requested and rendered only when the user enables **Diagnostic SQL** before
   submitting a question.
7. Denials, validator rejections, expired sessions, missing model configuration,
   and network failures receive distinct safe UI states.

Switching users clears the conversation so one role's prior context is not
carried into another role's session.

## Technology and serving model

The UI uses React 19, TypeScript, and Vite. The production image builds static
assets in Node and serves them through Nginx. Nginx proxies `/api`, `/health`,
and `/ready` to FastAPI, which keeps browser requests and the signed cookie on
one origin without adding a broad CORS policy.

This follows React's documented
[Vite setup](https://react.dev/learn/build-a-react-app-from-scratch#vite) and
Vite's recommendation to run `tsc --noEmit` separately because Vite transpiles
TypeScript but does not type-check it.

The Nginx response sets a same-origin Content Security Policy, denies framing,
and prevents MIME sniffing. Hashed assets are cached; `index.html` is not.

## Run with Docker

Copy `.env.example` to `.env`, add `PHARMA_OPENAI_API_KEY` for live model
answers, and start the full application profile:

```bash
docker compose --profile application up -d --build --wait
```

Open `http://localhost:3000`. FastAPI remains directly available on port 8000
for diagnostics. Without a model key, login and policy demonstrations still
work; ordinary analytics questions show the designed model-configuration state.

Run the same-origin container smoke test with:

```bash
./scripts/frontend_smoke_test.sh http://localhost:3000
```

## Local frontend development

With PostgreSQL and FastAPI running on their normal local ports:

```bash
cd frontend
npm install
npm run dev
```

Vite serves the development UI on `http://localhost:5173` and proxies API paths
to `http://localhost:8000`.

Quality commands:

```bash
npm run typecheck
npm run lint
npm run test:run
npm run build
```

The component tests cover database-backed user selection, scoped identity
rendering, table/assumption/SQL output, safe 503 handling, and bounded
conversation history in a follow-up request.
