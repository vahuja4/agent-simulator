"""Core datatypes. OpenAI-style message dicts are the lingua franca between
every component — that uniformity is what keeps the harness framework-agnostic.

Verdict types live here (not in trace.py) deliberately: the trace is the
immutable record of what happened; verdicts are derived from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Message:
    role: Literal["user", "assistant"]
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ToolCall:
    """One tool invocation by the agent-under-test, carrying its result
    payload — judges and assertions need results, not just calls."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments, "result": self.result}


@dataclass
class AgentInput:
    """What the simulator hands the agent-under-test each turn."""

    conversation_id: str
    messages: list[Message]

    @property
    def last_user_message(self) -> str:
        for m in reversed(self.messages):
            if m.role == "user":
                return m.content
        return ""


@dataclass
class AgentResponse:
    """What the agent-under-test returns: a reply plus any tool calls it made.

    ``selected_card`` is the adapter's report of which card is currently
    selected (None if none, or unknown for adapters that can't say) — the
    trace records it per turn for the card-switch checks.
    """

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    selected_card: str | None = None


@dataclass
class CriterionVerdict:
    criterion_id: str
    passed: bool
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "passed": self.passed,
            "reasoning": self.reasoning,
        }


@dataclass
class FailureRecord:
    """One failure in a run's merged outcome, with its source (amendment 14):
    a deterministic assertion or a judge criterion. Phase 4 clustering and
    reporting key on these fields as structured data, never on prose."""

    source: Literal["assertion", "judge"]
    id: str  # assertion id or criterion_id
    turn_index: int | None
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "id": self.id,
            "turn_index": self.turn_index,
            "message": self.message,
            "data": self.data,
        }


@dataclass
class TurnVerdict:
    decision: Literal["continue", "pass", "fail"]
    criteria: list[CriterionVerdict]
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "criteria": [c.to_dict() for c in self.criteria],
            "reasoning": self.reasoning,
        }
