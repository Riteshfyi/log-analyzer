"""
Exhaustive Search Agent v2 — Dynamic BFS-based log search with parallel execution.

Replaces the static sequential pipeline with a custom BaseAgent that:
1. Given any ID, searches relevant OpenSearch indexes directly (no MCP subprocess)
2. Extracts ALL discoverable IDs from results via a single LLM extractor
3. Repeats with newly found IDs (BFS graph traversal)
4. Parallelizes independent searches via asyncio.gather
5. If a session ID is the entry point, searches both Mobius AND wxcalling in parallel
"""

import os
import re
import json
import asyncio
import logging
import base64
import threading
import time
import requests
from collections import deque

_log_cache: dict[str, dict[str, str]] = {}
from pathlib import Path
from typing import Any, AsyncGenerator, Optional
from typing_extensions import override

from dotenv import load_dotenv
import litellm
from google.genai import types as genai_types
from google.adk.agents import LlmAgent, BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.models.lite_llm import LiteLlm

from analyze.incremental import (
    run_analysis_consumer,
    format_to_markdown,
    SENTINEL,
)
from opensearchpy import OpenSearch, RequestsHttpConnection

from oauth_context import SessionLiteLlm, get_oauth_token

# ═══════════════════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════════════════

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# OpenSearch OAuth Token Manager
# ═══════════════════════════════════════════════════════════════════════════════


class OpenSearchTokenManager:
    """
    Manages OAuth tokens for OpenSearch access via the identity broker flow.
    Supports both prod and int environments with independent token lifecycles.
    Thread-safe and auto-refreshes tokens before expiry.

    Flow: machine account credentials → bearer token → OAuth access token
    """

    # Token refresh buffer — refresh this many seconds before assumed expiry
    REFRESH_BUFFER_SECS = 300  # 5 minutes
    # Assume tokens live for 1 hour if no explicit expiry is given
    DEFAULT_TOKEN_LIFETIME_SECS = 3600

    def __init__(self, env_suffix: str = ""):
        """
        Args:
            env_suffix: "" for prod, "_INT" for int. Controls which env vars are read.
        """
        self._suffix = env_suffix
        self._env_label = "int" if env_suffix else "prod"
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._token_fetched_at: float = 0
        self._token_lifetime: float = self.DEFAULT_TOKEN_LIFETIME_SECS

        # Read credentials from env
        self._name = os.getenv(f"OPENSEARCH_OAUTH_NAME{env_suffix}", "")
        self._password = os.getenv(f"OPENSEARCH_OAUTH_PASSWORD{env_suffix}", "")
        self._client_id = os.getenv(f"OPENSEARCH_OAUTH_CLIENT_ID{env_suffix}", "")
        self._client_secret = os.getenv(f"OPENSEARCH_OAUTH_CLIENT_SECRET{env_suffix}", "")
        self._scope = os.getenv(f"OPENSEARCH_OAUTH_SCOPE{env_suffix}", "")
        self._bearer_token_url = os.getenv(f"OPENSEARCH_OAUTH_BEARER_TOKEN_URL{env_suffix}", "")
        self._oauth_token_url = os.getenv(f"OPENSEARCH_OAUTH_TOKEN_URL{env_suffix}", "")

        # Check if we already have a pre-set token in env
        pre_set = os.getenv(f"OPENSEARCH_OAUTH_TOKEN{env_suffix}", "")
        if pre_set:
            logger.debug(
                f"[OpenSearchTokenManager:{self._env_label}] "
                f"Found pre-set token in env (len={len(pre_set)})"
            )
            self._token = pre_set
            self._token_fetched_at = time.time()

        self._has_credentials = bool(
            self._name and self._password and self._bearer_token_url and self._oauth_token_url
        )

        logger.debug(
            f"[OpenSearchTokenManager:{self._env_label}] Initialized: "
            f"has_credentials={self._has_credentials}, "
            f"has_pre_set_token={bool(pre_set)}, "
            f"name={self._name[:10]}..., "
            f"bearer_url={self._bearer_token_url[:30]}..."
        )

    def _get_bearer_token(self) -> Optional[str]:
        """Step 1: Get bearer token from identity broker."""
        if not self._bearer_token_url or not self._name:
            logger.error(
                f"[OpenSearchTokenManager:{self._env_label}] "
                f"Missing bearer token URL or name"
            )
            return None
        try:
            payload = {"name": self._name, "password": self._password}
            headers = {"content-type": "application/json"}
            logger.debug(
                f"[OpenSearchTokenManager:{self._env_label}] "
                f"Requesting bearer token from {self._bearer_token_url}"
            )
            response = requests.post(
                self._bearer_token_url, json=payload, headers=headers, timeout=30
            )
            response.raise_for_status()
            token_data = response.json()
            bearer = token_data.get("BearerToken")
            if bearer:
                logger.debug(
                    f"[OpenSearchTokenManager:{self._env_label}] "
                    f"Got bearer token (len={len(bearer)})"
                )
                return bearer
            else:
                logger.error(
                    f"[OpenSearchTokenManager:{self._env_label}] "
                    f"BearerToken not in response: {list(token_data.keys())}"
                )
                return None
        except requests.RequestException as e:
            logger.error(
                f"[OpenSearchTokenManager:{self._env_label}] "
                f"Bearer token request failed: {e}"
            )
            return None

    def _exchange_for_oauth_token(self, bearer_token: str) -> Optional[str]:
        """Step 2: Exchange bearer token for OAuth access token."""
        try:
            credentials = f"{self._client_id}:{self._client_secret}"
            encoded = base64.b64encode(credentials.encode()).decode()
            payload = {
                "grant_type": "urn:ietf:params:oauth:grant-type:saml2-bearer",
                "scope": self._scope,
                "assertion": bearer_token,
            }
            headers = {
                "authorization": f"Basic {encoded}",
                "content-type": "application/x-www-form-urlencoded",
            }
            logger.debug(
                f"[OpenSearchTokenManager:{self._env_label}] "
                f"Exchanging bearer for OAuth token at {self._oauth_token_url}"
            )
            response = requests.post(
                self._oauth_token_url, data=payload, headers=headers, timeout=30
            )
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", self.DEFAULT_TOKEN_LIFETIME_SECS)

            if access_token:
                self._token_lifetime = float(expires_in)
                logger.debug(
                    f"[OpenSearchTokenManager:{self._env_label}] "
                    f"Got OAuth token (len={len(access_token)}, "
                    f"expires_in={expires_in}s)"
                )
                return access_token
            else:
                logger.error(
                    f"[OpenSearchTokenManager:{self._env_label}] "
                    f"access_token not in response: {list(token_data.keys())}"
                )
                return None
        except requests.RequestException as e:
            logger.error(
                f"[OpenSearchTokenManager:{self._env_label}] "
                f"OAuth token exchange failed: {e}"
            )
            return None

    def _fetch_token(self) -> Optional[str]:
        """Full flow: bearer → OAuth access token."""
        logger.info(
            f"[OpenSearchTokenManager:{self._env_label}] "
            f"Fetching new OAuth token via identity broker..."
        )
        bearer = self._get_bearer_token()
        if not bearer:
            return None
        token = self._exchange_for_oauth_token(bearer)
        if token:
            logger.info(
                f"[OpenSearchTokenManager:{self._env_label}] "
                f"Successfully obtained OAuth token"
            )
        return token

    def _is_token_expired(self) -> bool:
        if not self._token:
            return True
        age = time.time() - self._token_fetched_at
        expired = age >= (self._token_lifetime - self.REFRESH_BUFFER_SECS)
        if expired:
            logger.debug(
                f"[OpenSearchTokenManager:{self._env_label}] "
                f"Token expired/stale (age={age:.0f}s, "
                f"lifetime={self._token_lifetime:.0f}s)"
            )
        return expired

    def get_token(self) -> Optional[str]:
        """
        Get a valid OAuth token, refreshing if necessary. Thread-safe.
        Returns None if credentials are missing and no pre-set token exists.
        """
        # Fast path — token is still valid
        if self._token and not self._is_token_expired():
            logger.debug(
                f"[OpenSearchTokenManager:{self._env_label}] "
                f"Returning cached token (age="
                f"{time.time() - self._token_fetched_at:.0f}s)"
            )
            return self._token

        # Slow path — need to refresh
        with self._lock:
            # Double-check after acquiring lock
            if self._token and not self._is_token_expired():
                return self._token

            if not self._has_credentials:
                if self._token:
                    logger.warning(
                        f"[OpenSearchTokenManager:{self._env_label}] "
                        f"Token may be expired but no credentials to refresh. "
                        f"Returning stale token."
                    )
                    return self._token
                logger.error(
                    f"[OpenSearchTokenManager:{self._env_label}] "
                    f"No token and no credentials to fetch one. "
                    f"Set OPENSEARCH_OAUTH_NAME{self._suffix}, "
                    f"OPENSEARCH_OAUTH_PASSWORD{self._suffix}, etc."
                )
                return None

            new_token = self._fetch_token()
            if new_token:
                self._token = new_token
                self._token_fetched_at = time.time()
                # Also update env var so other code can see it
                os.environ[f"OPENSEARCH_OAUTH_TOKEN{self._suffix}"] = new_token
            else:
                logger.error(
                    f"[OpenSearchTokenManager:{self._env_label}] "
                    f"Token refresh failed"
                )
            return self._token


# ── Singleton instances ──
_token_manager_prod = OpenSearchTokenManager(env_suffix="")
_token_manager_int = OpenSearchTokenManager(env_suffix="_INT")


def get_opensearch_token(is_int: bool) -> Optional[str]:
    """Get a valid OpenSearch OAuth token for the given environment."""
    manager = _token_manager_int if is_int else _token_manager_prod
    return manager.get_token()

# ═══════════════════════════════════════════════════════════════════════════════
# Constants & Mappings
# ═══════════════════════════════════════════════════════════════════════════════

OPENSEARCH_INDEX_URL_MAP = {
    # Production
    "logstash-wxm-app": "https://logs-api-ci-wxm-app.o.webex.com/",
    "logstash-wxcalling": "https://logs-api-ci-wxcalling.o.webex.com/",
    "logstash-wxm-app-eu1": "https://logs-api-ci-wxm-app-eu1.o.webex.com/",
    "logstash-wxcallingeuc1": "https://logs-api-ci-wxcalling-euc1.o.webex.com/",
    "logstash-wbx2-access": "https://logs-api-ci-wbx2-access.o.webex.com/",
    # Integration
    "logstash-wxm-app-int": "https://logs-api-ci-wxm-app.o-int.webex.com/",
    "logstash-wxcalling-int": "https://logs-api-ci-wxcalling.o-int.webex.com/",
    "logstash-wxm-appeu-int": "https://logs-api-ci-wxm-appeu.o-int.webex.com/",
}

REGION_INDEX_MAPPING = {
    "wxm_app": {
        "prod": {"us": "logstash-wxm-app", "eu": "logstash-wxm-app-eu1"},
        "int": {"us": "logstash-wxm-app-int", "eu": "logstash-wxm-appeu-int"},
    },
    "wxcalling": {
        "prod": {"us": "logstash-wxcalling", "eu": "logstash-wxcallingeuc1"},
        "int": {"us": "logstash-wxcalling-int", "eu": "logstash-wxcalling-int"},
    },
}

# Maps an ID type → list of search targets (which service, field, query style, tag filter).
# When an ID type maps to multiple entries, ALL are searched in parallel.
# This is how session_id triggers parallel Mobius + wxcalling searches.
ID_TYPE_SEARCH_CONFIG = {
    "tracking_id": [
        {
            "service": "wxm_app",
            "query_type": "match_phrase",
            "field": "fields.WEBEX_TRACKINGID",
            "tag_filter": "mobius",
            "category": "mobius",
        },
    ],
    "session_id": [
        {
            "service": "wxm_app",
            "query_type": "session_id",
            "field": None,  # handled specially in build_query
            "tag_filter": "mobius",
            "category": "mobius",
        },
        {
            "service": "wxcalling",
            "query_type": "match_phrase",
            "field": "message",
            "tag_filter": "sse_mse",
            "category": "sse_mse",
        },
    ],
    "mobius_call_id": [
        {
            "service": "wxm_app",
            "query_type": "term",
            "field": "fields.mobiusCallId.keyword",
            "tag_filter": "mobius",
            "category": "mobius",
        },
    ],
    "sip_call_id": [
        {
            "service": "wxm_app",
            "query_type": "term",
            "field": "fields.sipCallId.keyword",
            "tag_filter": "mobius",
            "category": "mobius",
        },
    ],
    "sse_call_id": [
        {
            "service": "wxcalling",
            "query_type": "term",
            "field": "callId.keyword",
            "tag_filter": None,
            "category": "wxcas",
        },
    ],
    "call_id": [
        {
            "service": "wxcalling",
            "query_type": "term",
            "field": "callId.keyword",
            "tag_filter": None,
            "category": "wxcas",
        },
    ],
    "user_id": [
        {
            "service": "wxm_app",
            "query_type": "term",
            "field": "fields.USER_ID.keyword",
            "tag_filter": "mobius",
            "category": "mobius",
        },
    ],
    "device_id": [
        {
            "service": "wxm_app",
            "query_type": "term",
            "field": "fields.DEVICE_ID.keyword",
            "tag_filter": "mobius",
            "category": "mobius",
        },
    ],
    "trace_id": [
        {
            "service": "wxm_app",
            "query_type": "match_phrase",
            "field": "message",
            "tag_filter": "mobius",
            "category": "mobius",
        },
        {
            "service": "wxcalling",
            "query_type": "match_phrase",
            "field": "message",
            "tag_filter": None,
            "category": "wxcas",
        },
    ],
    # Fallback: match_phrase message search on both services
    "unknown": [
        {
            "service": "wxm_app",
            "query_type": "match_phrase",
            "field": "message",
            "tag_filter": "mobius",
            "category": "mobius",
        },
        {
            "service": "wxcalling",
            "query_type": "match_phrase",
            "field": "message",
            "tag_filter": None,
            "category": "wxcas",
        },
    ],
}

DUMMY_ID_VALUES = frozenset({
    "0000000000000000",
    "00000000000000000000000000000000",
    "00000000-0000-0000-0000-000000000000",
    "", "null", "None", "none", "N/A", "n/a", "unknown",
})

# Maps the LLM extractor's output keys → ID_TYPE_SEARCH_CONFIG keys
EXTRACTOR_KEY_TO_ID_TYPE = {
    "session_ids": "session_id",
    "tracking_ids": "tracking_id",
    "mobius_call_ids": "mobius_call_id",
    "sip_call_ids": "sip_call_id",
    "sse_call_ids": "sse_call_id",
    "call_ids": "call_id",
    # TODO: re-enable once we add time-range filters to avoid massive result sets
    # "user_ids": "user_id",
    # "device_ids": "device_id",
    "trace_ids": "trace_id",
}

# Regex for SSE Call-ID pattern in SIP message bodies
SSE_CALLID_PATTERN = re.compile(r"SSE\d+@[\d.]+")

# Pagination
PAGE_SIZE = 500

# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════


def _parse_json_from_llm(raw: Any) -> dict:
    """Extract a JSON object from LLM output, handling markdown code blocks."""
    logger.debug(f"[_parse_json_from_llm] Raw input type={type(raw).__name__}, length={len(str(raw))}")
    if isinstance(raw, dict):
        logger.debug("[_parse_json_from_llm] Input is already a dict, returning as-is")
        return raw
    raw = str(raw)
    # Direct parse
    try:
        result = json.loads(raw)
        logger.debug(f"[_parse_json_from_llm] Direct JSON parse succeeded, keys={list(result.keys())}")
        return result
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug(f"[_parse_json_from_llm] Direct parse failed: {e}")
    # Try code-block extraction: ```json { ... } ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group(1))
            logger.debug(f"[_parse_json_from_llm] Code-block extraction succeeded, keys={list(result.keys())}")
            return result
        except json.JSONDecodeError as e:
            logger.debug(f"[_parse_json_from_llm] Code-block parse failed: {e}")
    # Outermost { ... }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            result = json.loads(raw[start : end + 1])
            logger.debug(f"[_parse_json_from_llm] Brace extraction succeeded, keys={list(result.keys())}")
            return result
        except json.JSONDecodeError as e:
            logger.debug(f"[_parse_json_from_llm] Brace extraction failed: {e}")
    logger.warning(f"[_parse_json_from_llm] All parse attempts failed. Raw preview: {raw[:200]}")
    return {}


async def _extract_ids_from_batch(
    condensed: list[dict],
    instruction: str,
) -> dict:
    """Extract IDs from a single batch of condensed entries."""
    api_key = get_oauth_token()
    api_base = os.environ["AZURE_OPENAI_ENDPOINT"]
    user_content = json.dumps(condensed, default=str)

    try:
        response = await litellm.acompletion(
            model="openai/gpt-4.1-mini",
            api_key=api_key,
            api_base=api_base,
            extra_headers={"x-cisco-app": "microservice-log-analyzer"},
            messages=[
                {"role": "system", "content": instruction},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content
        return _parse_json_from_llm(raw)
    except Exception as e:
        logger.error(f"[_extract_ids_from_batch] Failed: {e}")
        return {}


def resolve_indexes(
    service: str, environments: list[str], regions: list[str]
) -> list[str]:
    """Resolve concrete OpenSearch index names for the given service/env/region combos."""
    logger.debug(f"[resolve_indexes] service={service}, envs={environments}, regions={regions}")
    indexes = []
    mapping = REGION_INDEX_MAPPING.get(service, {})
    if not mapping:
        logger.warning(f"[resolve_indexes] No mapping found for service '{service}'")
    for env in environments:
        env_mapping = mapping.get(env, {})
        if not env_mapping:
            logger.debug(f"[resolve_indexes] No mapping for service={service}, env={env}")
        for region in regions:
            idx = env_mapping.get(region)
            if idx:
                indexes.append(idx)
                logger.debug(f"[resolve_indexes] Resolved: {service}/{env}/{region} → {idx}")
            else:
                logger.debug(f"[resolve_indexes] No index for {service}/{env}/{region}")
    logger.debug(f"[resolve_indexes] Final indexes: {indexes}")
    return indexes


def build_query(
    id_value: str,
    query_type: str,
    field: str | None,
    tag_filter: str | None,
    time_range: tuple[str, str] | None = None,
) -> dict:
    """Build an OpenSearch DSL query body.

    Args:
        time_range: Optional (gte, lte) ISO timestamps to scope the search.
                    Applied as a @timestamp range filter to avoid full-index scans.
    """
    logger.info(
        f"[build_query] INPUTS: id_value={id_value}, query_type={query_type}, "
        f"field={field}, tag_filter={tag_filter}, time_range={time_range}"
    )
    # ── ID match clause ──
    # Uses term for exact keyword matches, match_phrase for text searches
    # (consistent with MCP OpenSearch DSL — no wildcard queries)
    if query_type == "term":
        id_clause = {"term": {field: id_value}}
        logger.debug(f"[build_query] Using term query on {field}")
    elif query_type == "match_phrase":
        target_field = field or "message"
        id_clause = {"match_phrase": {target_field: id_value}}
        logger.debug(f"[build_query] Using match_phrase on {target_field}")
    elif query_type == "session_id":
        # Search both localSessionId and remoteSessionId
        id_clause = {
            "bool": {
                "should": [
                    {"term": {"fields.localSessionId.keyword": id_value}},
                    {"term": {"fields.remoteSessionId.keyword": id_value}},
                ],
                "minimum_should_match": 1,
            }
        }
        logger.debug(f"[build_query] Using session_id dual-field query (local+remote)")
    else:
        # Fallback: match_phrase on message (uses inverted index, not char scan)
        id_clause = {"match_phrase": {"message": id_value}}
        logger.warning(f"[build_query] Unknown query_type '{query_type}', falling back to match_phrase on message")

    # ── Filter clauses (no scoring, cacheable — consistent with MCP OpenSearch DSL) ──
    filter_clauses: list[dict] = [id_clause]

    if tag_filter == "mobius":
        filter_clauses.append({"terms": {"tags": ["mobius"]}})
        logger.debug("[build_query] Added mobius tag filter")
    elif tag_filter == "sse_mse":
        filter_clauses.append({"terms": {"tags": ["sse", "mse"]}})
        logger.debug("[build_query] Added sse/mse tag filter")
    else:
        logger.debug("[build_query] No tag filter applied")

    # ── Time range filter — always applied to avoid full-index scans ──
    if time_range:
        filter_clauses.append(
            {"range": {"@timestamp": {"gte": time_range[0], "lte": time_range[1]}}}
        )
        logger.debug(
            f"[build_query] Added time range filter: {time_range[0]} → {time_range[1]}"
        )
    else:
        filter_clauses.append(
            {"range": {"@timestamp": {"gte": "now-7d/d", "format": "strict_date_optional_time"}}}
        )
        logger.debug("[build_query] Added default 7-day time range filter")

    query = {
        "query": {"bool": {"filter": filter_clauses}},
        "size": PAGE_SIZE,
        "sort": [{"@timestamp": {"order": "desc"}}],
    }
    logger.info(f"[build_query] Final DSL: {json.dumps(query, default=str)}")
    return query


async def search_opensearch(index: str, query: dict) -> dict:
    """
    Execute an OpenSearch search with search_after pagination.
    Returns all hits across all pages, accumulated into a single result dict.
    Parallel-safe — each call creates its own client with its own token.
    """
    logger.debug(f"[search_opensearch] Starting paginated search for index={index}")

    is_int = index.endswith("-int")
    token = get_opensearch_token(is_int)
    url = OPENSEARCH_INDEX_URL_MAP.get(index)

    if not url:
        logger.error(f"[search_opensearch] No URL mapping for index: {index}")
        return {"hits": {"hits": [], "total": {"value": 0}}}

    if not token:
        logger.error(
            f"[search_opensearch] No OAuth token available for "
            f"{'int' if is_int else 'prod'}. Check credentials."
        )
        return {"hits": {"hits": [], "total": {"value": 0}}}

    def _do_paginated_search() -> dict:
        client = OpenSearch(
            hosts=[url],
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            headers={"Authorization": f"Bearer {token}"},
            timeout=3000,
        )

        all_hits = []
        total_value = 0
        page_query = dict(query)
        page_num = 0

        while True:
            page_num += 1
            logger.debug(f"[search_opensearch] Page {page_num} for {index}")

            result = client.search(index=index, body=page_query)
            hits = result.get("hits", {}).get("hits", [])
            total_info = result.get("hits", {}).get("total", {})

            if page_num == 1:
                total_value = total_info.get("value", 0) if isinstance(total_info, dict) else total_info

            all_hits.extend(hits)

            logger.debug(
                f"[search_opensearch] Page {page_num}: {len(hits)} hits "
                f"(cumulative: {len(all_hits)}, total: {total_value})"
            )

            if len(hits) < PAGE_SIZE:
                break

            last_hit = hits[-1]
            sort_values = last_hit.get("sort")
            if not sort_values:
                logger.warning(
                    f"[search_opensearch] No sort values on last hit, "
                    f"stopping pagination at page {page_num}"
                )
                break

            page_query = dict(query)
            page_query["search_after"] = sort_values

        logger.info(
            f"[search_opensearch] Completed {page_num} page(s) for {index}: "
            f"{len(all_hits)} total hits (server total: {total_value})"
        )

        return {
            "hits": {
                "hits": all_hits,
                "total": {"value": total_value},
            },
            "pages": page_num,
        }

    try:
        result = await asyncio.to_thread(_do_paginated_search)
        return result
    except Exception as e:
        logger.error(
            f"[search_opensearch] Search failed for index {index}: "
            f"{type(e).__name__}: {e}", exc_info=True
        )
        return {"hits": {"hits": [], "total": {"value": 0}}}


async def search_opensearch_pages(
    index: str,
    query: dict,
) -> AsyncGenerator[list[dict], None]:
    """
    Streaming paginated search — yields each page of hits as it arrives.
    Used by the progressive staged search to process batches incrementally.
    """
    is_int = index.endswith("-int")
    token = get_opensearch_token(is_int)
    url = OPENSEARCH_INDEX_URL_MAP.get(index)

    logger.info(
        f"[search_opensearch_pages] Starting paginated search: index={index}, "
        f"url={url}, has_token={'yes' if token else 'NO'}, "
        f"is_int={is_int}"
    )
    logger.info(f"[search_opensearch_pages] Query DSL: {json.dumps(query, default=str)}")

    if not url or not token:
        logger.error(
            f"[search_opensearch_pages] Missing URL or token for {index} "
            f"(url={'set' if url else 'MISSING'}, token={'set' if token else 'MISSING'})"
        )
        return

    def _fetch_page(page_query: dict) -> dict:
        client = OpenSearch(
            hosts=[url],
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            headers={"Authorization": f"Bearer {token}"},
            timeout=3000,
        )
        return client.search(index=index, body=page_query)

    page_query = dict(query)
    page_num = 0

    while True:
        page_num += 1
        logger.info(
            f"[search_opensearch_pages] Fetching page {page_num} for {index}, "
            f"search_after={page_query.get('search_after', 'none')}"
        )
        try:
            result = await asyncio.to_thread(_fetch_page, page_query)
        except Exception as e:
            logger.error(f"[search_opensearch_pages] Page {page_num} failed: {e}")
            break

        total_info = result.get("hits", {}).get("total", {})
        total_value = total_info.get("value", 0) if isinstance(total_info, dict) else total_info
        hits = result.get("hits", {}).get("hits", [])

        logger.info(
            f"[search_opensearch_pages] Page {page_num} result: "
            f"{len(hits)} hits returned, server total={total_value}"
        )

        if not hits:
            logger.info(f"[search_opensearch_pages] No hits on page {page_num}, stopping")
            break

        yield hits

        if len(hits) < PAGE_SIZE:
            logger.info(
                f"[search_opensearch_pages] Last page ({len(hits)} < PAGE_SIZE={PAGE_SIZE}), stopping"
            )
            break

        sort_values = hits[-1].get("sort")
        if not sort_values:
            logger.warning(f"[search_opensearch_pages] No sort values on last hit, stopping")
            break

        logger.info(f"[search_opensearch_pages] search_after cursor: {sort_values}")
        page_query = dict(query)
        page_query["search_after"] = sort_values


def extract_id_fields_for_llm(hits: list[dict]) -> list[dict]:
    """
    Extract only ID-relevant fields from search hits for LLM consumption.
    Reduces token usage by stripping irrelevant data while preserving
    all identifiers and enough message context for embedded ID discovery.
    """
    logger.debug(f"[extract_id_fields_for_llm] Processing {len(hits)} hits")
    extracted = []
    ids_found_count = 0
    for hit in hits:
        source = hit.get("_source", {})
        fields = source.get("fields", {})
        entry: dict[str, Any] = {
            "timestamp": source.get("@timestamp"),
            "tags": source.get("tags"),
            # Truncate long SIP messages — SSE Call-IDs are in headers (first ~500 chars)
            "message": source.get("message") or "",
        }
        # Nested ID fields (Mobius log structure: _source.fields.<name>)
        for id_field in (
            "localSessionId",
            "remoteSessionId",
            "mobiusCallId",
            "sipCallId",
            "WEBEX_TRACKINGID",
            "USER_ID",
            "DEVICE_ID",
        ):
            val = fields.get(id_field)
            if isinstance(val, list):
                val = val[0] if val else None
            if val and str(val) not in DUMMY_ID_VALUES:
                entry[id_field] = val
        # Top-level ID fields (wxcalling log structure: _source.<name>)
        for id_field in ("callId", "traceId", "sessionId"):
            val = source.get(id_field)
            if isinstance(val, list):
                val = val[0] if val else None
            if val and str(val) not in DUMMY_ID_VALUES:
                entry[id_field] = val
                ids_found_count += 1
        extracted.append(entry)
    logger.debug(
        f"[extract_id_fields_for_llm] Extracted {len(extracted)} entries, "
        f"{ids_found_count} non-dummy ID field values found across all entries"
    )
    if extracted:
        logger.debug(f"[extract_id_fields_for_llm] Sample entry keys: {list(extracted[0].keys())}")
    return extracted


# ═══════════════════════════════════════════════════════════════════════════════
# LLM Model Factory
# ═══════════════════════════════════════════════════════════════════════════════


def _make_model() -> SessionLiteLlm:
    return SessionLiteLlm(
        model="openai/gpt-4.1-mini",
        api_key="pending-oauth",
        api_base=os.environ["AZURE_OPENAI_ENDPOINT"],
        extra_headers={"x-cisco-app": "microservice-log-analyzer"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# LLM Sub-Agents
# ═══════════════════════════════════════════════════════════════════════════════

query_parser = LlmAgent(
    model=_make_model(),
    name="query_parser",
    output_key="parsed_query",
    instruction="""You are a query parsing agent. Extract structured search parameters from the user's message.

Output ONLY a valid JSON object with this exact structure:
```json
{
    "identifiers": [{"value": "<id_value>", "type": "<id_type>"}],
    "environments": ["prod"],
    "regions": ["us"],
    "detailedAnalysis": false
}
```

**detailedAnalysis Detection:**
- Look for a "detailedAnalysis" field if the query is structured JSON
- Look for mentions of "detailed analysis", "detailed", "verbose", "full analysis"
- Default: false

**ID Type Detection Rules:**
- Pattern `SSE\\d+@[\\d.]+` (e.g. SSE0520080392@10.249.187.80) → type: "sse_call_id"
- Described as / labeled as tracking ID, or contains "sdk" → type: "tracking_id"
- Described as / labeled as session ID → type: "session_id"
- Described as / labeled as mobius call ID → type: "mobius_call_id"
- Described as / labeled as SIP call ID → type: "sip_call_id"
- Described as / labeled as user ID → type: "user_id"
- Described as / labeled as device ID → type: "device_id"
- Described as / labeled as call ID → type: "call_id"
- Described as / labeled as trace ID → type: "trace_id"
- Unable to determine → type: "unknown"

**Environment & Region Detection:**
- Look for "environments" or "regions" fields if the query is structured JSON
- Look for mentions of "prod"/"production", "int"/"integration", "us", "eu"
- Environment default: ["prod"]
- Region default: ["us"]

**Multiple IDs:** If the user provides multiple IDs, include all of them in the identifiers array.

Output ONLY the JSON object, no other text or markdown.""",
)

id_extractor = LlmAgent(
    model=_make_model(),
    name="id_extractor",
    output_key="extracted_ids",
    instruction="""You are an expert ID extraction agent for Webex Calling microservice logs.
Analyze the search results in {latest_search_results} and extract ALL unique identifiers.

**Output Format — JSON only:**
```json
{
    "session_ids": [],
    "tracking_ids": [],
    "mobius_call_ids": [],
    "sip_call_ids": [],
    "sse_call_ids": [],
    "call_ids": [],
    "user_ids": [],
    "device_ids": [],
    "trace_ids": []
}
```

**🚨 ID FORMAT GUIDE — use this to correctly classify IDs:**

1. **Session IDs** (`session_ids`):
   - Alphanumeric strings, typically 32 hex chars (NOT UUIDs with dashes)
   - Example: `a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4`
   - Found in: `localSessionId`, `remoteSessionId`, `sessionId` fields
   - IGNORE dummy: `0000000000000000`, `00000000000000000000000000000000`
   - These represent the calling session — both local and remote sides

2. **Tracking IDs** (`tracking_ids`):
   - Format: `<prefix>_<uuid>_<suffix>` — often contains "sdk"
   - Example: `webex-js-sdk_2b08d954-8cf8-460c-bf91-b9dddb1d8533_130`
   - Example: `ROUTER_67ad7bdd-3b2d-4e01-9b12-abcdef123456`
   - Found in: `WEBEX_TRACKINGID` field, or `trackingId` in message
   - These trace a request across all microservices

3. **Mobius Call IDs** (`mobius_call_ids`):
   - Mobius-internal call identifier, typically a UUID or hex string
   - Example: `e67b3f1a-2d4c-4e8f-9a1b-3c5d7e9f0a2b`
   - Found in: `mobiusCallId` field

4. **SIP Call IDs** (`sip_call_ids`):
   - Standard SIP Call-ID header values (NOT SSE format)
   - Example: `1-12345@10.0.0.1`, `abc123-def456@server.example.com`
   - Found in: `sipCallId` field

5. **SSE Call IDs** (`sse_call_ids`):
   - **VERY SPECIFIC pattern**: starts with `SSE`, followed by digits, then `@`, then IP address
   - Regex: `SSE[0-9]+@[0-9.]+`
   - Example: `SSE0520080392201261106889615@10.249.187.80`
   - Found in: `callId` field OR in SIP `Call-ID:` headers within `message` content
   - These are the KEY identifier for correlating SSE/MSE with WxCAS logs
   - ⚠️ ONLY classify as sse_call_ids if it matches the SSE+digits+@+IP pattern

6. **Generic Call IDs** (`call_ids`):
   - Any `callId` that does NOT match the SSE pattern above
   - Found in: `callId` field (top-level)

7. **User IDs** (`user_ids`):
   - Cisco user identifiers
   - Found in: `USER_ID` field

8. **Device IDs** (`device_ids`):
   - Cisco device identifiers, often base64-encoded URLs
   - Example: `Y2lzY29zcGFyazovL3VzL0RFVklDRS8xMmFiYzM0ZGVmNTY`
   - Found in: `DEVICE_ID` field

9. **Trace IDs** (`trace_ids`):
   - Distributed tracing identifiers
   - Found in: `traceId` field

**Where to Look:**
- Structured fields: `localSessionId`, `remoteSessionId`, `mobiusCallId`, `sipCallId`,
  `WEBEX_TRACKINGID`, `USER_ID`, `DEVICE_ID`, `traceId`, `callId`, `sessionId`
- Inside `message` content: SIP headers contain `Call-ID:` values (look for SSE pattern),
  tracking IDs, session IDs embedded in log text
- ⚠️ DO NOT just grab random UUIDs from message text — only extract values you can
  confidently classify into one of the above categories

**Rules:**
- IGNORE dummy values: `0000000000000000`, `00000000000000000000000000000000`,
  `00000000-0000-0000-0000-000000000000`, empty strings, null, "N/A", "unknown"
- IGNORE IDs that start with `NA_` prefix (e.g. `NA_a84585d5-9eb7-49d0-...`) — these are not real IDs
- DEDUPLICATE: each ID appears only once per category
- Include ALL categories in output, even if empty (use empty array [])
- Be PRECISE: only extract values you are confident about. A random hex string in a
  log message is NOT necessarily a session ID
- Output ONLY the JSON object, no other text or markdown""",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Custom Agent: ExhaustiveSearchAgent
# ═══════════════════════════════════════════════════════════════════════════════


class ExhaustiveSearchAgent(BaseAgent):
    """
    BFS graph-traversal search agent.

    Given any initial ID(s), this agent:
    1. Classifies each ID to determine which indexes/fields to search
    2. Executes all searches in parallel via asyncio.gather
    3. Extracts all discoverable IDs from results via LLM
    4. Feeds newly discovered IDs back into the search frontier
    5. Repeats until no new IDs are found or max_depth is reached

    Session IDs automatically trigger parallel searches on both Mobius and
    wxcalling indexes from the first iteration.
    """

    # ── Pydantic field declarations ──
    query_parser: LlmAgent
    id_extractor: LlmAgent
    max_depth: int = 5

    model_config = {"arbitrary_types_allowed": True}

    def __init__(
        self,
        name: str,
        query_parser: LlmAgent,
        id_extractor: LlmAgent,
        max_depth: int = 5,
    ):
        super().__init__(
            name=name,
            query_parser=query_parser,
            id_extractor=id_extractor,
            max_depth=max_depth,
            sub_agents=[query_parser, id_extractor],
        )

    # ── Helper: process a page of hits progressively ──
    async def _process_hits_progressive(
        self,
        hits: list[dict],
        all_logs: dict[str, list[dict]],
        seen_hit_ids: set[str],
        category: str,
        id_extractor_instruction: str,
        analysis_queue: "asyncio.Queue | None" = None,
    ) -> tuple[str, dict, int]:
        """
        Process a page of hits: deduplicate, extract IDs.
        Returns (extracted_ids, new_unique_count).
        """
        # Deduplicate
        new_hits = []
        dupes = 0
        for hit in hits:
            hid = hit.get("_id", "")
            if hid and hid not in seen_hit_ids:
                seen_hit_ids.add(hid)
                all_logs[category].append(hit)
                new_hits.append(hit)
            else:
                dupes += 1

        logger.info(
            f"[_process_hits_progressive] category={category}: "
            f"{len(hits)} hits in, {len(new_hits)} new, {dupes} dupes, "
            f"seen_hit_ids total={len(seen_hit_ids)}, "
            f"all_logs[{category}] total={len(all_logs[category])}"
        )

        if not new_hits:
            logger.info(f"[_process_hits_progressive] All dupes for {category}, skipping")
            return {}, 0

        condensed = extract_id_fields_for_llm(new_hits)
        logger.info(
            f"[_process_hits_progressive] Condensed {len(new_hits)} hits -> "
            f"{len(condensed)} entries for LLM"
        )

        if analysis_queue is not None:
            await analysis_queue.put(condensed)
            logger.info(
                f"[_process_hits_progressive] Pushed {len(condensed)} entries "
                f"to analysis queue"
            )

        extracted = await _extract_ids_from_batch(condensed, id_extractor_instruction)
        logger.info(
            f"[_process_hits_progressive] LLM results: "
            f"extracted_ids={json.dumps({k: len(v) for k, v in extracted.items() if v}, default=str)}"
        )

        return extracted, len(new_hits)

    # ── Helper: merge extracted IDs into accumulated set ──
    @staticmethod
    def _merge_extracted_ids(accumulated: dict, new_ids: dict) -> dict:
        """Merge new extracted IDs into the accumulated dict, deduplicating."""
        id_keys = [
            "session_ids", "tracking_ids", "mobius_call_ids", "sip_call_ids",
            "sse_call_ids", "call_ids", "user_ids", "device_ids", "trace_ids",
        ]
        if not accumulated:
            accumulated = {k: [] for k in id_keys}
        for key in id_keys:
            existing = set(accumulated.get(key, []))
            for val in new_ids.get(key, []):
                val = str(val).strip()
                if val and val not in existing:
                    existing.add(val)
                    accumulated.setdefault(key, []).append(val)
        return accumulated

    # ── Helper: add newly extracted IDs to frontier ──
    def _enqueue_new_ids(
        self,
        extracted: dict,
        all_seen_ids: set[str],
        frontier: deque,
        current_depth: int,
    ) -> tuple[int, int, int]:
        """Returns (new_count, skipped_seen, skipped_dummy)."""
        logger.info(
            f"[{self.name}] _enqueue_new_ids: depth={current_depth}, "
            f"all_seen_ids={len(all_seen_ids)}, frontier_before={len(frontier)}, "
            f"extracted keys with values: "
            f"{json.dumps({k: len(v) for k, v in extracted.items() if v}, default=str)}"
        )
        new_ids_count = 0
        skipped_seen = 0
        skipped_dummy = 0
        for extract_key, id_type in EXTRACTOR_KEY_TO_ID_TYPE.items():
            ids = extracted.get(extract_key, [])
            if isinstance(ids, str):
                ids = [ids]
            for id_val in ids:
                id_val = str(id_val).strip()
                if not id_val or id_val in DUMMY_ID_VALUES:
                    skipped_dummy += 1
                    logger.debug(f"[{self.name}]   SKIP dummy: {extract_key}='{id_val}'")
                    continue
                if id_val.startswith("NA_"):
                    skipped_dummy += 1
                    logger.debug(f"[{self.name}]   SKIP NA_ prefix: {extract_key}='{id_val}'")
                    continue
                # FLAG: Only follow webex-js-sdk tracking IDs for now.
                # Update this condition to allow other prefixes later.
                if extract_key == "tracking_ids" and not id_val.startswith("webex-js-sdk_"):
                    skipped_dummy += 1
                    logger.debug(f"[{self.name}]   SKIP non-sdk tracking ID: '{id_val}'")
                    continue
                if id_val in all_seen_ids:
                    skipped_seen += 1
                    logger.debug(f"[{self.name}]   SKIP already seen: {id_type}='{id_val}'")
                    continue
                frontier.append((id_val, id_type, current_depth + 1))
                all_seen_ids.add(id_val)
                new_ids_count += 1
                logger.info(f"[{self.name}]   ENQUEUE: {id_type}='{id_val}' -> depth {current_depth + 1}")
                print(f"  + {id_type} = {id_val} -> queued for depth {current_depth + 1}")

        logger.info(
            f"[{self.name}] _enqueue_new_ids result: new={new_ids_count}, "
            f"skipped_seen={skipped_seen}, skipped_dummy={skipped_dummy}, "
            f"frontier_after={len(frontier)}"
        )
        return new_ids_count, skipped_seen, skipped_dummy

    def _enqueue_fallback_device_ids(
        self,
        extracted: dict,
        all_seen_ids: set[str],
        frontier: deque,
        current_depth: int,
    ) -> int:
        """Enqueue device_ids as fallback when no other new IDs were found."""
        enqueued = 0
        for id_val in extracted.get("device_ids", []):
            id_val = str(id_val).strip()
            if not id_val or id_val in DUMMY_ID_VALUES or id_val.startswith("NA_"):
                continue
            if id_val in all_seen_ids:
                continue
            frontier.append((id_val, "device_id", current_depth + 1))
            all_seen_ids.add(id_val)
            enqueued += 1
            logger.info(f"[{self.name}]   ENQUEUE fallback: device_id='{id_val}' -> depth {current_depth + 1}")
            print(f"  + device_id = {id_val} -> queued for depth {current_depth + 1} (fallback)")
        return enqueued

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        logger.info(f"[{self.name}] Starting progressive staged search")

        # ══════════════════════════════════════════════════════════════════════
        # Step 1: Parse the user's query via LLM
        # ══════════════════════════════════════════════════════════════════════
        logger.info(f"[{self.name}] Step 1: Parsing user query via LLM...")
        async for event in self.query_parser.run_async(ctx):
            yield event

        raw_parsed = ctx.session.state.get("parsed_query", "{}")
        logger.info(f"[{self.name}] Raw parsed_query from LLM: {raw_parsed}")
        parsed = _parse_json_from_llm(raw_parsed)
        logger.info(f"[{self.name}] Parsed JSON: {json.dumps(parsed, default=str)}")

        identifiers = parsed.get("identifiers", [])
        environments = parsed.get("environments", ["prod"])
        regions = parsed.get("regions", ["us"])
        detailed_analysis = parsed.get("detailedAnalysis", False)

        ctx.session.state["detailed_analysis"] = detailed_analysis

        logger.info(
            f"[{self.name}] Query params: identifiers={json.dumps(identifiers, default=str)}, "
            f"envs={environments}, regions={regions}, detailedAnalysis={detailed_analysis}"
        )

        if not identifiers:
            logger.error(f"[{self.name}] No identifiers found in parsed query")
            return

        logger.info(
            f"[{self.name}] Parsed {len(identifiers)} identifier(s), "
            f"envs={environments}, regions={regions}"
        )

        # ══════════════════════════════════════════════════════════════════════
        # Step 2: Initialize BFS
        # ══════════════════════════════════════════════════════════════════════
        all_seen_ids: set[str] = set()
        frontier: deque[tuple[str, str, int]] = deque()
        all_logs: dict[str, list[dict]] = {"mobius": [], "sse_mse": [], "wxcas": []}
        seen_hit_ids: set[str] = set()
        search_history: list[dict] = []
        all_extracted_ids: dict = {}
        max_depth_reached = 0
        TIME_PADDING_HOURS = 2
        derived_time_range: tuple[str, str] | None = None

        analysis_queue: asyncio.Queue = asyncio.Queue()
        analysis_task = asyncio.create_task(
            run_analysis_consumer(
                queue=analysis_queue,
                sdk_logs=ctx.session.state.get("sdk_logs", ""),
            )
        )
        logger.info(f"[{self.name}] Analysis consumer task started in background")

        for ident in identifiers:
            id_val = ident["value"]
            id_type = ident.get("type", "unknown")
            if id_val not in all_seen_ids:
                frontier.append((id_val, id_type, 0))
                all_seen_ids.add(id_val)
                logger.info(f"[{self.name}] Seeded frontier: {id_type}={id_val} at depth 0")

        logger.info(
            f"[{self.name}] BFS initialized: frontier={len(frontier)}, "
            f"all_seen_ids={all_seen_ids}, derived_time_range={derived_time_range}"
        )

        # ══════════════════════════════════════════════════════════════════════
        # Step 3: Progressive BFS Loop with staged retrieval
        # ══════════════════════════════════════════════════════════════════════
        while frontier:
            current_depth = frontier[0][2]
            max_depth_reached = max(max_depth_reached, current_depth)

            if current_depth > self.max_depth:
                logger.info(f"[{self.name}] Reached max depth {self.max_depth}, stopping")
                break

            # ── 3a: Collect all IDs at current depth ──
            current_batch: list[tuple[str, str]] = []
            while frontier and frontier[0][2] == current_depth:
                id_val, id_type, depth = frontier.popleft()
                current_batch.append((id_val, id_type))

            if not current_batch:
                continue

            logger.info(
                f"[{self.name}] -- Depth {current_depth}: "
                f"searching {len(current_batch)} ID(s) --"
            )
            print(f"\n{'='*60}")
            print(f"  Depth {current_depth}: searching {len(current_batch)} ID(s)")
            for id_val, id_type in current_batch:
                print(f"  -> {id_type} = {id_val}")
            print(f"{'='*60}")

            # ── 3b: Build search tasks ──
            search_tasks: list[tuple[str, dict, str, str]] = []

            for id_val, id_type in current_batch:
                configs = ID_TYPE_SEARCH_CONFIG.get(
                    id_type, ID_TYPE_SEARCH_CONFIG["unknown"]
                )
                logger.info(
                    f"[{self.name}] ID: {id_type}={id_val} -> "
                    f"{len(configs)} config(s) from ID_TYPE_SEARCH_CONFIG"
                )
                for config in configs:
                    indexes = resolve_indexes(
                        config["service"], environments, regions
                    )
                    logger.info(
                        f"[{self.name}]   Config: service={config['service']}, "
                        f"query_type={config['query_type']}, field={config.get('field')}, "
                        f"tag_filter={config['tag_filter']}, category={config['category']} "
                        f"-> resolved indexes={indexes}"
                    )
                    query = build_query(
                        id_val,
                        config["query_type"],
                        config.get("field"),
                        config["tag_filter"],
                        time_range=derived_time_range,
                    )
                    logger.info(
                        f"[{self.name}]   Built DSL: {json.dumps(query, default=str)}"
                    )
                    category = config["category"]
                    for index in indexes:
                        search_tasks.append((index, query, id_val, category))
                        logger.info(f"[{self.name}]   Queued: {index} | {id_type}={id_val} -> {category}")

            if not search_tasks:
                continue

            # ── 3c: Progressive retrieval — stream pages per search task ──
            logger.info(f"[{self.name}] Executing {len(search_tasks)} search(es) with progressive pagination...")

            import time as _time
            _search_start = _time.monotonic()

            depth_new_hits = 0

            for task_idx, (index, query, id_val, category) in enumerate(search_tasks):
                task_hits = 0
                logger.info(
                    f"[{self.name}] Search task {task_idx+1}/{len(search_tasks)}: "
                    f"index={index}, id_val={id_val}, category={category}"
                )
                page_count = 0

                # Prefetch pages: fetch page N+1 from OpenSearch while
                # the LLM processes page N.  The fetch only needs the
                # sort cursor from the previous *fetch*, not from LLM
                # processing, so it can safely run ahead by one page.
                prefetch_queue: asyncio.Queue[list[dict] | None] = asyncio.Queue(maxsize=1)

                async def _prefetch_pages(idx: str, q: dict, out: asyncio.Queue) -> None:
                    async for page in search_opensearch_pages(idx, q):
                        await out.put(page)
                    await out.put(None)

                prefetch_task = asyncio.create_task(_prefetch_pages(index, query, prefetch_queue))

                while True:
                    page_hits = await prefetch_queue.get()
                    if page_hits is None:
                        break

                    page_count += 1
                    task_hits += len(page_hits)
                    logger.info(
                        f"[{self.name}]   Task {task_idx+1} page {page_count}: "
                        f"{len(page_hits)} hits (task cumulative: {task_hits})"
                    )

                    # Process this page while the next page is being fetched
                    page_extracted, new_count = await self._process_hits_progressive(
                        hits=page_hits,
                        all_logs=all_logs,
                        seen_hit_ids=seen_hit_ids,
                        category=category,
                        id_extractor_instruction=self.id_extractor.instruction,
                        analysis_queue=analysis_queue,
                    )
                    depth_new_hits += new_count

                    logger.info(
                        f"[{self.name}]   After processing: new_unique={new_count}, "
                        f"depth_new_hits={depth_new_hits}, "
                        f"extracted_ids={json.dumps(page_extracted, default=str)}"
                    )

                    # Merge extracted IDs
                    all_extracted_ids = self._merge_extracted_ids(all_extracted_ids, page_extracted)

                    logger.info(
                        f"[{self.name}]   Cumulative extracted IDs: "
                        f"{json.dumps({k: len(v) for k, v in all_extracted_ids.items() if v}, default=str)}"
                    )

                logger.info(
                    f"[{self.name}] Task {task_idx+1} complete: index={index}, "
                    f"total_hits={task_hits}, pages={page_count}"
                )

                search_history.append({
                    "depth": current_depth,
                    "index": index,
                    "id_searched": id_val,
                    "category": category,
                    "hits_found": task_hits,
                })

                if task_hits > 0:
                    print(f"  {index}: {task_hits} hit(s) for {id_val} -> {category}")

            _search_elapsed = _time.monotonic() - _search_start
            logger.info(
                f"[{self.name}] Depth {current_depth}: {depth_new_hits} new unique hits "
                f"in {_search_elapsed:.2f}s"
            )

            all_logs_counts = {k: len(v) for k, v in all_logs.items()}
            logger.info(
                f"[{self.name}] Depth {current_depth} search phase done: "
                f"depth_new_hits={depth_new_hits}, derived_time_range={derived_time_range}, "
                f"all_logs counts={all_logs_counts}, "
                f"seen_hit_ids={len(seen_hit_ids)}"
            )

            # ── Derive time range from first results ──
            if derived_time_range is None and depth_new_hits > 0:
                from datetime import datetime, timedelta, timezone
                timestamps: list[str] = []
                for cat_hits in all_logs.values():
                    for hit in cat_hits:
                        ts = hit.get("_source", {}).get("@timestamp")
                        if ts:
                            timestamps.append(str(ts))
                if timestamps:
                    timestamps.sort()
                    try:
                        t_min = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
                        t_max = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
                        pad = timedelta(hours=TIME_PADDING_HOURS)
                        derived_time_range = (
                            (t_min - pad).isoformat(),
                            (t_max + pad).isoformat(),
                        )
                        logger.info(
                            f"[{self.name}] Derived time range: "
                            f"{derived_time_range[0]} -> {derived_time_range[1]}"
                        )
                    except (ValueError, IndexError) as e:
                        logger.warning(f"[{self.name}] Failed to parse timestamps: {e}")

            # ── Store latest state ──
            ctx.session.state["extracted_ids"] = json.dumps(all_extracted_ids, default=str)
            ctx.session.state["latest_search_results"] = json.dumps(
                extract_id_fields_for_llm(
                    [h for cat in all_logs.values() for h in cat[-100:]]  # last 100 per cat
                ),
                default=str,
            )

            # Yield a progress event
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                content=genai_types.Content(
                    parts=[genai_types.Part(text=json.dumps(all_extracted_ids, default=str))],
                    role="model",
                ),
            )

            # ── Enqueue new IDs ──
            new_count, skipped_seen, skipped_dummy = self._enqueue_new_ids(
                all_extracted_ids, all_seen_ids, frontier, current_depth,
            )

            # Fallback: if no new IDs were found, try device_ids as a last resort
            if new_count == 0:
                fallback_count = self._enqueue_fallback_device_ids(
                    all_extracted_ids, all_seen_ids, frontier, current_depth,
                )
                if fallback_count > 0:
                    new_count += fallback_count
                    logger.info(
                        f"[{self.name}] Fallback: enqueued {fallback_count} device_id(s) "
                        f"since no other new IDs were found"
                    )
                    print(f"  Fallback: enqueued {fallback_count} device_id(s)")

            logger.info(
                f"[{self.name}] Depth {current_depth} summary: {new_count} new IDs, "
                f"{skipped_seen} already-seen, {skipped_dummy} dummy. "
                f"Frontier: {len(frontier)} pending"
            )
            print(
                f"\n  Depth {current_depth} summary: {new_count} new IDs, "
                f"{skipped_seen} already-seen, {skipped_dummy} dummy. "
                f"Frontier: {len(frontier)} pending"
            )

        # ══════════════════════════════════════════════════════════════════════
        # Step 3.5: Signal analysis consumer to finish and await results
        # ══════════════════════════════════════════════════════════════════════
        await analysis_queue.put(SENTINEL)
        logger.info(f"[{self.name}] Sent sentinel to analysis consumer, awaiting results...")
        try:
            analysis_markdown, analysis_rolling, analysis_evidence = await analysis_task
            logger.info(
                f"[{self.name}] Analysis consumer finished: "
                f"{analysis_rolling.get('batch_count', 0)} batches, "
                f"{len(analysis_evidence)} evidence refs"
            )
        except Exception as e:
            logger.error(f"[{self.name}] Analysis consumer failed: {e}")
            analysis_markdown = ""
            analysis_rolling = {}
            analysis_evidence = []

        # ══════════════════════════════════════════════════════════════════════
        # Step 4: Store final results in session state
        # ══════════════════════════════════════════════════════════════════════
        logger.info(f"[{self.name}] Step 4: Storing final results in session state")

        ctx.session.state["all_logs"] = json.dumps(
            {
                category: [hit.get("_source", {}) for hit in hits]
                for category, hits in all_logs.items()
            },
            default=str,
        )

        ctx.session.state["search_summary"] = json.dumps(
            {
                "total_mobius_logs": len(all_logs["mobius"]),
                "total_sse_mse_logs": len(all_logs["sse_mse"]),
                "total_wxcas_logs": len(all_logs["wxcas"]),
                "max_depth_reached": max_depth_reached,
                "total_ids_searched": len(all_seen_ids),
                "search_history": search_history,
            },
            default=str,
        )

        ctx.session.state["mobius_logs"] = json.dumps(
            [hit.get("_source", {}) for hit in all_logs["mobius"]], default=str
        )
        ctx.session.state["sse_mse_logs"] = json.dumps(
            [hit.get("_source", {}) for hit in all_logs["sse_mse"]], default=str
        )
        ctx.session.state["wxcas_logs"] = json.dumps(
            [hit.get("_source", {}) for hit in all_logs["wxcas"]], default=str
        )

        _log_cache[ctx.session.id] = {
            "mobius_logs": ctx.session.state["mobius_logs"],
            "sse_mse_logs": ctx.session.state["sse_mse_logs"],
            "wxcas_logs": ctx.session.state["wxcas_logs"],
            "all_logs": ctx.session.state["all_logs"],
            "search_summary": ctx.session.state["search_summary"],
        }
        ctx.session.state["chunk_analysis_summary"] = analysis_rolling.get("summary", "")

        # Re-format analysis markdown now that search_summary is available
        if analysis_rolling:
            analysis_markdown = format_to_markdown(
                analysis_rolling,
                analysis_evidence,
                search_summary=ctx.session.state.get("search_summary", ""),
            )
        ctx.session.state["analyze_results"] = analysis_markdown
        ctx.session.state["analysis_evidence"] = json.dumps(analysis_evidence, default=str)
        _log_cache[ctx.session.id]["analyze_results"] = analysis_markdown

        logger.info(
            f"[{self.name}] == Search complete ==\n"
            f"  Mobius:    {len(all_logs['mobius'])} logs\n"
            f"  SSE/MSE:  {len(all_logs['sse_mse'])} logs\n"
            f"  WxCAS:    {len(all_logs['wxcas'])} logs\n"
            f"  IDs searched: {len(all_seen_ids)}\n"
            f"  Max depth:    {max_depth_reached}"
        )
        print(f"\n{'='*60}")
        print(f"  Search complete!")
        print(f"  Mobius:      {len(all_logs['mobius'])} logs")
        print(f"  SSE/MSE:    {len(all_logs['sse_mse'])} logs")
        print(f"  WxCAS:      {len(all_logs['wxcas'])} logs")
        print(f"  IDs searched: {len(all_seen_ids)}")
        print(f"  Max depth:    {max_depth_reached}")
        print(f"  All IDs: {all_seen_ids}")
        print(f"{'='*60}")


# ═══════════════════════════════════════════════════════════════════════════════
# Agent instantiation
# ═══════════════════════════════════════════════════════════════════════════════

search_agent = ExhaustiveSearchAgent(
    name="search_agent_v2",
    query_parser=query_parser,
    id_extractor=id_extractor,
    max_depth=3,
)

# When running standalone (`adk web agents/search_agent_v2`), expose as root_agent.
# When imported by root_agent_v2, this is ignored (root_agent_v2 defines its own).
root_agent = search_agent
