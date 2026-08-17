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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CriterionVerdict:
        return cls(
            criterion_id=str(data["criterion_id"]),
            passed=bool(data["passed"]),
            reasoning=str(data.get("reasoning", "")),
        )


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailureRecord:
        return cls(
            source=data["source"],
            id=str(data["id"]),
            turn_index=data.get("turn_index"),
            message=str(data.get("message", "")),
            data=dict(data.get("data", {})),
        )


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TurnVerdict:
        return cls(
            decision=data["decision"],
            criteria=[
                CriterionVerdict.from_dict(item) for item in data.get("criteria", [])
            ],
            reasoning=str(data.get("reasoning", "")),
        )


BATCH_SCHEMA_VERSION = "1.0"


@dataclass
class BatchRunRecord:
    """Serializable result and manifest entry for one batch run.

    ``status`` is execution state; ``outcome`` is one of the four simulator
    outcome classes only after completion. Keeping them separate prevents a
    harness error or pending run from being mistaken for an agent failure.
    """

    run_key: str
    scenario: str
    scenario_source: str
    persona_variant: str
    defect_flags: dict[str, bool]
    model: str
    seed: int
    run_id: str
    status: Literal["pending", "running", "completed"] = "pending"
    outcome: Literal["pass", "fail", "task_incomplete", "error"] | None = None
    final_reasoning: str = ""
    # Full per-checkpoint judge history. Failures are the merged outcome;
    # verdicts preserve how the judge ruled as the conversation progressed.
    verdicts: list[TurnVerdict] = field(default_factory=list)
    failures: list[FailureRecord] = field(default_factory=list)
    degraded_checks: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    trace_path: str | None = None
    transcript_path: str | None = None
    replay_path: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_key": self.run_key,
            "scenario": self.scenario,
            "scenario_source": self.scenario_source,
            "persona_variant": self.persona_variant,
            "defect_flags": self.defect_flags,
            "model": self.model,
            "seed": self.seed,
            "run_id": self.run_id,
            "status": self.status,
            "outcome": self.outcome,
            "final_reasoning": self.final_reasoning,
            "verdicts": [verdict.to_dict() for verdict in self.verdicts],
            "failures": [failure.to_dict() for failure in self.failures],
            "degraded_checks": self.degraded_checks,
            "llm_calls": self.llm_calls,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "trace_path": self.trace_path,
            "transcript_path": self.transcript_path,
            "replay_path": self.replay_path,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchRunRecord:
        return cls(
            run_key=str(data["run_key"]),
            scenario=str(data["scenario"]),
            scenario_source=str(data.get("scenario_source", "")),
            persona_variant=str(data.get("persona_variant", "base")),
            defect_flags={
                str(key): bool(value)
                for key, value in dict(data.get("defect_flags", {})).items()
            },
            model=str(data.get("model", "")),
            seed=int(data.get("seed", 0)),
            run_id=str(data.get("run_id", "")),
            status=data.get("status", "pending"),
            outcome=data.get("outcome"),
            final_reasoning=str(data.get("final_reasoning", "")),
            verdicts=[TurnVerdict.from_dict(item) for item in data.get("verdicts", [])],
            failures=[FailureRecord.from_dict(item) for item in data.get("failures", [])],
            degraded_checks=[dict(item) for item in data.get("degraded_checks", [])],
            llm_calls=int(data.get("llm_calls", 0)),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            duration_seconds=data.get("duration_seconds"),
            trace_path=data.get("trace_path"),
            transcript_path=data.get("transcript_path"),
            replay_path=data.get("replay_path"),
            error=data.get("error"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class BatchManifest:
    batch_id: str
    created_at: str
    configuration: dict[str, Any] = field(default_factory=dict)
    runs: dict[str, BatchRunRecord] = field(default_factory=dict)
    label_llm_calls: int = 0
    schema_version: str = BATCH_SCHEMA_VERSION

    @property
    def run_llm_calls_total(self) -> int:
        return sum(
            record.llm_calls
            for record in self.runs.values()
            if record.status == "completed"
        )

    @property
    def llm_calls_total(self) -> int:
        return self.run_llm_calls_total + self.label_llm_calls

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "created_at": self.created_at,
            "configuration": self.configuration,
            "run_llm_calls_total": self.run_llm_calls_total,
            "label_llm_calls": self.label_llm_calls,
            "llm_calls_total": self.llm_calls_total,
            "runs": {
                key: self.runs[key].to_dict()
                for key in sorted(self.runs)
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchManifest:
        return cls(
            batch_id=str(data["batch_id"]),
            created_at=str(data["created_at"]),
            configuration=dict(data.get("configuration", {})),
            runs={
                str(key): BatchRunRecord.from_dict(value)
                for key, value in dict(data.get("runs", {})).items()
            },
            label_llm_calls=int(data.get("label_llm_calls", 0)),
            schema_version=str(data.get("schema_version", BATCH_SCHEMA_VERSION)),
        )


@dataclass
class FailureCluster:
    cluster_id: str
    source: str
    id: str
    membership_hash: str
    members: list[dict[str, Any]]
    label: str | None = None

    @property
    def size(self) -> int:
        return len(self.members)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "source": self.source,
            "id": self.id,
            "membership_hash": self.membership_hash,
            "size": self.size,
            "label": self.label,
            "members": self.members,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailureCluster:
        return cls(
            cluster_id=str(data["cluster_id"]),
            source=str(data["source"]),
            id=str(data["id"]),
            membership_hash=str(data["membership_hash"]),
            members=[dict(member) for member in data.get("members", [])],
            label=data.get("label"),
        )
