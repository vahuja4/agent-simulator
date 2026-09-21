"""Evaluation of a saved Episode directory. Offline: Episodes are played by
``run_episode`` against an in-memory adapter that hands back a hand-built
normalized Trace, and the Judge is a double — no HTTP, no model.

Nothing here says anything about Judge accuracy: the Judge criteria are
uncalibrated and the double rules whatever the test tells it to.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agentsim.adapters.conversation import (
    AdapterError,
    AgentReply,
    ConversationAdapter,
    ConversationHandle,
    RetrievedTrace,
)
from agentsim.batch import BatchRunner, BatchRunSpec
from agentsim.clustering import cluster_failures
from agentsim.journey import checks
from agentsim.journey import evaluation as ev
from agentsim.journey import judge as jj
from agentsim.journey.definition import load_journey_inputs
from agentsim.journey.episode import run_episode
from agentsim.journey.normalized_trace import Evidence, TraceAction, TraceMessage
from agentsim.journey.simulated_user import JourneySimTurn
from agentsim.judge import DEFAULT_CRITERIA, GeneralJudge
from agentsim.llm import LLMError
from agentsim.trace import Trace, TraceTurn
from agentsim.types import CriterionVerdict, FailureRecord, TurnVerdict
from tests.journey_trace_builder import (
    TraceBuilder,
    confirmed_reschedule,
    find_slots,
    journey_scenario,
    lookup,
    update,
)

JOURNEY_DIR = Path("journeys/appointment_rescheduling")
JOURNEY, FIXTURE_STATE = load_journey_inputs(JOURNEY_DIR)
AGENT_RAISED = AdapterError("service", "the agent raised", 500, "agent_error")


# ------------------------------------------------------------------ doubles


class TraceAdapter(ConversationAdapter):
    """Replies with the hand-built Trace's agent messages, under their ids,
    and returns that Trace at retrieval. ``fail`` maps ``"start"`` or
    ``("send", n)`` to what it raises."""

    def __init__(self, trace, *, fail=None, raw=True):
        self.trace = trace
        self.fail = dict(fail or {})
        self.raw = raw
        self.sends = 0

    def start_conversation(self, *, fixture_state, tool_failures=()):
        if "start" in self.fail:
            raise self.fail["start"]
        return ConversationHandle("conv-1", fixture_state.sha256, "stub")

    def send_message(self, handle, text):
        self.sends += 1
        if ("send", self.sends) in self.fail:
            raise self.fail[("send", self.sends)]
        messages = self.trace.messages
        user = [m for m in messages if m.role == "user"][self.sends - 1]
        agent = [m for m in messages if m.role == "agent"][self.sends - 1]
        return AgentReply(user.message_id, agent.message_id, agent.text)

    def retrieve_trace(self, handle):
        raw = {"trace_version": "1"} if self.raw else None
        return RetrievedTrace(raw, self.trace, None if self.raw else "retrieval failed")

    def release(self, handle):
        pass


class ScriptedUser:
    model = "double-simulator"

    def __init__(self, *script):
        self.script = list(script)

    async def next_turn(self, history):
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def say(text, stop_reason="none"):
    return JourneySimTurn(
        intent="scripted", text=text, stop=stop_reason != "none", stop_reason=stop_reason
    )


class JudgeDouble:
    """Rules what it is told to. ``failing`` criteria are marked false."""

    model = "double-judge"

    def __init__(self, *, failing=(), decision=None, omit=(), raises=None):
        self.failing, self.decision, self.omit, self.raises = failing, decision, omit, raises
        self.calls: list[tuple] = []

    async def judge_episode(self, scenario, trace):
        self.calls.append((scenario, trace))
        if self.raises is not None:
            raise self.raises
        criteria = [
            CriterionVerdict(i, i not in self.failing, f"reasoning about {i}")
            for i in scenario.judge_criterion_ids
            if i not in self.omit
        ]
        decision = self.decision or ("fail" if self.failing else "pass")
        return TurnVerdict(decision=decision, criteria=criteria, reasoning="overall")


async def play(tmp_path, trace, *, scenario=None, stop="goal_achieved", adapter=None, user=None):
    """Run one Episode whose conversation is the Trace's, and return its
    directory. ``stop="turn_limit"`` runs the Scenario out of Turns."""
    scenario = scenario or journey_scenario()
    texts = [m.text for m in trace.messages if m.role == "user"]
    if stop == "turn_limit":
        scenario = replace(scenario, max_turns=len(texts))
        script = [say(text) for text in texts]
    else:
        script = [say(text) for text in texts[:-1]] + [say(texts[-1], stop)]
    episode_dir = tmp_path / "episode"
    await run_episode(
        scenario,
        fixture_state=FIXTURE_STATE,
        adapter=adapter or TraceAdapter(trace),
        simulated_user=user or ScriptedUser(*script),
        episode_dir=episode_dir,
        service_url="http://127.0.0.1:8765",
    )
    return episode_dir


def evaluation_json(episode_dir):
    return json.loads((episode_dir / "evaluation.json").read_text())


# ------------------------------------------------------------------- Traces


def unconfirmed_update() -> TraceBuilder:
    """The slot is searched for and booked in one Turn: the customer never
    saw the change before it was made."""
    return (
        TraceBuilder()
        .turn("I need to move my cleaning, code HSD-4821.",
              "I found your cleaning with Dr. Alvarez on 6 October. When suits you?",
              lookup("A-1001"))
        .turn("Later that week if possible.",
              "Done. I moved it to 9 October at 11:00.",
              find_slots("A-1001", "S-101", "S-102"), update("A-1001", "S-101"))
    )


def failed_update(reply: str) -> TraceBuilder:
    return (
        TraceBuilder()
        .turn("I need to move my cleaning, code HSD-4821.",
              "I found your cleaning with Dr. Alvarez on 6 October. When suits you?",
              lookup("A-1001"))
        .turn("Later that week if possible.",
              "Dr. Alvarez has 9 October at 11:00. Shall I move it there?",
              find_slots("A-1001", "S-101", "S-102"))
        .turn("Yes, please move it.", reply, update("A-1001", "S-101", failed=True))
    )


def no_update_yet() -> TraceBuilder:
    return (
        TraceBuilder()
        .turn("I need to move my cleaning, code HSD-4821.",
              "I found your cleaning with Dr. Alvarez on 6 October. When suits you?",
              lookup("A-1001"))
        .turn("Later that week if possible.",
              "Dr. Alvarez has 9 October at 11:00. Shall I move it there?",
              find_slots("A-1001", "S-101", "S-102"))
    )


FAILURE_SCENARIO = dict(
    tool_failures=(checks.UPDATE_APPOINTMENT,),
    expected_outcome=checks.OUTCOME_UPDATE_FAILED_REPORTED,
)


# --------------------------------------------------------------------- pass


async def test_a_successful_episode_passes_and_leaves_evaluation_json(tmp_path):
    episode_dir = await play(tmp_path, confirmed_reschedule().build())
    judge = JudgeDouble()
    result = await ev.evaluate_episode(episode_dir, judge)

    assert (result.outcome, result.rule) == ("pass", 6)
    record = evaluation_json(episode_dir)
    assert record == result.record
    assert record["schema_version"] == "1.0"
    assert record["rule"] == {"number": 6, "name": "passed"}
    assert record["scenario_id"] == journey_scenario().scenario_id
    assert record["conversation_id"] == "conv-1"
    assert record["stop_reason"] == "user_finished"
    assert record["expected_outcome"] == "rescheduled"
    assert [(a["id"], a["status"]) for a in record["assertions"]] == [
        (i, "passed") for i in checks.ASSERTIONS
    ]
    assert record["outcome_evidence"]["status"] == "evidenced"
    assert record["outcome_evidence"]["action_ids"] == ["a3"]
    assert record["judge"]["called"] is True
    assert record["judge"]["model"] == "double-judge"
    assert record["judge"]["verdict"]["decision"] == "pass"
    assert record["simulator_model"] == "double-simulator"
    assert record["failures"] == [] and record["incomplete"] is None
    assert record["episode_error"] is None

    # The Judge was handed the Scenario saved in the Episode directory and the
    # projected Trace — messages and tool calls, nothing else.
    (scenario, trace), = judge.calls
    assert scenario.goal == journey_scenario().goal
    assert scenario.source == str(episode_dir / "scenario.yaml")
    assert [t.speaker for t in trace.turns] == ["user", "agent"] * 3
    assert trace.turns[5].tool_calls[0].name == checks.UPDATE_APPOINTMENT


# --------------------------------------------------- Assertion failure: fail


async def test_an_update_without_confirmation_fails_with_check_id_and_evidence(tmp_path):
    episode_dir = await play(tmp_path, unconfirmed_update().build())
    judge = JudgeDouble()  # would pass everything
    result = await ev.evaluate_episode(episode_dir, judge)

    assert (result.outcome, result.rule) == ("fail", 3)
    assert judge.calls == []  # never asked, so it cannot override
    assert result.record["judge"] == {
        "called": False, "model": "double-judge", "verdict": None, "error": None,
    }
    failure, = result.failures
    assert (failure.source, failure.id) == ("assertion", checks.USER_TURN_BEFORE_UPDATE)
    assert failure.message
    assert failure.data == {
        "tool": checks.UPDATE_APPOINTMENT,
        "reason": "no_user_turn_after_slot_surfaced",
        "slot_id": "S-101",
        "evidence": {
            "message_ids": ["m3", "m4"],
            "action_ids": ["a3"],
            "files": ["normalized_trace.json", "raw_trace.json", "transcript.jsonl"],
        },
    }
    assert checks.USER_TURN_BEFORE_UPDATE in result.explanation
    # evaluation.json carries the same failure, under the Assertion and merged.
    record = evaluation_json(episode_dir)
    assert record["failures"] == [failure.to_dict()]
    by_id = {a["id"]: a for a in record["assertions"]}
    assert by_id[checks.USER_TURN_BEFORE_UPDATE]["failures"] == [failure.to_dict()]
    # Every reference resolves: the ids are the normalized Trace's, the files exist.
    saved = json.loads((episode_dir / "normalized_trace.json").read_text())
    assert set(failure.data["evidence"]["message_ids"]) <= {
        m["message_id"] for m in saved["messages"]
    }
    assert all((episode_dir / name).is_file() for name in failure.data["evidence"]["files"])


async def test_structured_details_are_the_same_for_the_same_failure_in_another_episode(tmp_path):
    first = await ev.evaluate_episode(
        await play(tmp_path / "one", unconfirmed_update().build()), JudgeDouble()
    )
    second = await ev.evaluate_episode(
        await play(tmp_path / "two", unconfirmed_update().build()), JudgeDouble()
    )
    assert first.failures[0].data == second.failures[0].data
    assert first.episode_dir != second.episode_dir


# ------------------------------------------------- controlled tool failure


async def test_a_tool_failure_the_agent_explains_accurately_is_the_valid_outcome(tmp_path):
    scenario = journey_scenario(**FAILURE_SCENARIO)
    assert JOURNEY.outcome_for(scenario.fixture.tool_failures) == scenario.expected_outcome
    trace = failed_update("I'm sorry, the change did not go through. Nothing was moved.").build(
        tool_failures=scenario.fixture.tool_failures
    )
    episode_dir = await play(tmp_path, trace, scenario=scenario)
    result = await ev.evaluate_episode(episode_dir, JudgeDouble())

    assert (result.outcome, result.rule) == ("pass", 6)
    assert result.record["expected_outcome"] == "update_failed_reported"
    assert result.record["outcome_evidence"]["action_ids"] == ["a3"]


async def test_a_tool_failure_the_agent_reports_as_success_fails(tmp_path):
    scenario = journey_scenario(**FAILURE_SCENARIO)
    trace = failed_update("Done. Your cleaning is now on 9 October at 11:00.").build(
        tool_failures=scenario.fixture.tool_failures
    )
    episode_dir = await play(tmp_path, trace, scenario=scenario)
    # The Assertions cannot see words; Say/do consistency is the Judge's.
    judge = JudgeDouble(failing=("update_result_reported_accurately",))
    result = await ev.evaluate_episode(episode_dir, judge)

    assert (result.outcome, result.rule) == ("fail", 5)
    failure, = result.failures
    assert (failure.source, failure.id) == ("judge", "update_result_reported_accurately")
    assert failure.message == "reasoning about update_result_reported_accurately"
    assert failure.turn_index is None
    assert failure.data == {
        "stop_reason": "user_finished",
        "expected_outcome": "update_failed_reported",
        "outcome_status": "evidenced",
        "tools": [checks.UPDATE_APPOINTMENT],
        "evidence": {
            "message_ids": ["m5", "m6"],
            "action_ids": ["a3"],
            "files": ["normalized_trace.json", "raw_trace.json", "transcript.jsonl"],
        },
    }
    assert evaluation_json(episode_dir)["failures"] == [failure.to_dict()]


# ------------------------------------------ the Judge cannot override / pass


async def test_a_passing_judge_cannot_override_a_failed_assertion(tmp_path):
    trace = (
        confirmed_reschedule()
        .turn("And my other one too.", "Done, moved that as well.", update("A-2002", "S-101"))
        .build()
    )
    episode_dir = await play(tmp_path, trace)
    judge = JudgeDouble(decision="pass")
    result = await ev.evaluate_episode(episode_dir, judge)

    assert (result.outcome, result.rule) == ("fail", 3)
    assert judge.calls == []
    assert {f.id for f in result.failures} == {
        checks.UPDATE_TARGETS_IDENTIFIED_APPOINTMENT, checks.UPDATE_MATCHES_GOAL,
    }
    assert all(f.source == "assertion" for f in result.failures)


async def test_a_pass_decision_that_does_not_affirm_every_criterion_is_a_fail(tmp_path):
    episode_dir = await play(tmp_path, confirmed_reschedule().build())
    judge = JudgeDouble(decision="pass", omit=("reschedule_confirmed",))
    result = await ev.evaluate_episode(episode_dir, judge)

    assert (result.outcome, result.rule) == ("fail", 5)
    assert [f.id for f in result.failures] == ["reschedule_confirmed"]


async def test_a_fail_decision_with_every_criterion_affirmed_still_carries_a_failure(tmp_path):
    episode_dir = await play(tmp_path, confirmed_reschedule().build())
    result = await ev.evaluate_episode(episode_dir, JudgeDouble(decision="fail"))

    assert (result.outcome, result.rule) == ("fail", 5)
    failure, = result.failures
    assert (failure.source, failure.id, failure.message) == ("judge", "judge_decision", "overall")


async def test_a_continue_decision_is_never_a_pass(tmp_path):
    episode_dir = await play(tmp_path, confirmed_reschedule().build())
    result = await ev.evaluate_episode(episode_dir, JudgeDouble(decision="continue"))

    assert (result.outcome, result.rule) == ("task_incomplete", 7)
    assert result.record["incomplete"]["judge_decision"] == "continue"
    assert "'continue' rather than 'pass'" in result.explanation


# ---------------------------------------------------------- task_incomplete


@pytest.mark.parametrize(
    "stop, stop_reason", [("turn_limit", "turn_limit"), ("gave_up", "user_gave_up")]
)
async def test_an_unfinished_goal_with_clean_conduct_is_task_incomplete(tmp_path, stop, stop_reason):
    episode_dir = await play(tmp_path, no_update_yet().build(), stop=stop)
    result = await ev.evaluate_episode(episode_dir, JudgeDouble())

    assert (result.outcome, result.rule) == ("task_incomplete", 7)
    assert result.failures == ()
    # The gate carries no FailureRecord, so evaluation.json says why itself.
    record = evaluation_json(episode_dir)
    assert record["rule"]["name"] == "outcome_not_evidenced"
    assert record["incomplete"] == {
        "expected_outcome": "rescheduled",
        "outcome_status": "not_evidenced",
        "stop_reason": stop_reason,
        "judge_decision": "pass",
    }
    assert "'rescheduled' is not evidenced" in record["explanation"]
    assert stop_reason in record["explanation"]


@pytest.mark.parametrize("stop", ["turn_limit", "gave_up"])
async def test_the_same_stop_with_an_assertion_violation_is_a_fail(tmp_path, stop):
    # An update aimed at an appointment no lookup returned; it failed, so the
    # Goal is still unfinished — and the attempt is the violation.
    trace = (
        no_update_yet()
        .turn("Fine, do it.", "That did not work.", update("A-9999", "S-101", failed=True))
        .build()
    )
    episode_dir = await play(tmp_path, trace, stop=stop)
    result = await ev.evaluate_episode(episode_dir, JudgeDouble())

    assert (result.outcome, result.rule) == ("fail", 3)
    assert [f.id for f in result.failures] == [checks.UPDATE_TARGETS_IDENTIFIED_APPOINTMENT]


@pytest.mark.parametrize("stop", ["turn_limit", "gave_up"])
async def test_the_same_stop_with_a_judge_violation_is_a_fail(tmp_path, stop):
    episode_dir = await play(tmp_path, no_update_yet().build(), stop=stop)
    judge = JudgeDouble(failing=("offered_slots_grounded",))
    result = await ev.evaluate_episode(episode_dir, judge)

    assert (result.outcome, result.rule) == ("fail", 5)
    failure, = result.failures
    assert failure.id == "offered_slots_grounded"
    assert failure.data["outcome_status"] == "not_evidenced"
    assert failure.data["evidence"]["action_ids"] == ["a1", "a2"]
    assert failure.data["evidence"]["message_ids"] == ["m1", "m2", "m3", "m4"]


# ------------------------------------------- missing evidence is never pass


async def test_a_missing_normalized_trace_is_an_error(tmp_path):
    episode_dir = await play(tmp_path, confirmed_reschedule().build())
    (episode_dir / "normalized_trace.json").unlink()
    judge = JudgeDouble()
    result = await ev.evaluate_episode(episode_dir, judge)

    assert (result.outcome, result.rule) == ("error", 2)
    assert judge.calls == []
    assert "normalized_trace.json cannot be read" in result.explanation
    assert result.to_run_result().trace.turns == []


async def test_a_fallback_trace_is_an_error_under_rule_2(tmp_path):
    # Retrieval failed: messages from the adapter's own record, without a
    # sequence; no actions at all.
    built = confirmed_reschedule()
    reason = "retrieval failed: transport: connection refused"
    fallback = replace(
        built.build(Evidence("partial", "unavailable", (reason,))),
        messages=tuple(replace(m, sequence=None) for m in built.messages),
        actions=(),
    )
    episode_dir = await play(tmp_path, fallback, adapter=TraceAdapter(fallback, raw=False))
    assert not (episode_dir / "raw_trace.json").exists()
    judge = JudgeDouble()
    result = await ev.evaluate_episode(episode_dir, judge)

    assert (result.outcome, result.rule) == ("error", 2)
    assert judge.calls == []
    assert reason in result.explanation
    assert result.record["evidence"]["actions"] == "unavailable"
    # Every Assertion on such a Trace is unavailable, which is the same rule.
    scenario = journey_scenario()
    assert {r.status for r in checks.run_assertions(scenario.assertion_ids, fallback, scenario)} == {
        "unavailable"
    }


async def test_an_unavailable_assertion_is_an_error_even_if_the_judge_would_pass(tmp_path):
    # Both evidence classes say 'available', yet the update lost its arguments.
    trace = (
        no_update_yet()
        .turn("Yes, please move it.", "Done.", update("A-1001", "S-101", arguments=None))
        .build()
    )
    episode_dir = await play(tmp_path, trace)
    judge = JudgeDouble(decision="pass")
    result = await ev.evaluate_episode(episode_dir, judge)

    assert (result.outcome, result.rule) == ("error", 2)
    assert judge.calls == []
    assert result.failures == ()
    unavailable = [a["id"] for a in result.record["assertions"] if a["status"] == "unavailable"]
    assert unavailable == list(checks.ASSERTIONS)
    assert result.record["outcome_evidence"]["status"] == "unavailable"
    assert "no recorded arguments" in result.explanation
    assert [d["id"] for d in result.to_run_result().degraded_checks] == unavailable


async def test_an_unavailable_outcome_gate_alone_is_an_error(tmp_path):
    episode_dir = await play(tmp_path, confirmed_reschedule().build())

    def criteria(scenario):
        return replace(
            ev.criteria_for(scenario),
            outcome_gate=lambda trace, scenario: checks.OutcomeEvidence(
                scenario.expected_outcome, "unavailable", reason="the gate could not read it"
            ),
        )

    result = await ev.evaluate_episode(episode_dir, JudgeDouble(), criteria=criteria)
    assert (result.outcome, result.rule) == ("error", 2)
    assert "the gate could not read it" in result.explanation


async def test_an_unreadable_episode_directory_is_an_error(tmp_path):
    episode_dir = await play(tmp_path, confirmed_reschedule().build())
    (episode_dir / "scenario.yaml").write_text("journey: J1\n")
    result = await ev.evaluate_episode(episode_dir, JudgeDouble())

    assert (result.outcome, result.rule) == ("error", 0)
    assert result.record["rule"]["name"] == "episode_unreadable"
    assert evaluation_json(episode_dir)["scenario_id"] is None

    with pytest.raises(ev.EvaluationError):
        await ev.evaluate_episode(tmp_path / "nowhere", JudgeDouble())
    assert not (tmp_path / "nowhere").exists()


# ------------------------------------------------- infrastructure: error


async def test_an_agent_error_is_rule_1_before_the_trace_is_projected(tmp_path):
    # After a 500 agent_error the Trace is evidence-'available' yet holds an
    # action with no reply, which to_trace() refuses.
    built = no_update_yet()
    built.messages.append(TraceMessage("m5", 90, "user", "Yes, please move it."))
    built.actions.append(
        TraceAction(
            "a3", 91, checks.UPDATE_APPOINTMENT,
            {"appointment_id": "A-1001", "slot_id": "S-101"}, None, True, "failed",
            None, "m5", None,
        )
    )
    trace = built.build()
    assert trace.evidence.complete
    with pytest.raises(ValueError):
        trace.to_trace()

    adapter = TraceAdapter(trace, fail={("send", 3): AGENT_RAISED})
    episode_dir = await play(tmp_path, trace, adapter=adapter)
    judge = JudgeDouble(decision="pass")
    result = await ev.evaluate_episode(episode_dir, judge)

    assert (result.outcome, result.rule) == ("error", 1)
    assert judge.calls == []
    assert result.record["assertions"] == []  # nothing was asserted either
    # AdapterError.to_dict() travels with the result, unchanged.
    episode = json.loads((episode_dir / "episode.json").read_text())
    assert result.record["episode_error"] == episode["error"]
    assert result.record["episode_error"]["adapter_error"] == AGENT_RAISED.to_dict()
    assert result.record["episode_error"]["adapter_error"]["agent_fault"] is True
    assert "the agent raised" in result.explanation


async def test_an_infrastructure_adapter_error_is_an_error_not_a_fail(tmp_path):
    timeout = AdapterError("transport", "timed out after 120s")
    trace = unconfirmed_update().build()  # conduct that would otherwise fail
    adapter = TraceAdapter(trace, fail={("send", 2): timeout})
    episode_dir = await play(tmp_path, trace, adapter=adapter)
    result = await ev.evaluate_episode(episode_dir, JudgeDouble())

    assert (result.outcome, result.rule) == ("error", 1)
    assert result.failures == ()
    assert result.record["episode_error"]["adapter_error"] == timeout.to_dict()
    assert "infrastructure" in result.explanation


async def test_a_conversation_that_never_started_is_an_error(tmp_path):
    adapter = TraceAdapter(None, fail={"start": AdapterError("transport", "connection refused")})
    episode_dir = await play(tmp_path, confirmed_reschedule().build(), adapter=adapter)
    result = await ev.evaluate_episode(episode_dir, JudgeDouble())

    assert (result.outcome, result.rule) == ("error", 1)
    assert result.record["episode_error"]["operation"] == "start_conversation"
    assert result.record["conversation_id"] is None


@pytest.mark.parametrize("raised", [LLMError("no answer"), RuntimeError("a broken double")])
async def test_any_simulated_user_exception_is_an_error(tmp_path, raised):
    trace = confirmed_reschedule().build()
    episode_dir = await play(tmp_path, trace, user=ScriptedUser(say("hello"), raised))
    result = await ev.evaluate_episode(episode_dir, JudgeDouble())

    assert (result.outcome, result.rule) == ("error", 1)
    assert result.record["stop_reason"] == "simulator_error"
    assert result.record["episode_error"]["source"] == "simulated_user"
    assert result.record["episode_error"]["type"] == type(raised).__name__


async def test_an_aborted_episode_has_no_stop_reason_and_is_an_error(tmp_path):
    trace = confirmed_reschedule().build()
    adapter = TraceAdapter(trace, fail={("send", 2): KeyError("a harness bug")})
    with pytest.raises(KeyError):
        await play(tmp_path, trace, adapter=adapter)
    episode_dir = tmp_path / "episode"
    episode = json.loads((episode_dir / "episode.json").read_text())
    assert (episode["status"], episode["stop_reason"]) == ("aborted", None)

    result = await ev.evaluate_episode(episode_dir, JudgeDouble())
    assert (result.outcome, result.rule) == ("error", 1)
    assert result.record["episode_status"] == "aborted"
    assert result.record["episode_error"]["source"] == "harness"
    assert "did not complete" in result.explanation


async def test_a_judge_that_raises_is_an_error(tmp_path):
    episode_dir = await play(tmp_path, confirmed_reschedule().build())
    result = await ev.evaluate_episode(episode_dir, JudgeDouble(raises=LLMError("rate limited")))

    assert (result.outcome, result.rule) == ("error", 4)
    assert result.record["judge"]["called"] is True
    assert result.record["judge"]["error"] == {"type": "LLMError", "message": "rate limited"}
    assert result.failures == ()
    assert result.to_run_result().llm_calls == 1


# ------------------------------------------ mechanics take criteria as input


async def test_the_mechanics_run_whatever_criteria_they_are_handed(tmp_path):
    episode_dir = await play(tmp_path, confirmed_reschedule().build())

    def never_on_a_thursday(trace, scenario):
        return [FailureRecord("assertion", "never_on_a_thursday", None, "it was Thursday")]

    def criteria(scenario):
        return ev.EvaluationCriteria(
            assertions=(checks.AssertionSpec("never_on_a_thursday", (), never_on_a_thursday),),
            outcome_gate=checks.expected_outcome_evidenced,
            judge_criterion_tools={},
        )

    result = await ev.evaluate_episode(episode_dir, JudgeDouble(), criteria=criteria)
    assert (result.outcome, result.rule) == ("fail", 3)
    failure, = result.failures
    assert failure.id == "never_on_a_thursday"
    assert failure.data["evidence"]["files"]  # filled even when the Assertion gave none


def test_the_default_criteria_are_the_ones_the_scenario_references():
    scenario = replace(
        journey_scenario(),
        assertion_ids=(checks.UPDATE_MATCHES_GOAL,),
        judge_criterion_ids=("reschedule_confirmed",),
    )
    applied = ev.criteria_for(scenario)
    assert [spec.id for spec in applied.assertions] == [checks.UPDATE_MATCHES_GOAL]
    assert applied.judge_criterion_tools == {
        "reschedule_confirmed": (checks.UPDATE_APPOINTMENT,)
    }
    # Every Judge criterion says which tools it is about, and only Journey tools.
    assert set(checks.JUDGE_CRITERION_TOOLS) == set(checks.JUDGE_CRITERIA)
    assert {t for tools in checks.JUDGE_CRITERION_TOOLS.values() for t in tools} <= set(JOURNEY.tools)


# --------------------------------------- BatchRunRecord / BatchManifest shape


async def test_results_become_batch_records_that_clustering_groups(tmp_path):
    scenario = journey_scenario()
    dirs = {}

    async def execute(spec):
        episode_dir = await play(tmp_path / spec.run_id, unconfirmed_update().build())
        dirs[spec.run_key] = episode_dir
        return (await ev.evaluate_episode(episode_dir, JudgeDouble())).to_run_result()

    specs = [BatchRunSpec(scenario=scenario, run_id=f"run-{n}") for n in (1, 2)]
    batch_dir = tmp_path / "journey_runs"
    manifest = await BatchRunner(batch_dir, concurrency=1).run(specs, execute)

    for spec in specs:
        record = manifest.runs[spec.run_key]
        saved = evaluation_json(dirs[spec.run_key])
        assert (record.status, record.outcome) == ("completed", "fail")
        assert record.final_reasoning == saved["explanation"]
        assert [f.to_dict() for f in record.failures] == saved["failures"]
        assert record.llm_calls == 0
        # evaluation.json alone rebuilds the same record fields.
        assert [FailureRecord.from_dict(f) for f in saved["failures"]] == record.failures
    cluster, = cluster_failures(batch_dir)
    assert (cluster.source, cluster.id, cluster.size) == (
        "assertion", checks.USER_TURN_BEFORE_UPDATE, 2,
    )


async def test_a_judge_verdict_round_trips_into_the_batch_record(tmp_path):
    episode_dir = await play(tmp_path, confirmed_reschedule().build())
    result = await ev.evaluate_episode(episode_dir, JudgeDouble())
    run_result = result.to_run_result()

    assert run_result.outcome == "pass" and run_result.llm_calls == 1
    saved = evaluation_json(episode_dir)["judge"]["verdict"]
    assert [TurnVerdict.from_dict(saved)] == run_result.verdicts
    assert run_result.trace.conversation_id == "conv-1"


# ------------------------------------------------------------ the Judge prompt


def _pass_output(scenario):
    return {
        "criteria": [
            {"criterion_id": i, "passed": True, "reasoning": "held"}
            for i in scenario.judge_criterion_ids
        ],
        "decision": "pass",
        "reasoning": "clean",
    }


async def test_the_judge_prompt_holds_the_four_permitted_inputs_and_nothing_else(tmp_path, stub_llm):
    scenario = journey_scenario(**FAILURE_SCENARIO)
    trace = failed_update("I'm sorry, the change did not go through.").build(
        tool_failures=scenario.fixture.tool_failures
    )
    episode_dir = await play(tmp_path, trace, scenario=scenario)
    stub_llm.push(_pass_output(scenario))
    result = await ev.evaluate_episode(episode_dir, jj.JourneyJudge(stub_llm, JOURNEY))

    assert result.outcome == "pass"
    call, = stub_llm.calls  # one batched call
    system, (message,) = call["system"], call["messages"]
    prompt = system + "\n" + message["content"]

    # 1. The Scenario Goal.
    assert scenario.goal in message["content"]
    # 2. The criteria and required rules the Journey definition states.
    for criterion in checks.judge_criteria(scenario.judge_criterion_ids):
        assert f"- {criterion.id}: {criterion.description}" in system
    for rule in JOURNEY.required_rules:
        assert f"- {rule.id}: {rule.statement}" in message["content"]
    assert call["schema"]["properties"]["criteria"]["items"]["properties"]["criterion_id"][
        "enum"
    ] == list(scenario.judge_criterion_ids)
    # 3. The transcript. 4. The projected normalized Trace.
    assert "[4] Customer: Yes, please move it." in message["content"]
    assert "[5] Assistant: I'm sorry, the change did not go through." in message["content"]
    assert result.trace.to_json(indent=2) in message["content"]
    assert '"status": "failed"' in message["content"]
    assert JOURNEY.agent_role in system

    # Nothing else: not the expected outcome, the Fixture condition, the
    # Persona, the checks' wiring, or anything about how the agent is built.
    for absent in (
        "tool_failures", scenario.expected_outcome, "expected_outcome",
        scenario.persona.traits, scenario.persona.archetype, scenario.knowledge_level,
        "assertion:", "judge:", scenario.scenario_id, "stub",
    ):
        assert absent not in prompt, absent
    for absent in ("langgraph", "graph", "node", "workflow", "state machine"):
        assert absent not in prompt.lower(), absent
    # A completed conversation: the ruling is final.
    assert "COMPLETED conversation" in system and "never answer 'continue'" in system


def test_the_judge_is_shown_only_rules_the_scenario_references():
    scenario = replace(
        journey_scenario(),
        assertion_ids=(checks.UPDATE_MATCHES_GOAL,),
        judge_criterion_ids=("reschedule_confirmed",),
    )
    assert [rule.id for rule in jj.required_rules_for(JOURNEY, scenario)] == [
        "confirm_before_changing", "change_only_what_was_asked",
    ]
    assert [r.id for r in jj.required_rules_for(JOURNEY, journey_scenario())] == [
        r.id for r in JOURNEY.required_rules
    ]


async def test_the_journey_judge_inherits_fail_closed(stub_llm):
    scenario = journey_scenario()
    output = _pass_output(scenario)
    output["criteria"][1]["passed"] = False
    stub_llm.push(output)
    verdict = await jj.JourneyJudge(stub_llm, JOURNEY).judge_episode(
        scenario, confirmed_reschedule().build().to_trace()
    )
    assert verdict.decision == "fail"

    with pytest.raises(ValueError, match="not this Judge's"):
        await jj.JourneyJudge(stub_llm, JOURNEY).judge_episode(
            replace(scenario, journey="another-journey"), Trace(conversation_id="c")
        )
    with pytest.raises(ValueError, match="not bound"):
        jj.JourneyJudge(stub_llm, JOURNEY)._render(Trace(conversation_id="c"))


def test_payments_judge_prompts_are_unchanged():
    judge = GeneralJudge(None)
    trace = Trace(
        conversation_id="c",
        turns=[TraceTurn(index=0, speaker="user", text="hi"),
               TraceTurn(index=1, speaker="agent", text="hello")],
    )
    text = judge._system_prompt(DEFAULT_CRITERIA) + "\x00" + judge._render(trace)
    assert hashlib.sha256(text.encode()).hexdigest() == (
        "ee4b5df77409cf70029f9f88f7e91381c14b1b9269154cda2d437a10e299684c"
    )
    assert not set(checks.JUDGE_CRITERIA) & {c.id for c in DEFAULT_CRITERIA}


# ------------------------------------------------------------- model wiring


def test_the_live_judge_is_always_the_calibrated_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("AGENTSIM_MODEL", "some-other-model")
    judge = jj.live_journey_judge(JOURNEY)
    assert isinstance(judge, jj.JourneyJudge)
    assert judge.model == judge.llm.model == jj.JUDGE_MODEL == "gpt-5.5"


def test_missing_judge_configuration_fails_in_one_line_before_any_client(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(jj.JudgeConfigError, match="OPENAI_API_KEY") as caught:
        jj.live_journey_judge(JOURNEY)
    assert "\n" not in str(caught.value)


def test_enforced_model_family_separation_refuses_a_same_family_simulator(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    with pytest.raises(jj.JudgeConfigError, match="share a model family"):
        jj.live_journey_judge(
            JOURNEY, simulator_model="gpt-5.5-mini", enforce_model_family_separation=True
        )
    with pytest.raises(jj.JudgeConfigError, match="no Simulated-user model"):
        jj.live_journey_judge(JOURNEY, enforce_model_family_separation=True)
    # Default-off during development: the same pair is accepted.
    assert jj.live_journey_judge(JOURNEY, simulator_model="gpt-5.5-mini").model == "gpt-5.5"
    assert jj.live_journey_judge(
        JOURNEY, simulator_model="claude-sonnet-5", enforce_model_family_separation=True
    ).model == "gpt-5.5"
