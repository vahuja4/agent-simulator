"""The seam. The simulator core only ever talks to this interface — the
agent-under-test is a black box behind one small adapter, so the same suite
runs against a mock today and Sierra over HTTP tomorrow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..types import AgentInput, AgentResponse


class AgentAdapter(ABC):
    """One async call: receive conversation state, return the agent's reply
    plus any tool calls it made. Multi-turn state is the adapter's concern,
    keyed by ``AgentInput.conversation_id``.
    """

    @abstractmethod
    async def call(self, input: AgentInput) -> AgentResponse:
        """Produce the agent's next reply for this conversation."""
        raise NotImplementedError
