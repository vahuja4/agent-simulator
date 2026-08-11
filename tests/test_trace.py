from agentsim.trace import TRACE_SCHEMA_VERSION, Trace, TraceToolCall


def build_sample() -> Trace:
    trace = Trace(conversation_id="conv-1")
    trace.add_user_turn("I want to pay my card", intent="open", selected_card=None)
    trace.add_agent_turn(
        "Which card?",
        tool_calls=[
            TraceToolCall(
                name="PayeeList",
                arguments={},
                result={"payees": [{"payeeId": "card-1"}]},
            )
        ],
        selected_card=None,
    )
    trace.add_user_turn("The Sapphire", intent="answer", selected_card=None)
    trace.add_agent_turn("Got it.", tool_calls=[], selected_card="Chase Sapphire Preferred (...9013)")
    trace.outcome = "pass"
    return trace


def test_schema_version_serialized():
    d = build_sample().to_dict()
    assert d["schema_version"] == TRACE_SCHEMA_VERSION


def test_json_round_trip():
    trace = build_sample()
    assert Trace.from_json(trace.to_json()) == trace


def test_round_trip_preserves_results_and_state():
    d = build_sample().to_dict()
    restored = Trace.from_dict(d)
    _, call = next(restored.iter_tool_calls())
    assert call.result == {"payees": [{"payeeId": "card-1"}]}
    assert restored.turns[3].selected_card == "Chase Sapphire Preferred (...9013)"


def test_turns_are_ordered_and_speaker_tagged():
    trace = build_sample()
    assert [t.index for t in trace.turns] == [0, 1, 2, 3]
    assert [t.speaker for t in trace.turns] == ["user", "agent", "user", "agent"]
    # User turns are distinct records (never folded into agent turns) — the
    # confirmation-ordering assertion depends on this.
    assert trace.turns[2].intent == "answer"


def test_tool_call_names_in_order():
    assert build_sample().tool_call_names() == ["PayeeList"]
