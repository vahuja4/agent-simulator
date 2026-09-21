"""A whole Journey Run on doubles, for the command and report tests
(session 08). The Scenarios are really synthesized (stub narrative) so the set
passes its provenance check; the agent, the Simulated user and the Judge are
doubles. Nothing here talks to a network or a model.

Each Scenario of the set is given a *behaviour* by position, in the order
``run`` plays them (sorted accepted file names):

    pass              identify, offer, confirm, update — the expected outcome
    padded            the same after two Turns of small talk (other ids)
    unconfirmed       slot searched for and booked in one Turn (Assertion fails)
    never_offered     books the target slot without ever searching for slots
    gave_up           the customer gives up after the offer (task_incomplete)
    agent_error       the agent raises on the first message
    transport         the service stops answering on the first message
    simulator_error   the Simulated user raises
    interrupt         the Simulated user is cancelled, as Ctrl-C would
"""

from __future__ import annotations

import asyncio
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentsim.adapters.conversation import (
    AdapterError,
    ConversationAdapter,
    ConversationHandle,
)
from agentsim.journey.scenario import JourneyScenario, load_journey_scenario
from agentsim.llm import LLMError
from scenario_synthesis import journey_synthesis as js
from scripts import journey_harness as jh
from tests.journey_trace_builder import TraceBuilder, find_slots, lookup, update
from tests.test_journey_evaluation import JudgeDouble, ScriptedUser, TraceAdapter, say

JOURNEY_DIR = Path("journeys/appointment_rescheduling")
SERVICE_URL = "http://127.0.0.1:8765"
AGENT_RAISED = AdapterError("service", "the agent raised", 500, "agent_error")
NO_ANSWER = AdapterError("transport", "timed out after 120.0 s")


def synthesize(root: Path, count: int, *, set_id: str = "set-1") -> Path:
    result = js.synthesize_set(
        JOURNEY_DIR, count=count, set_id=set_id, provider=js.StubNarrativeProvider(),
        seed=0, output_root=root / "sets",
    )
    assert not result.shortfall
    return result.set_dir


def saved_scenarios(set_dir: Path) -> list[JourneyScenario]:
    return [load_journey_scenario(p) for p in sorted((set_dir / "accepted").glob("*.yaml"))]


def conversation(scenario: JourneyScenario, behaviour: str) -> TraceBuilder:
    """The hand-built conversation of one behaviour, on the Scenario's own
    Fixture bindings so the Assertions judge the behaviour and nothing else."""
    appointment, slot = scenario.fixture.appointment_id, scenario.fixture.target_slot_ids[0]
    fails = bool(scenario.fixture.tool_failures)
    done = "I'm sorry, the update failed; nothing was changed." if fails else "Done, it is moved."
    builder = TraceBuilder()
    if behaviour == "padded":
        builder.turn("Hello?", "Hello, how can I help?")
        builder.turn("Are you still there?", "Yes. What do you need?")
    builder.turn("I need to move my appointment.", "I found it. When suits you?",
                 lookup(appointment))
    if behaviour == "never_offered":
        return builder.turn("Any later time.", done, update(appointment, slot, failed=fails))
    if behaviour == "unconfirmed":
        return builder.turn("Any later time.", done, find_slots(appointment, slot),
                            update(appointment, slot, failed=fails))
    builder.turn("Any later time.", "There is one later slot. Shall I move it there?",
                 find_slots(appointment, slot))
    if behaviour == "gave_up":
        return builder
    return builder.turn("Yes, please move it.", done, update(appointment, slot, failed=fails))


class ScenarioJudge(JudgeDouble):
    """Rules ``pass`` except for the criteria named per Scenario id."""

    def __init__(self, failing: dict[str, tuple[str, ...]] | None = None):
        super().__init__()
        self.by_scenario = dict(failing or {})

    async def judge_episode(self, scenario, trace):
        self.failing = self.by_scenario.get(scenario.scenario_id, ())
        return await super().judge_episode(scenario, trace)


class SequenceAdapter(ConversationAdapter):
    """Answers ``run``'s probe conversation, then hands each Episode to the
    next adapter in line. It refuses a second conversation while one is open:
    a Run is sequential."""

    def __init__(self, adapters: list[ConversationAdapter], *, agent: str = "stub"):
        self.adapters, self.agent = list(adapters), agent
        self.current: ConversationAdapter | None = None
        self.probed = self.open = False

    def start_conversation(self, *, fixture_state, tool_failures=()):
        assert not self.open, "a conversation was started while another was open"
        if not self.probed:
            self.probed = self.open = True
            return ConversationHandle("probe", fixture_state.sha256, self.agent)
        self.current = self.adapters.pop(0)
        handle = self.current.start_conversation(
            fixture_state=fixture_state, tool_failures=tool_failures
        )
        self.open = True
        return handle

    def send_message(self, handle, text):
        return self.current.send_message(handle, text)

    def retrieve_trace(self, handle):
        return self.current.retrieve_trace(handle)

    def release(self, handle):
        self.open = False
        if handle.conversation_id != "probe":
            self.current.release(handle)


@dataclass
class PlayedRun:
    status: int | None
    run_dir: Path
    output: str
    scenarios: list[JourneyScenario]
    adapter: SequenceAdapter
    judge: ScenarioJudge
    raised: BaseException | None = None
    run_keys: dict[str, str] = field(default_factory=dict)  # scenario id -> run key

    def episode_dir(self, index: int) -> Path:
        return self.run_dir / "runs" / self.run_keys[self.scenarios[index].scenario_id]


def _double_for(scenario: JourneyScenario, behaviour: str) -> tuple[Any, Any]:
    """``(adapter, Simulated user)`` for one Episode."""
    if behaviour in ("agent_error", "transport"):
        error = AGENT_RAISED if behaviour == "agent_error" else NO_ANSWER
        trace = conversation(scenario, "pass").build()
        return TraceAdapter(trace, fail={("send", 1): error}), ScriptedUser(say("Hello."))
    if behaviour == "simulator_error":
        trace = conversation(scenario, "pass").build()
        return TraceAdapter(trace), ScriptedUser(LLMError("the model did not answer"))
    if behaviour == "interrupt":
        trace = conversation(scenario, "pass").build()
        return TraceAdapter(trace), ScriptedUser(
            say(trace.messages[0].text), asyncio.CancelledError()
        )
    trace = conversation(scenario, behaviour).build(
        tool_failures=scenario.fixture.tool_failures
    )
    texts = [m.text for m in trace.messages if m.role == "user"]
    stop = "gave_up" if behaviour == "gave_up" else "goal_achieved"
    script = [say(text) for text in texts[:-1]] + [say(texts[-1], stop)]
    return TraceAdapter(trace), ScriptedUser(*script)


def play_run(
    root: Path,
    behaviours: list[str],
    *,
    run_id: str = "run-1",
    judge_failing: dict[int, tuple[str, ...]] | None = None,
    set_dir: Path | None = None,
    unbuildable: dict[int, Exception] | None = None,
    **overrides: Any,
) -> PlayedRun:
    """Synthesize ``len(behaviours)`` Scenarios and ``run`` them on doubles.
    ``unbuildable`` makes building the Simulated user raise for those Scenarios,
    which therefore never start a conversation."""
    set_dir = set_dir or synthesize(root, len(behaviours))
    scenarios = saved_scenarios(set_dir)
    unbuildable = {scenarios[i].scenario_id: e for i, e in (unbuildable or {}).items()}
    doubles = [_double_for(s, b) for s, b in zip(scenarios, behaviours, strict=True)]
    users = {s.scenario_id: user for s, (_, user) in zip(scenarios, doubles)}
    adapter = SequenceAdapter(
        [a for s, (a, _) in zip(scenarios, doubles) if s.scenario_id not in unbuildable]
    )

    def build_user(scenario: JourneyScenario) -> Any:
        if scenario.scenario_id in unbuildable:
            raise unbuildable[scenario.scenario_id]
        return users[scenario.scenario_id]

    judge = ScenarioJudge(
        {scenarios[i].scenario_id: failing for i, failing in (judge_failing or {}).items()}
    )
    out = io.StringIO()
    arguments = dict(
        journey_dir=JOURNEY_DIR, scenarios_dir=set_dir, service_url=SERVICE_URL,
        run_id=run_id, output_root=root / "journey_runs", out=out, adapter=adapter,
        simulated_user_factory=build_user, judge=judge,
    )
    arguments.update(overrides)
    status, raised = None, None
    try:
        status = jh.run_command(**arguments)
    except BaseException as error:  # the interrupt behaviour propagates, as it must
        raised = error
    run_dir = Path(arguments["output_root"]) / run_id
    played = PlayedRun(status, run_dir, out.getvalue(), scenarios, adapter, judge, raised)
    if (run_dir / "manifest.json").is_file():
        manifest = json.loads((run_dir / "manifest.json").read_text())
        played.run_keys = {r["scenario"]: key for key, r in manifest["runs"].items()}
    return played
