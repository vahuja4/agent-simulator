"""The Simulated user on the Journey-definition path: what it is told, what it
is never told, and how it says it has stopped. Offline — the model is a double.

The instructions are designed, not empirically validated; nothing here is a
Persona-fidelity check.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agentsim.journey import checks
from agentsim.journey import simulated_user as su
from agentsim.journey.definition import load_journey_inputs
from agentsim.journey.scenario import GroundedFact, load_journey_scenario
from agentsim.llm import LLMError
from agentsim.simulator import Persona, UserSimulator
from agentsim.types import Message
from scenario_synthesis import journey_synthesis as js
from tests.journey_trace_builder import journey_scenario

JOURNEY_DIR = Path("journeys/appointment_rescheduling")
AGENT_ROLE = "an appointment-scheduling assistant for a fictional dental clinic"


def _synthesized(tmp_path, complication, *, tool_failures=()):
    """A real synthesized Scenario (stub narrative) with this Complication."""
    result = js.synthesize_set(
        JOURNEY_DIR, count=1, set_id="set-1", provider=js.StubNarrativeProvider(),
        settings=js.VariationSettings(
            complications=(complication,), tool_failure_conditions=(tuple(tool_failures),)
        ),
        output_root=tmp_path / complication,
    )
    return load_journey_scenario(result.accepted[0])


async def _prompt(stub_llm, scenario, history=()):
    """Everything the model is shown for one turn."""
    stub_llm.push({"intent": "state goal", "message": "hi", "stop_reason": "none"})
    user = su.JourneySimulatedUser.for_scenario(stub_llm, scenario, agent_role=AGENT_ROLE)
    await user.next_turn(list(history))
    call = stub_llm.calls[-1]
    return "\n".join([call["system"], *(m["content"] for m in call["messages"])])


# ------------------------------------------------------ what it is never told


async def test_the_prompt_holds_no_check_outcome_tool_failure_or_fact_path(stub_llm, tmp_path):
    scenario = _synthesized(tmp_path, "none", tool_failures=("update_appointment",))
    assert scenario.expected_outcome == checks.OUTCOME_UPDATE_FAILED_REPORTED
    prompt = await _prompt(stub_llm, scenario, [Message("user", "hi"), Message("assistant", "hello")])

    journey, _ = load_journey_inputs(JOURNEY_DIR)
    assert len(journey.judge_criteria) == 5
    for check_id in (*checks.ASSERTIONS, *journey.judge_criterion_ids):
        assert check_id not in prompt
    for criterion in journey.judge_criteria:
        assert criterion.statement not in prompt
    for outcome in checks.OUTCOME_IDS:
        assert outcome not in prompt
    for withheld in ("tool_failures", "update_appointment", "update_failed", "expected_outcome"):
        assert withheld not in prompt
    binding = scenario.fixture
    for fact in scenario.grounded_facts:
        assert fact.path not in prompt
    for fixture_id in (binding.customer_id, binding.appointment_id, *binding.target_slot_ids):
        assert fixture_id not in prompt


async def test_it_is_told_its_persona_goal_and_the_agent_role_not_the_payments_wording(stub_llm):
    scenario = journey_scenario()
    prompt = await _prompt(stub_llm, scenario)
    assert "Maya Okafor" in prompt and "polite and brief" in prompt
    assert scenario.goal in prompt
    assert AGENT_ROLE in prompt
    for payments in ("Chase", "payment", "card", "###STOP###"):
        assert payments not in prompt


async def test_instructions_that_would_fight_an_existing_persona_are_not_carried_over(stub_llm):
    """The conflict check of docs/solutions/journey-episode-loop-and-simulated-user.md:
    a high Knowledge level Persona states a rule unprompted, a persistent one
    re-attempts after a refusal, a false-premise one holds a mistaken belief."""
    prompt = await _prompt(stub_llm, journey_scenario())
    assert "never explain policies" not in prompt
    assert "Reveal details only when" not in prompt
    assert "pushed as far as your personality would" in prompt
    assert "hold a mistaken belief or use a wrong word for something real" in prompt


# ----------------------------------------------------------- knowledge text


def test_knowledge_renders_values_under_customer_facing_headings():
    scenario = replace(
        journey_scenario(),
        grounded_facts=(
            GroundedFact("customers.C-100.name", "Maya Okafor"),
            GroundedFact("appointments.A-1001.provider", "Dr. Alvarez"),
            GroundedFact("appointments.A-1001.confirmation_code", "HSD-4821"),
            GroundedFact("appointments.A-1001.start", "2026-10-06T10:00:00"),
            GroundedFact("slots.S-101.start", "2026-10-09T11:00:00"),
        ),
    )
    assert su.render_journey_knowledge(scenario) == (
        "About you:\n"
        "- name: Maya Okafor\n"
        "The appointment you want to move:\n"
        "- provider: Dr. Alvarez\n"
        "- confirmation code: HSD-4821\n"
        "- date and time: Tuesday 6 October 2026 at 10:00\n"
        "The new time you want:\n"
        "- date and time: Friday 9 October 2026 at 11:00"
    )


@pytest.mark.parametrize(
    ("complication", "other_collection", "other_fields"),
    [
        # the provider the customer wrongly believes in
        ("false-premise", "slots", {"provider"}),
        # the slot asked for first, before the correction
        ("mid-conversation-correction", "slots", {"start", "provider"}),
        # the customer's other appointment for the same service
        ("ambiguous-reference", "appointments", {"start", "provider"}),
    ],
)
def test_knowledge_keeps_the_other_entity_facts_a_complication_needs(
    tmp_path, complication, other_collection, other_fields
):
    scenario = _synthesized(tmp_path, complication)
    assert scenario.complication == complication
    binding = scenario.fixture
    own = (binding.customer_id, binding.appointment_id, *binding.target_slot_ids)
    others = [f for f in scenario.grounded_facts if f.path.split(".")[1] not in own]
    assert {f.path.split(".")[0] for f in others} == {other_collection}
    assert {f.path.split(".")[2] for f in others} == other_fields

    knowledge = su.render_journey_knowledge(scenario)
    heading = (
        "Another appointment you know about:" if other_collection == "appointments"
        else "Another appointment time you know about:"
    )
    other_section = knowledge.split(heading)[1]
    for fact in others:
        assert su._render_value(fact.value) in other_section
    for fact in scenario.grounded_facts:
        assert fact.path not in knowledge
        assert su._render_value(fact.value) in knowledge


def test_a_date_time_is_rendered_as_written_never_converted():
    assert su._render_value("2026-10-13T15:30:00") == "Tuesday 13 October 2026 at 15:30"
    assert su._render_value("2026-10-13T15:30:00-04:00") == "Tuesday 13 October 2026 at 15:30"
    assert su._render_value("HSD-4821") == "HSD-4821"


# ------------------------------------------------------ confirmation gate


def test_the_confirmation_gate_text_equals_the_payments_simulator(stub_llm):
    payments = UserSimulator(stub_llm, persona=Persona("A", "b"), goal="g", knowledge="k")
    journey = su.JourneySimulatedUser.for_scenario(
        stub_llm, journey_scenario(), agent_role=AGENT_ROLE
    )
    assert su.CONFIRMATION_GATE_PARAGRAPH in payments._system_prompt()
    assert su.CONFIRMATION_GATE_PARAGRAPH in journey._system_prompt()
    assert su.CONFIRMATION_GATE_REMINDER in payments._turn_context()["content"]
    assert su.CONFIRMATION_GATE_REMINDER in journey._turn_context()["content"]
    # The whole gate, not a fragment of it: from its first sentence to the
    # sentence before the payments stop rule.
    assert su.CONFIRMATION_GATE_PARAGRAPH.startswith("If the assistant asks a yes/no")
    assert su.CONFIRMATION_GATE_PARAGRAPH.endswith("for the answer.")
    assert f"{su.CONFIRMATION_GATE_PARAGRAPH} You may only stop" in payments._system_prompt()


# ------------------------------------------------------------ turn handling


@pytest.mark.parametrize(
    ("stop_reason", "stop"), [("none", False), ("goal_achieved", True), ("gave_up", True)]
)
async def test_a_turn_carries_its_stop_reason(stub_llm, stop_reason, stop):
    stub_llm.push({"intent": "confirm", "message": "```\nYes, go ahead.\n```",
                   "stop_reason": stop_reason})
    user = su.JourneySimulatedUser.for_scenario(stub_llm, journey_scenario(), agent_role=AGENT_ROLE)
    turn = await user.next_turn([])
    assert (turn.intent, turn.text, turn.stop, turn.stop_reason) == (
        "confirm", "Yes, go ahead.", stop, stop_reason
    )
    assert stub_llm.calls[0]["schema"]["properties"]["stop_reason"]["enum"] == [
        "none", "goal_achieved", "gave_up"
    ]


async def test_history_is_role_reversed_after_a_journey_opening_line(stub_llm):
    stub_llm.push({"intent": "answer", "message": "ok", "stop_reason": "none"})
    user = su.JourneySimulatedUser.for_scenario(stub_llm, journey_scenario(), agent_role=AGENT_ROLE)
    await user.next_turn([Message("user", "hi"), Message("assistant", "hello")])
    messages = stub_llm.calls[0]["messages"]
    assert AGENT_ROLE in messages[0]["content"]
    assert messages[1:3] == [
        {"role": "assistant", "content": "hi"}, {"role": "user", "content": "hello"},
    ]
    assert messages[-1]["role"] == "system"


@pytest.mark.parametrize(
    "response",
    [
        {"intent": "x", "message": "hi", "stop_reason": "finished"},
        {"intent": "x", "message": "hi"},
        {"intent": "x", "message": "  ", "stop_reason": "none"},
    ],
)
async def test_an_unusable_model_answer_is_an_llm_error(stub_llm, response):
    stub_llm.push(response)
    user = su.JourneySimulatedUser.for_scenario(stub_llm, journey_scenario(), agent_role=AGENT_ROLE)
    with pytest.raises(LLMError):
        await user.next_turn([])


async def test_a_silent_stop_is_allowed(stub_llm):
    stub_llm.push({"intent": "stop", "message": "", "stop_reason": "gave_up"})
    user = su.JourneySimulatedUser.for_scenario(stub_llm, journey_scenario(), agent_role=AGENT_ROLE)
    turn = await user.next_turn([])
    assert (turn.text, turn.stop_reason) == ("", "gave_up")


# ------------------------------------------------------------ model wiring


def test_missing_model_configuration_fails_in_one_line_before_any_call(monkeypatch):
    journey, _ = load_journey_inputs(JOURNEY_DIR)
    built = []
    monkeypatch.setattr(su, "OpenAILLM", lambda model: built.append(model))

    monkeypatch.delenv(su.SIMULATOR_MODEL_ENV, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    with pytest.raises(su.SimulatorConfigError) as missing_model:
        su.live_simulated_user(journey_scenario(), journey)
    assert su.SIMULATOR_MODEL_ENV in str(missing_model.value)
    assert "\n" not in str(missing_model.value)

    monkeypatch.setenv(su.SIMULATOR_MODEL_ENV, "some-model")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(su.SimulatorConfigError) as missing_key:
        su.live_simulated_user(journey_scenario(), journey)
    assert "OPENAI_API_KEY" in str(missing_key.value)
    assert "\n" not in str(missing_key.value)
    assert built == []


def test_the_configured_model_reaches_the_client_and_the_episode_record(monkeypatch):
    journey, _ = load_journey_inputs(JOURNEY_DIR)
    built = []
    monkeypatch.setattr(su, "OpenAILLM", lambda model: built.append(model) or object())
    monkeypatch.setenv(su.SIMULATOR_MODEL_ENV, "env-model")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")

    assert su.live_simulated_user(journey_scenario(), journey).model == "env-model"
    user = su.live_simulated_user(journey_scenario(), journey, model="flag-model")
    assert user.model == "flag-model"
    assert user.agent_role == journey.agent_role
    assert built == ["env-model", "flag-model"]
