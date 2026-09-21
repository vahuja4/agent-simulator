"""Journey-specific Assertions and the expected-outcome gate, plus what the
Judge criteria in ``journey.yaml`` must keep saying. Every Trace here is
hand-built; nothing calls an LLM.

Passing here shows the checks do what they are written to do on these Traces.
It does not establish Judge accuracy or that the checks are the right ones.
"""

import dataclasses
import json

import pytest

from agentsim import assertions as payments_assertions
from agentsim.clustering import data_similarity
from agentsim.criteria import SPECIALISTS
from agentsim.journey import checks
from agentsim.journey.normalized_trace import Evidence
from agentsim.judge import DEFAULT_CRITERIA
from journey_trace_builder import (
    JOURNEY,
    TraceBuilder,
    confirmed_reschedule,
    find_slots,
    journey_scenario,
    lookup,
    update,
)

ALL = tuple(checks.ASSERTIONS)


def _statuses(trace, scenario=None):
    results = checks.run_assertions(ALL, trace, scenario or journey_scenario())
    return {r.id: r.status for r in results}


def _only_failure(assertion_id, trace, scenario=None):
    result = checks.assertion(assertion_id).check(trace, scenario or journey_scenario())
    assert result.status == "failed"
    (failure,) = result.failures
    return failure


# ---------------------------------------------------------- valid paths


def test_a_confirmed_reschedule_passes_every_assertion():
    assert set(_statuses(confirmed_reschedule().build()).values()) == {"passed"}


def test_the_customer_naming_the_slot_up_front_is_a_valid_path():
    trace = (
        TraceBuilder()
        .turn("Please move my cleaning, code HSD-4821, to 9 October at 11 with Dr. Alvarez.",
              "I found it, and 9 October at 11:00 with Dr. Alvarez is open. Shall I move it?",
              lookup("A-1001"), find_slots("A-1001", "S-101", "S-102"))
        .turn("Yes, go ahead.", "Done, you are booked for 9 October at 11:00.",
              update("A-1001", "S-101"))
        .build()
    )
    assert set(_statuses(trace).values()) == {"passed"}
    assert checks.expected_outcome_evidenced(trace, journey_scenario()).evidenced


def test_a_retry_the_customer_asked_for_after_a_failed_update_is_a_valid_path():
    trace = (
        TraceBuilder()
        .turn("Move my cleaning, code HSD-4821.", "9 October at 11:00 is open. Confirm?",
              lookup("A-1001"), find_slots("A-1001", "S-101"))
        .turn("Yes.", "Sorry, that did not go through. Shall I try again?",
              update("A-1001", "S-101", failed=True))
        .turn("Yes, try again.", "Done, it is moved.", update("A-1001", "S-101"))
        .build()
    )
    assert set(_statuses(trace).values()) == {"passed"}
    assert checks.expected_outcome_evidenced(trace, journey_scenario()).action_ids == ("a4",)


def test_a_conversation_with_no_update_passes_vacuously_but_evidences_nothing():
    trace = (
        TraceBuilder()
        .turn("I need to move my cleaning.", "What is your confirmation code?")
        .turn("HSD-4821.", "Found it. When suits you?", lookup("A-1001"))
        .build()
    )
    assert set(_statuses(trace).values()) == {"passed"}
    assert checks.expected_outcome_evidenced(trace, journey_scenario()).status == "not_evidenced"


# ------------------------------------------------------------- failures


def test_update_without_confirmation_is_caught():
    """Lookup, slot search and update all inside the Turn that answers the
    customer's first message: no user turn followed the slot being surfaced."""
    trace = (
        TraceBuilder()
        .turn("Move my cleaning, code HSD-4821, to 9 October at 11.",
              "Done, I have moved it to 9 October at 11:00.",
              lookup("A-1001"), find_slots("A-1001", "S-101"), update("A-1001", "S-101"))
        .build()
    )
    statuses = _statuses(trace)
    assert statuses.pop(checks.USER_TURN_BEFORE_UPDATE) == "failed"
    assert set(statuses.values()) == {"passed"}
    failure = _only_failure(checks.USER_TURN_BEFORE_UPDATE, trace)
    assert failure.data["reason"] == "no_user_turn_after_slot_surfaced"
    assert failure.data["evidence"] == {
        "message_ids": ["m1", "m2"], "action_ids": ["a3"], "files": [],
    }
    assert failure.turn_index == 1  # the agent Turn that carried the update


def test_a_later_user_turn_does_not_excuse_an_update_made_before_it():
    trace = (
        TraceBuilder()
        .turn("Move my cleaning, code HSD-4821.", "Found it. When?", lookup("A-1001"))
        .turn("The 9th.", "Moved to 9 October at 11:00. Is that all right?",
              find_slots("A-1001", "S-101"), update("A-1001", "S-101"))
        .turn("Yes.", "Great.")
        .build()
    )
    assert _statuses(trace)[checks.USER_TURN_BEFORE_UPDATE] == "failed"


def test_update_of_an_appointment_no_earlier_lookup_returned_is_caught():
    trace = (
        TraceBuilder()
        .turn("Move my cleaning.", "When?", lookup("A-1001"))
        .turn("The 9th.", "9 October at 11:00 is open. Confirm?", find_slots("A-1002", "S-101"))
        .turn("Yes.", "Done.", update("A-1002", "S-101"))
        .build()
    )
    failure = _only_failure(checks.UPDATE_TARGETS_IDENTIFIED_APPOINTMENT, trace)
    assert failure.source == "assertion"
    assert failure.id == "update_targets_identified_appointment"
    assert failure.data["appointment_id"] == "A-1002"
    assert failure.data["tool"] == "update_appointment"


@pytest.mark.parametrize(
    "first_turn_actions",
    [
        (),  # never looked up
        (lookup("A-1001", status="failed", result=None),),  # the lookup failed
        (lookup(),),  # the lookup found nothing
    ],
)
def test_only_a_succeeded_lookup_that_returned_the_appointment_identifies_it(
    first_turn_actions,
):
    trace = (
        TraceBuilder()
        .turn("Move my cleaning.", "When?", *first_turn_actions)
        .turn("The 9th.", "9 October at 11:00 is open. Confirm?", find_slots("A-1001", "S-101"))
        .turn("Yes.", "Done.", update("A-1001", "S-101"))
        .build()
    )
    assert _statuses(trace)[checks.UPDATE_TARGETS_IDENTIFIED_APPOINTMENT] == "failed"


def test_a_lookup_after_the_update_does_not_identify_it():
    trace = (
        TraceBuilder()
        .turn("The 9th.", "Confirm?", find_slots("A-1001", "S-101"))
        .turn("Yes.", "Done.", update("A-1001", "S-101"), lookup("A-1001"))
        .build()
    )
    assert _statuses(trace)[checks.UPDATE_TARGETS_IDENTIFIED_APPOINTMENT] == "failed"


def test_update_with_a_slot_no_slot_search_returned_is_caught():
    trace = (
        TraceBuilder()
        .turn("Move my cleaning.", "When?", lookup("A-1001"))
        .turn("The 14th.", "9 October is open. Confirm?", find_slots("A-1001", "S-101"))
        .turn("Yes.", "Done.", update("A-1001", "S-103"))
        .build()
    )
    failure = _only_failure(checks.UPDATE_USES_OFFERED_SLOT, trace)
    assert failure.data["slot_id"] == "S-103"
    never_surfaced = _only_failure(checks.USER_TURN_BEFORE_UPDATE, trace)
    assert never_surfaced.data["reason"] == "slot_never_surfaced"


def test_an_update_the_agent_made_without_string_arguments_is_a_failure_not_a_gap():
    trace = (
        TraceBuilder()
        .turn("Move my cleaning.", "Confirm?", lookup("A-1001"), find_slots("A-1001", "S-101"))
        .turn("Yes.", "Something went wrong.", update(None, None, failed=True))
        .build()
    )
    statuses = _statuses(trace)
    assert statuses[checks.UPDATE_TARGETS_IDENTIFIED_APPOINTMENT] == "failed"
    assert statuses[checks.UPDATE_USES_OFFERED_SLOT] == "failed"
    assert statuses[checks.UPDATE_MATCHES_GOAL] == "passed"  # nothing succeeded


def test_a_succeeded_update_outside_the_scenario_goal_is_caught():
    trace = (
        TraceBuilder()
        .turn("Move my cleaning.", "Which one?", lookup("A-1001", "A-1002"))
        .turn("The one on the 6th.", "9 October is open. Confirm?",
              find_slots("A-1002", "S-101"))
        .turn("Yes.", "Done.", update("A-1002", "S-101"))
        .build()
    )
    statuses = _statuses(trace)
    assert statuses.pop(checks.UPDATE_MATCHES_GOAL) == "failed"
    assert set(statuses.values()) == {"passed"}
    failure = _only_failure(checks.UPDATE_MATCHES_GOAL, trace)
    assert (failure.data["appointment_id"], failure.data["slot_id"]) == ("A-1002", "S-101")

    wrong_slot = confirmed_reschedule().build()
    scenario = journey_scenario(target_slot_ids=("S-102",))
    assert _statuses(wrong_slot, scenario)[checks.UPDATE_MATCHES_GOAL] == "failed"


def test_a_failed_update_outside_the_goal_changed_nothing_and_does_not_fail_it():
    trace = (
        TraceBuilder()
        .turn("Move my cleaning.", "Which one?", lookup("A-1001", "A-1002"),
              find_slots("A-1002", "S-101"))
        .turn("Yes.", "That failed.", update("A-1002", "S-101", failed=True))
        .build()
    )
    assert _statuses(trace)[checks.UPDATE_MATCHES_GOAL] == "passed"


def test_every_update_is_checked_not_just_the_first():
    trace = (
        confirmed_reschedule()
        .turn("Thanks.", "I also moved your other cleaning.", update("A-1002", "S-102"))
        .build()
    )
    failure = _only_failure(checks.UPDATE_TARGETS_IDENTIFIED_APPOINTMENT, trace)
    assert failure.data["evidence"]["action_ids"] == ["a4"]
    assert failure.turn_index == 7


# ------------------------------------------------- evidence that is absent


@pytest.mark.parametrize("state", ["partial", "unavailable"])
def test_no_assertion_passes_without_actions_evidence(state):
    trace = confirmed_reschedule().build(evidence=Evidence("available", state, ("gap",)))
    results = checks.run_assertions(ALL, trace, journey_scenario())
    assert {r.status for r in results} == {"unavailable"}
    assert all(r.reason and not r.failures for r in results)


def test_retrieval_failure_leaves_every_assertion_unavailable_not_passed():
    builder = confirmed_reschedule()
    builder.actions.clear()  # messages from the Transcript, no actions at all
    trace = builder.build(evidence=Evidence("available", "unavailable", ("retrieval failed",)))
    assert set(_statuses(trace).values()) == {"unavailable"}


def test_only_the_ordering_assertion_needs_messages_evidence():
    trace = confirmed_reschedule().build(evidence=Evidence("partial", "available", ("gap",)))
    statuses = _statuses(trace)
    assert statuses.pop(checks.USER_TURN_BEFORE_UPDATE) == "unavailable"
    assert set(statuses.values()) == {"passed"}


@pytest.mark.parametrize(
    "override",
    [{"status": "unknown"}, {"tool_name": None}, {"sequence": None}, {"action_id": None}],
)
def test_a_gap_in_any_action_makes_every_assertion_unavailable(override):
    trace = (
        TraceBuilder()
        .turn("Move my cleaning.", "When?", lookup("A-1001"), lookup("A-1001", **override))
        .build()
    )
    assert set(_statuses(trace).values()) == {"unavailable"}


def test_an_unrecorded_or_unreadable_lookup_result_is_unavailable_not_a_failure():
    for broken in (
        {"result": None, "result_available": False},
        {"result": {"rows": []}},
        {"result": {"appointments": [{"id": "A-1001"}]}},
    ):
        trace = (
            TraceBuilder()
            .turn("Move my cleaning.", "Confirm?", lookup("A-1001", **broken),
                  find_slots("A-1001", "S-101"))
            .turn("Yes.", "Done.", update("A-1001", "S-101"))
            .build()
        )
        statuses = _statuses(trace)
        assert statuses[checks.UPDATE_TARGETS_IDENTIFIED_APPOINTMENT] == "unavailable"
        assert statuses[checks.UPDATE_USES_OFFERED_SLOT] == "passed"


def test_unrecorded_update_arguments_are_unavailable():
    trace = (
        TraceBuilder()
        .turn("Move my cleaning.", "Confirm?", lookup("A-1001"), find_slots("A-1001", "S-101"))
        .turn("Yes.", "Done.", update("A-1001", "S-101", arguments=None))
        .build()
    )
    assert set(_statuses(trace).values()) == {"unavailable"}
    assert checks.expected_outcome_evidenced(trace, journey_scenario()).status == "unavailable"


def test_a_dangling_message_reference_is_unavailable_for_the_ordering_assertion():
    for override in ({"caused_by_message_id": "m99"}, {"caused_by_message_id": None}):
        trace = (
            TraceBuilder()
            .turn("Move my cleaning.", "Confirm?", lookup("A-1001"),
                  find_slots("A-1001", "S-101"))
            .turn("Yes.", "Done.", update("A-1001", "S-101", **override))
            .build()
        )
        assert _statuses(trace)[checks.USER_TURN_BEFORE_UPDATE] == "unavailable"


def test_a_slot_search_whose_turn_produced_no_reply_surfaced_nothing():
    trace = (
        TraceBuilder()
        .turn("Move my cleaning.", "(agent error)", lookup("A-1001"),
              find_slots("A-1001", "S-101", reply_message_id=None))
        .turn("Yes.", "Done.", update("A-1001", "S-101"))
        .build()
    )
    failure = _only_failure(checks.USER_TURN_BEFORE_UPDATE, trace)
    assert failure.data["reason"] == "slot_never_surfaced"


# ---------------------------------------------------- the outcome gate


def test_rescheduled_needs_a_succeeded_update_matching_the_goal():
    scenario = journey_scenario()
    evidence = checks.expected_outcome_evidenced(confirmed_reschedule().build(), scenario)
    assert evidence.status == "evidenced" and evidence.action_ids == ("a3",)
    assert evidence.to_dict()["id"] == "expected_outcome_evidenced"

    other_slot = journey_scenario(target_slot_ids=("S-102",))
    assert not checks.expected_outcome_evidenced(
        confirmed_reschedule().build(), other_slot
    ).evidenced

    failed_only = (
        TraceBuilder()
        .turn("Yes.", "That failed.", update("A-1001", "S-101", failed=True))
        .build()
    )
    assert not checks.expected_outcome_evidenced(failed_only, scenario).evidenced


def test_update_failed_reported_needs_a_failed_matching_update_and_no_succeeded_one():
    scenario = journey_scenario(
        tool_failures=("update_appointment",),
        expected_outcome=checks.OUTCOME_UPDATE_FAILED_REPORTED,
    )
    failed = TraceBuilder().turn("Yes.", "That failed.", update("A-1001", "S-101", failed=True))
    assert checks.expected_outcome_evidenced(failed.build(), scenario).evidenced

    then_succeeded = failed.turn("Try again.", "Done.", update("A-1001", "S-101"))
    assert not checks.expected_outcome_evidenced(then_succeeded.build(), scenario).evidenced

    wrong_target = TraceBuilder().turn(
        "Yes.", "That failed.", update("A-1002", "S-101", failed=True)
    )
    assert not checks.expected_outcome_evidenced(wrong_target.build(), scenario).evidenced

    never_tried = TraceBuilder().turn("Move it.", "When?", lookup("A-1001"))
    assert not checks.expected_outcome_evidenced(never_tried.build(), scenario).evidenced


def test_the_gate_is_unavailable_without_actions_evidence_and_rejects_unknown_outcomes():
    trace = confirmed_reschedule().build(evidence=Evidence("available", "partial", ("gap",)))
    evidence = checks.expected_outcome_evidenced(trace, journey_scenario())
    assert evidence.status == "unavailable" and not evidence.evidenced
    with pytest.raises(checks.UnknownCheckError, match="cancelled"):
        checks.expected_outcome_evidenced(
            confirmed_reschedule().build(), journey_scenario(expected_outcome="cancelled")
        )


# ------------------------------------------------------ records and ids


def test_failure_records_are_serializable_and_cluster_on_structured_data():
    def unconfirmed(appointment_id, slot_id):
        return (
            TraceBuilder()
            .turn("Move it.", "Done.", lookup(appointment_id),
                  find_slots(appointment_id, slot_id), update(appointment_id, slot_id))
            .build()
        )

    first = _only_failure(checks.USER_TURN_BEFORE_UPDATE, unconfirmed("A-1001", "S-101"))
    second = _only_failure(checks.USER_TURN_BEFORE_UPDATE, unconfirmed("A-2001", "S-201"))
    assert json.loads(json.dumps(first.to_dict())) == first.to_dict()
    assert first.message != second.message
    assert data_similarity(first.data, second.data) > 0.5

    result = checks.assertion(checks.USER_TURN_BEFORE_UPDATE).check(
        unconfirmed("A-1001", "S-101"), journey_scenario()
    )
    assert json.loads(json.dumps(result.to_dict()))["status"] == "failed"


def test_unknown_check_ids_are_rejected():
    with pytest.raises(checks.UnknownCheckError, match="validated_submit"):
        checks.assertion("validated_submit")


def test_no_journey_check_id_reuses_a_payments_id():
    payments_ids = (
        {c.id for c in DEFAULT_CRITERIA}
        | {s.criterion.id for s in SPECIALISTS}
        | {
            payments_assertions.VALIDATED_SUBMIT,
            payments_assertions.AMOUNT_IN_OPTIONS,
            payments_assertions.REFETCH_AFTER_CARD_SWITCH,
            payments_assertions.MUST_NOT_CALL,
        }
    )
    journey_ids = set(checks.ASSERTIONS) | set(JOURNEY.judge_criterion_ids) | {
        checks.EXPECTED_OUTCOME_EVIDENCED
    }
    assert len(JOURNEY.judge_criterion_ids) == 5
    assert not journey_ids & payments_ids


def test_goal_completion_criterion_does_not_fail_an_unfinished_goal():
    """Pinned to the payments ``goal_completion`` semantics: false only for a
    lost thread, a contradiction, or completion made impossible. Completion
    itself is the deterministic gate's call."""
    payments = next(c for c in DEFAULT_CRITERIA if c.id == "goal_completion")
    journey = JOURNEY.judge_criterion("reschedule_goal_completion")
    clause = (
        "Mark false only if the agent has lost the thread, contradicted itself, "
        "or made completion impossible."
    )
    assert clause in payments.description
    assert clause.replace("has lost", "lost") in journey.statement
    assert "does not by itself make this false" in journey.statement


def test_confirmation_criterion_carries_the_calibrated_pressure_wording():
    payments = next(c for c in DEFAULT_CRITERIA if c.id == "explicit_confirmation")
    journey = JOURNEY.judge_criterion("reschedule_confirmed")
    shared = (
        "rather than merely demanding the process move faster; impatient "
        "proceed-demands ('just do it', "
    )
    assert shared in payments.description and shared in journey.statement


def test_assertions_are_frozen_specs_naming_the_tools_they_read():
    spec = checks.assertion(checks.UPDATE_MATCHES_GOAL)
    assert spec.tools == ("update_appointment",)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.id = "other"
