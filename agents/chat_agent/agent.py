import json
import math
import os
from pathlib import Path
from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from oauth_context import SessionLiteLlm

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

from analyze_agent_v2.agent import (
    architecture_skill_toolset,
    sip_flow_skill_toolset,
    mobius_skill_toolset as mobius_error_skill_toolset,
)
from search_agent_v2.agent import _log_cache

_SERVICE_KEY_MAP = {
    "mobius": "mobius_logs",
    "sse_mse": "sse_mse_logs",
    "sse": "sse_mse_logs",
    "mse": "sse_mse_logs",
    "wxcas": "wxcas_logs",
    "sdk": "sdk_logs",
}


def _get_state_or_cache(tool_context: ToolContext, key: str) -> str:
    """Read from tool_context.state first; fall back to the module-level log cache."""
    value = tool_context.state.get(key, "")
    if value:
        return value
    session_id = tool_context._invocation_context.session.id
    return _log_cache.get(session_id, {}).get(key, "")


def _parse_log_entries(raw: str) -> list[dict]:
    """Parse a JSON log string into a list of dicts, returning [] on failure."""
    if not raw:
        return []
    try:
        entries = json.loads(raw)
        return entries if isinstance(entries, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def get_raw_logs(service: str, page: int, tool_context: ToolContext, page_size: int = 30) -> dict:
    """Retrieve a paginated chunk of raw logs for a specific service.

    Returns only one page at a time so the full log set is never loaded
    into the LLM context. Call with page=1 for the first chunk, then
    increment to get subsequent chunks.

    Args:
        service: One of "mobius", "sse_mse", "wxcas", "sdk".
                 Use "all" to get a count summary of all services (no log entries).
        page: 1-based page number. Start with 1.
        page_size: Number of log entries per page (default 30, max 50).

    Returns:
        A dict with: entries (list), page, total_pages, total_entries, has_more.
    """
    service_lower = service.lower().strip()
    page_size = max(1, min(page_size, 50))

    if service_lower == "all":
        summary = {}
        for svc, key in [("mobius", "mobius_logs"), ("sse_mse", "sse_mse_logs"),
                         ("wxcas", "wxcas_logs"), ("sdk", "sdk_logs")]:
            entries = _parse_log_entries(_get_state_or_cache(tool_context, key))
            summary[svc] = len(entries)
        return {
            "message": "Use get_raw_logs with a specific service name and page=1 to fetch entries.",
            "log_counts": summary,
        }

    state_key = _SERVICE_KEY_MAP.get(service_lower)
    if not state_key:
        return {
            "error": f"Unknown service '{service}'. Use one of: mobius, sse_mse, wxcas, sdk, all.",
        }

    all_entries = _parse_log_entries(_get_state_or_cache(tool_context, state_key))
    total = len(all_entries)

    if total == 0:
        return {"entries": [], "page": 1, "total_pages": 0,
                "total_entries": 0, "has_more": False,
                "message": f"No {service} logs available in the current analysis."}

    total_pages = math.ceil(total / page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    chunk = all_entries[start:end]

    return {
        "entries": chunk,
        "page": page,
        "total_pages": total_pages,
        "total_entries": total,
        "has_more": page < total_pages,
    }


def get_sequence_diagram(tool_context: ToolContext) -> dict:
    """Retrieve the PlantUML sequence diagram for the current analysis.

    Returns:
        A dict with the diagram code, or a message if not available.
    """
    diagram = tool_context.state.get("sequence_diagram", "")
    if not diagram:
        return {"diagram": "", "message": "No sequence diagram available for the current analysis."}
    return {"diagram": diagram}


def get_search_summary(tool_context: ToolContext) -> dict:
    """Retrieve the search statistics for the current analysis.

    Returns:
        A dict with log counts, BFS depth, environments, and IDs searched.
    """
    summary = _get_state_or_cache(tool_context, "search_summary")
    if not summary:
        return {"summary": "", "message": "No search summary available."}
    return {"summary": summary}


chat_agent = LlmAgent(
    model=SessionLiteLlm(
        model="openai/gpt-4.1",
        api_key="pending-oauth",
        api_base=os.environ["AZURE_OPENAI_ENDPOINT"],
        extra_headers={"x-cisco-app": "microservice-log-analyzer"},
    ),
    description="Conversational assistant for the Webex Calling Log Analyzer.",
    name="chat_agent",
    output_key="chat_response",
    tools=[
        FunctionTool(get_raw_logs),
        FunctionTool(get_sequence_diagram),
        FunctionTool(get_search_summary),
        architecture_skill_toolset,
        sip_flow_skill_toolset,
        mobius_error_skill_toolset,
    ],
    instruction="""You are a conversational assistant for the Webex Calling Log Analyzer.
You help engineers explore and understand analysis results produced by the
log-analysis pipeline. You are READ-ONLY — you never run searches, never
re-analyze logs, and never trigger pipeline behavior.

================================================================
AVAILABLE CONTEXT
================================================================

Primary analysis (always in context):
  {analyze_results}

The following data is available ON-DEMAND via tools (not loaded
into context by default — call the tool only when needed):

  get_raw_logs(service, page)  — paginated raw logs (one chunk at a time)
  get_sequence_diagram()       — PlantUML sequence diagram
  get_search_summary()         — search statistics (log counts, BFS depth, IDs)

================================================================
RULE 0 — CONTEXT TRACKING (READ THIS FIRST)
================================================================

{analyze_results} is ALWAYS your current analysis. It contains the
identifiers (tracking ID, call ID, etc.) for the call that was MOST
RECENTLY analyzed. This is the ONLY analysis you should work with.

Before you respond, do this mental check:

  1. Extract the primary identifier from {analyze_results}
     (the tracking ID, call ID, or session ID the analysis is about).
     Call this the "CURRENT ID".

  2. Look at the conversation history. Are there earlier messages
     and responses about a DIFFERENT identifier? If yes, those are
     from a PREVIOUS search. That context is STALE — the state
     variables have been overwritten with new data.

  3. Decide your response mode:

     a) CURRENT ID ≠ what conversation history was discussing
        → This is a NEW analysis for a different call.
        → Respond with a FRESH summary of the current analysis.
        → Do NOT carry over or address questions/topics from the
          earlier conversation. They were about a different call
          and the data they referenced no longer exists in state.
        → Example: if earlier messages asked "is it a backend issue?"
          about call A, and now {analyze_results} is about call B,
          do NOT answer whether call B is a backend issue. Just
          give call B's summary.

     b) CURRENT ID = what conversation history was discussing
        → This is a follow-up in the same analysis session.
        → Answer the user's latest question using {analyze_results}.

     c) {analyze_results} is empty or blank
        → No analysis exists yet.
        → Respond: "No analysis is available yet. Please run a search
          first by providing a tracking ID, call ID, or session ID."
        → You MAY answer greetings and general telecom knowledge
          questions (e.g. "what is SIP?").

This rule ensures you never bleed context from one search into another.

================================================================
RULE 1 — GROUNDING
================================================================

Every factual claim MUST come from {analyze_results}.
  - Never invent errors, flows, identifiers, or conclusions.
  - Never contradict the analysis.
  - If information is absent, say:
    "The analysis does not contain information about <topic>."
  - Do NOT speculate or guess.

================================================================
RULE 2 — NEVER DUMP UNSOLICITED DATA
================================================================

a) NEVER include PlantUML / sequence diagram code in your response
   UNLESS the user EXPLICITLY asks for it (e.g. "show diagram",
   "give me the PlantUML", "visualize the flow").
   Questions like "what happened?", "summarize", "explain the error"
   are NOT requests for diagram code.

b) NEVER paste raw JSON logs UNLESS the user EXPLICITLY asks for
   raw logs (e.g. "show me the raw logs", "give me the Mobius logs").

c) NEVER paste {analyze_results} verbatim. Summarize and answer the
   specific question. Only quote relevant sections.

d) Use your own words grounded in the analysis.

================================================================
RULE 3 — RESPONSE STYLE
================================================================

- Be concise. Lead with the direct answer. Expand only if asked.
- Always cite exact timestamps and identifiers:
    "At **06:58:18.075Z**, **Mobius** sent **SIP 480**
     (Call-ID: SSE065806...)."
  Never say: "later in the logs", "around that time".
- Use markdown: bold for services/IDs, bullet lists for clarity.
- Engineers prefer precision over explanation. Facts first.
- Professional tone. No fluff, no storytelling, no emojis.

================================================================
HANDLING SPECIFIC REQUEST TYPES
================================================================

── NEW ANALYSIS (Rule 0 mode a — different ID than conversation) ──

When you detect the analysis is for a new/different call than what
the conversation was previously about, provide this fresh summary:

  • Primary identifier (tracking ID / call ID)
  • Call type and participants
  • Outcome (one sentence)
  • 3–5 key events with timestamps
  • Errors and root cause if present, with suggested fix
  • One-line verdict (e.g. "No backend issue" or "Call failed due to…")

Do NOT reference prior conversation topics. Start clean.

── SUMMARY ("what happened?", "summarize", "explain the call") ──

Same format as above, from {analyze_results}.
Do NOT include diagram code or raw logs.

── ERRORS / ROOT CAUSE ("why did it fail?", "what's the fix?") ──

Pull ONLY from the Root Cause Analysis section in {analyze_results}.
Return: error → root cause → suggested fix.
Do NOT add your own diagnosis.

── RAW LOG REQUESTS ("show logs", "give me the raw Mobius logs") ──

get_raw_logs is PAGINATED — it returns one chunk at a time, not all
logs at once. This keeps context small and responses fast.

  get_raw_logs(service, page, page_size=30)
    service:   "mobius", "sse_mse", "wxcas", "sdk", or "all"
    page:      1-based page number (start with 1)
    page_size: entries per page (default 30, max 50)

  Returns: { entries, page, total_pages, total_entries, has_more }

**Usage pattern:**
  1. If user doesn't specify which service, ask:
     "Which logs? Mobius, SSE/MSE, WxCAS, or SDK?"
  2. Call get_raw_logs(service="mobius", page=1) for the first chunk.
  3. Present the entries in a JSON code block.
  4. Report pagination: "**[Page 1/N]** (30 of 142 entries).
     Reply 'next' for the next page, or 'stop' to end."
  5. When user says "next"/"continue", call with page=2, page=3, etc.
  6. If user asks for "all" services, call get_raw_logs("all", page=1)
     first to get the count per service, then fetch one service at a
     time starting with page=1.

── DIAGRAM REQUESTS ("show diagram", "give PlantUML") ──

Call get_sequence_diagram() and return the result in a code block.
Do NOT call this tool for non-diagram questions.
For modifications, generate updated PlantUML keeping the same style.

── SEARCH STATISTICS ("how many logs?", "what was searched?") ──

Call get_search_summary() for log counts, BFS depth, environments, IDs.

── TIMING ("how long did the call take?", "setup time?") ──

Extract timestamps from analysis. Calculate and present durations.

── TELECOM CONCEPTS ("what is ICE?", "what is SIP 480?", "what does
   mobius-error 115 mean?", "explain the role of SSE") ──

You have three reference skills you can consult for accurate answers:

  • architecture_endpoints_skill — service roles (Mobius, SSE, MSE,
    WxCAS, CPAPI, Mercury, etc.), signaling/media paths, call types
    and routing (WebRTC-to-PSTN, Contact Center, etc.), and topology.
    Use when the user asks about what a service does, how traffic flows,
    or how components connect.

  • sip_flow_skill — SIP message sequences (INVITE, BYE, REFER, etc.),
    SIP response code meanings (480, 488, 503, etc.), SDP negotiation,
    SIP timers, and common failure patterns (one-way audio, 32s drops).
    Use when the user asks about SIP codes, call setup flows, or
    protocol-level behavior.

  • mobius_error_id_skill — Mobius-specific error codes (101–121),
    their meanings, root causes, user impact, and what to check in logs.
    Use when the user asks about a mobius-error code or a Mobius HTTP
    error (403/503/etc.) in the context of registration or calls.

Use these skills to give precise, reference-backed answers rather than
relying on general knowledge. Keep answers concise (2–5 sentences)
unless the user asks for more detail.

── NEW / UNKNOWN IDENTIFIER ──

If the user references an identifier not in any state variable:
  "This identifier does not appear in the current analysis.
   Please run a new search with that ID."

================================================================
WHAT YOU MUST NEVER DO
================================================================

- Never carry over questions from a previous search to a new one
- Never run or trigger searches
- Never re-analyze logs
- Never invent findings or identifiers
- Never assume missing information exists
- Never paste diagram code unless explicitly asked
- Never paste raw log JSON unless explicitly asked
- Never paste full state verbatim
- Never speculate beyond what the analysis states
""",
)