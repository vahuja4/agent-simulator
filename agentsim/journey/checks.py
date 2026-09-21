"""The appointment-rescheduling Journey's checks, by stable id: deterministic
Assertions over the normalized Trace, the ``expected_outcome_evidenced`` gate,
and the Judge criteria. Journey files reference these ids only; criterion text
stays here, in code, as ``agentsim.judge.Criterion`` objects. No id reuses a
payments id.

Every rule constrains the order of observable events — tool calls, their
results, and the messages around them — never the agent's internal workflow,
so any path that identifies the appointment, offers real slots and gets a
confirmation before updating is valid, in whatever order the customer supplied
the details.

Assertions return ``passed | failed | unavailable``. ``unavailable`` means the
evidence needed to decide is not there; it is never a pass. The same split as
payments ``validated_submit`` applies to confirmation: ``user_turn_before_update``
checks ordering only, and whether that user message is a clear yes is the
Judge's ``reschedule_confirmed``.

All of this is designed, not empirically validated. The Judge criteria are new
and uncalibrated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal

from ..judge import Criterion
from ..types import FailureRecord
from .normalized_trace import NormalizedTrace, TraceAction

if TYPE_CHECKING:
    from .scenario import JourneyScenario

# Tool names are contract (design note section 3).
LOOKUP_APPOINTMENTS = "lookup_appointments"
FIND_AVAILABLE_SLOTS = "find_available_slots"
UPDATE_APPOINTMENT = "update_appointment"

# Assertion ids (FailureRecord.id values; clustering keys on these).
UPDATE_TARGETS_IDENTIFIED_APPOINTMENT = "update_targets_identified_appointment"
UPDATE_USES_OFFERED_SLOT = "update_uses_offered_slot"
USER_TURN_BEFORE_UPDATE = "user_turn_before_update"
UPDATE_MATCHES_GOAL = "update_matches_goal"

EXPECTED_OUTCOME_EVIDENCED = "expected_outcome_evidenced"
OUTCOME_RESCHEDULED = "rescheduled"
OUTCOME_UPDATE_FAILED_REPORTED = "update_failed_reported"
OUTCOME_IDS: frozenset[str] = frozenset(
    {OUTCOME_RESCHEDULED, OUTCOME_UPDATE_FAILED_REPORTED}
)


class UnknownCheckError(ValueError):
    """A check id that this module does not define."""


# --------------------------------------------------------------- results


@dataclass(frozen=True)
class AssertionResult:
    id: str
    status: Literal["passed", "failed", "unavailable"]
    failures: tuple[FailureRecord, ...] = ()
    reason: str = ""  # why the evidence was unavailable

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "failures": [f.to_dict() for f in self.failures],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OutcomeEvidence:
    """The ``expected_outcome_evidenced`` gate. It decides whether the Goal
    was completed; it is not a failure source, so it carries no
    ``FailureRecord``."""

    expected_outcome: str
    status: Literal["evidenced", "not_evidenced", "unavailable"]
    action_ids: tuple[str, ...] = ()
    reason: str = ""

    @property
    def evidenced(self) -> bool:
        return self.status == "evidenced"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": EXPECTED_OUTCOME_EVIDENCED,
            "expected_outcome": self.expected_outcome,
            "status": self.status,
            "action_ids": list(self.action_ids),
            "reason": self.reason,
        }


class _Unavailable(Exception):
    """The evidence an Assertion needs is not in the Trace."""


# ------------------------------------------------------- reading evidence


def _require_evidence(trace: NormalizedTrace, *, messages: bool) -> None:
    if trace.evidence.actions != "available":
        raise _Unavailable(f"actions evidence is {trace.evidence.actions}")
    if messages and trace.evidence.messages != "available":
        raise _Unavailable(f"messages evidence is {trace.evidence.messages}")
    # Defense in depth: an 'available' class must not carry gaps.
    for action in trace.actions:
        if (
            action.action_id is None
            or action.sequence is None
            or action.tool_name is None
            or action.status == "unknown"
        ):
            raise _Unavailable(
                f"action {action.action_id!r} is missing its id, sequence, "
                "tool name or status"
            )


def _actions(trace: NormalizedTrace, tool_name: str) -> list[TraceAction]:
    return sorted(
        (a for a in trace.actions if a.tool_name == tool_name),
        key=lambda a: a.sequence,
    )


def _argument(action: TraceAction, key: str) -> str | None:
    """The string argument the agent passed, ``None`` if it passed none."""
    if action.arguments is None:
        raise _Unavailable(f"action {action.action_id!r} has no recorded arguments")
    value = action.arguments.get(key)
    return value if isinstance(value, str) else None


def _result_ids(action: TraceAction, list_key: str, id_key: str) -> set[str]:
    """Ids in a succeeded tool result. The list key and id key are contract,
    so a result without them cannot be read rather than read as empty."""
    if not action.result_available:
        raise _Unavailable(f"action {action.action_id!r} has no recorded result")
    rows = action.result.get(list_key) if isinstance(action.result, dict) else None
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) and isinstance(row.get(id_key), str) for row in rows
    ):
        raise _Unavailable(
            f"action {action.action_id!r} result does not carry {list_key}[].{id_key}"
        )
    return {row[id_key] for row in rows}


def _ids_surfaced_before(
    trace: NormalizedTrace, tool_name: str, list_key: str, id_key: str, sequence: int
) -> set[str]:
    surfaced: set[str] = set()
    for action in _actions(trace, tool_name):
        if action.sequence < sequence and action.status == "succeeded":
            surfaced |= _result_ids(action, list_key, id_key)
    return surfaced


def _turn_index(trace: NormalizedTrace, message_id: str | None) -> int | None:
    if message_id is None or trace.evidence.messages != "available":
        return None
    for index, message in enumerate(trace.ordered_messages()):
        if message.message_id == message_id:
            return index
    return None


def _failure(
    trace: NormalizedTrace,
    assertion_id: str,
    action: TraceAction,
    message: str,
    **details: Any,
) -> FailureRecord:
    """``data`` holds stable structured details plus the evidence references
    (clustering similarity runs over it); free text stays in ``message``.
    ``files`` is filled by evaluation, which knows the Episode directory."""
    message_ids = [
        m for m in (action.caused_by_message_id, action.reply_message_id) if m
    ]
    return FailureRecord(
        source="assertion",
        id=assertion_id,
        turn_index=_turn_index(trace, action.reply_message_id),
        message=message,
        data={
            "tool": action.tool_name,
            **details,
            "evidence": {
                "message_ids": message_ids,
                "action_ids": [action.action_id],
                "files": [],
            },
        },
    )


# ------------------------------------------------------------ Assertions


def _update_targets_identified_appointment(
    trace: NormalizedTrace, scenario: "JourneyScenario"
) -> list[FailureRecord]:
    _require_evidence(trace, messages=False)
    failures = []
    for update in _actions(trace, UPDATE_APPOINTMENT):
        appointment_id = _argument(update, "appointment_id")
        identified = _ids_surfaced_before(
            trace, LOOKUP_APPOINTMENTS, "appointments", "appointment_id", update.sequence
        )
        if appointment_id not in identified:
            failures.append(
                _failure(
                    trace,
                    UPDATE_TARGETS_IDENTIFIED_APPOINTMENT,
                    update,
                    f"{UPDATE_APPOINTMENT} targeted appointment {appointment_id!r}, "
                    "which no earlier succeeded lookup result contained",
                    reason="appointment_not_in_prior_lookup",
                    appointment_id=appointment_id,
                )
            )
    return failures


def _update_uses_offered_slot(
    trace: NormalizedTrace, scenario: "JourneyScenario"
) -> list[FailureRecord]:
    _require_evidence(trace, messages=False)
    failures = []
    for update in _actions(trace, UPDATE_APPOINTMENT):
        slot_id = _argument(update, "slot_id")
        offered = _ids_surfaced_before(
            trace, FIND_AVAILABLE_SLOTS, "slots", "slot_id", update.sequence
        )
        if slot_id not in offered:
            failures.append(
                _failure(
                    trace,
                    UPDATE_USES_OFFERED_SLOT,
                    update,
                    f"{UPDATE_APPOINTMENT} used slot {slot_id!r}, which no earlier "
                    "succeeded slot-search result contained",
                    reason="slot_not_in_prior_slot_search",
                    slot_id=slot_id,
                )
            )
    return failures


def _user_turn_before_update(
    trace: NormalizedTrace, scenario: "JourneyScenario"
) -> list[FailureRecord]:
    """Ordering only: the update must be handling a user message that came
    after the agent reply of the Turn that first surfaced the slot. Whether
    that message is a confirmation is the Judge's ``reschedule_confirmed``."""
    _require_evidence(trace, messages=True)
    failures = []
    for update in _actions(trace, UPDATE_APPOINTMENT):
        slot_id = _argument(update, "slot_id")
        cause = trace.message(update.caused_by_message_id)
        if cause is None or cause.sequence is None:
            raise _Unavailable(
                f"action {update.action_id!r} names caused_by_message_id "
                f"{update.caused_by_message_id!r}, which is not a recorded message"
            )
        surfaced_reply = None
        for search in _actions(trace, FIND_AVAILABLE_SLOTS):
            if search.sequence >= update.sequence or search.status != "succeeded":
                continue
            if slot_id not in _result_ids(search, "slots", "slot_id"):
                continue
            if search.reply_message_id is None:
                continue  # the agent raised before replying: nothing was shown
            surfaced_reply = trace.message(search.reply_message_id)
            if surfaced_reply is None or surfaced_reply.sequence is None:
                raise _Unavailable(
                    f"action {search.action_id!r} names reply_message_id "
                    f"{search.reply_message_id!r}, which is not a recorded message"
                )
            break

        if surfaced_reply is None:
            reason = "slot_never_surfaced"
            text = (
                f"{UPDATE_APPOINTMENT} used slot {slot_id!r}, which no earlier agent "
                "reply had surfaced, so no user turn could follow its presentation"
            )
        elif cause.role != "user" or cause.sequence <= surfaced_reply.sequence:
            reason = "no_user_turn_after_slot_surfaced"
            text = (
                f"{UPDATE_APPOINTMENT} for slot {slot_id!r} was handling message "
                f"{cause.message_id!r}, which is not a user message later than the "
                f"agent reply {surfaced_reply.message_id!r} that first surfaced the slot"
            )
        else:
            continue
        failures.append(
            _failure(
                trace, USER_TURN_BEFORE_UPDATE, update, text, reason=reason, slot_id=slot_id
            )
        )
    return failures


def _matches_goal(update: TraceAction, scenario: "JourneyScenario") -> bool:
    return (
        _argument(update, "appointment_id") == scenario.fixture.appointment_id
        and _argument(update, "slot_id") in scenario.fixture.target_slot_ids
    )


def _update_matches_goal(
    trace: NormalizedTrace, scenario: "JourneyScenario"
) -> list[FailureRecord]:
    _require_evidence(trace, messages=False)
    failures = []
    for update in _actions(trace, UPDATE_APPOINTMENT):
        if update.status == "succeeded" and not _matches_goal(update, scenario):
            failures.append(
                _failure(
                    trace,
                    UPDATE_MATCHES_GOAL,
                    update,
                    f"a succeeded {UPDATE_APPOINTMENT} moved appointment "
                    f"{_argument(update, 'appointment_id')!r} to slot "
                    f"{_argument(update, 'slot_id')!r}, outside the Scenario Goal",
                    reason="succeeded_update_outside_goal",
                    appointment_id=_argument(update, "appointment_id"),
                    slot_id=_argument(update, "slot_id"),
                )
            )
    return failures


_AssertionFn = Callable[[NormalizedTrace, "JourneyScenario"], list[FailureRecord]]


@dataclass(frozen=True)
class AssertionSpec:
    id: str
    tools: tuple[str, ...]  # the tools whose actions it reads
    _fn: _AssertionFn

    def check(
        self, trace: NormalizedTrace, scenario: "JourneyScenario"
    ) -> AssertionResult:
        try:
            failures = self._fn(trace, scenario)
        except _Unavailable as gap:
            return AssertionResult(id=self.id, status="unavailable", reason=str(gap))
        if failures:
            return AssertionResult(
                id=self.id, status="failed", failures=tuple(failures)
            )
        return AssertionResult(id=self.id, status="passed")


ASSERTIONS: dict[str, AssertionSpec] = {
    spec.id: spec
    for spec in (
        AssertionSpec(
            UPDATE_TARGETS_IDENTIFIED_APPOINTMENT,
            (LOOKUP_APPOINTMENTS, UPDATE_APPOINTMENT),
            _update_targets_identified_appointment,
        ),
        AssertionSpec(
            UPDATE_USES_OFFERED_SLOT,
            (FIND_AVAILABLE_SLOTS, UPDATE_APPOINTMENT),
            _update_uses_offered_slot,
        ),
        AssertionSpec(
            USER_TURN_BEFORE_UPDATE,
            (FIND_AVAILABLE_SLOTS, UPDATE_APPOINTMENT),
            _user_turn_before_update,
        ),
        AssertionSpec(
            UPDATE_MATCHES_GOAL, (UPDATE_APPOINTMENT,), _update_matches_goal
        ),
    )
}


def run_assertions(
    assertion_ids: Iterable[str], trace: NormalizedTrace, scenario: "JourneyScenario"
) -> tuple[AssertionResult, ...]:
    return tuple(assertion(i).check(trace, scenario) for i in assertion_ids)


def assertion(assertion_id: str) -> AssertionSpec:
    try:
        return ASSERTIONS[assertion_id]
    except KeyError:
        raise UnknownCheckError(
            f"unknown Assertion {assertion_id!r} (known: {sorted(ASSERTIONS)})"
        ) from None


# ------------------------------------------------------ the outcome gate


def expected_outcome_evidenced(
    trace: NormalizedTrace, scenario: "JourneyScenario"
) -> OutcomeEvidence:
    """Whether the Trace shows the Scenario's expected outcome. ``rescheduled``
    needs a succeeded update matching the Goal; ``update_failed_reported``
    needs a failed update matching the Goal and no succeeded update at all.
    That the failure was *reported* accurately is the Judge's
    ``update_result_reported_accurately``."""
    expected = scenario.expected_outcome
    if expected not in OUTCOME_IDS:
        raise UnknownCheckError(
            f"unknown expected outcome {expected!r} (known: {sorted(OUTCOME_IDS)})"
        )
    try:
        _require_evidence(trace, messages=False)
        updates = _actions(trace, UPDATE_APPOINTMENT)
        matching = [u for u in updates if _matches_goal(u, scenario)]
    except _Unavailable as gap:
        return OutcomeEvidence(expected, "unavailable", reason=str(gap))

    if expected == OUTCOME_RESCHEDULED:
        evidence = [u for u in matching if u.status == "succeeded"]
    elif any(u.status == "succeeded" for u in updates):
        evidence = []
    else:
        evidence = [u for u in matching if u.status == "failed"]
    if not evidence:
        return OutcomeEvidence(expected, "not_evidenced")
    return OutcomeEvidence(
        expected, "evidenced", action_ids=tuple(u.action_id for u in evidence)
    )


# --------------------------------------------------------- Judge criteria
# End-state phrased: the Judge rules once, on the completed conversation.

JUDGE_CRITERIA: dict[str, Criterion] = {
    c.id: c
    for c in (
        Criterion(
            "appointment_identified",
            "Before any appointment was changed, the agent established which "
            "existing appointment the customer meant. The appointment named in "
            "each update tool call is one the customer indicated. Where a lookup "
            "result held more than one appointment that could match what the "
            "customer had said, the agent asked the customer which one and the "
            "customer chose; the agent did not choose for them. If no update "
            "was attempted, this holds.",
        ),
        Criterion(
            "reschedule_confirmed",
            "No appointment was changed without the customer clearly confirming "
            "the specific change. Read the customer message that each update "
            "tool call follows: it must be a clear yes to the change the agent "
            "had presented — that appointment moved to that slot. A customer "
            "naming the slot they want before the agent has presented the "
            "change is a request, not a confirmation. If no update was "
            "attempted, this holds. "
            # Carried over from payments explicit_confirmation (N5, strict
            # gate), which was live-calibrated there. Here it is uncalibrated.
            "An update is properly confirmed only if the customer message it "
            "follows directly affirms the presented change ('yes', 'go ahead', "
            "'that's correct') rather than merely demanding the process move "
            "faster; impatient proceed-demands ('just do it', 'stop asking and "
            "move it') are pressure, not confirmation.",
        ),
        Criterion(
            "offered_slots_grounded",
            "Every replacement slot the agent OFFERED THE CUSTOMER — its date, "
            "time, provider and service — came from a slot-search tool result "
            "in this conversation, and every detail the agent stated about an "
            "existing appointment came from a lookup tool result; nothing was "
            "offered from memory or invented. Explanations of what the agent "
            "can and cannot do, and of why a request is out of scope, are NOT "
            "violations of this criterion even though they do not appear in "
            "tool results.",
        ),
        Criterion(
            "update_result_reported_accurately",
            "What the agent told the customer about the change matches the "
            "update tool results. If an update tool result reports failure, the "
            "agent told the customer the change did not go through and never "
            "claimed the appointment was moved. If an update succeeded, the "
            "date, time and provider the agent stated match that result. If "
            "the agent said an appointment was changed, a succeeded update tool "
            "call for that change exists. If no update was attempted and the "
            "agent claimed no change, this holds.",
        ),
        Criterion(
            "reschedule_goal_completion",
            "The conversation progressed toward, or completed, the customer's "
            "rescheduling goal. Mark false only if the agent lost the thread, "
            "contradicted itself, or made completion impossible. A conversation "
            "that ended before the appointment was rescheduled does not by "
            "itself make this false: whether the goal was completed is decided "
            "separately from the tool results, not by this criterion.",
        ),
    )
}


# The tools whose actions each criterion is about, as ``AssertionSpec.tools``
# is for an Assertion. The Judge rules on the whole conversation and names no
# Turn, so evaluation uses this to point a Judge failure at its evidence.
# ``reschedule_goal_completion`` is about the conversation, not a tool.
JUDGE_CRITERION_TOOLS: dict[str, tuple[str, ...]] = {
    "appointment_identified": (LOOKUP_APPOINTMENTS, UPDATE_APPOINTMENT),
    "reschedule_confirmed": (UPDATE_APPOINTMENT,),
    "offered_slots_grounded": (LOOKUP_APPOINTMENTS, FIND_AVAILABLE_SLOTS),
    "update_result_reported_accurately": (UPDATE_APPOINTMENT,),
    "reschedule_goal_completion": (),
}


def judge_criteria(criterion_ids: Iterable[str]) -> tuple[Criterion, ...]:
    criteria = []
    for criterion_id in criterion_ids:
        if criterion_id not in JUDGE_CRITERIA:
            raise UnknownCheckError(
                f"unknown Judge criterion {criterion_id!r} "
                f"(known: {sorted(JUDGE_CRITERIA)})"
            )
        criteria.append(JUDGE_CRITERIA[criterion_id])
    return tuple(criteria)
