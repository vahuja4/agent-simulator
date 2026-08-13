"""Scripting DSL tests: validation errors, scripted/autonomous parity of the
Trace, judge-only-at-checkpoints, proceed() handoff, adjustment 1 (a script
with no judge ruling is task_incomplete; assertions can force fail but never
produce pass), serialization, and the Phase 4 replay contract — a script
built mechanically from a recorded trace reproduces the tool-call sequence.
"""

from __future__ import annotations

import pytest

from agentsim import registry
from agentsim.adapters import MockConfig, MockPayCardAgent
from agentsim.assertions import AssertionEngine
from agentsim.orchestrator import run_conversation
from agentsim.script import (
    ScriptError,
    agent,
    judge,
    proceed,
    script_from_dicts,
    script_to_dicts,
    user,
    validate_script,
)
from agentsim.simulator import SimTurn
from test_orchestrator import (
    EchoAgent,
    FakeSimulator,
    PassHappyJudge,
    ScriptedJudge,
    ViolatingAgent,
    sim_turns,
)


# ------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "steps, fragment",
    [
        ([], "empty"),
        ([user("a"), user("b")], "user() follows user()"),
        ([agent()], "without a preceding user()"),
        ([user("a"), judge()], "between user() and agent()"),
        ([judge()], "before any agent turn"),
        ([user("a"), agent(), proceed(), user("b"), agent()], "final step"),
        ([user("a"), agent(), proceed(turns=0)], "must be positive"),
        ([user("a")], "awaiting its agent()"),
        ([user("a"), "not a step"], "not a script step"),
    ],
)
def test_validate_script_rejects_malformed_sequences(steps, fragment):
    import re

    with pytest.raises(ScriptError, match=re.escape(fragment)):
        validate_script(steps)


def test_validate_script_accepts_the_canonical_shapes():
    validate_script([user("a"), agent(), judge()])
    validate_script([user("a"), agent(), user(), agent(), judge(), proceed(2)])
    validate_script([user("a"), agent(), proceed()])


# --------------------------------------------------------------- running


async def test_fully_scripted_run_with_checkpoint_pass():
    result = await run_conversation(
        agent=EchoAgent(),
        judge=ScriptedJudge(["pass"]),
        script=[user("hello"), agent(), user("pay it"), agent(), judge()],
        max_turns=5,
    )
    assert result.outcome == "pass"
    assert len(result.verdicts) == 1  # only the checkpoint ruled
    trace = result.trace
    assert [t.speaker for t in trace.turns] == ["user", "agent", "user", "agent"]
    assert all(t.intent == "scripted" for t in trace.turns if t.speaker == "user")


async def test_scripted_turns_are_not_judged_without_checkpoints():
    judge_obj = PassHappyJudge()
    PassHappyJudge.calls = 0
    result = await run_conversation(
        agent=EchoAgent(),
        judge=judge_obj,
        script=[user("a"), agent(), user("b"), agent()],
        max_turns=5,
    )
    assert PassHappyJudge.calls == 0
    assert result.outcome == "task_incomplete"


async def test_script_without_judge_ruling_is_task_incomplete():
    # Adjustment 1: pass is judge-earned only — a clean scripted run that
    # ends with no ruling cannot pass.
    result = await run_conversation(
        agent=EchoAgent(),
        script=[user("a"), agent()],
        max_turns=5,
        assertions=AssertionEngine(),
    )
    assert result.outcome == "task_incomplete"
    assert "without a judge ruling" in result.final_reasoning
    assert result.failures == []


async def test_assertions_force_fail_in_a_judgeless_script():
    result = await run_conversation(
        agent=ViolatingAgent(),
        script=[user("just do it"), agent()],
        max_turns=5,
        assertions=AssertionEngine(),
    )
    assert result.outcome == "fail"
    assert [f.id for f in result.failures] == ["validated_submit"]


async def test_proceed_hands_off_to_the_autonomous_loop():
    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("second", "third")),
        agent=EchoAgent(),
        judge=ScriptedJudge(["continue", "pass"]),
        script=[user("first — scripted"), agent(), proceed()],
        max_turns=5,
    )
    assert result.outcome == "pass"
    trace = result.trace
    assert trace.turns[0].text == "first — scripted"
    assert trace.turns[0].intent == "scripted"
    assert trace.turns[2].intent == "turn 0"  # simulator-produced
    assert len(result.verdicts) == 2  # judged per turn only after proceed()


async def test_proceed_shares_the_max_turns_budget():
    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("a", "b", "c")),
        agent=EchoAgent(),
        judge=ScriptedJudge(["continue"] * 3),
        script=[user("scripted opener"), agent(), proceed()],
        max_turns=3,  # 1 scripted + 2 autonomous
    )
    assert result.outcome == "task_incomplete"
    assert "max_turns" in result.final_reasoning
    assert sum(1 for t in result.trace.turns if t.speaker == "user") == 3


async def test_proceed_turn_cap_is_reported():
    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("a", "b")),
        agent=EchoAgent(),
        judge=ScriptedJudge(["continue"]),
        script=[user("opener"), agent(), proceed(turns=1)],
        max_turns=10,
    )
    assert result.outcome == "task_incomplete"
    assert "proceed(turns=1)" in result.final_reasoning


async def test_sim_delegated_user_step():
    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("from the sim")),
        agent=EchoAgent(),
        judge=ScriptedJudge(["pass"]),
        script=[user(), agent(), judge()],
        max_turns=5,
    )
    assert result.outcome == "pass"
    assert result.trace.turns[0].text == "from the sim"
    assert result.trace.turns[0].intent == "turn 0"


async def test_missing_simulator_or_judge_is_a_clear_error():
    with pytest.raises(ValueError, match="simulator is None"):
        await run_conversation(agent=EchoAgent(), script=[user(), agent()])
    with pytest.raises(ValueError, match="judge is None"):
        await run_conversation(agent=EchoAgent(), script=[user("a"), agent(), judge()])
    with pytest.raises(ValueError, match="autonomous runs require"):
        await run_conversation(agent=EchoAgent())


# ---------------------------------------------------------- serialization


def test_steps_round_trip_through_dicts():
    steps = [user("hi"), agent(), user(), agent(), judge(), proceed(turns=3)]
    revived = script_from_dicts(script_to_dicts(steps))
    assert revived == steps


# ------------------------------------------------- the Phase 4 replay contract


async def test_replay_script_from_recorded_trace_reproduces_tool_calls():
    """A script built mechanically from a recorded trace's turn list drives a
    fresh mock through the identical tool-call sequence — the contract the
    Phase 4 replay emitter will rely on."""
    recorded = await run_conversation(
        simulator=FakeSimulator(sim_turns(
            "Pay the statement balance on my Chase Sapphire Preferred ending "
            "9013 from my Chase Total Checking ending 5678 on the due date.",
            "Yes, go ahead.",
        )),
        agent=MockPayCardAgent(),
        judge=ScriptedJudge(["continue", "continue"]),
        max_turns=2,
    )
    assert registry.ADD_ONE_TIME_PAYMENT in recorded.trace.tool_call_names()

    replay_script = [
        user(t.text) if t.speaker == "user" else agent() for t in recorded.trace.turns
    ]
    replayed = await run_conversation(
        agent=MockPayCardAgent(),
        script=replay_script,
        max_turns=len(replay_script),
        assertions=AssertionEngine(),
    )
    assert replayed.trace.tool_call_names() == recorded.trace.tool_call_names()
    assert [t.text for t in replayed.trace.turns] == [t.text for t in recorded.trace.turns]
