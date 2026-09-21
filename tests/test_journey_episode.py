"""The Episode loop on the conversation lifecycle. Offline: an in-memory fake
adapter and a scripted Simulated-user double — no HTTP, no model.

Nothing here evaluates an Episode; ``run_episode`` assigns no outcome.
"""

from __future__ import annotations

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
from agentsim.journey import episode as ep
from agentsim.journey.definition import load_journey_inputs
from agentsim.journey.normalized_trace import Evidence, NormalizedTrace
from agentsim.journey.scenario import load_journey_scenario
from agentsim.journey.simulated_user import JourneySimTurn
from agentsim.llm import LLMError
from tests.journey_trace_builder import TraceBuilder, journey_scenario

JOURNEY_DIR = Path("journeys/appointment_rescheduling")
SERVICE_URL = "http://127.0.0.1:8765"
EPISODE_FILES = {
    "scenario.yaml", "transcript.jsonl", "episode.json", "raw_trace.json",
    "normalized_trace.json",
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeAdapter(ConversationAdapter):
    """In-memory conversation lifecycle. ``calls`` is the order of operations;
    ``fail`` maps an operation (or ``("send_message", n)``) to what it raises."""

    def __init__(self, *, fail=None, retrieval_gap=False, clock=None, seconds_per_send=0.0,
                 on_send=None):
        self.calls: list[str] = []
        self.fail = dict(fail or {})
        self.retrieval_gap = retrieval_gap
        self.clock = clock
        self.seconds_per_send = seconds_per_send
        self.on_send = on_send
        self.started_with = None
        self.exchanges: list[tuple[str, str]] = []
        self.released = False

    def _maybe_fail(self, *keys):
        for key in keys:
            if key in self.fail:
                raise self.fail[key]

    def start_conversation(self, *, fixture_state, tool_failures=()):
        self.calls.append("start_conversation")
        self.started_with = (fixture_state.sha256, tuple(tool_failures))
        self._maybe_fail("start_conversation")
        return ConversationHandle("conv-1", fixture_state.sha256, "stub")

    def send_message(self, handle, text):
        self.calls.append("send_message")
        sends = self.calls.count("send_message")
        if self.on_send is not None:
            self.on_send(sends, text)
        if self.clock is not None:
            self.clock.now += self.seconds_per_send
        self._maybe_fail("send_message", ("send_message", sends))
        reply = f"reply {sends}"
        self.exchanges.append((text, reply))
        n = len(self.exchanges)
        return AgentReply(f"m{2 * n - 1}", f"m{2 * n}", reply)

    def retrieve_trace(self, handle):
        assert not self.released, "retrieve after release: the adapter's record is gone"
        self.calls.append("retrieve_trace")
        self._maybe_fail("retrieve_trace")
        builder = TraceBuilder()
        for user_text, reply in self.exchanges:
            builder.turn(user_text, reply)
        if self.retrieval_gap:
            reason = "retrieval failed: transport: connection refused"
            gap = replace(
                builder.build(Evidence("partial", "unavailable", (reason,))),
                messages=tuple(replace(m, sequence=None) for m in builder.messages),
            )
            return RetrievedTrace(None, gap, reason)
        normalized = builder.build()
        return RetrievedTrace({"trace_version": "1", "events": len(self.exchanges)}, normalized)

    def release(self, handle):
        self.calls.append("release")
        self.released = True
        self._maybe_fail("release")


class ScriptedUser:
    """A Simulated-user double: plays its script, records the history it saw."""

    model = "double-model"

    def __init__(self, *script):
        self.script = list(script)
        self.histories: list[list] = []

    async def next_turn(self, history):
        self.histories.append(list(history))
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, BaseException):
            raise step
        return step


def say(text, stop_reason="none"):
    return JourneySimTurn(
        intent="scripted", text=text, stop=stop_reason != "none", stop_reason=stop_reason
    )


async def run(tmp_path, adapter, user, *, scenario=None, **kwargs):
    _, fixture_state = load_journey_inputs(JOURNEY_DIR)
    return await ep.run_episode(
        scenario or journey_scenario(),
        fixture_state=fixture_state, adapter=adapter, simulated_user=user,
        episode_dir=tmp_path / "episode", service_url=SERVICE_URL, **kwargs,
    )


def transcript(result):
    lines = (result.episode_dir / "transcript.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def episode_json(result):
    return json.loads((result.episode_dir / "episode.json").read_text())


# ---------------------------------------------------------------- normal run


async def test_a_normal_run_leaves_every_episode_file_and_retrieves_only_at_the_end(tmp_path):
    seen_on_disk = []

    def on_send(sends, text):
        # Each user message is on disk before it is sent; every earlier
        # exchange is already there: a crash now would lose nothing.
        lines = (tmp_path / "episode" / "transcript.jsonl").read_text().splitlines()
        seen_on_disk.append([(json.loads(l)["role"], json.loads(l)["text"]) for l in lines])

    adapter = FakeAdapter(on_send=on_send)
    user = ScriptedUser(say("move my cleaning"), say("the 9th"), say("yes, thanks", "goal_achieved"))
    result = await run(tmp_path, adapter, user)

    assert adapter.calls == [
        "start_conversation", "send_message", "send_message", "send_message",
        "retrieve_trace", "release",
    ]
    assert seen_on_disk == [
        [("user", "move my cleaning")],
        [("user", "move my cleaning"), ("agent", "reply 1"), ("user", "the 9th")],
        [("user", "move my cleaning"), ("agent", "reply 1"), ("user", "the 9th"),
         ("agent", "reply 2"), ("user", "yes, thanks")],
    ]
    assert {p.name for p in result.episode_dir.iterdir()} == EPISODE_FILES

    record = episode_json(result)
    assert record == result.record
    assert record["status"] == "complete"
    assert record["stop_reason"] == "user_finished" == result.stop_reason
    assert record["turns_completed"] == 3
    assert record["service_url"] == SERVICE_URL
    assert record["agent"] == "stub"
    assert record["conversation_id"] == "conv-1"
    assert record["simulator_model"] == "double-model"
    assert record["error"] is None
    assert record["retrieval"] == {
        "attempted": True, "raw_trace_saved": True, "error": None,
        "evidence": {"messages": "available", "actions": "available", "reasons": []},
    }
    assert record["release"] == {"attempted": True, "error": None}
    assert record["started_at"] <= record["ended_at"] and record["duration_s"] >= 0
    for never_assigned in ("outcome", "verdict", "expected_outcome"):
        assert never_assigned not in record

    lines = transcript(result)
    assert [(l["turn"], l["role"]) for l in lines] == [
        (1, "user"), (1, "agent"), (2, "user"), (2, "agent"), (3, "user"), (3, "agent"),
    ]
    assert lines[1]["message_id"] == "m2" and lines[1]["user_message_id"] == "m1"
    assert lines[4]["stop_reason"] == "goal_achieved"

    assert json.loads((result.episode_dir / "raw_trace.json").read_text()) == {
        "trace_version": "1", "events": 3,
    }
    normalized = NormalizedTrace.from_json(
        (result.episode_dir / "normalized_trace.json").read_text()
    )
    assert [m.text for m in normalized.messages][-1] == "reply 3"


async def test_the_simulated_user_sees_the_conversation_so_far(tmp_path):
    user = ScriptedUser(say("one"), say("two", "goal_achieved"))
    await run(tmp_path, FakeAdapter(), user)
    assert user.histories[0] == []
    assert [(m.role, m.content) for m in user.histories[1]] == [
        ("user", "one"), ("assistant", "reply 1"),
    ]


async def test_the_conversation_starts_on_the_scenarios_fixture_conditions(tmp_path):
    _, fixture_state = load_journey_inputs(JOURNEY_DIR)
    adapter = FakeAdapter()
    scenario = journey_scenario(tool_failures=("update_appointment",))
    await run(tmp_path, adapter, ScriptedUser(say("hi", "gave_up")), scenario=scenario)
    assert adapter.started_with == (fixture_state.sha256, ("update_appointment",))


async def test_the_saved_scenario_is_the_one_that_ran(tmp_path):
    scenario = journey_scenario(tool_failures=("update_appointment",))
    result = await run(tmp_path, FakeAdapter(), ScriptedUser(say("hi", "gave_up")), scenario=scenario)
    saved = load_journey_scenario(result.episode_dir / "scenario.yaml")
    assert replace(saved, source=scenario.source) == scenario


# -------------------------------------------------------------- stop reasons


async def test_the_user_giving_up_ends_the_episode(tmp_path):
    adapter = FakeAdapter()
    result = await run(tmp_path, adapter, ScriptedUser(say("hi"), say("forget it", "gave_up")))
    assert result.stop_reason == "user_gave_up"
    assert result.record["turns_completed"] == 2
    assert adapter.calls[-2:] == ["retrieve_trace", "release"]


async def test_a_silent_stop_sends_nothing_more(tmp_path):
    adapter = FakeAdapter()
    result = await run(tmp_path, adapter, ScriptedUser(say("hi"), say("", "goal_achieved")))
    assert result.stop_reason == "user_finished"
    assert adapter.calls.count("send_message") == 1
    assert len(transcript(result)) == 2


async def test_the_turn_limit_ends_the_episode(tmp_path):
    adapter = FakeAdapter()
    scenario = replace(journey_scenario(), max_turns=3)
    result = await run(tmp_path, adapter, ScriptedUser(say("again")), scenario=scenario)
    assert result.stop_reason == "turn_limit"
    assert result.record["turns_completed"] == 3
    assert adapter.calls.count("send_message") == 3
    assert adapter.calls[-2:] == ["retrieve_trace", "release"]


async def test_the_time_limit_is_checked_between_turns_and_defaults_to_600_s(tmp_path):
    assert ep.DEFAULT_TIME_LIMIT_S == 600.0
    clock = FakeClock()
    adapter = FakeAdapter(clock=clock, seconds_per_send=250.0)
    result = await run(tmp_path, adapter, ScriptedUser(say("again")), clock=clock)
    # 0 s, 250 s and 500 s start a Turn; at 750 s the next one does not.
    assert result.stop_reason == "time_limit"
    assert result.record["turns_completed"] == 3
    assert result.record["time_limit_s"] == 600.0
    assert result.record["duration_s"] == 750.0
    assert adapter.calls[-2:] == ["retrieve_trace", "release"]


async def test_the_time_limit_is_a_parameter(tmp_path):
    clock = FakeClock()
    adapter = FakeAdapter(clock=clock, seconds_per_send=250.0)
    result = await run(tmp_path, adapter, ScriptedUser(say("again")), clock=clock,
                       time_limit_s=100.0)
    assert (result.stop_reason, result.record["turns_completed"]) == ("time_limit", 1)


async def test_the_agent_claiming_completion_does_not_end_the_conversation(tmp_path):
    class Claims(FakeAdapter):
        def send_message(self, handle, text):
            reply = super().send_message(handle, text)
            return replace(reply, text="Done! Your appointment has been rescheduled.")

    scenario = replace(journey_scenario(), max_turns=2)
    result = await run(tmp_path, Claims(), ScriptedUser(say("hm")), scenario=scenario)
    assert result.stop_reason == "turn_limit"


# -------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    ("error", "agent_fault"),
    [
        (AdapterError("service", "the agent raised", status=500, code="agent_error"), True),
        (AdapterError("transport", "POST timed out after 120.0 s"), False),
    ],
)
async def test_an_adapter_error_mid_conversation_keeps_the_evidence(tmp_path, error, agent_fault):
    adapter = FakeAdapter(fail={("send_message", 3): error})
    result = await run(tmp_path, adapter, ScriptedUser(say("one"), say("two"), say("three")))

    assert result.stop_reason == "adapter_error"
    # The agent may have finished the Turn server-side: the Trace is still fetched.
    assert adapter.calls[-3:] == ["send_message", "retrieve_trace", "release"]
    assert [(l["role"], l["text"]) for l in transcript(result)] == [
        ("user", "one"), ("agent", "reply 1"), ("user", "two"), ("agent", "reply 2"),
        ("user", "three"),  # the failed send survives only here
    ]
    record = episode_json(result)
    assert record["status"] == "complete"
    assert record["turns_completed"] == 2
    assert record["error"] == {
        "source": "adapter", "operation": "send_message", "turn": 3,
        "adapter_error": error.to_dict(),
    }
    assert record["error"]["adapter_error"]["kind"] == error.kind
    assert record["error"]["adapter_error"]["status"] == error.status
    assert record["error"]["adapter_error"]["code"] == error.code
    assert record["error"]["adapter_error"]["agent_fault"] is agent_fault
    assert {p.name for p in result.episode_dir.iterdir()} == EPISODE_FILES


async def test_a_failed_start_is_recorded_with_nothing_to_retrieve_or_release(tmp_path):
    error = AdapterError("transport", "connection refused")
    adapter = FakeAdapter(fail={"start_conversation": error})
    result = await run(tmp_path, adapter, ScriptedUser(say("hi")))

    assert adapter.calls == ["start_conversation"]
    record = episode_json(result)
    assert record["stop_reason"] == "adapter_error"
    assert record["agent"] is None and record["conversation_id"] is None
    assert record["error"]["operation"] == "start_conversation"
    assert record["error"]["adapter_error"] == error.to_dict()
    assert record["retrieval"]["attempted"] is False
    assert record["release"]["attempted"] is False
    assert not (result.episode_dir / "raw_trace.json").exists()
    normalized = NormalizedTrace.from_json(
        (result.episode_dir / "normalized_trace.json").read_text()
    )
    assert (normalized.evidence.messages, normalized.evidence.actions) == (
        "unavailable", "unavailable"
    )
    assert normalized.evidence.reasons == ("no conversation was started",)
    assert normalized.messages == () and normalized.actions == ()


@pytest.mark.parametrize(
    "failure", [LLMError("model refused the request"), AssertionError("a broken double")]
)
async def test_a_simulator_error_mid_conversation_keeps_the_evidence(tmp_path, failure):
    adapter = FakeAdapter()
    result = await run(tmp_path, adapter, ScriptedUser(say("one"), say("two"), failure))

    assert result.stop_reason == "simulator_error"
    assert adapter.calls == [
        "start_conversation", "send_message", "send_message", "retrieve_trace", "release",
    ]
    assert len(transcript(result)) == 4
    record = episode_json(result)
    assert record["error"] == {
        "source": "simulated_user", "turn": 3,
        "type": type(failure).__name__, "message": str(failure),
    }
    assert record["retrieval"]["evidence"]["actions"] == "available"
    assert {p.name for p in result.episode_dir.iterdir()} == EPISODE_FILES


async def test_a_turn_that_neither_speaks_nor_stops_is_a_simulator_error(tmp_path):
    result = await run(tmp_path, FakeAdapter(), ScriptedUser(say("")))
    assert result.stop_reason == "simulator_error"
    assert "unusable Simulated-user turn" in result.record["error"]["message"]


async def test_a_retrieval_gap_is_recorded_and_the_episode_still_completes(tmp_path):
    adapter = FakeAdapter(retrieval_gap=True)
    result = await run(tmp_path, adapter, ScriptedUser(say("one"), say("bye", "goal_achieved")))

    assert result.stop_reason == "user_finished"
    assert adapter.calls[-2:] == ["retrieve_trace", "release"]
    assert not (result.episode_dir / "raw_trace.json").exists()
    assert {p.name for p in result.episode_dir.iterdir()} == EPISODE_FILES - {"raw_trace.json"}
    normalized = NormalizedTrace.from_json(
        (result.episode_dir / "normalized_trace.json").read_text()
    )
    assert (normalized.evidence.messages, normalized.evidence.actions) == (
        "partial", "unavailable"
    )
    record = episode_json(result)
    assert record["status"] == "complete"
    assert record["retrieval"] == {
        "attempted": True, "raw_trace_saved": False,
        "error": "retrieval failed: transport: connection refused",
        "evidence": normalized.evidence.to_dict(),
    }


async def test_a_release_failure_is_recorded_and_changes_nothing_else(tmp_path):
    error = AdapterError("service", "gone", status=404, code="unknown_conversation")
    adapter = FakeAdapter(fail={"release": error})
    result = await run(tmp_path, adapter, ScriptedUser(say("bye", "goal_achieved")))
    assert result.stop_reason == "user_finished"
    assert result.record["release"] == {"attempted": True, "error": error.to_dict()}
    assert (result.episode_dir / "raw_trace.json").exists()


@pytest.mark.parametrize(
    "fail",
    [
        {("send_message", 2): AdapterError("transport", "timed out")},
        {("send_message", 2): RuntimeError("a harness bug")},
        {"retrieve_trace": RuntimeError("retrieve must not raise, and did")},
    ],
)
async def test_retrieve_comes_before_release_on_every_path(tmp_path, fail):
    adapter = FakeAdapter(fail=fail)
    try:
        await run(tmp_path, adapter, ScriptedUser(say("one"), say("two"), say("x", "gave_up")))
    except RuntimeError:
        pass
    assert adapter.calls.count("retrieve_trace") == 1
    assert adapter.calls.count("release") == 1
    assert adapter.calls.index("retrieve_trace") < adapter.calls.index("release")
    assert adapter.calls[-1] == "release"


async def test_an_unexpected_failure_keeps_what_was_written_and_marks_the_record_aborted(tmp_path):
    adapter = FakeAdapter(fail={("send_message", 2): RuntimeError("a harness bug")})
    with pytest.raises(RuntimeError, match="a harness bug"):
        await run(tmp_path, adapter, ScriptedUser(say("one"), say("two")))

    episode_dir = tmp_path / "episode"
    assert adapter.calls[-2:] == ["retrieve_trace", "release"]
    record = json.loads((episode_dir / "episode.json").read_text())
    assert record["status"] == "aborted"
    assert record["stop_reason"] is None
    assert record["error"] == {
        "source": "harness", "type": "RuntimeError", "message": "a harness bug",
    }
    lines = (episode_dir / "transcript.jsonl").read_text().splitlines()
    assert [json.loads(l)["text"] for l in lines] == ["one", "reply 1", "two"]
    assert (episode_dir / "normalized_trace.json").exists()


# ------------------------------------------------------------------ requests


async def test_an_existing_episode_is_never_overwritten(tmp_path):
    await run(tmp_path, FakeAdapter(), ScriptedUser(say("bye", "goal_achieved")))
    before = (tmp_path / "episode" / "transcript.jsonl").read_text()
    adapter = FakeAdapter()
    with pytest.raises(ep.EpisodeError, match="never overwritten"):
        await run(tmp_path, adapter, ScriptedUser(say("again", "goal_achieved")))
    assert adapter.calls == []
    assert (tmp_path / "episode" / "transcript.jsonl").read_text() == before


async def test_a_non_positive_time_limit_is_refused_before_any_write(tmp_path):
    with pytest.raises(ep.EpisodeError, match="time_limit_s"):
        await run(tmp_path, FakeAdapter(), ScriptedUser(say("hi")), time_limit_s=0)
    assert not (tmp_path / "episode").exists()


def test_the_stop_reasons_are_the_design_notes_closed_set():
    assert ep.EPISODE_STOP_REASONS == (
        "user_finished", "user_gave_up", "turn_limit", "time_limit",
        "adapter_error", "simulator_error",
    )
