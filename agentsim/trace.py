"""The canonical Trace schema — the immutable, versioned record of one
conversation. Everything downstream (judges now; the deterministic assertion
engine, failure clustering, and reporting later) reads this artifact, never
engine internals. Traces round-trip to/from JSON; Phase 4 reporting and
failure reproduction depend on the serialized form, so ``schema_version`` is
serialized with every trace.

This module must stay free of judge/verdict imports: verdicts are *derived*
from a trace, and future consumers must be able to re-read traces
independently of any judge's conclusions. ``outcome`` is a plain string.

What future checks need from this schema
----------------------------------------
Tool *calls only* (names + arguments + ordering) suffice for:
  - validate→submit pairing (a submit tool requires a prior successful
    validate for the same card/amount/date),
  - amount ∈ options fetched for the currently selected card,
  - card switch → options re-fetched (via ``selected_card`` per turn).

Tool *results* are additionally required for:
  - honest failure handling (reply text vs. the submit result's status),
  - "successful" validate (the pairing check must read the validate result's
    status; a blocking error poisons the pair),
  - status-code-overrides-warnings,
  - tool-output truth (amounts presented must appear in the options result).

The explicit-confirmation check is split (design amendment 4): the
deterministic assertion only checks *ordering* — that a user turn exists
between the agent turn carrying the validate call and the agent turn carrying
the submit call. Whether that user turn actually constitutes a confirmation
is a judge criterion reading the turn's ``text``. Hence user turns are
recorded as distinct TraceTurns, never folded into agent turns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

TRACE_SCHEMA_VERSION = "1.0"

# The full outcome vocabulary. ``task_incomplete`` (simulator stopped or
# max_turns hit without goal completion) is distinct from ``fail``: running
# out of turns is not a policy failure.
Outcome = Literal["pass", "fail", "task_incomplete", "error"]


@dataclass
class TraceToolCall:
    """One tool invocation: name, arguments, AND the result payload."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments, "result": self.result}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TraceToolCall:
        return cls(name=d["name"], arguments=d.get("arguments", {}), result=d.get("result"))


@dataclass
class TraceTurn:
    """One turn by one speaker. User turns carry ``intent`` (the simulator's
    declared per-turn intent); agent turns carry ``tool_calls``.
    ``selected_card`` is the agent-reported selected-card state as of this
    turn (last known value on user turns) — the card-switch assertions key
    off it.
    """

    index: int
    speaker: Literal["user", "agent"]
    text: str
    intent: str | None = None
    tool_calls: list[TraceToolCall] = field(default_factory=list)
    selected_card: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "speaker": self.speaker,
            "text": self.text,
            "intent": self.intent,
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "selected_card": self.selected_card,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TraceTurn:
        return cls(
            index=d["index"],
            speaker=d["speaker"],
            text=d["text"],
            intent=d.get("intent"),
            tool_calls=[TraceToolCall.from_dict(t) for t in d.get("tool_calls", [])],
            selected_card=d.get("selected_card"),
        )


@dataclass
class Trace:
    conversation_id: str
    turns: list[TraceTurn] = field(default_factory=list)
    outcome: str | None = None  # one of Outcome once the run finishes
    schema_version: str = TRACE_SCHEMA_VERSION

    def add_user_turn(self, text: str, intent: str | None, selected_card: str | None) -> TraceTurn:
        turn = TraceTurn(
            index=len(self.turns),
            speaker="user",
            text=text,
            intent=intent,
            selected_card=selected_card,
        )
        self.turns.append(turn)
        return turn

    def add_agent_turn(
        self,
        text: str,
        tool_calls: list[TraceToolCall],
        selected_card: str | None,
    ) -> TraceTurn:
        turn = TraceTurn(
            index=len(self.turns),
            speaker="agent",
            text=text,
            tool_calls=tool_calls,
            selected_card=selected_card,
        )
        self.turns.append(turn)
        return turn

    def iter_tool_calls(self) -> Iterator[tuple[TraceTurn, TraceToolCall]]:
        """All tool calls in conversation order, with their carrying turn."""
        for turn in self.turns:
            for call in turn.tool_calls:
                yield turn, call

    def tool_call_names(self) -> list[str]:
        return [call.name for _, call in self.iter_tool_calls()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "conversation_id": self.conversation_id,
            "outcome": self.outcome,
            "turns": [t.to_dict() for t in self.turns],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Trace:
        return cls(
            conversation_id=d["conversation_id"],
            turns=[TraceTurn.from_dict(t) for t in d.get("turns", [])],
            outcome=d.get("outcome"),
            schema_version=d["schema_version"],
        )

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, s: str) -> Trace:
        return cls.from_dict(json.loads(s))
