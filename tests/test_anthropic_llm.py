"""The Anthropic client: same contract as the OpenAI one — schema-constrained
JSON out, refusals and truncation raised rather than returned. No network: the
SDK client is replaced by a double."""

import json

import pytest

from agentsim.anthropic_llm import (
    API_KEY_ENV,
    DEFAULT_MODEL,
    AnthropicLLM,
)
from agentsim.journey.simulated_user import SimulatorConfigError, _client_for
from agentsim.llm import LLMError, LLMTruncationError, model_family, models_share_family

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"message": {"type": "string"}},
    "required": ["message"],
}


class _Block:
    def __init__(self, type_: str, text: str = "") -> None:
        self.type = type_
        self.text = text


class _Usage:
    def __init__(self) -> None:
        self.input_tokens = 11
        self.output_tokens = 7

    def model_dump(self) -> dict:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


class _Response:
    def __init__(self, *, content, stop_reason="end_turn", stop_details=None):
        self.content = content
        self.stop_reason = stop_reason
        self.stop_details = stop_details
        self.usage = _Usage()


class _Messages:
    def __init__(self, response, error=None):
        self._response = response
        self._error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _Client:
    def __init__(self, response=None, error=None):
        self.messages = _Messages(response, error)


@pytest.fixture
def client(monkeypatch):
    def install(response=None, error=None):
        double = _Client(response, error)
        monkeypatch.setattr("agentsim.anthropic_llm._get_client", lambda: double)
        return double

    return install


async def _call(llm, **kwargs):
    return await llm.structured(
        system="s", messages=[{"role": "user", "content": "u"}], schema=SCHEMA, **kwargs
    )


# ------------------------------------------------------------- the call


async def test_it_returns_the_parsed_object(client):
    client(_Response(content=[_Block("text", json.dumps({"message": "hi"}))]))
    assert await _call(AnthropicLLM("claude-opus-5")) == {"message": "hi"}


async def test_the_schema_is_sent_as_the_output_format(client):
    double = client(_Response(content=[_Block("text", '{"message": "hi"}')]))
    await _call(AnthropicLLM("claude-opus-5"))
    sent = double.messages.calls[0]
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert sent["model"] == "claude-opus-5"
    assert sent["system"] == "s"


async def test_the_answer_is_read_past_a_thinking_block(client):
    """Thinking is on by default on current models, so the JSON is not
    necessarily the first block."""
    client(
        _Response(
            content=[_Block("thinking"), _Block("text", '{"message": "hi"}')]
        )
    )
    assert await _call(AnthropicLLM()) == {"message": "hi"}


@pytest.mark.parametrize(
    "asked,sent",
    [("high", "high"), ("low", "low"), ("max", "max"), ("none", "low"), ("minimal", "low")],
)
async def test_effort_maps_onto_the_levels_the_api_has(client, asked, sent):
    """The shared interface has ``none``; the API's lowest is ``low``."""
    double = client(_Response(content=[_Block("text", '{"message": "hi"}')]))
    await _call(AnthropicLLM(), effort=asked)
    assert double.messages.calls[0]["output_config"]["effort"] == sent


async def test_an_unknown_effort_is_refused_before_the_call(client):
    double = client(_Response(content=[_Block("text", '{"message": "hi"}')]))
    with pytest.raises(LLMError, match="unknown effort"):
        await _call(AnthropicLLM(), effort="colossal")
    assert double.messages.calls == [], "nothing is spent on a request that cannot be right"


# ----------------------------------------------------------- failures


async def test_truncation_is_an_error_not_a_short_answer(client):
    client(
        _Response(
            content=[_Block("text", '{"message": "hi')], stop_reason="max_tokens"
        )
    )
    with pytest.raises(LLMTruncationError, match="truncated"):
        await _call(AnthropicLLM())


async def test_a_refusal_is_an_error_and_names_its_category(client):
    class _Details:
        category = "cyber"

    client(
        _Response(content=[], stop_reason="refusal", stop_details=_Details())
    )
    with pytest.raises(LLMError, match="refused.*cyber"):
        await _call(AnthropicLLM())


async def test_unparseable_output_is_an_error(client):
    client(_Response(content=[_Block("text", "not json")]))
    with pytest.raises(LLMError, match="unparseable structured output"):
        await _call(AnthropicLLM())


async def test_a_response_with_no_text_block_is_an_error(client):
    client(_Response(content=[_Block("thinking")]))
    with pytest.raises(LLMError, match="no text block"):
        await _call(AnthropicLLM())


async def test_an_authentication_failure_names_the_variable_to_set(client):
    import anthropic

    error = anthropic.AuthenticationError.__new__(anthropic.AuthenticationError)
    Exception.__init__(error, "401")
    client(error=error)
    with pytest.raises(LLMError, match=API_KEY_ENV):
        await _call(AnthropicLLM())


async def test_usage_is_recorded(client, tmp_path):
    path = tmp_path / "usage.jsonl"
    client(_Response(content=[_Block("text", '{"message": "hi"}')]))
    llm = AnthropicLLM("claude-opus-5", usage_path=path)
    await _call(llm)
    assert llm.usage_records == [
        {"model": "claude-opus-5", "usage": {"input_tokens": 11, "output_tokens": 7}}
    ]
    assert json.loads(path.read_text())["model"] == "claude-opus-5"


# ------------------------------------------------- family and selection


@pytest.mark.parametrize(
    "model,family",
    [
        ("gpt-5.5", "gpt-5"),
        ("gpt-5.5-2026-01-01", "gpt-5"),
        ("claude-opus-5", "claude"),
        ("claude-sonnet-5", "claude"),
        ("claude-haiku-4-5", "claude"),
        ("llama-4", "llama-4"),
    ],
)
def test_model_family(model, family):
    assert model_family(model) == family


def test_every_anthropic_model_is_one_family():
    """Two Claude models are not 'separated' in the sense the rule means; before
    this they read as different families and would have passed the check."""
    assert models_share_family("claude-opus-5", "claude-sonnet-5")
    assert not models_share_family("claude-opus-5", "gpt-5.5")


def test_a_claude_simulator_model_selects_the_anthropic_client(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "test-key")
    assert isinstance(_client_for("claude-opus-5"), AnthropicLLM)


def test_a_gpt_simulator_model_still_selects_the_openai_client(monkeypatch):
    from agentsim.llm import OpenAILLM

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert isinstance(_client_for("gpt-5.5"), OpenAILLM)


def test_a_claude_model_without_its_key_is_refused_by_name(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with pytest.raises(SimulatorConfigError, match=API_KEY_ENV):
        _client_for("claude-opus-5")


def test_the_default_model_is_an_anthropic_one():
    assert model_family(DEFAULT_MODEL) == "claude"
