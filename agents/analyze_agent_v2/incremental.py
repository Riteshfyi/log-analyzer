"""
Incremental Map-Reduce Analysis — processes log batches as they arrive from search.

Exports a clean function interface consumed by search_agent_v2:
  - new_rolling_analysis()        → empty rolling state
  - map_batch()                   → MAP: one batch + compact memory → structured JSON
  - reduce()                      → REDUCE: merge map output into rolling state
  - compress_analysis_summary()   → shrink rolling summary when it exceeds token cap
  - format_to_markdown()          → convert final rolling state to markdown report
  - run_analysis_consumer()       → asyncio.Queue consumer loop (producer-consumer pattern)
  - analyze_upload_only()         → single-pass analysis for SDK-only uploads
"""

import asyncio
import json
import logging
import os
from typing import Any

import litellm
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)

# Re-use TokenBudget from search_agent_v2 (imported by callers, passed in as arg).
# We only reference the type for documentation; no import needed at module level.

# ═══════════════════════════════════════════════════════════════════════════════
# Skill References (loaded on-demand via tool calls)
# ═══════════════════════════════════════════════════════════════════════════════

_SKILLS_DIR = Path(__file__).parent / "skills"

_SKILL_FILE_MAP = {
    "lookup_mobius_error_codes": _SKILLS_DIR / "mobius-error-id-skill" / "references" / "mobius_error_ids.md",
    "lookup_architecture": _SKILLS_DIR / "architecture-endpoints-skill" / "references" / "architecture_and_endpoints.md",
    "lookup_sip_flows": _SKILLS_DIR / "sip-flow-skill" / "references" / "sip_flows.md",
    "lookup_calling_flow": _SKILLS_DIR / "architecture-endpoints-skill" / "references" / "calling_flow.md",
    "lookup_contact_center_flow": _SKILLS_DIR / "architecture-endpoints-skill" / "references" / "contact_center_flow.md",
}

_SKILL_CACHE: dict[str, str] = {}


def _load_skill_reference(name: str) -> str:
    """Load a skill reference file, with caching."""
    if name in _SKILL_CACHE:
        return _SKILL_CACHE[name]
    path = _SKILL_FILE_MAP.get(name)
    if not path or not path.exists():
        return f"Reference '{name}' not found."
    content = path.read_text(encoding="utf-8")
    _SKILL_CACHE[name] = content
    logger.info(f"[_load_skill_reference] Loaded {name}: {len(content)} chars")
    return content


_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_mobius_error_codes",
            "description": (
                "Look up Mobius HTTP error codes and mobius-error codes "
                "(e.g., 101, 102, 103, 403, 503). Returns detailed reference "
                "with root cause direction, user impact, and what to check in logs. "
                "Call this when you see mobius-error codes or unexpected HTTP status "
                "codes from Mobius in the log batch."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_architecture",
            "description": (
                "Look up Webex Calling / Contact Center architecture: service roles "
                "(Mobius, SSE, MSE, WxCAS, CPAPI, Mercury, WDM, U2C), signaling and "
                "media paths, call types, multi-instance deployment, timers, failover. "
                "Call this when you need to understand how services connect or what a "
                "specific component does."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_sip_flows",
            "description": (
                "Look up SIP message flow references: call setup (INVITE transaction), "
                "early media (183), hold/resume (re-INVITE), call transfer (REFER), "
                "registration (REGISTER), SIP response codes, SDP negotiation, timers, "
                "and common failure patterns. Call this when you see SIP messages in logs "
                "and need to verify the expected flow or diagnose a SIP failure."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_calling_flow",
            "description": (
                "Look up WebRTC Calling end-to-end flow: signaling path, media path, "
                "call types (WebRTC-to-WebRTC, WebRTC-to-PSTN, WebRTC-to-DeskPhone). "
                "Call this when analyzing a standard calling flow."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_contact_center_flow",
            "description": (
                "Look up Contact Center architecture: Kamailio SIP proxy, RTMS, RAS, "
                "health ping endpoints, Mobius timers, Kafka failover, inter-regional "
                "failover. Call this when logs indicate a Contact Center flow."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def _handle_tool_calls(tool_calls: list) -> list[dict]:
    """Execute tool calls and return tool result messages."""
    results = []
    for tc in tool_calls:
        name = tc.function.name
        content = _load_skill_reference(name)
        results.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": content,
        })
        logger.info(f"[_handle_tool_calls] Executed {name} -> {len(content)} chars")
    return results

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

CHARS_PER_TOKEN_ESTIMATE = 4
ROLLING_SUMMARY_TOKEN_CAP = 4_000
TIMELINE_MAX_EVENTS = 50

_IDENTIFIER_KEYS = [
    "session_ids",
    "call_ids",
    "tracking_ids",
    "user_ids",
    "device_ids",
    "trace_ids",
    "sip_call_ids",
    "sse_call_ids",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════════════


def new_rolling_analysis() -> dict:
    """Factory: returns an empty rolling_analysis structure."""
    return {
        "identifiers": {k: [] for k in _IDENTIFIER_KEYS},
        "timeline": [],
        "errors": [],
        "state_machine": [],
        "cross_service_correlations": [],
        "summary": "",
        "evidence_count": 0,
        "batch_count": 0,
    }


def _estimate_tokens(text: str) -> int:
    """Estimate token count from character length."""
    return len(text) // CHARS_PER_TOKEN_ESTIMATE


def _get_llm_config() -> tuple[str, str]:
    """Return (api_key, api_base) for LLM calls."""
    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("AZURE_OPENAI_API_KEY")
        or "pending-oauth"
    )
    api_base = os.environ["AZURE_OPENAI_ENDPOINT"]
    return api_key, api_base


def _parse_json_from_llm(raw: Any) -> dict:
    """Extract a JSON object from LLM output, handling markdown code blocks."""
    import re

    if isinstance(raw, dict):
        return raw
    raw = str(raw)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            pass
    logger.warning("[_parse_json_from_llm] Could not extract JSON, returning empty dict")
    return {}


# ═══════════════════════════════════════════════════════════════════════════════
# MAP Step
# ═══════════════════════════════════════════════════════════════════════════════

_MAP_INSTRUCTION = """\
You are an analysis agent with deep expertise in HTTP, WebRTC, \
SIP protocols and their interactions. You will receive a BATCH of microservice log entries \
(condensed JSON) and a PRIOR ANALYSIS SUMMARY from earlier batches.

These logs come from a Webex Calling / Contact Center platform. You have access to \
reference tools — use them when you need detailed knowledge:

- **lookup_mobius_error_codes**: Call when you see `mobius-error` codes or unexpected HTTP \
status codes from Mobius. Returns code-level root cause and debugging guidance.
- **lookup_architecture**: Call when you need to understand service roles (Mobius, SSE, MSE, \
WxCAS, CPAPI, Mercury, WDM, U2C), signaling/media paths, or how services interconnect.
- **lookup_sip_flows**: Call when analyzing SIP messages (INVITE, BYE, REGISTER, re-INVITE, \
REFER, etc.) and you need the expected sequence, SDP details, or failure patterns.
- **lookup_calling_flow**: Call when analyzing an end-to-end calling flow (WebRTC-to-WebRTC, \
WebRTC-to-PSTN, WebRTC-to-DeskPhone).
- **lookup_contact_center_flow**: Call when logs indicate a Contact Center scenario (Kamailio, \
RTMS, RAS, health pings, Kafka failover).

## Output Schema

Analyze THIS batch and produce a structured JSON object. \
Output ONLY valid JSON — no markdown fences, no preamble.

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
      "detail": "<method, path, status code, SIP method/response, Call-ID, or description>"
    }
  ],
  "errors": [
    {
      "timestamp": "<ISO timestamp>",
      "code": "<HTTP status, SIP response code, mobius-error code>",
      "service": "<Mobius|SSE|MSE|WxCAS|CPAPI>",
      "message": "<error message text>",
      "suspected_cause": "<root cause hypothesis — use lookup tools for specifics>"
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
  "delta_summary": "<2-4 sentence summary of what THIS batch reveals that is NEW compared to the prior summary>"
}

## Analysis Guidance

Be THOROUGH and EXHAUSTIVE — every log entry matters for debugging.

- **HTTP**: capture every request/response with timestamp, source→destination, method, \
full path, status code, relevant IDs. Flag non-2xx responses. Note latency if visible.
- **SIP**: capture INVITE, 100 Trying, 180 Ringing, 183 Session Progress, 200 OK, ACK, \
BYE, CANCEL, UPDATE, re-INVITE, PRACK, REFER with Call-ID and CSeq. Extract SDP details \
(codec, media type, ICE candidates) when visible. Identify retransmissions and timeouts. \
Use **lookup_sip_flows** if you need to verify the expected sequence.
- **Errors**: every non-2xx HTTP, every 4xx/5xx/6xx SIP, every mobius-error code, every \
logged error/warning/exception. Use **lookup_mobius_error_codes** for Mobius-specific codes.
- **State transitions**: call state changes (idle→calling→connected→disconnected), \
registration state (unregistered→registered→expired), SIP dialog state, media negotiation.
- **Cross-service correlation**: the SAME call appears in Mobius (HTTP side), SSE (SIP side), \
and WxCAS (routing side) with shared IDs. Note when you see the same transaction across services. \
Identify gaps. Use **lookup_architecture** if you need to understand the expected path.
- **Timing**: note delays >2s between expected sequential events. Calculate setup time \
(INVITE to 200 OK). Flag timeouts.
- **Evidence**: mark log entries critical for debugging (errors, state changes, first/last events, \
SIP milestones).
- **delta_summary**: focus on what is NEW in this batch vs the prior summary — avoid repeating.

If no items exist for a category, use an empty list [].
"""

_MAP_USER_TEMPLATE = """\
## Prior Analysis Summary
{compact_memory}

## Log Batch (analyze this)
{batch_json}
"""


async def map_batch(
    condensed_hits: list[dict],
    compact_memory: str,
    budget: "TokenBudget",
) -> dict:
    """MAP step: analyze one batch of log entries via LLM.

    Args:
        condensed_hits: list of condensed log entries (from extract_id_fields_for_llm)
        compact_memory: the rolling_analysis["summary"] from prior batches (few KB)
        budget: TokenBudget instance for tracking/limiting token usage

    Returns:
        MapOutput dict matching the schema in _MAP_INSTRUCTION, or empty dict on failure.
    """
    api_key, api_base = _get_llm_config()
    batch_json = json.dumps(condensed_hits, default=str)

    user_content = _MAP_USER_TEMPLATE.format(
        compact_memory=compact_memory or "(No prior analysis — this is the first batch)",
        batch_json=batch_json,
    )

    full_prompt = _MAP_INSTRUCTION + user_content
    est_tokens = _estimate_tokens(full_prompt)

    if budget and not budget.can_afford(full_prompt):
        allowed_chars = (
            budget.remaining_stage() * CHARS_PER_TOKEN_ESTIMATE
            - len(_MAP_INSTRUCTION)
            - len(_MAP_USER_TEMPLATE)
            - len(compact_memory or "")
            - 200
        )
        if allowed_chars < 500:
            logger.warning("[map_batch] Budget too tight, skipping batch")
            return {}
        batch_json = batch_json[:allowed_chars]
        user_content = _MAP_USER_TEMPLATE.format(
            compact_memory=compact_memory or "(No prior analysis — this is the first batch)",
            batch_json=batch_json,
        )
        logger.info(f"[map_batch] Trimmed batch for budget: {len(batch_json)} chars")

    MAX_TOOL_ROUNDS = 3

    messages = [
        {"role": "system", "content": _MAP_INSTRUCTION},
        {"role": "user", "content": user_content},
    ]

    try:
        for _round in range(MAX_TOOL_ROUNDS + 1):
            response = await litellm.acompletion(
                model="openai/gpt-4.1",
                api_key=api_key,
                api_base=api_base,
                extra_headers={"x-cisco-app": "microservice-log-analyzer"},
                messages=messages,
                tools=_TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0,
            )
            if budget:
                budget.record_usage(est_tokens)

            choice = response.choices[0]

            if choice.finish_reason == "tool_calls" or (
                choice.message.tool_calls and not choice.message.content
            ):
                tool_calls = choice.message.tool_calls
                logger.info(
                    f"[map_batch] Round {_round}: LLM requested "
                    f"{len(tool_calls)} skill(s): "
                    f"{[tc.function.name for tc in tool_calls]}"
                )
                messages.append(choice.message)
                messages.extend(_handle_tool_calls(tool_calls))
                continue

            raw = choice.message.content or "{}"
            result = _parse_json_from_llm(raw)

            logger.info(
                f"[map_batch] Extracted (after {_round} tool round(s)): "
                f"events={len(result.get('events', []))}, "
                f"errors={len(result.get('errors', []))}, "
                f"state_updates={len(result.get('state_updates', []))}, "
                f"evidence_refs={len(result.get('evidence_refs', []))}"
            )
            return result

        logger.warning("[map_batch] Exhausted tool rounds, returning last response")
        return _parse_json_from_llm(response.choices[0].message.content or "{}")

    except Exception as e:
        logger.error(f"[map_batch] LLM call failed: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# REDUCE Step
# ═══════════════════════════════════════════════════════════════════════════════


def reduce(
    rolling: dict,
    map_output: dict,
    evidence_index: list[dict],
) -> tuple[dict, list[dict]]:
    """REDUCE step: merge one map_batch output into the rolling analysis.

    Pure Python — no LLM calls. Deduplicates identifiers, appends events/errors/
    state_updates, moves evidence_refs to the separate evidence_index, and appends
    the delta_summary to the rolling summary.

    Args:
        rolling: the current rolling_analysis dict (mutated in place and returned)
        map_output: the structured dict returned by map_batch()
        evidence_index: the accumulated evidence list (mutated in place and returned)

    Returns:
        (updated rolling_analysis, updated evidence_index)
    """
    if not map_output:
        return rolling, evidence_index

    rolling["batch_count"] += 1

    # ── Merge identifiers (deduplicated) ──
    new_ids = map_output.get("new_identifiers", {})
    for key in _IDENTIFIER_KEYS:
        existing = set(rolling["identifiers"].get(key, []))
        for val in new_ids.get(key, []):
            val = str(val).strip()
            if val and val not in existing:
                existing.add(val)
                rolling["identifiers"].setdefault(key, []).append(val)

    # ── Append timeline events (capped at TIMELINE_MAX_EVENTS) ──
    new_events = map_output.get("events", [])
    rolling["timeline"].extend(new_events)
    if len(rolling["timeline"]) > TIMELINE_MAX_EVENTS:
        rolling["timeline"] = _prune_timeline(rolling["timeline"])

    # ── Append errors (never pruned) ──
    new_errors = map_output.get("errors", [])
    rolling["errors"].extend(new_errors)

    # ── Append state machine transitions ──
    new_states = map_output.get("state_updates", [])
    rolling["state_machine"].extend(new_states)

    # ── Move evidence_refs to separate index ──
    new_evidence = map_output.get("evidence_refs", [])
    evidence_index.extend(new_evidence)
    rolling["evidence_count"] = len(evidence_index)

    # ── Append delta_summary to rolling summary ──
    delta = map_output.get("delta_summary", "")
    if delta:
        if rolling["summary"]:
            rolling["summary"] = f"{rolling['summary']}\n\n[Batch {rolling['batch_count']}] {delta}"
        else:
            rolling["summary"] = f"[Batch {rolling['batch_count']}] {delta}"

    logger.info(
        f"[reduce] Batch {rolling['batch_count']}: "
        f"+{len(new_events)} events, +{len(new_errors)} errors, "
        f"+{len(new_states)} state_updates, +{len(new_evidence)} evidence_refs, "
        f"summary={_estimate_tokens(rolling['summary'])} tokens"
    )

    return rolling, evidence_index


def _prune_timeline(timeline: list[dict]) -> list[dict]:
    """Keep timeline within TIMELINE_MAX_EVENTS by removing low-value entries.

    Preserves: errors, first/last events, SIP milestones, state changes.
    Removes: routine success HTTP requests, redundant info entries.
    """
    if len(timeline) <= TIMELINE_MAX_EVENTS:
        return timeline

    high_priority_types = {"SIP", "error", "routing", "media", "registration"}

    high = []
    low = []
    for event in timeline:
        etype = event.get("type", "")
        detail = event.get("detail", "")
        is_error = "error" in etype.lower() or "error" in detail.lower()
        is_high = etype in high_priority_types or is_error
        if is_high:
            high.append(event)
        else:
            low.append(event)

    remaining_slots = TIMELINE_MAX_EVENTS - len(high)
    if remaining_slots > 0:
        kept_low = low[:remaining_slots]
    else:
        kept_low = []
        high = high[:TIMELINE_MAX_EVENTS]

    result = high + kept_low
    result.sort(key=lambda e: e.get("timestamp", ""))

    logger.info(
        f"[_prune_timeline] Pruned {len(timeline)} -> {len(result)} events "
        f"({len(high)} high-priority, {len(kept_low)} low-priority kept)"
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Compression
# ═══════════════════════════════════════════════════════════════════════════════

_ANALYSIS_COMPRESS_INSTRUCTION = """\
You are a log analysis compressor. The rolling analysis summary below has grown \
too large and must be compressed to approximately HALF its current length.

MUST preserve:
1. ALL errors — timestamps, codes, services, suspected causes (never drop these)
2. ALL correlation-critical IDs (session IDs, call IDs, tracking IDs linking services)
3. Key timeline milestones (first event, last event, SIP state transitions, error events)
4. Cross-service correlation evidence
5. Any unresolved questions or anomalies

MAY abbreviate or remove:
- Redundant success confirmations
- Verbose details of normal/expected HTTP 200 responses
- Duplicate information across batch summaries
- Routine registration or keep-alive events

Output the compressed summary directly, no preamble or explanation.\
"""


async def compress_analysis_summary(
    rolling: dict,
    budget: "TokenBudget",
) -> dict:
    """Compress rolling_analysis['summary'] when it exceeds ROLLING_SUMMARY_TOKEN_CAP.

    Calls the LLM to produce a shorter version that preserves errors, IDs, and
    key milestones. Mutates and returns the rolling dict.
    """
    summary = rolling.get("summary", "")
    current_tokens = _estimate_tokens(summary)

    if current_tokens <= ROLLING_SUMMARY_TOKEN_CAP:
        return rolling

    logger.info(
        f"[compress_analysis_summary] Summary at {current_tokens} tokens "
        f"(cap={ROLLING_SUMMARY_TOKEN_CAP}), compressing..."
    )

    api_key, api_base = _get_llm_config()

    try:
        response = await litellm.acompletion(
            model="openai/gpt-4.1",
            api_key=api_key,
            api_base=api_base,
            extra_headers={"x-cisco-app": "microservice-log-analyzer"},
            messages=[
                {"role": "system", "content": _ANALYSIS_COMPRESS_INSTRUCTION},
                {"role": "user", "content": summary},
            ],
            temperature=0,
        )

        compressed = response.choices[0].message.content or summary
        old_tokens = current_tokens
        new_tokens = _estimate_tokens(compressed)

        if budget:
            budget.record_usage(
                _estimate_tokens(summary) + _estimate_tokens(_ANALYSIS_COMPRESS_INSTRUCTION)
            )

        rolling["summary"] = compressed
        logger.info(
            f"[compress_analysis_summary] Compressed: {old_tokens} -> {new_tokens} tokens "
            f"(saved ~{old_tokens - new_tokens})"
        )

    except Exception as e:
        logger.error(f"[compress_analysis_summary] Compression failed: {e}")

    return rolling


# ═══════════════════════════════════════════════════════════════════════════════
# Format to Markdown
# ═══════════════════════════════════════════════════════════════════════════════


def format_to_markdown(
    rolling: dict,
    evidence_index: list[dict],
    search_summary: str = "",
) -> str:
    """Convert the final rolling_analysis + evidence_index into a markdown report.

    The output mirrors the section structure expected by downstream agents
    (sequence_diagram, chat_agent).
    """
    sections = []

    # ── Root Cause Analysis (errors) ──
    sections.append("---\n### Root Cause Analysis")
    errors = rolling.get("errors", [])
    if not errors:
        sections.append(
            "No errors or issues detected. The flow appears to have completed normally."
        )
    else:
        for err in errors:
            ts = err.get("timestamp", "unknown")
            code = err.get("code", "N/A")
            svc = err.get("service", "unknown")
            msg = err.get("message", "")
            cause = err.get("suspected_cause", "")
            sections.append(
                f"**[{ts}]**: {code}\n"
                f"  **Service**: {svc}\n"
                f"  **Description**: {msg}\n"
                f"  **Suspected Root Cause**: {cause}"
            )

    # ── Extracted Identifiers ──
    sections.append("\n---\n### Extracted Identifiers")
    ids = rolling.get("identifiers", {})
    label_map = {
        "session_ids": "Session ID",
        "call_ids": "Call ID (Mobius)",
        "sip_call_ids": "Call ID (SIP)",
        "sse_call_ids": "Call ID (SSE)",
        "tracking_ids": "Tracking ID",
        "user_ids": "User ID",
        "device_ids": "Device ID",
        "trace_ids": "Trace ID",
    }
    for key, label in label_map.items():
        vals = ids.get(key, [])
        if vals:
            sections.append(f"- **{label}**: {', '.join(vals)}")
        else:
            sections.append(f"- **{label}**: (not found)")

    # ── Search Scope ──
    if search_summary:
        sections.append("\n---\n### Search Scope")
        sections.append(search_summary)

    # ── Cross-Service Correlation ──
    sections.append("\n---\n### Cross-Service Correlation")
    corrs = rolling.get("cross_service_correlations", [])
    if corrs:
        for c in corrs:
            sections.append(f"- {c}")
    else:
        summary_text = rolling.get("summary", "")
        if "cross" in summary_text.lower() or "correlat" in summary_text.lower():
            sections.append("(See analysis summary below for cross-service details)")
        else:
            sections.append("No explicit cross-service correlations captured.")

    # ── Timing Analysis ──
    sections.append("\n---\n### Timing Analysis")
    timeline = rolling.get("timeline", [])
    if timeline:
        first = timeline[0].get("timestamp", "")
        last = timeline[-1].get("timestamp", "")
        sections.append(f"- **First event**: {first}")
        sections.append(f"- **Last event**: {last}")
        sections.append(f"- **Events captured**: {len(timeline)}")

        sip_events = [e for e in timeline if e.get("type") == "SIP"]
        if sip_events:
            sections.append(f"- **SIP messages**: {len(sip_events)}")
    else:
        sections.append("No timeline events captured.")

    # ── Final Outcome (analysis summary) ──
    sections.append("\n---\n### Final Outcome")
    summary = rolling.get("summary", "")
    if summary:
        sections.append(summary)
    else:
        sections.append("Analysis produced no summary.")

    # ── Timeline (condensed) ──
    if timeline:
        sections.append("\n---\n### Communication Flow")
        for event in timeline:
            ts = event.get("timestamp", "?")
            etype = event.get("type", "")
            src = event.get("source", "?")
            dst = event.get("destination", "?")
            detail = event.get("detail", "")
            sections.append(f"**[{ts}]** {src} -> {dst}: {etype} {detail}")

    # ── Evidence References ──
    if evidence_index:
        sections.append(f"\n---\n### Evidence Index ({len(evidence_index)} references)")
        for i, ref in enumerate(evidence_index[:20], 1):
            doc_id = ref.get("doc_id", "?")
            idx = ref.get("index", "?")
            ts = ref.get("timestamp", "?")
            cat = ref.get("category", "?")
            rel = ref.get("relevance", "")
            sections.append(f"{i}. `{doc_id}` ({idx}, {cat}) [{ts}] — {rel}")
        if len(evidence_index) > 20:
            sections.append(f"  ... and {len(evidence_index) - 20} more references")

    # ── Stats ──
    sections.append(f"\n---\n*Analysis: {rolling.get('batch_count', 0)} batches processed, "
                    f"{rolling.get('evidence_count', 0)} evidence references collected.*")

    return "\n".join(sections)


# ═══════════════════════════════════════════════════════════════════════════════
# Producer-Consumer: analysis consumer loop
# ═══════════════════════════════════════════════════════════════════════════════

SENTINEL = None  # pushed by the producer to signal "no more batches"


async def run_analysis_consumer(
    queue: "asyncio.Queue[list[dict] | None]",
    budget: "TokenBudget",
    search_summary: str = "",
) -> tuple[str, dict, list[dict]]:
    """Consume condensed hit batches from an asyncio.Queue and run MAP-REDUCE.

    The search producer pushes list[dict] items (condensed hits per page) onto
    the queue, then pushes SENTINEL (None) when done. This consumer processes
    them one-at-a-time with map_batch -> reduce, compressing the summary when
    it exceeds the token cap.

    Args:
        queue: asyncio.Queue fed by the search producer; items are
               list[dict] (condensed hits) or None (sentinel).
        budget: TokenBudget instance shared with the caller.
        search_summary: optional search_summary string for the final markdown.

    Returns:
        (markdown_report, rolling_analysis, evidence_index)
    """
    rolling = new_rolling_analysis()
    evidence_index: list[dict] = []

    batch_num = 0
    while True:
        item = await queue.get()
        if item is SENTINEL:
            queue.task_done()
            logger.info("[analysis_consumer] Received sentinel, finishing analysis")
            break

        batch_num += 1
        condensed_hits = item
        logger.info(
            f"[analysis_consumer] Processing batch {batch_num} "
            f"({len(condensed_hits)} entries)"
        )

        compact_memory = rolling["summary"]

        map_output = await map_batch(condensed_hits, compact_memory, budget)
        if map_output:
            rolling, evidence_index = reduce(rolling, map_output, evidence_index)

        summary_tokens = _estimate_tokens(rolling.get("summary", ""))
        if summary_tokens > ROLLING_SUMMARY_TOKEN_CAP:
            rolling = await compress_analysis_summary(rolling, budget)

        queue.task_done()

    markdown = format_to_markdown(rolling, evidence_index, search_summary)
    logger.info(
        f"[analysis_consumer] Done — {batch_num} batches, "
        f"{len(evidence_index)} evidence refs, "
        f"{_estimate_tokens(markdown)} tokens in report"
    )
    return markdown, rolling, evidence_index


# ═══════════════════════════════════════════════════════════════════════════════
# Upload-only (SDK logs pasted directly, no search)
# ═══════════════════════════════════════════════════════════════════════════════

_UPLOAD_BATCH_SIZE = 200


async def analyze_upload_only(
    sdk_logs: str,
    budget: "TokenBudget | None" = None,
) -> tuple[str, dict, list[dict]]:
    """Analyze SDK logs that were uploaded directly (no OpenSearch search).

    Splits the raw log text into line-based batches and runs the same
    map -> reduce -> compress pipeline.

    Args:
        sdk_logs: raw log text pasted or uploaded by the user.
        budget: optional TokenBudget for controlling LLM spend.

    Returns:
        (markdown_report, rolling_analysis, evidence_index)
    """
    if not sdk_logs or not sdk_logs.strip():
        return "(No SDK logs provided)", new_rolling_analysis(), []

    lines = sdk_logs.strip().splitlines()
    logger.info(f"[analyze_upload_only] Processing {len(lines)} lines of SDK logs")

    rolling = new_rolling_analysis()
    evidence_index: list[dict] = []

    for start in range(0, len(lines), _UPLOAD_BATCH_SIZE):
        batch_lines = lines[start : start + _UPLOAD_BATCH_SIZE]
        condensed = [{"raw_line": line, "line_num": start + i + 1}
                     for i, line in enumerate(batch_lines)]

        compact_memory = rolling["summary"]
        map_output = await map_batch(condensed, compact_memory, budget)

        if map_output:
            rolling, evidence_index = reduce(rolling, map_output, evidence_index)

        summary_tokens = _estimate_tokens(rolling.get("summary", ""))
        if summary_tokens > ROLLING_SUMMARY_TOKEN_CAP:
            rolling = await compress_analysis_summary(rolling, budget)

    markdown = format_to_markdown(rolling, evidence_index, search_summary="(SDK log upload)")
    logger.info(
        f"[analyze_upload_only] Done — {rolling['batch_count']} batches, "
        f"{len(evidence_index)} evidence refs"
    )
    return markdown, rolling, evidence_index
