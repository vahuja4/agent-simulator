"""Shared OpenAI client for the harness's own LLM components (user simulator,
judges, failure clustering). The agent-under-test is NOT called through here —
it lives behind the AgentAdapter seam and can be anything.

All calls use structured outputs (response_format json_schema, strict) so
downstream code never parses free text, and refusals are surfaced as errors
so judges can fail closed.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

import openai
from openai import AsyncOpenAI

DEFAULT_MODEL = os.environ.get("AGENTSIM_MODEL", "gpt-5.5")

_DATED_MODEL_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}$")

_client: AsyncOpenAI | None = None


class LLMError(Exception):
    """A harness LLM call failed in a way the caller must treat as a failure."""


class LLMTruncationError(LLMError):
    """The model exhausted its completion budget before finishing output."""


def model_family(model: str) -> str:
    """Return the stable family name for a model alias or dated snapshot."""
    return _DATED_MODEL_SUFFIX.sub("", model.strip().lower())


def models_share_family(simulator_model: str, judge_model: str) -> bool:
    """Whether simulator and judge model identifiers name the same family."""
    return model_family(simulator_model) == model_family(judge_model)


class LLMClient(Protocol):
    """The one small interface the simulator and judge depend on — tests
    stub it; production uses OpenAILLM."""

    async def structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        effort: str = "high",
        max_tokens: int = 8192,
    ) -> dict[str, Any]: ...


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()
    return _client


async def structured(
    *,
    system: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    model: str | None = None,
    effort: str = "high",
    max_tokens: int = 8192,
) -> dict[str, Any]:
    """One OpenAI call constrained to a JSON schema. Returns the parsed object.

    Raises LLMError on refusal, truncation, or unparseable output — callers
    (especially judges) are expected to fail closed on that.
    """
    client = _get_client()
    kwargs: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "max_completion_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, *messages],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "structured_output", "strict": True, "schema": schema},
        },
    }

    try:
        try:
            response = await client.chat.completions.create(
                reasoning_effort=effort, **kwargs
            )
        except (TypeError, openai.BadRequestError):
            # Model (or SDK) without reasoning_effort support: plain request.
            response = await client.chat.completions.create(**kwargs)
    except openai.AuthenticationError as e:
        raise LLMError(
            "OpenAI authentication failed. Set OPENAI_API_KEY."
        ) from e

    choice = response.choices[0]
    if choice.message.refusal:
        raise LLMError(f"model refused the request: {choice.message.refusal}")
    if choice.finish_reason == "length":
        raise LLMTruncationError("model output truncated at max_completion_tokens")

    text = choice.message.content
    if not text:
        raise LLMError("no content in model response")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"unparseable structured output: {e}") from e


class OpenAILLM:
    """LLMClient backed by the module-level ``structured()`` OpenAI call."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or DEFAULT_MODEL

    async def structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        effort: str = "high",
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        return await structured(
            system=system,
            messages=messages,
            schema=schema,
            model=self.model,
            effort=effort,
            max_tokens=max_tokens,
        )
