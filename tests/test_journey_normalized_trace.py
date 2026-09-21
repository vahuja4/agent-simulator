"""NormalizedTrace types and the ``to_trace()`` projection the Judge reads."""

import dataclasses

import pytest

from agentsim.journey.normalized_trace import (
    NORMALIZED_TRACE_SCHEMA_VERSION,
    Evidence,
    NormalizedTrace,
    NormalizedTraceError,
    TraceMessage,
    TraceProjectionError,
)
from agentsim.trace import Trace
from journey_trace_builder import (
    AVAILABLE,
    TraceBuilder,
    confirmed_reschedule,
    find_slots,
    lookup,
    update,
)


def test_to_trace_makes_one_turn_per_message_in_sequence_order():
    normalized = confirmed_reschedule().build()
    trace = normalized.to_trace()
    assert isinstance(trace, Trace)
    assert trace.conversation_id == "conv-1"
    assert [t.index for t in trace.turns] == list(range(6))
    assert [t.speaker for t in trace.turns] == ["user", "agent"] * 3
    assert [t.text for t in trace.turns] == [m.text for m in normalized.messages]
    assert all(t.selected_card is None and t.intent is None for t in trace.turns)


def test_to_trace_orders_by_sequence_not_by_list_position():
    normalized = confirmed_reschedule().build()
    shuffled = dataclasses.replace(
        normalized,
        messages=tuple(reversed(normalized.messages)),
        actions=tuple(reversed(normalized.actions)),
    )
    assert shuffled.to_trace().to_dict() == normalized.to_trace().to_dict()


def test_turn_index_maps_back_to_the_message_id():
    normalized = confirmed_reschedule().build()
    trace = normalized.to_trace()
    ordered = normalized.ordered_messages()
    for turn in trace.turns:
        assert ordered[turn.index].text == turn.text
    assert [m.message_id for m in ordered] == ["m1", "m2", "m3", "m4", "m5", "m6"]


def test_each_action_lands_on_the_turn_its_reply_message_id_names():
    normalized = (
        TraceBuilder()
        .turn("Move my cleaning to the 9th at 11.", "I can do 9 October at 11:00. Confirm?",
              lookup("A-1001"), find_slots("A-1001", "S-101"))
        .turn("Yes.", "Sorry, that did not go through.", update("A-1001", "S-101", failed=True))
        .build()
    )
    trace = normalized.to_trace()
    assert [c.name for c in trace.turns[1].tool_calls] == [
        "lookup_appointments", "find_available_slots",
    ]
    assert [c.name for c in trace.turns[3].tool_calls] == ["update_appointment"]
    assert trace.turns[0].tool_calls == [] and trace.turns[2].tool_calls == []
    # action-to-message references survive: every action is on its reply Turn
    ordered = normalized.ordered_messages()
    for action in normalized.actions:
        index = [m.message_id for m in ordered].index(action.reply_message_id)
        assert action.tool_name in [c.name for c in trace.turns[index].tool_calls]


def test_tool_call_result_carries_status_output_and_error():
    normalized = (
        TraceBuilder()
        .turn("Yes.", "Sorry, that failed.", update("A-1001", "S-101", failed=True))
        .turn("Try again.", "Done.", update("A-1001", "S-101"))
        .build()
    )
    failed, succeeded = [call for _, call in normalized.to_trace().iter_tool_calls()]
    assert failed.arguments == {"appointment_id": "A-1001", "slot_id": "S-101"}
    assert failed.result == {
        "status": "failed",
        "output": None,
        "error": {"code": "update_failed",
                  "message": "the appointment system rejected the update"},
    }
    assert succeeded.result == {
        "status": "succeeded",
        "output": {"appointment": {"appointment_id": "A-1001"}},
        "error": None,
    }


@pytest.mark.parametrize(
    "evidence",
    [
        Evidence("partial", "available", ("raw messages disagree with the Transcript",)),
        Evidence("available", "partial", ("action a1 has no status",)),
        Evidence("available", "unavailable", ("trace retrieval failed",)),
        Evidence("unavailable", "unavailable"),
    ],
)
def test_to_trace_raises_unless_both_evidence_classes_are_available(evidence):
    normalized = confirmed_reschedule().build(evidence=evidence)
    with pytest.raises(TraceProjectionError, match="both 'available'"):
        normalized.to_trace()


def test_to_trace_refuses_an_action_it_cannot_place():
    builder = TraceBuilder().turn("Hi", "Hello", lookup("A-1001", reply_message_id=None))
    with pytest.raises(TraceProjectionError, match="not an agent message"):
        builder.build().to_trace()
    builder = TraceBuilder().turn("Hi", "Hello", lookup("A-1001", reply_message_id="m1"))
    with pytest.raises(TraceProjectionError, match="not an agent message"):
        builder.build().to_trace()


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"action_id": None}, "has no action_id"),
        ({"sequence": None}, "has no sequence"),
        ({"sequence": 1}, "share a sequence number"),
        ({"tool_name": None}, "missing its tool name or status"),
        ({"status": "unknown"}, "missing its tool name or status"),
    ],
)
def test_to_trace_refuses_gaps_even_when_evidence_claims_available(override, fragment):
    builder = TraceBuilder().turn("Hi", "Hello", lookup("A-1001", **override))
    with pytest.raises(TraceProjectionError, match=fragment):
        builder.build().to_trace()


def test_to_trace_refuses_a_message_without_text_or_with_a_duplicate_id():
    normalized = confirmed_reschedule().build()
    no_text = (TraceMessage("m1", 1, "user", None),) + normalized.messages[1:]
    with pytest.raises(TraceProjectionError, match="has no text"):
        dataclasses.replace(normalized, messages=no_text).to_trace()
    duplicate = (TraceMessage("m2", 1, "user", "hi"),) + normalized.messages[1:]
    with pytest.raises(TraceProjectionError, match="duplicate message_id"):
        dataclasses.replace(normalized, messages=duplicate).to_trace()


def test_closed_vocabularies_are_enforced_on_construction():
    with pytest.raises(NormalizedTraceError, match="evidence.actions"):
        Evidence("available", "mostly")
    with pytest.raises(NormalizedTraceError, match="message.role"):
        TraceMessage("m1", 1, "assistant", "hi")
    with pytest.raises(NormalizedTraceError, match="action.status"):
        TraceBuilder().turn("Hi", "Hello", lookup("A-1001", status="ok"))


def test_json_round_trip_preserves_every_field_including_gaps():
    normalized = (
        TraceBuilder()
        .turn("Yes.", "Sorry, that failed.", update("A-1001", "S-101", failed=True),
              lookup("A-1001", result=None, result_available=False, status="unknown",
                     arguments=None, reply_message_id=None))
        .build(
            evidence=Evidence("available", "partial", ("action a2 has no result",)),
            tool_failures=("update_appointment",),
        )
    )
    restored = NormalizedTrace.from_json(normalized.to_json())
    assert restored == normalized
    assert restored.to_dict()["schema_version"] == NORMALIZED_TRACE_SCHEMA_VERSION == "1.0"
    assert restored.tool_failures == ("update_appointment",)


def test_from_dict_rejects_another_schema_version():
    payload = confirmed_reschedule().build().to_dict()
    payload["schema_version"] = "2.0"
    with pytest.raises(NormalizedTraceError, match="schema_version"):
        NormalizedTrace.from_dict(payload)


def test_retrieval_failure_shape_keeps_transcript_messages_and_no_actions():
    builder = confirmed_reschedule()
    builder.actions.clear()
    normalized = builder.build(
        evidence=Evidence("available", "unavailable", ("trace retrieval failed: transport",))
    )
    assert len(normalized.messages) == 6 and normalized.actions == ()
    assert normalized.message("m2").role == "agent"
    assert normalized.message(None) is None and normalized.message("m99") is None
    with pytest.raises(TraceProjectionError):
        normalized.to_trace()


def test_available_is_the_builder_default():
    assert AVAILABLE.complete and not Evidence("available", "partial").complete
