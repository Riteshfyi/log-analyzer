import json
import os
import logging
from typing import Any, AsyncGenerator
from pathlib import Path
from dotenv import load_dotenv

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

from root_agent_v2.agent import root_agent as pipeline
from analyze_agent_v2.agent import analyze_agent
from visualAgent.agent import sequence_diagram_agent

logger = logging.getLogger(__name__)

STATE_DEFAULTS = {
    "mobius_logs": "",
    "sse_mse_logs": "",
    "wxcas_logs": "",
    "all_logs": "",
    "search_summary": "",
    "parsed_query": "",
    "extracted_ids": "",
    "latest_search_results": "",
    "analyze_results": "",
    "sequence_diagram": "",
    "sdk_logs": "",
}

PIPELINE_STATE_KEYS = [
    "mobius_logs", "sse_mse_logs", "wxcas_logs", "all_logs",
    "search_summary", "parsed_query", "extracted_ids",
    "latest_search_results", "analyze_results", "sequence_diagram",
    "sdk_logs",
]

# ── Intent parser (LlmAgent used internally, output never shown to user) ─────
intent_parser = LlmAgent(
    name="intent_parser",
    model=LiteLlm(
        model="openai/gpt-4.1-mini",
        api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY") or "pending-oauth",
        api_base=os.environ["AZURE_OPENAI_ENDPOINT"],
        extra_headers={"x-cisco-app": "microservice-log-analyzer"},
    ),
    output_key="parsed_intent",
    description="Internal intent classifier. Never shown to user.",
    instruction="""You are a silent intent classifier for a telecom log analysis tool.
You ONLY output a raw JSON object. No markdown. No explanation. No text.

================================================================
TASK
================================================================
Classify the user's CURRENT message as one of four intents:
  "search"    — the user provides a concrete identifier to look up
  "re_search" — the user wants to re-run a PREVIOUS search with different parameters
                (environment, region, detail level) but does NOT supply a new ID
  "upload"    — the user wants to analyze uploaded SDK/client logs (e.g. "analyze these logs",
                "look at the uploaded logs", "what do the SDK logs show") when sdk_logs are in state
  "chat"      — anything else (questions, explanations, comparisons, follow-ups)

================================================================
CRITICAL RULES (read carefully)
================================================================

1. ONLY look at the CURRENT message. Do NOT mine conversation history for IDs.

2. A message is SEARCH only when ALL of these are true:
   a) The current message contains a concrete identifier — one of:
      - Tracking ID  (pattern: *_uuid_* or MOBIUS_uuid, e.g. "webex-js-sdk_abc-123_14")
      - Call ID       (UUID like "e6764ee5-2500-4ae6-8dad-81b40936ef6d")
      - Session ID    (hex string like "2ee61aa6b1d34a59bc3d2c03dcfbd807")
      - SIP Call ID   (pattern: SSE*@ip, e.g. "SSE093819274240226@150.253.214.219")
      - Correlation ID (UUID)
   b) The user's intent is to retrieve/search logs for that identifier
      (explicit words like "search", "look up", "find", "fetch", "check logs for",
       OR simply pasting an ID with optional context like environment/region)

3. A message is RE_SEARCH when ALL of these are true:
   a) The current message does NOT contain a concrete identifier
   b) The user explicitly wants to repeat / retry / re-run a previous search
      with CHANGED parameters (different environment, region, or detail level)
   c) Key signals: "try … in integration", "search int instead of prod",
      "same but in EU", "re-run in prod", "now try prod", "switch to int"
   NOTE: If the message contains a concrete ID, classify as SEARCH, not RE_SEARCH.

4. A message is CHAT in ALL of these cases:
   - Questions about existing results: "what happened?", "explain the error",
     "why did this fail?", "tell me more", "in simpler words"
   - References to prior results: "the earlier one", "the first search",
     "compare them", "show me that again", "the 404 error"
   - Requests for logs/diagrams already in state: "show me the logs",
     "give me the diagram", "show the SIP flow"
   - Greetings, meta questions, or anything without a concrete ID AND without
     an explicit request to change search parameters
   - Vague references without parameter changes: "search for the same thing",
     "try that again", "the one before"

5. When in doubt between CHAT and RE_SEARCH, classify as "chat".
   When in doubt between CHAT and SEARCH, classify as "chat".
   False chat is harmless (user can rephrase). False search wastes resources.

================================================================
SEARCH FIELD DETECTION (for SEARCH intent only)
================================================================
Extract these from the CURRENT message only:

- searchValue: the exact identifier string from the message
- searchField: infer from the identifier pattern:
    * Contains "webex-js-sdk_" or "webex-web-client_" or "MOBIUS_" → "trackingId"
    * Contains "SSE" and "@" → "sipCallId"
    * 32-char hex (no dashes) → "sessionId"
    * UUID format (8-4-4-4-12 with dashes) → "callId"
    * Otherwise → "trackingId" (default)
- environment: "prod" or "int" ONLY if explicitly stated in the message, else null
- region: "us", "eu", etc. ONLY if explicitly stated, else null

================================================================
RE_SEARCH OVERRIDE EXTRACTION
================================================================
For RE_SEARCH, extract ONLY the parameters the user wants to change:

- environment: "prod" or "int" if mentioned, else null
- region: "us", "eu", etc. if mentioned, else null
(The system will merge these overrides with the previous search parameters.)

================================================================
OUTPUT FORMAT
================================================================
Output ONLY a raw JSON object. No markdown fences. No explanation.

Search (new ID):
{"intent": "search", "searchValue": "webex-js-sdk_abc-def_14", "searchField": "trackingId", "environment": "prod", "region": "us"}

Re-search (modify previous):
{"intent": "re_search", "environment": "int", "region": null}

Chat:
{"intent": "chat"}

================================================================
EXAMPLES
================================================================

Message: "webex-js-sdk_a649c9c0-11d0-40f2-8a08-ccb071b2ab55_14"
→ {"intent": "search", "searchValue": "webex-js-sdk_a649c9c0-11d0-40f2-8a08-ccb071b2ab55_14", "searchField": "trackingId", "environment": null, "region": null}

Message: "search prod tracking id webex-js-sdk_0a9b6e16-59b9-4f61-816b-d08421157087_138"
→ {"intent": "search", "searchValue": "webex-js-sdk_0a9b6e16-59b9-4f61-816b-d08421157087_138", "searchField": "trackingId", "environment": "prod", "region": null}

Message: "US int e6764ee5-2500-4ae6-8dad-81b40936ef6d"
→ {"intent": "search", "searchValue": "e6764ee5-2500-4ae6-8dad-81b40936ef6d", "searchField": "callId", "environment": "int", "region": "us"}

Message: "check SSE093819274240226-754428057@150.253.214.219 in prod"
→ {"intent": "search", "searchValue": "SSE093819274240226-754428057@150.253.214.219", "searchField": "sipCallId", "environment": "prod", "region": null}

Message: "try that tracking ID in integration"
→ {"intent": "re_search", "environment": "int", "region": null}
(No concrete ID, but explicit request to re-run in a different environment.)

Message: "maybe search for int instead of prod"
→ {"intent": "re_search", "environment": "int", "region": null}
(No concrete ID, but explicit environment change request.)

Message: "same thing but in EU"
→ {"intent": "re_search", "environment": null, "region": "eu"}

Message: "now try prod"
→ {"intent": "re_search", "environment": "prod", "region": null}

Message: "search for int instead of prod for webex-js-sdk_0a9b6e16-59b9-4f61-816b-d08421157087_138"
→ {"intent": "search", "searchValue": "webex-js-sdk_0a9b6e16-59b9-4f61-816b-d08421157087_138", "searchField": "trackingId", "environment": "int", "region": null}
(Contains a concrete ID — always SEARCH, not RE_SEARCH.)

Message: "explain in simpler words"
→ {"intent": "chat"}

Message: "the earlier one"
→ {"intent": "chat"}

Message: "can you compare the two errors?"
→ {"intent": "chat"}

Message: "show me the logs"
→ {"intent": "chat"}

Message: "what was the root cause?"
→ {"intent": "chat"}

Message: "hello"
→ {"intent": "chat"}

Message: "analyze these logs"
→ {"intent": "upload"}
(User wants to analyze uploaded SDK logs.)

Message: "what do the uploaded logs show?"
→ {"intent": "upload"}

Message: "search for the same thing"
→ {"intent": "chat"}
(Vague. No parameter change specified. User can rephrase.)

Message: "try that again"
→ {"intent": "chat"}
(No parameter change specified.)
""",
)


class QueryAnalyzerAgent(BaseAgent):
    """
    Deterministic routing agent with LLM intent parsing fallback.

    Fast path: structured JSON from frontend → parsed directly, no LLM.
    Slow path: natural language → intent_parser LLM classifies silently.

    The intent_parser events are consumed but NEVER yielded, so the user
    never sees its output. Only pipeline events are shown.
    """

    intent_parser: Any

    model_config = {"arbitrary_types_allowed": True}

    def __init__(self):
        super().__init__(
            name="query_analyzer",
            intent_parser=intent_parser,
            sub_agents=[intent_parser, pipeline],
        )

    @staticmethod
    def _propagate_api_key(token: str) -> None:
        """Update api_key on all LiteLlm model instances in the pipeline at runtime."""
        from chat_agent.agent import chat_agent

        agents_to_update = [intent_parser, chat_agent]
        for sub in pipeline.sub_agents:
            agents_to_update.append(sub)
            if hasattr(sub, "sub_agents"):
                agents_to_update.extend(sub.sub_agents)

        for agent in agents_to_update:
            model = getattr(agent, "model", None)
            if model and hasattr(model, "_additional_args"):
                model._additional_args["api_key"] = token

    # ── Fast path: structured JSON ───────────────────────────────

    def _parse_json_search(self, message: str) -> dict | None:
        try:
            params = json.loads(message)
            if not isinstance(params, dict):
                return None
            has_search = params.get("searchValue") and params.get("searchField")
            has_upload = params.get("uploadedFile")
            if has_search:
                return params
            if has_upload:
                return {
                    "type": "upload_only",
                    "sdk_logs": has_upload.get("content", ""),
                    "fileName": has_upload.get("name", ""),
                }
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    # ── Slow path: parse intent_parser LLM output ────────────────

    def _parse_llm_intent(self, raw: str, ctx: InvocationContext) -> dict | None:
        try:
            cleaned = raw.strip()
            cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            result = json.loads(cleaned)
            if not isinstance(result, dict):
                return None

            intent = result.get("intent")

            if intent == "search" and result.get("searchValue"):
                return {
                    "searchValue": result["searchValue"],
                    "searchField": result.get("searchField", "trackingId"),
                    "environment": result.get("environment"),
                    "region": result.get("region"),
                }

            if intent == "re_search":
                stored = ctx.session.state.get("last_search_params")
                if not stored:
                    logger.info("[query_analyzer] re_search but no previous search — treating as chat")
                    return None
                last = json.loads(stored) if isinstance(stored, str) else stored
                if not isinstance(last, dict):
                    return None
                merged = dict(last)
                for key in ("environment", "region"):
                    val = result.get(key)
                    if val is not None:
                        merged[key] = val
                return merged

        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        return None

    # ── Same-search comparison ───────────────────────────────────

    def _is_same_search(self, current: dict, ctx: InvocationContext) -> bool:
        stored = ctx.session.state.get("last_search_params")
        if not stored:
            return False
        try:
            last = json.loads(stored) if isinstance(stored, str) else stored
            return isinstance(last, dict) and current == last
        except (json.JSONDecodeError, TypeError):
            return False

    # ── Main routing logic ───────────────────────────────────────

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        # ── Step 0: initialize missing state defaults (must run before any early return
        #    so that chat_agent's instruction templates can resolve) ────────────
        for key, default in STATE_DEFAULTS.items():
            ctx.session.state.setdefault(key, default)

        # ── Step 1: set OAuth token from session state ───────────
        oauth_token = ctx.session.state.get("oauth_token", "")
        logger.info(f"[query_router] oauth_token from session: {'yes (' + str(len(oauth_token)) + ' chars)' if oauth_token else 'EMPTY'}")
        if oauth_token:
            os.environ["AZURE_OPENAI_API_KEY"] = oauth_token
            os.environ["OPENAI_API_KEY"] = oauth_token

            import litellm as _litellm
            _litellm.api_key = oauth_token
            _litellm.openai_key = oauth_token

            from dotenv import load_dotenv as _reload_dotenv
            os.environ["AZURE_OPENAI_API_KEY"] = oauth_token
            os.environ["OPENAI_API_KEY"] = oauth_token

            self._propagate_api_key(oauth_token)
            logger.info(f"[query_router] Token propagated to env, litellm global, and all agent models")
        elif not os.environ.get("AZURE_OPENAI_API_KEY"):
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="No OAuth token provided. Please sign in with Webex and try again.")]
                ),
            )
            return

        # ── Step 2: extract user message ─────────────────────────
        user_message = ""
        if ctx.session.events:
            last_event = ctx.session.events[-1]
            if last_event.content and last_event.content.parts:
                user_message = last_event.content.parts[0].text or ""

        # ── Step 3: resolve intent ───────────────────────────────
        search_params = self._parse_json_search(user_message)
        from_frontend = search_params is not None

        if from_frontend:
            logger.info("[query_analyzer] Fast path — structured JSON")
        elif user_message:
            logger.info("[query_analyzer] Slow path — running intent_parser")
            intent_text = ""
            async for event in self.intent_parser.run_async(ctx):
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            intent_text = part.text

            search_params = self._parse_llm_intent(intent_text, ctx)
            if search_params:
                logger.info("[query_analyzer] Intent parser extracted search: %s", search_params)
            else:
                logger.info("[query_analyzer] Intent parser classified as chat")

        # ── Step 4: decide whether to run pipeline ───────────────
        has_results = bool(ctx.session.state.get("analyze_results"))
        needs_pipeline = False
        upload_only = False

        if search_params is not None:
            if search_params.get("type") == "upload_only":
                needs_pipeline = True
                upload_only = True
            elif from_frontend and has_results and self._is_same_search(search_params, ctx):
                logger.info("[query_analyzer] Same JSON params from frontend — skipping pipeline")
            else:
                needs_pipeline = True
        elif not has_results:
            logger.info("[query_analyzer] No results and not a search — chat will handle")

        # ── Step 5: run pipeline if needed, otherwise stay silent ─
        if needs_pipeline:
            for key in PIPELINE_STATE_KEYS:
                ctx.session.state.pop(key, None)
            # Ensure sdk_logs always has a default so agent instructions
            # referencing {sdk_logs} don't raise KeyError when no file is uploaded.
            ctx.session.state["sdk_logs"] = ""

            # Store SDK logs if uploaded
            if upload_only:
                ctx.session.state["sdk_logs"] = search_params.get("sdk_logs", "")
                logger.info("[query_analyzer] Upload-only mode — skipping search, running analyze + visualize")
                async for event in analyze_agent.run_async(ctx):
                    yield event
                async for event in sequence_diagram_agent.run_async(ctx):
                    yield event
            else:
                uploaded = search_params.get("uploadedFile")
                if uploaded:
                    ctx.session.state["sdk_logs"] = uploaded.get("content", "")
                    logger.info("[query_analyzer] SDK logs uploaded alongside search")
                ctx.session.state["last_search_params"] = json.dumps(
                    search_params, sort_keys=True
                )
                logger.info("[query_analyzer] Running pipeline")
                async for event in pipeline.run_async(ctx):
                    yield event

        else:
            logger.info("[query_analyzer] Skipping pipeline — passing to chat_agent")
            return
            yield


query_router = QueryAnalyzerAgent()