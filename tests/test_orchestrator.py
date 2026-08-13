"""Orchestrator tests with scripted fakes — no LLM, no real mock needed."""

from __future__ import annotations

from agentsim.llm import LLMError
from agentsim.orchestrator import run_conversation
from agentsim.simulator import SimTurn
from agentsim.types import AgentResponse, CriterionVerdict, ToolCall, TurnVerdict


class FakeSimulator:
    def __init__(self, turns: list[SimTurn]) -> None:
        self.turns = list(turns)

    async def next_turn(self, history):
        return self.turns.pop(0)


class EchoAgent:
    def __init__(self) -> None:
        self.selected_card = None

    async def call(self, input):
        return AgentResponse(
            content=f"echo: {input.last_user_message}",
            tool_calls=[ToolCall(name="PayeeList", arguments={}, result={"payees": []})],
            selected_card=self.selected_card,
        )


class ScriptedJudge:
    def __init__(self, decisions: list[str]) -> None:
        self.decisions = list(decisions)

    async def judge(self, trace):
        d = self.decisions.pop(0)
        return TurnVerdict(
            decision=d,
            criteria=[CriterionVerdict("goal_completion", d != "fail", "scripted")],
            reasoning=f"scripted {d}",
        )


def sim_turns(*texts: str, stop_last: bool = False) -> list[SimTurn]:
    turns = [SimTurn(intent=f"turn {i}", text=t, stop=False) for i, t in enumerate(texts)]
    if stop_last and turns:
        turns[-1].stop = True
    return turns


async def test_trace_shape_and_outcome_on_pass():
    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("hello", "pay it")),
        agent=EchoAgent(),
        judge=ScriptedJudge(["continue", "pass"]),
        conversation_id="t1",
        max_turns=5,
    )
    assert result.outcome == "pass"
    assert result.trace.outcome == "pass"
    trace = result.trace
    assert [t.speaker for t in trace.turns] == ["user", "agent", "user", "agent"]
    assert trace.turns[0].intent == "turn 0"
    assert trace.turns[1].tool_calls[0].result == {"payees": []}
    assert len(result.verdicts) == 2


async def test_judge_fail_stops_the_run():
    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("a", "b", "c")),
        agent=EchoAgent(),
        judge=ScriptedJudge(["fail", "continue", "continue"]),
        max_turns=5,
    )
    assert result.outcome == "fail"
    assert len(result.trace.turns) == 2  # stopped after the first exchange


async def test_max_turns_is_task_incomplete():
    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("a", "b", "c")),
        agent=EchoAgent(),
        judge=ScriptedJudge(["continue"] * 3),
        max_turns=3,
    )
    assert result.outcome == "task_incomplete"
    assert "max_turns" in result.final_reasoning


async def test_stop_sentinel_without_verdict_is_task_incomplete():
    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("a", "bye", stop_last=True)),
        agent=EchoAgent(),
        judge=ScriptedJudge(["continue", "continue"]),
        max_turns=10,
    )
    assert result.outcome == "task_incomplete"
    # The stopping message was still delivered and judged.
    assert len(result.trace.turns) == 4


async def test_silent_stop_breaks_immediately():
    result = await run_conversation(
        simulator=FakeSimulator([SimTurn(intent="stop", text="", stop=True)]),
        agent=EchoAgent(),
        judge=ScriptedJudge([]),
        max_turns=10,
    )
    assert result.outcome == "task_incomplete"
    assert result.trace.turns == []


class ViolatingAgent:
    """Submits without any validate — trips validated_submit on its first turn."""

    async def call(self, input):
        return AgentResponse(
            content="done, submitted!",
            tool_calls=[
                ToolCall(name="AddOneTimePayment", arguments={"formId": "form-1"}, result={})
            ],
            selected_card=None,
        )


class PassHappyJudge:
    """Claims pass on every turn — the assertion gate must not care."""

    calls = 0

    async def judge(self, trace):
        type(self).calls += 1
        return TurnVerdict(
            decision="pass",
            criteria=[CriterionVerdict("goal_completion", True, "looks great")],
            reasoning="pass",
        )


async def test_assertion_failure_hard_gates_before_the_judge():
    from agentsim.assertions import AssertionEngine

    judge = PassHappyJudge()
    PassHappyJudge.calls = 0
    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("just do it")),
        agent=ViolatingAgent(),
        judge=judge,
        max_turns=5,
        assertions=AssertionEngine(),
    )
    # The judge would have said pass — the assertion overrides structurally:
    # it never even ruled on the violating turn.
    assert result.outcome == "fail"
    assert PassHappyJudge.calls == 0
    assert result.verdicts == []
    assert "assertion failure" in result.final_reasoning
    assert [f.source for f in result.failures] == ["assertion"]
    assert result.failures[0].id == "validated_submit"
    assert result.failures[0].turn_index == 1


async def test_assertions_none_preserves_old_behavior():
    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("just do it", "again")),
        agent=ViolatingAgent(),
        judge=ScriptedJudge(["continue", "pass"]),
        max_turns=5,
    )
    assert result.outcome == "pass"  # nothing gates without an engine
    assert result.failures == []


async def test_judge_fail_records_failure_sources():
    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("a")),
        agent=EchoAgent(),
        judge=ScriptedJudge(["fail"]),
        max_turns=5,
    )
    assert result.outcome == "fail"
    assert [(f.source, f.id) for f in result.failures] == [("judge", "goal_completion")]
    assert result.failures[0].turn_index == 1  # the ruled-on agent turn


async def test_clean_agent_passes_through_the_engine():
    from agentsim.assertions import AssertionEngine

    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("hello", "pay it")),
        agent=EchoAgent(),
        judge=ScriptedJudge(["continue", "pass"]),
        max_turns=5,
        assertions=AssertionEngine(),
    )
    assert result.outcome == "pass"
    assert result.failures == []


async def test_llm_error_is_error_outcome():
    class BrokenJudge:
        async def judge(self, trace):
            raise LLMError("boom")

    result = await run_conversation(
        simulator=FakeSimulator(sim_turns("a")),
        agent=EchoAgent(),
        judge=BrokenJudge(),
        max_turns=3,
    )
    assert result.outcome == "error"
    assert "boom" in result.final_reasoning
    assert result.trace.outcome == "error"
