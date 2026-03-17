"""
Incremental Map-Reduce Analysis — processes log batches as they arrive from search.

MAP step invokes batch_analysis_agent (from agent.py) via ADK Runner, giving each
batch the full power of calling_agent / contact_center_agent with skills and routing.
A single temporary ADK session is created per analysis run (not per batch) and
destroyed when the run finishes.

Exports a clean function interface consumed by search_agent_v2:
  - new_rolling_analysis()        → empty rolling state
  - map_batch()                   → MAP: one batch via ADK Runner → structured JSON
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
import uuid
from typing import Any

import litellm
from dotenv import load_dotenv
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from oauth_context import get_oauth_token

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)

from analyze.agent import batch_analysis_agent

# ═══════════════════════════════════════════════════════════════════════════════
# ADK Runner setup (reused across all map_batch calls)
# ═══════════════════════════════════════════════════════════════════════════════

_APP_NAME = "log-analyzer-incremental"
_USER_ID = "incremental-pipeline"

_session_service = InMemorySessionService()
_runner = Runner(
    agent=batch_analysis_agent,
    app_name=_APP_NAME,
    session_service=_session_service,
)

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
    """Return (api_key, api_base) for LLM calls.

    Prefers the per-request OAuth token from the contextvar (set by the
    router at request start) over stale env-var values.
    """
    api_key = get_oauth_token() or os.environ.get("OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY") or "pending-oauth"
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
# MAP Step — invokes batch_analysis_agent via ADK Runner
# ═══════════════════════════════════════════════════════════════════════════════

_MAP_USER_TEMPLATE = """\
## Prior Analysis Summary
{compact_memory}

## Log Batch (analyze this)
{batch_json}
"""


async def map_batch(
    condensed_hits: list[dict],
    compact_memory: str,
    session_id: str = "",
) -> dict:
    """MAP step: analyze one batch of log entries via ADK Runner.

    Creates a fresh session per batch to avoid context bloat — the
    compact_memory already carries forward essential context from prior
    batches, so session history is redundant.

    Args:
        condensed_hits: list of condensed log entries (from extract_id_fields_for_llm)
        compact_memory: the rolling_analysis["summary"] from prior batches (few KB)
        session_id: ignored (kept for API compat); a fresh session is created per call

    Returns:
        MapOutput dict matching the JSON schema, or empty dict on failure.
    """
    batch_json = json.dumps(condensed_hits, default=str)

    user_content = _MAP_USER_TEMPLATE.format(
        compact_memory=compact_memory or "(No prior analysis — this is the first batch)",
        batch_json=batch_json,
    )

    batch_session_id = f"batch-{uuid.uuid4().hex[:12]}"
    try:
        await _session_service.create_session(
            app_name=_APP_NAME,
            user_id=_USER_ID,
            session_id=batch_session_id,
        )

        user_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_content)],
        )

        final_text = ""
        async for event in _runner.run_async(
            user_id=_USER_ID,
            session_id=batch_session_id,
            new_message=user_message,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        final_text = part.text

        result = _parse_json_from_llm(final_text or "{}")

        logger.info(
            f"[map_batch] ADK Runner result: "
            f"events={len(result.get('events', []))}, "
            f"errors={len(result.get('errors', []))}, "
            f"state_updates={len(result.get('state_updates', []))}, "
            f"evidence_refs={len(result.get('evidence_refs', []))}"
        )
        return result

    except Exception as e:
        logger.error(f"[map_batch] ADK Runner call failed: {e}")
        return {}
    finally:
        try:
            await _session_service.delete_session(
                app_name=_APP_NAME,
                user_id=_USER_ID,
                session_id=batch_session_id,
            )
        except Exception:
            pass




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


async def compress_analysis_summary(rolling: dict) -> dict:
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
    lines: list[str] = []
    errors = rolling.get("errors", [])
    timeline = rolling.get("timeline", [])
    ids = rolling.get("identifiers", {})
    summary = rolling.get("summary", "")

    # ── Root Cause Analysis ──
    lines.append("### Root Cause Analysis\n")
    if not errors:
        lines.append(
            "No errors or issues detected. The flow appears to have completed normally.\n"
        )
    else:
        for i, err in enumerate(errors, 1):
            ts = err.get("timestamp", "unknown")
            code = err.get("code", "N/A")
            svc = err.get("service", "unknown")
            msg = err.get("message", "")
            cause = err.get("suspected_cause", "")
            ctx = err.get("context", "")
            fix = err.get("suggested_fix", "")
            impact = err.get("impact", "")

            lines.append(f"{i}. [{ts}] — `{code}`\n")
            lines.append("| Field | Detail |")
            lines.append("|-------|--------|")
            lines.append(f"| Service | {svc} |")
            lines.append(f"| Description | {msg} |")
            if ctx:
                lines.append(f"| Context | {ctx} |")
            lines.append(f"| Root Cause | {cause} |")
            if fix:
                lines.append(f"| Suggested Fix | {fix} |")
            if impact:
                lines.append(f"| Impact | {impact} |")
            lines.append("")

    # ── Extracted Identifiers ──
    lines.append("### Extracted Identifiers\n")
    label_map = {
        "tracking_ids": "Tracking ID",
        "call_ids": "Call ID (Mobius)",
        "sip_call_ids": "Call ID (SIP)",
        "sse_call_ids": "Call ID (SSE)",
        "session_ids": "Session ID",
        "user_ids": "User ID",
        "device_ids": "Device ID",
        "trace_ids": "Trace ID",
    }
    has_any_id = False
    for key, label in label_map.items():
        vals = ids.get(key, [])
        if vals:
            has_any_id = True
            lines.append(f"- {label}: `{'`, `'.join(vals)}`")
    if not has_any_id:
        lines.append("No identifiers extracted.")
    lines.append("")

    # ── Search Scope ──
    if search_summary:
        lines.append("### Search Scope\n")
        lines.append(search_summary)
        lines.append("")

    # ── Cross-Service Correlation ──
    lines.append("### Cross-Service Correlation\n")
    corrs = rolling.get("cross_service_correlations", [])
    if corrs:
        for c in corrs:
            lines.append(f"- {c}")
    else:
        if "cross" in summary.lower() or "correlat" in summary.lower():
            lines.append("(See Final Outcome below for cross-service details)")
        else:
            lines.append("No explicit cross-service correlations captured.")
    lines.append("")

    # ── Timing Analysis ──
    lines.append("### Timing Analysis\n")
    if timeline:
        first_ts = timeline[0].get("timestamp", "")
        last_ts = timeline[-1].get("timestamp", "")
        sip_evts = [e for e in timeline if e.get("type") == "SIP"]
        http_evts = [e for e in timeline if e.get("type") == "HTTP"]
        error_evts = [e for e in timeline if e.get("type") == "error"]

        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| First event | {first_ts} |")
        lines.append(f"| Last event | {last_ts} |")
        lines.append(f"| Total events | {len(timeline)} |")
        if http_evts:
            lines.append(f"| HTTP requests | {len(http_evts)} |")
        if sip_evts:
            lines.append(f"| SIP messages | {len(sip_evts)} |")
        if error_evts:
            lines.append(f"| Error events | {len(error_evts)} |")
    else:
        lines.append("No timeline events captured.")
    lines.append("")

    # ── Final Outcome ──
    lines.append("### Final Outcome\n")
    if summary:
        lines.append(summary)
    else:
        lines.append("Analysis produced no summary.")
    lines.append("")

    # ── Communication Flow (split by protocol) ──
    if timeline:
        http_evts = [e for e in timeline if e.get("type") == "HTTP"]
        sip_evts = [e for e in timeline if e.get("type") == "SIP"]
        other_evts = [e for e in timeline if e.get("type") not in ("HTTP", "SIP")]

        if http_evts:
            lines.append(f"### HTTP Communication Flow ({len(http_evts)} requests)\n")
            for ev in http_evts:
                ts = ev.get("timestamp", "?")
                src = ev.get("source", "?")
                dst = ev.get("destination", "?")
                detail = ev.get("detail", "")
                lines.append(f"- [{ts}] {src} \u2192 {dst}: {detail}")
            lines.append("")

        if sip_evts:
            lines.append(f"### SIP Communication Flow ({len(sip_evts)} messages)\n")
            for ev in sip_evts:
                ts = ev.get("timestamp", "?")
                src = ev.get("source", "?")
                dst = ev.get("destination", "?")
                detail = ev.get("detail", "")
                lines.append(f"- [{ts}] {src} \u2192 {dst}: {detail}")
            lines.append("")

        if other_evts:
            lines.append(f"### Other Events ({len(other_evts)})\n")
            for ev in other_evts:
                ts = ev.get("timestamp", "?")
                etype = ev.get("type", "")
                src = ev.get("source", "?")
                dst = ev.get("destination", "?")
                detail = ev.get("detail", "")
                lines.append(f"- [{ts}] `{etype}` {src} \u2192 {dst}: {detail}")
            lines.append("")

    # ── Evidence References ──
    if evidence_index:
        lines.append(f"### Evidence Index ({len(evidence_index)} references)\n")
        display_refs = evidence_index[:25]
        lines.append("| # | Doc ID | Index | Category | Timestamp | Relevance |")
        lines.append("|---|--------|-------|----------|-----------|-----------|")
        for i, ref in enumerate(display_refs, 1):
            doc_id = ref.get("doc_id", "?")
            idx = ref.get("index", "?")
            ts = ref.get("timestamp", "?")
            cat = ref.get("category", "?")
            rel = ref.get("relevance", "")
            lines.append(f"| {i} | `{doc_id}` | {idx} | {cat} | {ts} | {rel} |")
        if len(evidence_index) > 25:
            lines.append(f"\n*... and {len(evidence_index) - 25} more references*")
        lines.append("")

    # ── Stats ──
    lines.append(
        f"*Analysis: {rolling.get('batch_count', 0)} batches processed, "
        f"{len(errors)} errors found, "
        f"{len(timeline)} events captured, "
        f"{rolling.get('evidence_count', 0)} evidence references collected.*"
    )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Producer-Consumer: analysis consumer loop
# ═══════════════════════════════════════════════════════════════════════════════

SENTINEL = None  # pushed by the producer to signal "no more batches"


async def run_analysis_consumer(
    queue: "asyncio.Queue[list[dict] | None]",
    search_summary: str = "",
    sdk_logs: str = "",
) -> tuple[str, dict, list[dict]]:
    """Consume condensed hit batches from an asyncio.Queue and run MAP-REDUCE.

    The search producer pushes list[dict] items (condensed hits per page) onto
    the queue, then pushes SENTINEL (None) when done. This consumer processes
    them one-at-a-time with map_batch -> reduce, compressing the summary when
    it exceeds the token cap.

    After all search batches are consumed, if sdk_logs is provided the consumer
    chunks them and processes those batches too — building a unified
    rolling_analysis covering both data sources.

    Each batch gets a fresh ADK session (created/destroyed inside map_batch)
    to avoid context bloat. The compact_memory carries forward essential context.

    Args:
        queue: asyncio.Queue fed by the search producer; items are
               list[dict] (condensed hits) or None (sentinel).
        search_summary: optional search_summary string for the final markdown.
        sdk_logs: optional raw SDK log text to analyze after search batches.

    Returns:
        (markdown_report, rolling_analysis, evidence_index)
    """
    rolling = new_rolling_analysis()
    evidence_index: list[dict] = []

    logger.info("[analysis_consumer] Started (fresh session per batch mode)")

    batch_num = 0

    # Phase 1: consume search batches from the queue
    while True:
        item = await queue.get()
        if item is SENTINEL:
            queue.task_done()
            logger.info("[analysis_consumer] Received sentinel, search batches done")
            break

        batch_num += 1
        condensed_hits = item
        logger.info(
            f"[analysis_consumer] Processing search batch {batch_num} "
            f"({len(condensed_hits)} entries)"
        )

        compact_memory = rolling["summary"]

        map_output = await map_batch(condensed_hits, compact_memory)
        if map_output:
            rolling, evidence_index = reduce(rolling, map_output, evidence_index)

        summary_tokens = _estimate_tokens(rolling.get("summary", ""))
        if summary_tokens > ROLLING_SUMMARY_TOKEN_CAP:
            rolling = await compress_analysis_summary(rolling)

        queue.task_done()

    # Phase 2: chunk and process SDK logs (if provided)
    sdk_batches = chunk_sdk_logs(sdk_logs)
    if sdk_batches:
        logger.info(
            f"[analysis_consumer] Processing {len(sdk_batches)} SDK log batches "
            f"({sum(len(b) for b in sdk_batches)} lines)"
        )
        for condensed in sdk_batches:
            batch_num += 1
            logger.info(
                f"[analysis_consumer] Processing SDK batch {batch_num} "
                f"({len(condensed)} entries)"
            )

            compact_memory = rolling["summary"]
            map_output = await map_batch(condensed, compact_memory)
            if map_output:
                rolling, evidence_index = reduce(rolling, map_output, evidence_index)

            summary_tokens = _estimate_tokens(rolling.get("summary", ""))
            if summary_tokens > ROLLING_SUMMARY_TOKEN_CAP:
                rolling = await compress_analysis_summary(rolling)

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


def chunk_sdk_logs(sdk_logs: str, batch_size: int = _UPLOAD_BATCH_SIZE) -> list[list[dict]]:
    """Split raw SDK log text into batches of condensed dicts.

    Each dict has {"raw_line": <line text>, "line_num": <1-based line number>}.
    Returns an empty list if sdk_logs is blank.
    """
    if not sdk_logs or not sdk_logs.strip():
        return []
    lines = sdk_logs.strip().splitlines()
    batches: list[list[dict]] = []
    for start in range(0, len(lines), batch_size):
        batch_lines = lines[start : start + batch_size]
        batches.append([
            {"raw_line": line, "line_num": start + i + 1}
            for i, line in enumerate(batch_lines)
        ])
    return batches


async def analyze_upload_only(
    sdk_logs: str,
) -> tuple[str, dict, list[dict]]:
    """Analyze SDK logs that were uploaded directly (no OpenSearch search).

    Splits the raw log text into line-based batches and runs the same
    map -> reduce -> compress pipeline. Each batch gets a fresh ADK session
    (created/destroyed inside map_batch) to avoid context bloat.

    Args:
        sdk_logs: raw log text pasted or uploaded by the user.

    Returns:
        (markdown_report, rolling_analysis, evidence_index)
    """
    batches = chunk_sdk_logs(sdk_logs)
    if not batches:
        return "(No SDK logs provided)", new_rolling_analysis(), []

    logger.info(f"[analyze_upload_only] Processing {sum(len(b) for b in batches)} lines in {len(batches)} batches")

    rolling = new_rolling_analysis()
    evidence_index: list[dict] = []

    for condensed in batches:
        compact_memory = rolling["summary"]
        map_output = await map_batch(condensed, compact_memory)

        if map_output:
            rolling, evidence_index = reduce(rolling, map_output, evidence_index)

        summary_tokens = _estimate_tokens(rolling.get("summary", ""))
        if summary_tokens > ROLLING_SUMMARY_TOKEN_CAP:
            rolling = await compress_analysis_summary(rolling)

    markdown = format_to_markdown(rolling, evidence_index, search_summary="(SDK log upload)")
    logger.info(
        f"[analyze_upload_only] Done — {rolling['batch_count']} batches, "
        f"{len(evidence_index)} evidence refs"
    )
    return markdown, rolling, evidence_index
