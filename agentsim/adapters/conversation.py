"""The conversation lifecycle: the Agent adapter interface for a platform whose
tool evidence arrives only after the conversation ends.

A second interface beside the payments path's one-method ``AgentAdapter``,
which is untouched. Contract: ``docs/plans/langgraph-harness.md`` section 1.

Synchronous on purpose: execution is sequential by requirement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from ..journey.definition import FixtureState
from ..journey.normalized_trace import NormalizedTrace

AdapterErrorKind = Literal["transport", "service", "protocol"]
ADAPTER_ERROR_KINDS: tuple[str, ...] = ("transport", "service", "protocol")

# The service's code for "the agent raised while handling this message".
AGENT_ERROR_CODE = "agent_error"


class AdapterError(Exception):
    """An adapter operation failed, and whose fault it is.

    ``transport``: the platform could not be reached or did not answer in time
    (infrastructure). ``service``: the platform answered with one of its
    documented errors; ``status`` and ``code`` are its own. ``protocol``: the
    platform answered with something the contract does not allow.
    """

    def __init__(
        self,
        kind: AdapterErrorKind,
        detail: str,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        if kind not in ADAPTER_ERROR_KINDS:
            raise ValueError(f"kind must be one of {ADAPTER_ERROR_KINDS}, got {kind!r}")
        self.kind = kind
        self.detail = detail
        self.status = status
        self.code = code
        super().__init__(str(self))

    @property
    def agent_fault(self) -> bool:
        """The agent-under-test raised; everything else is infrastructure."""
        return self.kind == "service" and self.code == AGENT_ERROR_CODE

    def __str__(self) -> str:
        parts = [self.kind]
        if self.status is not None:
            parts.append(str(self.status))
        if self.code is not None:
            parts.append(self.code)
        return f"{' '.join(parts)}: {self.detail}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "code": self.code,
            "detail": self.detail,
            "agent_fault": self.agent_fault,
        }


@dataclass(frozen=True)
class ConversationHandle:
    """One isolated conversation. ``agent`` is the kind of agent the platform
    says is answering (``stub`` | ``langgraph`` for the journey service)."""

    conversation_id: str
    fixture_state_sha256: str
    agent: str


@dataclass(frozen=True)
class AgentReply:
    """Text only: no tool call crosses the adapter before the conversation
    ends. Both ids are the platform's and reappear in the Trace."""

    user_message_id: str
    message_id: str
    text: str


@dataclass(frozen=True)
class RetrievedTrace:
    """What retrieval produced. ``raw`` is the platform's payload, untouched,
    ``None`` when none arrived. ``normalized`` always exists and states its
    gaps. ``error`` says why retrieval failed or why ``raw`` could not be
    used, ``None`` otherwise."""

    raw: dict[str, Any] | None
    normalized: NormalizedTrace
    error: str | None = None


class ConversationAdapter(ABC):
    """start → send* → retrieve → release. Every method but
    ``retrieve_trace`` raises ``AdapterError``; ``retrieve_trace`` never
    raises for a platform-side problem — it returns the gap, so the caller
    can always save something."""

    @abstractmethod
    def start_conversation(
        self, *, fixture_state: FixtureState, tool_failures: tuple[str, ...] = ()
    ) -> ConversationHandle: ...

    @abstractmethod
    def send_message(self, handle: ConversationHandle, text: str) -> AgentReply: ...

    @abstractmethod
    def retrieve_trace(self, handle: ConversationHandle) -> RetrievedTrace: ...

    @abstractmethod
    def release(self, handle: ConversationHandle) -> None: ...
