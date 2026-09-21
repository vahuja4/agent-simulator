"""The normalized Trace: what the harness knows about one completed
conversation, with every gap stated rather than filled.

``agentsim.trace.Trace`` is the versioned payments contract and is not
extended. This type carries what that one cannot: stable message and action
ids, one explicit ordering across both, action-to-message references, and a
per-class statement of how much evidence was actually retrieved.

Assertions read a ``NormalizedTrace`` directly. The Judge reads the
``to_trace()`` projection, which exists only when both evidence classes are
``available`` — the Judge never sees a Trace with gaps.

This module holds the types only. Turning a platform's raw payload into a
``NormalizedTrace`` belongs to the adapter side, and it copies and never
infers: a missing field stays ``None`` / ``result_available: false`` /
``status: unknown``, its evidence class becomes ``partial``, and a reason is
recorded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from ..trace import Trace, TraceTurn
from ..types import ToolCall

NORMALIZED_TRACE_SCHEMA_VERSION = "1.0"

EvidenceState = Literal["available", "partial", "unavailable"]
EVIDENCE_STATES: tuple[str, ...] = ("available", "partial", "unavailable")
MESSAGE_ROLES: tuple[str, ...] = ("user", "agent")
ACTION_STATUSES: tuple[str, ...] = ("succeeded", "failed", "unknown")


class NormalizedTraceError(ValueError):
    """A normalized Trace holds a value outside its closed vocabulary."""


class TraceProjectionError(NormalizedTraceError):
    """``to_trace()`` was asked to project a Trace the Judge must not see."""


def _closed(value: Any, allowed: tuple[str, ...], where: str) -> None:
    if value not in allowed:
        raise NormalizedTraceError(f"{where} must be one of {allowed}, got {value!r}")


@dataclass(frozen=True)
class Evidence:
    """How much of each evidence class was retrieved, and why not all of it."""

    messages: EvidenceState
    actions: EvidenceState
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _closed(self.messages, EVIDENCE_STATES, "evidence.messages")
        _closed(self.actions, EVIDENCE_STATES, "evidence.actions")

    @property
    def complete(self) -> bool:
        return self.messages == "available" and self.actions == "available"

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "actions": self.actions,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Evidence:
        return cls(
            messages=d["messages"],
            actions=d["actions"],
            reasons=tuple(d.get("reasons", ())),
        )


@dataclass(frozen=True)
class TraceMessage:
    message_id: str | None
    sequence: int | None
    role: Literal["user", "agent"]
    text: str | None

    def __post_init__(self) -> None:
        _closed(self.role, MESSAGE_ROLES, "message.role")

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "sequence": self.sequence,
            "role": self.role,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TraceMessage:
        return cls(
            message_id=d.get("message_id"),
            sequence=d.get("sequence"),
            role=d["role"],
            text=d.get("text"),
        )


@dataclass(frozen=True)
class ActionError:
    code: str | None
    message: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class TraceAction:
    """One tool call the agent made. ``caused_by_message_id`` is the user
    message being handled; ``reply_message_id`` is the agent message that Turn
    produced, ``None`` when the agent raised before replying."""

    action_id: str | None
    sequence: int | None
    tool_name: str | None
    arguments: dict[str, Any] | None
    result: Any
    result_available: bool
    status: Literal["succeeded", "failed", "unknown"]
    error: ActionError | None
    caused_by_message_id: str | None
    reply_message_id: str | None

    def __post_init__(self) -> None:
        _closed(self.status, ACTION_STATUSES, "action.status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "sequence": self.sequence,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "result": self.result,
            "result_available": self.result_available,
            "status": self.status,
            "error": self.error.to_dict() if self.error is not None else None,
            "caused_by_message_id": self.caused_by_message_id,
            "reply_message_id": self.reply_message_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TraceAction:
        error = d.get("error")
        return cls(
            action_id=d.get("action_id"),
            sequence=d.get("sequence"),
            tool_name=d.get("tool_name"),
            arguments=d.get("arguments"),
            result=d.get("result"),
            result_available=d["result_available"],
            status=d["status"],
            error=(
                ActionError(code=error.get("code"), message=error.get("message"))
                if error is not None
                else None
            ),
            caused_by_message_id=d.get("caused_by_message_id"),
            reply_message_id=d.get("reply_message_id"),
        )


@dataclass(frozen=True)
class NormalizedTrace:
    conversation_id: str
    platform: str
    fixture_state_sha256: str | None
    tool_failures: tuple[str, ...]
    evidence: Evidence
    messages: tuple[TraceMessage, ...] = ()
    actions: tuple[TraceAction, ...] = ()
    schema_version: str = NORMALIZED_TRACE_SCHEMA_VERSION

    def message(self, message_id: str | None) -> TraceMessage | None:
        if message_id is None:
            return None
        for message in self.messages:
            if message.message_id == message_id:
                return message
        return None

    def to_trace(self) -> Trace:
        """Project to the Judge's ``Trace``: one ``TraceTurn`` per message in
        ``sequence`` order (``index`` is that position, so a
        ``FailureRecord.turn_index`` maps back to ``message_id`` through
        ``ordered_messages()``), each action a ``ToolCall`` on the Turn its
        ``reply_message_id`` names.

        Raises ``TraceProjectionError`` unless both evidence classes are
        ``available``, and for any action that cannot be placed — a projection
        that silently dropped an action would show the Judge an agent that did
        less than it did.
        """
        if not self.evidence.complete:
            raise TraceProjectionError(
                "to_trace() needs messages and actions evidence both 'available'; got "
                f"messages={self.evidence.messages!r}, actions={self.evidence.actions!r}"
            )
        _require_ids(self.messages, "message", "message_id")
        _require_ids(self.actions, "action", "action_id")
        _require_one_ordering(self.messages + self.actions)

        turns: list[TraceTurn] = []
        turn_by_message_id: dict[str, TraceTurn] = {}
        for message in self.ordered_messages():
            if message.text is None:
                raise TraceProjectionError(
                    f"message {message.message_id!r} has no text"
                )
            turn = TraceTurn(
                index=len(turns), speaker=message.role, text=message.text
            )
            turns.append(turn)
            turn_by_message_id[message.message_id] = turn

        for action in sorted(self.actions, key=lambda a: a.sequence):
            turn = turn_by_message_id.get(action.reply_message_id)
            if turn is None or turn.speaker != "agent":
                raise TraceProjectionError(
                    f"action {action.action_id!r} names reply_message_id "
                    f"{action.reply_message_id!r}, which is not an agent message"
                )
            if action.tool_name is None or action.status == "unknown":
                raise TraceProjectionError(
                    f"action {action.action_id!r} is missing its tool name or status"
                )
            turn.tool_calls.append(
                ToolCall(
                    name=action.tool_name,
                    arguments=dict(action.arguments or {}),
                    result={
                        "status": action.status,
                        "output": action.result,
                        "error": (
                            action.error.to_dict() if action.error is not None else None
                        ),
                    },
                )
            )
        return Trace(conversation_id=self.conversation_id, turns=turns)

    def ordered_messages(self) -> tuple[TraceMessage, ...]:
        """Messages in ``sequence`` order; position equals ``to_trace()``'s
        turn ``index``. Messages without a sequence keep their given order,
        last."""
        return tuple(
            sorted(
                self.messages,
                key=lambda m: (m.sequence is None, m.sequence or 0),
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "conversation_id": self.conversation_id,
            "platform": self.platform,
            "fixture_state_sha256": self.fixture_state_sha256,
            "tool_failures": list(self.tool_failures),
            "evidence": self.evidence.to_dict(),
            "messages": [m.to_dict() for m in self.messages],
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NormalizedTrace:
        version = d.get("schema_version")
        if version != NORMALIZED_TRACE_SCHEMA_VERSION:
            raise NormalizedTraceError(
                f"normalized Trace schema_version must be "
                f"{NORMALIZED_TRACE_SCHEMA_VERSION!r}, got {version!r}"
            )
        return cls(
            conversation_id=d["conversation_id"],
            platform=d["platform"],
            fixture_state_sha256=d.get("fixture_state_sha256"),
            tool_failures=tuple(d.get("tool_failures", ())),
            evidence=Evidence.from_dict(d["evidence"]),
            messages=tuple(TraceMessage.from_dict(m) for m in d.get("messages", ())),
            actions=tuple(TraceAction.from_dict(a) for a in d.get("actions", ())),
        )

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, s: str) -> NormalizedTrace:
        return cls.from_dict(json.loads(s))


def _require_ids(items: tuple[Any, ...], kind: str, id_field: str) -> None:
    ids = [getattr(item, id_field) for item in items]
    if any(not isinstance(i, str) or not i for i in ids):
        raise TraceProjectionError(f"a {kind} has no {id_field}")
    if len(set(ids)) != len(ids):
        raise TraceProjectionError(f"duplicate {id_field} among {kind}s")


def _require_one_ordering(items: tuple[Any, ...]) -> None:
    """``sequence`` is one counter across messages and actions."""
    sequences = [item.sequence for item in items]
    if any(isinstance(s, bool) or not isinstance(s, int) for s in sequences):
        raise TraceProjectionError("a message or action has no sequence")
    if len(set(sequences)) != len(sequences):
        raise TraceProjectionError("messages and actions share a sequence number")
