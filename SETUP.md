# Setup Guide

Step-by-step instructions to set up the Microservice Log Analyzer from scratch. This guide is written so that an AI assistant (like Claude) can follow it end-to-end.

## System Requirements

- **Python**: 3.10 or higher
- **Node.js**: 18 or higher
- **pnpm**: 8 or higher (install via `npm install -g pnpm` or `corepack enable`)
- **Git**: any recent version
- **OS**: macOS, Linux, or WSL on Windows

## Step 1: Clone the Repository

```bash
git clone <repo-url>
cd microservice-log-analyzer
```

## Step 2: Backend Setup (agents/)

### 2a. Create Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows
```

### 2b. Install Python dependencies

```bash
pip install --upgrade pip
pip install -r agents/requirements.txt
```

This installs:
- `google-adk` — Google Agent Development Kit (provides `adk` CLI)
- `litellm` — LLM proxy abstraction (routes to Azure OpenAI)
- `opensearch-py` — OpenSearch Python client
- `python-dotenv` — .env file loading
- `requests` — HTTP client (for OAuth token exchange)

### 2c. Create the backend .env file

```bash
cp agents/.env.example agents/.env
```

Edit `agents/.env` and fill in all values. The file has these sections:

#### Production OpenSearch OAuth Credentials

These authenticate against Webex OpenSearch clusters (production environment).

```
OPENSEARCH_OAUTH_TOKEN=            # Leave empty; auto-refreshed at runtime
OPENSEARCH_OAUTH_NAME=             # Machine account name (e.g. "svc-log-analyzer")
OPENSEARCH_OAUTH_PASSWORD=         # Machine account password
OPENSEARCH_OAUTH_CLIENT_ID=        # OAuth client ID for OpenSearch
OPENSEARCH_OAUTH_CLIENT_SECRET=    # OAuth client secret
OPENSEARCH_OAUTH_SCOPE=            # OAuth scope (e.g. "opensearch:read")
OPENSEARCH_OAUTH_BEARER_TOKEN_URL= # Identity broker URL for bearer token (step 1)
OPENSEARCH_OAUTH_TOKEN_URL=        # OAuth token exchange URL (step 2)
```

#### Integration OpenSearch OAuth Credentials

Same as above but for the integration (int) environment. All variables have `_INT` suffix:

```
OPENSEARCH_OAUTH_TOKEN_INT=
OPENSEARCH_OAUTH_NAME_INT=
OPENSEARCH_OAUTH_PASSWORD_INT=
OPENSEARCH_OAUTH_CLIENT_ID_INT=
OPENSEARCH_OAUTH_CLIENT_SECRET_INT=
OPENSEARCH_OAUTH_SCOPE_INT=
OPENSEARCH_OAUTH_BEARER_TOKEN_URL_INT=
OPENSEARCH_OAUTH_TOKEN_URL_INT=
```

#### Azure OpenAI (LLM Proxy)

```
AZURE_OPENAI_ENDPOINT=     # Full URL to Azure OpenAI proxy (e.g. "https://proxy.example.com/v1")
AZURE_API_VERSION=          # API version (e.g. "2024-02-01")
AZURE_OPENAI_API_KEY=       # API key, or leave empty if using LLM OAuth below
```

#### LLM Proxy OAuth (Machine Account)

If the LLM proxy requires OAuth authentication instead of a static API key:

```
LLM_OAUTH_IDENTITY_BROKER_URL=       # Identity broker endpoint
LLM_OAUTH_ENVIRONMENT=               # e.g. "production"
LLM_OAUTH_ORG_ID=                    # Organization ID
LLM_OAUTH_MACHINE_ACCOUNT_NAME=      # Machine account name
LLM_OAUTH_MACHINE_ACCOUNT_UUID=      # Machine account UUID
LLM_OAUTH_MACHINE_ACCOUNT_PASSWORD=  # Machine account password
LLM_OAUTH_CLIENT_ID=                 # OAuth client ID
LLM_OAUTH_CLIENT_SECRET=             # OAuth client secret
LLM_OAUTH_SCOPE=                     # OAuth scope
```

### 2d. Verify backend starts

```bash
cd agents
adk web
```

Expected output: ADK server starts on `http://127.0.0.1:8000`. The entry point is the `root` agent directory.

Press Ctrl+C to stop, then proceed to frontend setup.

## Step 3: Frontend Setup (frontend/)

### 3a. Install Node.js dependencies

```bash
cd frontend
pnpm install
```

### 3b. Create the frontend .env file

```bash
cp .env.example .env.local
```

Edit `frontend/.env.local`:

```
# Webex OAuth Integration
WEBEX_CLIENT_ID=           # From Webex developer portal integration
WEBEX_CLIENT_SECRET=       # From Webex developer portal integration
WEBEX_REDIRECT_URI=http://localhost:3000/api/auth/callback
WEBEX_SCOPES=spark:all spark:applications_token spark:kms
WEBEX_AUTH_URL=https://integration.webexapis.com/v1/authorize
WEBEX_TOKEN_URL=https://integration.webexapis.com/v1/access_token

# ADK Backend URL
NEXT_PUBLIC_ADK_API_URL=http://127.0.0.1:8000
```

To get Webex OAuth credentials:
1. Go to the Webex developer portal
2. Create or use an existing integration
3. Set the redirect URI to `http://localhost:3000/api/auth/callback`
4. Copy the Client ID and Client Secret

### 3c. Start the frontend

```bash
pnpm dev
```

The UI starts on `http://localhost:3000`.

## Step 4: Run the Full Stack

Open two terminals:

**Terminal 1 — Backend:**
```bash
cd microservice-log-analyzer
source .venv/bin/activate
cd agents
adk web
```

**Terminal 2 — Frontend:**
```bash
cd microservice-log-analyzer/frontend
pnpm dev
```

Then open `http://localhost:3000`, sign in with Webex, and paste a tracking ID or call ID to search.

## Project Structure

```
microservice-log-analyzer/
├── agents/                    # Python ADK backend
│   ├── root/                  # Entry point agent (APP_NAME = "root")
│   ├── router/                # Intent routing (search vs chat vs re-search)
│   ├── pipeline/              # Sequential: search -> analyze -> visualize
│   ├── search/                # BFS search + ID extraction from OpenSearch
│   ├── analyze/               # Log analysis (calling_agent / contact_center_agent)
│   │   └── skills/            # ADK skills (error lookups, SIP flows, architecture)
│   ├── chat/                  # Conversational follow-up agent
│   ├── visualize/             # PlantUML sequence diagram generation
│   ├── oauth_context.py       # Per-request OAuth token via Python contextvars
│   ├── .env                   # Secrets (not committed)
│   ├── .env.example           # Template
│   └── requirements.txt       # Python dependencies
├── frontend/                  # Next.js frontend
│   ├── app/                   # Next.js App Router pages
│   ├── components/            # React components (search, analysis, chat, etc.)
│   ├── lib/session-manager.ts # ADK session management (APP_NAME = "root")
│   ├── .env.local             # Secrets (not committed)
│   └── .env.example           # Template
├── .github/workflows/         # GitHub Pages deployment
├── README.md                  # Project overview
└── SETUP.md                   # This file
```

## Troubleshooting

### Backend won't start
- Ensure `.venv` is activated (`which python` should point to `.venv/bin/python`)
- Ensure `agents/.env` exists and has valid values
- Check Python version: `python3 --version` (need 3.10+)

### Frontend can't connect to backend
- Ensure backend is running on port 8000
- Check `NEXT_PUBLIC_ADK_API_URL` in `frontend/.env.local` matches backend URL
- Check browser console for CORS errors — backend must allow requests from `localhost:3000`

### OAuth login fails
- Ensure `WEBEX_CLIENT_ID` and `WEBEX_CLIENT_SECRET` are set in `frontend/.env.local`
- Ensure redirect URI in Webex portal matches `WEBEX_REDIRECT_URI` exactly
- Check that the Webex integration has the required scopes

### Search returns no results
- Verify OpenSearch credentials in `agents/.env` are valid
- Check backend terminal for OAuth token errors
- Ensure the identifier you're searching is from the last 7 days (default time range)
