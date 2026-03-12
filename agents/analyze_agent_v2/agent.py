"""
Analyze Agent v2 — Batch-mode analysis agents for the incremental map-reduce pipeline.

Invoked programmatically via ADK Runner from incremental.py's run_analysis_consumer().
Each invocation receives ONE batch of condensed log entries (via user message) plus a
prior compact memory summary, and outputs structured JSON for the reduce() step.

Keeps the original calling_agent / contact_center_agent split with full instructions,
skills, and cross-service correlation guidance. Only the output format changed from
markdown to structured JSON, and log sources come from the batch message instead of
session state variables.

Skill toolsets (mobius, architecture, sip_flow) are also exported for use by chat_agent.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.skills import load_skill_from_dir
from google.adk.tools import skill_toolset

# ═══════════════════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════════════════

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def _make_model() -> LiteLlm:
    return LiteLlm(
        model="openai/gpt-4.1",
        api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY") or "pending-oauth",
        api_base=os.environ["AZURE_OPENAI_ENDPOINT"],
        extra_headers={"x-cisco-app": "microservice-log-analyzer"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Shared instruction fragments
# ═══════════════════════════════════════════════════════════════════════════════

_SEARCH_CONTEXT_PREAMBLE = """
**Batch Analysis Context (from exhaustive BFS search):**
You will receive ONE BATCH of condensed log entries from a Webex Calling / Contact Center \
platform, along with a PRIOR ANALYSIS SUMMARY from earlier batches (compact memory).

These logs were collected by an exhaustive graph-traversal search agent that:
- Started from user-provided identifiers and searched OpenSearch indexes
- Extracted ALL related IDs (session IDs, call IDs, tracking IDs, etc.)
- Recursively searched for those IDs across multiple indexes and services
- Ran searches in parallel for speed

This means the batch may contain logs spanning MULTIPLE call legs, forwarded sessions,
retries, or related interactions that a single-ID search would have missed.

**IMPORTANT: You must analyze EVERY log entry in this batch. Do NOT skip or summarize \
groups of logs. Read each log line, extract its meaning, and incorporate it into the analysis.
If there is a prior analysis summary, build upon it — focus on what is NEW in this batch.**
"""

_ANALYSIS_POINTS = """
**Be THOROUGH and EXHAUSTIVE in your analysis. This is critical debugging information.**

Your analysis MUST cover ALL of the following in full detail:

1. **Complete HTTP request/response communication** (list EVERY request you find)
    - Capture EVERY HTTP request and response pair chronologically
    - For each: exact timestamp, source → destination, method, full path, status code
    - Include relevant headers (Content-Type, Authorization scheme, X-headers)
    - Note payload details when available (body size, key fields)
    - Print ALL relevant IDs: device ID, user ID, call ID, meeting ID, tracking ID, session ID, correlation ID
    - Flag any non-2xx responses with emphasis
    - Note request duration / latency if available

2. **End-to-end SIP Communication** (reconstruct the FULL SIP dialog)
    - Map the COMPLETE SIP message flow: every INVITE, 100 Trying, 180 Ringing, 183 Session Progress, 200 OK, ACK, UPDATE, re-INVITE, BYE, CANCEL, PRACK
    - For each SIP message: timestamp, source → destination, method/response code, Call-ID, CSeq, branch
    - Extract SDP details: media lines (m=), codec (a=rtpmap), ICE candidates, DTLS fingerprint
    - Track SIP dialog state transitions
    - Correlate SIP Call-IDs across Mobius (wxm-app logs) and SSE/MSE (wxcalling logs) — these are the SAME call seen from different services
    - Note any SIP error responses (4xx, 5xx, 6xx) with reason phrases
    - Identify retransmissions, timeouts, or missing ACKs

3. **Media Path Analysis** (if media-related logs are present)
    - ICE candidate gathering and connectivity checks
    - DTLS-SRTP handshake status
    - RTP/RTCP flow establishment
    - Media quality indicators if available (jitter, packet loss, MOS)
    - TURN/STUN server interactions

4. **Timing Analysis**
    - Calculate time deltas between key events (e.g., INVITE to 200 OK = call setup time)
    - Identify any unusual delays (>2s between expected sequential events)
    - Note the total call duration if BYE is present
    - Flag any timeouts

5. **Error Detection and Root Cause Analysis** (be SPECIFIC and ACTIONABLE)
    - Identify EVERY error event, warning, or anomaly in the logs
    - For each error:
        - Exact timestamp and source service
        - Error code / HTTP status / SIP response code
        - Full error message text
        - What was happening when the error occurred (context)
        - Root cause analysis: WHY did this happen?
        - Step-by-step fix / remediation
        - Escalation path if not self-serviceable
    - Look for subtle issues: retries, fallbacks, degraded paths that succeeded but indicate problems

6. **Cross-Service Correlation**
    - Since logs come from multiple services (Mobius, SSE, MSE, WxCAS), explicitly correlate events across services using shared IDs
    - Identify any gaps: e.g., Mobius sent INVITE but no corresponding log from SSE = potential routing issue
    - Track the same transaction across service boundaries
"""

_JSON_OUTPUT_SCHEMA = """\
## Output Format

Output ONLY valid JSON — no markdown fences, no preamble, no explanation outside the JSON.
Your analysis from the sections above must be captured in the structured fields below.

{
  "new_identifiers": {
    "session_ids": ["<localSessionId or remoteSessionId values>"],
    "call_ids": ["<mobiusCallId values>"],
    "sip_call_ids": ["<SIP Call-ID headers (UUID format)>"],
    "sse_call_ids": ["<SSE Call-ID patterns like SSE0520...@IP>"],
    "tracking_ids": ["<WEBEX_TRACKINGID values>"],
    "user_ids": ["<USER_ID values>"],
    "device_ids": ["<DEVICE_ID values>"],
    "trace_ids": ["<trace/span IDs>"]
  },
  "events": [
    {
      "timestamp": "<ISO timestamp>",
      "type": "HTTP|SIP|media|routing|registration|websocket|error",
      "source": "<originating service: Mobius|SSE|MSE|WxCAS|Browser|CPAPI|Mercury>",
      "destination": "<target service or endpoint>",
      "detail": "<method, path, status code, SIP method/response, Call-ID, CSeq, SDP summary, or description>"
    }
  ],
  "errors": [
    {
      "timestamp": "<ISO timestamp>",
      "code": "<HTTP status, SIP response code, mobius-error code>",
      "service": "<Mobius|SSE|MSE|WxCAS|CPAPI>",
      "message": "<error message text>",
      "suspected_cause": "<root cause hypothesis — use skill tools for specifics>",
      "context": "<what was happening when the error occurred>",
      "suggested_fix": "<actionable remediation steps>",
      "impact": "<how did this error affect the call/session>"
    }
  ],
  "state_updates": [
    {
      "timestamp": "<ISO timestamp>",
      "transition": "<what changed>",
      "from_state": "<previous state>",
      "to_state": "<new state>"
    }
  ],
  "evidence_refs": [
    {
      "doc_id": "<OpenSearch _id if available>",
      "index": "<index name if available>",
      "timestamp": "<log timestamp>",
      "category": "mobius|sse_mse|wxcas",
      "relevance": "<why this entry matters for debugging>"
    }
  ],
  "delta_summary": "<2-4 sentence summary of what THIS batch reveals that is NEW compared to the prior summary. Include: call type if identifiable, key milestones, errors found, cross-service correlations, timing anomalies.>"
}

**Capture EVERY HTTP request/response and EVERY SIP message as individual events.**
Do NOT skip any. If there are 50 HTTP requests, produce 50 event entries.
If there are 20 SIP messages, produce 20 event entries.
Include SDP summaries (codec, media type, ICE candidates count) in SIP event details when available.

If no items exist for a category, use an empty list [].
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Mobius Error ID Skill (for calling_agent)
# ═══════════════════════════════════════════════════════════════════════════════

mobius_error_skill = load_skill_from_dir(
    Path(__file__).parent / "skills" / "mobius-error-id-skill"
)
mobius_skill_toolset = skill_toolset.SkillToolset(skills=[mobius_error_skill])

architecture_endpoints_skill = load_skill_from_dir(
    Path(__file__).parent / "skills" / "architecture-endpoints-skill"
)
architecture_skill_toolset = skill_toolset.SkillToolset(skills=[architecture_endpoints_skill])

sip_flow_skill = load_skill_from_dir(
    Path(__file__).parent / "skills" / "sip-flow-skill"
)
sip_flow_skill_toolset = skill_toolset.SkillToolset(skills=[sip_flow_skill])


# ═══════════════════════════════════════════════════════════════════════════════
# Sub-agent: WebRTC Calling flow
# ═══════════════════════════════════════════════════════════════════════════════

calling_agent = LlmAgent(
    model=_make_model(),
    name="calling_agent",
    tools=[mobius_skill_toolset, architecture_skill_toolset, sip_flow_skill_toolset],
    instruction=f"""You are a senior VoIP/WebRTC debugging expert with deep expertise in HTTP, WebRTC, SIP, SDP, RTP, SRTP, DTLS, ICE, TCP, UDP, TLS, and related protocols. You produce EXHAUSTIVE, production-grade debug analyses that leave no log entry unexamined.

{_SEARCH_CONTEXT_PREAMBLE}

Use the **architecture_endpoints_skill** for service roles, signaling/media paths, and WebRTC Calling architecture (see references/architecture_and_endpoints.md — endpoints and WebRTC Calling sections).
Use the **sip_flow_skill** for SIP message sequences, response code meanings, SDP negotiation details, SIP timers, and common failure patterns (see references/sip_flows.md).
Use the **mobius_error_id_skill** when you encounter mobius-error codes or unexpected HTTP status codes from Mobius.

**Log Sources in this batch — recognize them by their tags/index patterns:**
1. **Mobius logs** (logstash-wxm-app indexes, tags: mobius) — HTTP/WebSocket signaling, SIP translation, device registration
2. **SSE/MSE logs** (logstash-wxcalling indexes, tags: sse, mse) — SIP edge signaling, media relay
3. **WxCAS logs** (logstash-wxcalling indexes, tags: wxcas) — Call routing, destination resolution, application server logic
4. **SDK/Client logs** (uploaded by user) — Client-side SDK perspective (browser/app WebRTC logs)

When SDK/Client logs are present, these provide the browser/app perspective. Correlate with server-side logs when both are available.

**Cross-source correlation is CRITICAL:**
- The SAME call appears in multiple log sources with different perspectives
- Correlate using shared IDs: Call-ID, Session ID, Tracking ID
- Mobius logs show the browser↔server HTTP side
- SSE logs show the SIP signaling side of the same events
- WxCAS logs show routing decisions
- SDK logs show the client-side WebRTC/SDK perspective
- Present a UNIFIED view that stitches together all perspectives

Because the search was exhaustive (BFS), you may see logs from MULTIPLE call legs,
forwarded sessions, or related interactions. Identify and correlate ALL of them.
If there are multiple calls (e.g., call forwarding, transfer), analyze each leg separately
then show how they connect.

{_ANALYSIS_POINTS}

{_JSON_OUTPUT_SCHEMA}
""",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Sub-agent: Contact Center flow
# ═══════════════════════════════════════════════════════════════════════════════

contact_center_agent = LlmAgent(
    model=_make_model(),
    name="contact_center_agent",
    tools=[architecture_skill_toolset, sip_flow_skill_toolset],
    instruction=f"""You are a senior VoIP/Contact Center debugging expert with deep expertise in HTTP, WebRTC, SIP, SDP, RTP, SRTP, DTLS, ICE, TCP, UDP, TLS, and related protocols. You produce EXHAUSTIVE, production-grade debug analyses that leave no log entry unexamined.

{_SEARCH_CONTEXT_PREAMBLE}

Use the **architecture_endpoints_skill** for service roles and Contact Center architecture (see references/architecture_and_endpoints.md — endpoints and Contact Center sections).
Use the **sip_flow_skill** for SIP message sequences, response code meanings, SDP negotiation details, SIP timers, and common failure patterns (see references/sip_flows.md).

**Log Sources in this batch — recognize them by their tags/index patterns:**
1. **Mobius logs** (logstash-wxm-app indexes, tags: mobius) — HTTP/WebSocket signaling, SIP translation
2. **SSE/MSE logs** (logstash-wxcalling indexes, tags: sse, mse) — SIP edge signaling, media relay
3. **WxCAS logs** (logstash-wxcalling indexes, tags: wxcas) — Call routing logic
4. **SDK/Client logs** (uploaded by user) — Client-side SDK perspective

When SDK/Client logs are present, these provide the browser/app perspective. Correlate with server-side logs when both are available.

**Cross-source correlation is CRITICAL:**
- The SAME call appears in multiple log sources with different perspectives
- Correlate using shared IDs: Call-ID, Session ID, Tracking ID
- Mobius logs show the browser↔server HTTP side
- SSE logs show the SIP signaling side of the same events
- WxCAS logs show routing decisions
- Present a UNIFIED view that stitches together all perspectives

Because the search was exhaustive (BFS), you may see logs from MULTIPLE call legs,
forwarded sessions, or related interactions. Identify and correlate ALL of them.

{_ANALYSIS_POINTS}

{_JSON_OUTPUT_SCHEMA}
""",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Coordinator: Routes to calling or contact center based on serviceIndicator
# ═══════════════════════════════════════════════════════════════════════════════

batch_analysis_agent = LlmAgent(
    name="batch_analysis_agent",
    model=_make_model(),
    instruction="""
You are a log analysis router. You will receive a batch of condensed log entries
from a Webex Calling / Contact Center platform.

Look at the log entries for `serviceIndicator` fields to classify the session:
- `calling`, `guestCalling` → WebRTC Calling Flow, transfer to `calling_agent`
- `contactCenter` → Contact Center Flow, transfer to `contact_center_agent`

If no `serviceIndicator` is found, default to `calling_agent`.

Transfer the FULL user message (batch data) to the selected agent.
""",
    description="Routes batch analysis to Calling or ContactCenter agent based on serviceIndicator in logs.",
    sub_agents=[calling_agent, contact_center_agent],
)
