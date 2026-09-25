"""Anthropic client for the harness's own LLM components, beside the OpenAI one
in ``agentsim.llm``.

It exists for one reason: the Judge model is calibration-locked to ``gpt-5.5``
(AGENTS.md), and a reported Run needs the Simulated user on a different model
family. The agent-under-test is NOT called through here — it lives behind the
Agent adapter seam.

Same contract as ``OpenAILLM``: one ``structured`` call constrained to a JSON
schema, so downstream code never parses free text, with refusals and truncation
raised as errors rather than returned as content. ``LLMError`` and
``LLMTruncationError`` are the shared types from ``agentsim.llm``, so a caller
handles either backend with one ``except``.

Two differences from the OpenAI path, both forced by the API:

- Effort has no ``none``. The levels are low, medium, high, xhigh and max, so
  ``none`` maps to ``low`` rather than being passed through and rejected.
- A response may carry thinking blocks beside the answer (thinking is on by
  default on current models), so the JSON is read from the text block rather
  than from the first block.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from .llm import LLMError, LLMTruncationError

DEFAULT_MODEL = "claude-opus-5"
API_KEY_ENV = "ANTHROPIC_API_KEY"

# The API's levels. The shared interface's ``none`` has no equivalent; the
# nearest honest reading of "spend as little thought as possible" is ``low``.
_EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})
_EFFORT_ALIASES = {"none": "low", "minimal": "low"}

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()
    return _client


def _effort(effort: str) -> str:
    level = _EFFORT_ALIASES.get(effort, effort)
    if level not in _EFFORT_LEVELS:
        raise LLMError(
            f"unknown effort {effort!r} (known: {sorted(_EFFORT_LEVELS)}, "
            f"aliases: {sorted(_EFFORT_ALIASES)})"
        )
    return level


def _text_block(response: Any) -> str:
    """The answer, from a response that may also carry thinking blocks."""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise LLMError("no text block in model response")


class AnthropicLLM:
    """LLMClient backed by the Anthropic Messages API."""

    def __init__(
        self,
        model: str | None = None,
        *,
        usage_path: str | Path | None = None,
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self.usage_records: list[dict[str, Any]] = []
        self.usage_path = Path(usage_path) if usage_path is not None else None

    async def structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        effort: str = "high",
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        """One Anthropic call constrained to ``schema``. Returns the parsed
        object; raises ``LLMError`` or ``LLMTruncationError``."""
        client = _get_client()
        try:
            response = await client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                output_config={
                    "effort": _effort(effort),
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except anthropic.AuthenticationError as error:
            raise LLMError(
                f"Anthropic authentication failed. Set {API_KEY_ENV}."
            ) from error

        self._record_usage(response)

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            raise LLMError(f"model refused the request (category {category!r})")
        if response.stop_reason == "max_tokens":
            raise LLMTruncationError("model output truncated at max_tokens")

        text = _text_block(response)
        if not text:
            raise LLMError("no content in model response")
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise LLMError(f"unparseable structured output: {error}") from error

    def _record_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        record = {
            "model": self.model,
            "usage": usage.model_dump() if hasattr(usage, "model_dump") else dict(usage),
        }
        self.usage_records.append(record)
        if self.usage_path is not None:
            self.usage_path.parent.mkdir(parents=True, exist_ok=True)
            with self.usage_path.open("a") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
