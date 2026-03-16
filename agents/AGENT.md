# Agents

AI-powered log analysis pipeline for Webex Calling microservice logs (Mobius, SSE, MSE, WxCAS). Uses Google ADK with LiteLLM (Azure OpenAI).

## Folder layout

```
agents/
├── .env.example           # Template for all env vars
├── requirements.txt       # Python dependencies
├── oauth_context.py       # Per-request OAuth token via contextvars
│
├── root/                  # Entry point: routes queries + chat
├── router/                # Intent routing (structured JSON / LLM fallback)
├── pipeline/              # Sequential: search -> analyze -> visualize
├── search/                # BFS search + ID extraction (OpenSearch direct)
├── analyze/               # Analysis routing (calling vs contact center)
├── chat/                  # Conversational follow-up
└── visualize/             # PlantUML sequence diagram generation
```

## Agent dependency tree

```
root (entry point — APP_NAME in frontend)
├── router           → routes search vs chat vs re-search vs upload
│   ├── pipeline     → sequential: search -> analyze -> visualize
│   │   ├── search
│   │   ├── analyze  (calling_agent | contact_center_agent)
│   │   └── visualize
│   ├── analyze      (for upload-only mode)
│   └── visualize    (for upload-only mode)
└── chat             → follow-up questions on existing results
```

## Pipeline

1. **search** — BFS graph traversal across OpenSearch indexes. Extracts IDs via LLM, follows new IDs, falls back to device_id when stuck.
2. **analyze** — Routes to `calling_agent` or `contact_center_agent` based on service type. Uses ADK skills for error lookups and architecture references.
3. **visualize** — Generates PlantUML sequence diagrams from analysis context.

## Conventions

- All agents load `agents/.env` via `Path(__file__).parent.parent / ".env"`
- Models use `SessionLiteLlm` with per-request OAuth from contextvars
- State contract: search sets keys consumed by analyze. Changing key names must be done in both.
- Skills live under `analyze/skills/<name>/` with `SKILL.md` + `references/`

## Frontend integration

- **App name**: `root` (set in `frontend/lib/session-manager.ts`)
- **OAuth**: Frontend passes `oauth_token` in session state
- Frontend parses events by `author` field — keep agent names stable
