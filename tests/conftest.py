from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Run tests against the repo checkout without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsim.clock import FrozenClock  # noqa: E402
from agentsim.types import AgentInput, AgentResponse, Message  # noqa: E402
from fixtures.paycard import FROZEN_NOW  # noqa: E402


class MockDriver:
    """Feeds scripted user lines to a mock agent, maintaining history.
    Shared by the Phase 2 journey/defect tests (test_mock_paycard.py keeps
    its own Phase 1 copy, unmodified)."""

    def __init__(self, agent, conversation_id: str = "c1") -> None:
        self.agent = agent
        self.conversation_id = conversation_id
        self.history: list[Message] = []

    async def say(self, text: str) -> AgentResponse:
        self.history.append(Message("user", text))
        resp = await self.agent.call(AgentInput(self.conversation_id, list(self.history)))
        self.history.append(Message("assistant", resp.content))
        return resp

    @property
    def state(self):
        return self.agent._states[self.conversation_id]


class StubLLMClient:
    """Scripted LLMClient: returns queued structured responses in order and
    records every call's kwargs for prompt assertions."""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.responses: list[dict[str, Any]] = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def push(self, *responses: dict[str, Any]) -> None:
        self.responses.extend(responses)

    async def structured(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("StubLLMClient ran out of scripted responses")
        return self.responses.pop(0)


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock(FROZEN_NOW)


@pytest.fixture
def stub_llm() -> StubLLMClient:
    return StubLLMClient()
