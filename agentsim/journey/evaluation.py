"""Evaluation of one saved Episode directory (design note sections 8 and 9).

It runs after the conversation is over and the Trace has been retrieved:
deterministic Assertions first, then the Judge, which can never override an
Assertion failure because it is not called after one. The outcome is the first
matching rule, applied strictly in order:

0. The Episode directory cannot be read → ``error``.
1. The Episode was aborted, or stopped on an adapter or Simulated-user error
   → ``error``.
2. An evidence class is not ``available``, an Assertion or the outcome gate is
   ``unavailable``, or the Trace cannot be projected for the Judge → ``error``.
3. Any Assertion ``failed`` → ``fail``. The Judge is not called.
4. The Judge raised → ``error``.
5. The Judge ruled ``fail``, or did not affirm every criterion → ``fail``.
6. The Judge ruled ``pass`` and the expected outcome is evidenced → ``pass``.
7. Otherwise → ``task_incomplete``.

The Trace is projected for the Judge only after rules 1 and 2: after a
``500 agent_error`` the Trace is evidence-``available`` yet ``to_trace()``
refuses it, and rule 1 has already made that Episode an ``error``.

These are mechanics. What is checked comes in as ``EvaluationCriteria``,
resolved from the Scenario's criterion references; the Scenario itself is read
from ``<episode_dir>/scenario.yaml`` and from nowhere else. The Judge half of
the criteria comes from the ``JourneyDefinition`` evaluation is handed. A
Scenario for another Journey, or one naming a Judge criterion that definition
does not define, is rule 0. Infrastructure problems are ``error``, never
``fail``, and missing evidence is never ``pass``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple, Protocol

from .._io import _atomic_json
from ..orchestrator import RunResult
from ..trace import Trace
from ..types import FailureRecord, TurnVerdict
from . import checks
from .checks import AssertionResult, AssertionSpec, OutcomeEvidence
from .definition import JourneyDefinition
from .episode import (
    EPISODE_FILE,
    EPISODE_STOP_REASONS,
    NORMALIZED_TRACE_FILE,
    RAW_TRACE_FILE,
    SCENARIO_FILE,
    STOP_ADAPTER_ERROR,
    STOP_SIMULATOR_ERROR,
    TRANSCRIPT_FILE,
)
from .normalized_trace import NormalizedTrace, NormalizedTraceError
from .scenario import JourneyScenario, load_journey_scenario

EVALUATION_SCHEMA_VERSION = "1.0"
EVALUATION_FILE = "evaluation.json"

OUTCOME_PASS = "pass"
OUTCOME_FAIL = "fail"
OUTCOME_TASK_INCOMPLETE = "task_incomplete"
OUTCOME_ERROR = "error"

# Rule number -> stable name (``evaluation.json`` ``rule``).
RULES: dict[int, str] = {
    0: "episode_unreadable",
    1: "episode_error",
    2: "evidence_unavailable",
    3: "assertion_failed",
    4: "judge_error",
    5: "judge_failed",
    6: "passed",
    7: "outcome_not_evidenced",
}

# The id of the failure recorded when the Judge rules ``fail`` yet affirms
# every criterion, so a ``fail`` never reaches clustering with nothing to group.
JUDGE_DECISION = "judge_decision"


class EvaluationError(ValueError):
    """Evaluation cannot start; nothing was written."""


class EpisodeJudge(Protocol):
    async def judge_episode(self, scenario: JourneyScenario, trace: Trace) -> TurnVerdict: ...


@dataclass(frozen=True)
class EvaluationCriteria:
    """What evaluation checks, handed to the mechanics. ``judge_criterion_tools``
    names the tools each Judge criterion is about, which is how a Judge failure
    is pointed at its evidence."""

    assertions: tuple[AssertionSpec, ...]
    outcome_gate: Callable[[NormalizedTrace, JourneyScenario], OutcomeEvidence]
    judge_criterion_tools: Mapping[str, tuple[str, ...]]


def criteria_for(
    scenario: JourneyScenario, journey: JourneyDefinition
) -> EvaluationCriteria:
    """The criteria the Scenario's references name: Assertions from
    ``agentsim.journey.checks``, Judge criteria from the Journey definition. A
    Judge criterion the definition does not define raises."""
    return EvaluationCriteria(
        assertions=tuple(checks.assertion(i) for i in scenario.assertion_ids),
        outcome_gate=checks.expected_outcome_evidenced,
        judge_criterion_tools={
            i: journey.judge_criterion(i).tools for i in scenario.judge_criterion_ids
        },
    )


CriteriaResolver = Callable[[JourneyScenario, JourneyDefinition], EvaluationCriteria]


@dataclass(frozen=True)
class EvaluationResult:
    """``record`` is what ``evaluation.json`` holds."""

    episode_dir: Path
    record: dict[str, Any]
    trace: Trace
    verdict: TurnVerdict | None = None
    failures: tuple[FailureRecord, ...] = ()

    @property
    def outcome(self) -> str:
        return self.record["outcome"]

    @property
    def rule(self) -> int:
        return self.record["rule"]["number"]

    @property
    def explanation(self) -> str:
        return self.record["explanation"]

    def to_run_result(self) -> RunResult:
        """The ``BatchRunner`` shape. The Trace is empty when it could not be
        projected. ``llm_calls`` counts the Judge call only: the Episode record
        does not count the Simulated user's."""
        return RunResult(
            trace=self.trace,
            verdicts=[self.verdict] if self.verdict is not None else [],
            outcome=self.outcome,
            final_reasoning=self.explanation,
            failures=list(self.failures),
            degraded_checks=[
                {"id": item["id"], "status": item["status"], "reason": item["reason"]}
                for item in self.record["assertions"]
                if item["status"] == "unavailable"
            ],
            llm_calls=1 if self.record["judge"]["called"] else 0,
        )


class _Decision(NamedTuple):
    """The first matching rule."""

    outcome: str
    rule: int
    explanation: str


@dataclass
class _Working:
    trace: Trace
    verdict: TurnVerdict | None = None
    failures: tuple[FailureRecord, ...] = ()


async def evaluate_episode(
    episode_dir: str | Path,
    judge: EpisodeJudge,
    journey: JourneyDefinition,
    *,
    criteria: CriteriaResolver = criteria_for,
) -> EvaluationResult:
    """Evaluate a saved Episode and write ``evaluation.json`` beside it. The
    file is derived from the rest of the directory, so re-evaluating replaces it.
    ``journey`` is the definition the Episode's Scenario was written for."""
    episode_dir = Path(episode_dir)
    if not episode_dir.is_dir():
        raise EvaluationError(f"{episode_dir} is not an Episode directory")

    record: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "scenario_id": None,
        "journey": None,
        "conversation_id": None,
        "episode_status": None,
        "stop_reason": None,
        "expected_outcome": None,
        "outcome": None,
        "rule": None,
        "explanation": None,
        "evidence": None,
        "assertions": [],
        "outcome_evidence": None,
        "judge": {
            "called": False, "model": getattr(judge, "model", None),
            "verdict": None, "error": None,
        },
        "failures": [],
        "incomplete": None,
        "episode_error": None,
        "simulator_model": None,
    }
    working = _Working(trace=Trace(conversation_id=episode_dir.name))
    decided = await _apply_rules(episode_dir, judge, journey, criteria, record, working)
    record["outcome"] = decided.outcome
    record["rule"] = {"number": decided.rule, "name": RULES[decided.rule]}
    record["explanation"] = decided.explanation
    record["failures"] = [failure.to_dict() for failure in working.failures]
    _atomic_json(episode_dir / EVALUATION_FILE, record)
    return EvaluationResult(
        episode_dir, record, working.trace, working.verdict, working.failures
    )


async def _apply_rules(
    episode_dir: Path,
    judge: EpisodeJudge,
    journey: JourneyDefinition,
    criteria: CriteriaResolver,
    record: dict[str, Any],
    working: _Working,
) -> _Decision:
    """The first matching rule, filling ``record`` and ``working`` on the way."""
    # Rule 0.
    try:
        episode = json.loads((episode_dir / EPISODE_FILE).read_text(encoding="utf-8"))
        if not isinstance(episode, dict):
            raise ValueError(f"{EPISODE_FILE} is not an object")
        scenario = load_journey_scenario(episode_dir / SCENARIO_FILE)
        if scenario.journey != journey.journey_id:
            raise ValueError(
                f"{SCENARIO_FILE} is for Journey {scenario.journey!r}, not the "
                f"Journey definition {journey.journey_id!r} it is evaluated against"
            )
        applied = criteria(scenario, journey)
        undefined = sorted(
            set(scenario.judge_criterion_ids) - set(applied.judge_criterion_tools)
        )
        if undefined:
            raise ValueError(
                f"{SCENARIO_FILE} names Judge criterion(s) {undefined} that the "
                "criteria it is evaluated with do not define"
            )
    except (OSError, ValueError) as error:
        return _Decision(
            OUTCOME_ERROR, 0, f"the Episode directory cannot be read: {error}"
        )
    stop_reason = episode.get("stop_reason")
    record.update(
        scenario_id=scenario.scenario_id,
        journey=scenario.journey,
        conversation_id=episode.get("conversation_id"),
        episode_status=episode.get("status"),
        stop_reason=stop_reason,
        expected_outcome=scenario.expected_outcome,
        simulator_model=episode.get("simulator_model"),
    )
    if episode.get("conversation_id"):
        working.trace = Trace(conversation_id=episode["conversation_id"])

    # Rule 1. An aborted Episode has no stop reason; it is an error all the same.
    if (
        episode.get("status") != "complete"
        or stop_reason in (STOP_ADAPTER_ERROR, STOP_SIMULATOR_ERROR)
        or stop_reason not in EPISODE_STOP_REASONS
    ):
        record["episode_error"] = episode.get("error")
        return _Decision(OUTCOME_ERROR, 1, _episode_error_explanation(episode))

    # Rule 2.
    try:
        normalized = NormalizedTrace.from_json(
            (episode_dir / NORMALIZED_TRACE_FILE).read_text(encoding="utf-8")
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return _Decision(
            OUTCOME_ERROR, 2,
            f"{NORMALIZED_TRACE_FILE} cannot be read: {type(error).__name__}: {error}",
        )
    record["evidence"] = normalized.evidence.to_dict()
    if not normalized.evidence.complete:
        reasons = "; ".join(normalized.evidence.reasons) or "no reason recorded"
        return _Decision(
            OUTCOME_ERROR, 2,
            f"Trace evidence is incomplete (messages {normalized.evidence.messages}, "
            f"actions {normalized.evidence.actions}): {reasons}",
        )
    files = _evidence_files(episode_dir)
    results = tuple(
        _with_files(spec.check(normalized, scenario), files) for spec in applied.assertions
    )
    gate = applied.outcome_gate(normalized, scenario)
    record["assertions"] = [result.to_dict() for result in results]
    record["outcome_evidence"] = gate.to_dict()
    gaps = [f"{r.id}: {r.reason}" for r in results if r.status == "unavailable"]
    if gate.status == "unavailable":
        gaps.append(f"{checks.EXPECTED_OUTCOME_EVIDENCED}: {gate.reason}")
    if gaps:
        return _Decision(
            OUTCOME_ERROR, 2,
            "required evidence is unavailable, so nothing can be concluded — "
            + "; ".join(gaps),
        )
    try:
        working.trace = normalized.to_trace()
    except NormalizedTraceError as error:
        return _Decision(
            OUTCOME_ERROR, 2, f"the Trace cannot be shown to the Judge: {error}"
        )

    # Rule 3. The Judge is not called, so it cannot override.
    working.failures = tuple(f for result in results for f in result.failures)
    if working.failures:
        failed = [r.id for r in results if r.status == "failed"]
        return _Decision(
            OUTCOME_FAIL, 3,
            f"Assertion(s) failed: {', '.join(failed)}. The Judge was not called.",
        )

    # Rule 4.
    record["judge"]["called"] = True
    try:
        verdict = await judge.judge_episode(scenario, working.trace)
    except Exception as error:  # LLMError, or a broken Judge: infrastructure either way
        record["judge"]["error"] = {"type": type(error).__name__, "message": str(error)}
        return _Decision(
            OUTCOME_ERROR, 4, f"the Judge raised {type(error).__name__}: {error}"
        )
    working.verdict = verdict
    record["judge"]["verdict"] = verdict.to_dict()

    # Rule 5. Fail-closed again here: a criterion the Judge did not affirm is
    # violated, whatever decision came with it.
    affirmed = {c.criterion_id for c in verdict.criteria if c.passed is True}
    violated = [i for i in scenario.judge_criterion_ids if i not in affirmed]
    if verdict.decision == "fail" or violated:
        details = {
            "stop_reason": stop_reason,
            "expected_outcome": scenario.expected_outcome,
            "outcome_status": gate.status,
        }
        reasoning = {c.criterion_id: c.reasoning for c in verdict.criteria}
        working.failures = tuple(
            _judge_failure(
                criterion_id, reasoning.get(criterion_id, ""), details, normalized,
                applied.judge_criterion_tools[criterion_id], files,
            )
            for criterion_id in violated
        ) or (
            _judge_failure(JUDGE_DECISION, verdict.reasoning, details, normalized, (), files),
        )
        return _Decision(
            OUTCOME_FAIL, 5,
            "the Judge ruled fail: " + ", ".join(f.id for f in working.failures),
        )

    # Rule 6.
    if verdict.decision == "pass" and gate.evidenced:
        return _Decision(
            OUTCOME_PASS, 6,
            "every Assertion passed, the Judge ruled pass, and expected outcome "
            f"{scenario.expected_outcome!r} is evidenced by "
            f"{', '.join(gate.action_ids)}",
        )

    # Rule 7. The gate carries no FailureRecord, so the reason is stated here.
    record["incomplete"] = {
        "expected_outcome": scenario.expected_outcome,
        "outcome_status": gate.status,
        "stop_reason": stop_reason,
        "judge_decision": verdict.decision,
    }
    if gate.evidenced:
        why = (
            f"expected outcome {scenario.expected_outcome!r} is evidenced, but the Judge "
            f"answered {verdict.decision!r} rather than 'pass'"
        )
    else:
        why = (
            f"expected outcome {scenario.expected_outcome!r} is not evidenced in the Trace"
        )
    return _Decision(
        OUTCOME_TASK_INCOMPLETE, 7,
        "conduct was clean — every Assertion passed and the Judge found no violated "
        f"criterion — but {why}; the conversation ended on {stop_reason}",
    )


def _episode_error_explanation(episode: Mapping[str, Any]) -> str:
    status, stop_reason = episode.get("status"), episode.get("stop_reason")
    if status != "complete":
        head = f"the Episode did not complete (status {status!r})"
    elif stop_reason in (STOP_ADAPTER_ERROR, STOP_SIMULATOR_ERROR):
        head = f"the Episode stopped on {stop_reason}"
    else:
        head = f"the Episode has an unknown stop reason {stop_reason!r}"
    error = episode.get("error")
    if not isinstance(error, Mapping):
        return head
    adapter_error = error.get("adapter_error")
    if isinstance(adapter_error, Mapping):
        fault = "the agent raised" if adapter_error.get("agent_fault") else "infrastructure"
        return (
            f"{head} during {error.get('operation')}: {adapter_error.get('kind')} "
            f"{adapter_error.get('detail')} ({fault})"
        )
    return f"{head}: {error.get('type')}: {error.get('message')}"


def _evidence_files(episode_dir: Path) -> list[str]:
    """Evidence file references, relative to the Episode directory so they are
    the same for every Episode and do not pull clusters apart."""
    names = (NORMALIZED_TRACE_FILE, RAW_TRACE_FILE, TRANSCRIPT_FILE)
    return [name for name in names if (episode_dir / name).is_file()]


def _with_files(result: AssertionResult, files: list[str]) -> AssertionResult:
    """Fill ``data["evidence"]["files"]``, which Assertions leave empty."""
    filled = []
    for failure in result.failures:
        data = copy.deepcopy(failure.data)
        data.setdefault("evidence", {})["files"] = list(files)
        filled.append(replace(failure, data=data))
    return replace(result, failures=tuple(filled))


def _judge_failure(
    failure_id: str,
    reasoning: str,
    details: Mapping[str, Any],
    trace: NormalizedTrace,
    tools: tuple[str, ...],
    files: list[str],
) -> FailureRecord:
    """The Judge rules once on the whole conversation and names no Turn, so
    the evidence is every action of the tools the criterion is about, with the
    user message each handled and the reply it produced. Identities come from
    the normalized Trace, never from Transcript line numbers."""
    actions = sorted(
        (a for a in trace.actions if a.tool_name in tools), key=lambda a: a.sequence
    )
    message_ids: list[str] = []
    for action in actions:
        for message_id in (action.caused_by_message_id, action.reply_message_id):
            if message_id and message_id not in message_ids:
                message_ids.append(message_id)
    return FailureRecord(
        source="judge",
        id=failure_id,
        turn_index=None,
        message=reasoning,
        data={
            **details,
            "tools": list(tools),
            "evidence": {
                "message_ids": message_ids,
                "action_ids": [a.action_id for a in actions],
                "files": list(files),
            },
        },
    )
