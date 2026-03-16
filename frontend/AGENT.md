# Log Analyzer Frontend — AI context for the UI

Use this file when working in the `frontend/` folder. It describes structure, conventions, and how the UI talks to the agents.

---

## Purpose

Next.js app that provides the **UI for the microservice log analyzer**: search form, session management with the ADK backend, and results (analysis, raw logs, sequence diagram). It targets Webex microservice log analysis (Mobius, SSE, MSE, WxCAS, etc.).

---

## Stack

- **Framework**: Next.js 14 (App Router).
- **Language**: TypeScript.
- **Styling**: Tailwind CSS.
- **UI primitives**: Radix UI (shadcn-style components under `components/ui/`).
- **Diagram rendering**: Mermaid (for sequence diagram from agent output).
- **PWA**: `@ducanh2912/next-pwa`; offline fallback page at `app/offline/page.tsx`.
- **Package manager**: pnpm.

---

## Folder layout

```
frontend/
├── AGENT.md                 # This file
├── .env.local               # Local env (not committed; copy from .env.example)
├── .env.example             # Template for Webex OAuth + ADK URL
├── app/
│   ├── page.tsx             # Main page: SearchForm + ResultsTabs, session + event handling
│   ├── layout.tsx           # Root layout
│   ├── api/auth/            # Webex OAuth callback + login routes
│   └── offline/
│       └── page.tsx         # PWA offline fallback
├── components/
│   ├── search-form.tsx      # Search params: field, value, env, region
│   ├── results-tabs.tsx     # Tabs: Analysis | Raw Logs | Charts
│   ├── analysis-view.tsx    # Renders markdown analysis
│   ├── chat-panel.tsx       # Chat interface for follow-up questions
│   ├── chat-view.tsx        # Chat message rendering
│   ├── logs-view.tsx        # Raw log list/cards
│   ├── charts-view.tsx      # Renders PlantUML/Mermaid diagram
│   ├── file-upload.tsx      # SDK log file upload
│   ├── log-card.tsx         # Single log card
│   ├── log-detail-modal.tsx
│   ├── connection-status.tsx
│   └── ui/                  # Radix-based primitives (button, card, tabs, dialog, etc.)
├── lib/
│   ├── session-manager.ts   # ADK session + sendMessage (APP_NAME: root)
│   └── utils.ts
├── public/                  # PWA assets
├── next.config.mjs          # Next config + PWA (withPWA)
└── package.json
```

---

## Data flow

1. **OAuth**: User signs in via Webex OAuth (`/api/auth/login` -> callback). Token stored in session state.
2. **Session**: `SessionManager` creates a session via `POST .../apps/root/users/{userId}/sessions`. `NEXT_PUBLIC_ADK_API_URL` defaults to `http://127.0.0.1:8000`.
3. **Search**: User submits the form or types a message -> `sessionManager.sendMessage(text)` -> POST `${ADK_API_URL}/run`.
4. **Response**: API returns a list of **events**. Each event has `author` and `content.parts`.
5. **Parsing** (in `app/page.tsx`): Events are parsed by `author` field to extract logs, analysis text, and diagram code.

---

## Conventions

- **Env**: Backend URL via `NEXT_PUBLIC_ADK_API_URL` (default `http://127.0.0.1:8000`). Webex OAuth creds in `.env.local`.
- **Imports**: Use `@/` for app and components (e.g. `@/components/search-form`, `@/lib/session-manager`).
- **Client components**: Main pages and forms use `"use client"`; keep data fetching and event handling in the client.
- **Agent names**: Frontend logic depends on `author` values. Changing agent names in the backend requires updating `app/page.tsx`.

---

## Key files to touch when...

- **Changing how run results are parsed**: `app/page.tsx` (event loop, `author` checks).
- **Changing search options or form fields**: `components/search-form.tsx`.
- **Changing layout of results (tabs, views)**: `components/results-tabs.tsx`, `analysis-view.tsx`, `logs-view.tsx`, `charts-view.tsx`.
- **Changing backend URL or session/run API**: `lib/session-manager.ts`.
- **Adding UI components**: Prefer `components/ui/` for primitives; keep feature components in `components/`.

---

## Backend (agents) contract

- **App name**: `root` (must match what ADK serves).
- **OAuth**: Token passed in session state as `oauth_token`.
- **Events**: Frontend expects events with recognizable `author` values and `content.parts` containing `text`. Keep agent names stable or update the frontend parsing accordingly.

For agent-side context and pipeline details, see **`agents/AGENT.md`**.
