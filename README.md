# Microservice Log Analyzer

AI-powered log analysis tool for Webex Calling microservice logs (Mobius, SSE, MSE, WxCAS). Uses Google ADK (Agent Development Kit) with LiteLLM (Azure OpenAI) to search OpenSearch indexes, analyze HTTP/SIP/WebRTC flows, and produce markdown analysis + PlantUML sequence diagrams.

## Repository Structure

```
├── agents/                 # Python ADK agents (backend)
│   ├── root/               # Entry point: routes queries + chat
│   ├── router/             # Intent routing (structured JSON / LLM fallback)
│   ├── pipeline/           # Sequential: search -> analyze -> visualize
│   ├── search/             # BFS search + ID extraction (OpenSearch direct)
│   ├── analyze/            # Analysis with skill-based routing
│   ├── chat/               # Conversational follow-up
│   ├── visualize/          # PlantUML sequence diagram generation
│   └── oauth_context.py    # Per-request OAuth via contextvars
├── frontend/               # Next.js frontend
└── .github/workflows/      # GitHub Pages deployment
```

## Prerequisites

- Python 3.10+
- Node.js 18+ and pnpm
- Access to Webex OpenSearch clusters (OAuth credentials)
- Azure OpenAI endpoint (LLM proxy)

## Setup

### 1. Clone and create virtual environment

```bash
git clone <repo-url>
cd microservice-log-analyzer

python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Python dependencies

```bash
pip install -r agents/requirements.txt
```

### 3. Configure backend environment

```bash
cp agents/.env.example agents/.env
```

Edit `agents/.env` and fill in:

| Variable Group | Description |
|---|---|
| `OPENSEARCH_OAUTH_*` | Production OpenSearch OAuth credentials (name, password, client ID/secret, scope, token URLs) |
| `OPENSEARCH_OAUTH_*_INT` | Integration environment OpenSearch credentials (same fields with `_INT` suffix) |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI proxy endpoint |
| `AZURE_API_VERSION` | Azure OpenAI API version |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key (or leave empty if using LLM OAuth) |
| `LLM_OAUTH_*` | LLM proxy machine account OAuth credentials (identity broker URL, org ID, account name/UUID/password, client ID/secret, scope) |

### 4. Start the backend

```bash
cd agents
adk web
```

The ADK server starts on `http://127.0.0.1:8000`. The entry point agent is `root`.

### 5. Configure frontend environment

```bash
cp frontend/.env.example frontend/.env.local
```

Edit `frontend/.env.local` and fill in:

| Variable | Description |
|---|---|
| `WEBEX_CLIENT_ID` | Webex OAuth integration client ID |
| `WEBEX_CLIENT_SECRET` | Webex OAuth integration client secret |
| `WEBEX_REDIRECT_URI` | OAuth callback URL (default: `http://localhost:3000/api/auth/callback`) |
| `NEXT_PUBLIC_ADK_API_URL` | Backend URL (default: `http://127.0.0.1:8000`) |

### 6. Start the frontend

```bash
cd frontend
pnpm install
pnpm dev
```

The UI starts on `http://localhost:3000`.

### 7. Sign in and search

1. Open `http://localhost:3000`
2. Sign in with Webex (OAuth flow)
3. Paste a tracking ID, session ID, call ID, or any identifier
4. The pipeline runs: search (BFS) -> analysis -> sequence diagram

## How It Works

### Search

BFS graph traversal across OpenSearch indexes:

1. **Parse** the user's query to extract identifiers, environment, and region
2. **Search** OpenSearch indexes based on ID type (Mobius, wxcalling, etc.)
3. **Extract** new IDs from search results via LLM
4. **Repeat** with newly discovered IDs until no new IDs are found or max depth is reached
5. Falls back to **device_id** search when no other new IDs are found at a depth level

Supports: tracking IDs, session IDs, mobius call IDs, SIP call IDs, SSE call IDs, trace IDs, device IDs. Searches both production and integration environments, US and EU regions.

### Analysis

Routes to specialized sub-agents based on service type:
- **calling_agent**: WebRTC Calling flow analysis (HTTP, SIP, media)
- **contact_center_agent**: Contact Center flow analysis

Uses ADK skills for Mobius error lookups, architecture references, and SIP flow knowledge.

### Visualization

Generates PlantUML sequence diagrams from the analysis context showing service interactions, message flows, and error points.

## GitHub Pages Deployment

The frontend can be deployed to GitHub Pages via the included workflow:

1. Set a repo variable `NEXT_PUBLIC_ADK_API_URL` to your backend URL (e.g. ngrok)
2. Push to `main` or trigger the workflow manually
3. In GitHub Pages settings, choose Source: GitHub Actions
