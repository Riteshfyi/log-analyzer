"""Per-request OAuth token using contextvars for async-safe isolation."""

from contextvars import ContextVar
from typing import AsyncGenerator

from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

# One ContextVar per async task — no cross-request bleed
oauth_token_var: ContextVar[str] = ContextVar("oauth_token", default="")


def get_oauth_token() -> str:
    """Read the current request's OAuth token."""
    return oauth_token_var.get()


def set_oauth_token(token: str) -> None:
    """Set the OAuth token for the current async context."""
    oauth_token_var.set(token)


class SessionLiteLlm(LiteLlm):
    """LiteLlm subclass that reads api_key from the per-request contextvar.

    Always overwrites _additional_args["api_key"] from the contextvar so that
    a stale token from a previous request never leaks to a different user.
    """

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        # Always overwrite — clears stale tokens when contextvar is empty
        self._additional_args["api_key"] = oauth_token_var.get()
        async for chunk in super().generate_content_async(llm_request, stream):
            yield chunk
