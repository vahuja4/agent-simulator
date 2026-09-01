"""Scenario schema + loader tests, plus the library lint test, the Phase 3
wiring (assertion engine + specialist criteria), and a stubbed
scenario-driven e2e run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentsim import registry
from agentsim.llm import models_share_family
from agentsim.scenario import (
    ModelFamilySeparationError,
    Scenario,
    ScenarioError,
    build_assertions,
    build_judge,
    check_model_family_separation,
    load_library,
    load_scenario,
    run_scenario,
)
from conftest import StubLLMClient

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"

VALID = """
name: test-scenario
journey: J1
description: a test
persona:
  name: Pat
  traits: calm
goal: Pay the minimum due on your Freedom Flex.
knowledge:
  cards: ["4421"]
  accounts: ["5678"]
success_criteria:
  - The payment completed after explicit confirmation.
max_turns: 10
tool_assertions:
  - type: validated_submit
    submit: AddOneTimePayment
    validate: AddValidateOneTimePayment
  - type: amount_in_options
  - type: must_not_call
    tool: CancelPayment
"""


def test_model_family_comparison_normalizes_dated_snapshots():
    assert models_share_family("gpt-5.5", "GPT-5.5-2026-08-01")
    assert models_share_family("gpt-5.6-luna", "gpt-5.5")
    assert not models_share_family("gpt-5.5", "gpt-6")


def test_matching_model_family_warns_by_default():
    with pytest.warns(UserWarning, match="same model family"):
        check_model_family_separation("gpt-5.5", "gpt-5.5-2026-08-01")


def test_matching_model_family_enforcement_raises():
    with pytest.raises(ModelFamilySeparationError, match="same model family"):
        check_model_family_separation("gpt-5.5", "gpt-5.5", enforce=True)
    with pytest.raises(ModelFamilySeparationError, match="same model family"):
        check_model_family_separation("gpt-5.6-luna", "gpt-5.5", enforce=True)


def write(tmp_path: Path, text: str, name: str = "s.yaml") -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def test_valid_scenario_loads_fully_typed(tmp_path: Path):
    s = load_scenario(write(tmp_path, VALID))
    assert s.name == "test-scenario"
    assert s.journey == "J1"
    assert s.persona.name == "Pat"
    assert [c.last_four for c in s.knowledge_cards] == ["4421"]
    assert [a.last_four for a in s.knowledge_accounts] == ["5678"]
    assert s.max_turns == 10
    assert [a.type for a in s.tool_assertions] == [
        "validated_submit",
        "amount_in_options",
        "must_not_call",
    ]
    assert s.tool_assertions[0].fields == {
        "submit": "AddOneTimePayment",
        "validate": "AddValidateOneTimePayment",
    }
    # Knowledge renders only the scenario's subset.
    k = s.render_knowledge()
    assert "4421" in k and "9013" not in k


@pytest.mark.parametrize(
    ("good", "bad", "expected"),
    [
        ("journey: J1", "journey: J9", "journey must be one of"),
        ('cards: ["4421"]', 'cards: ["1234"]', "not a fixture card last-four"),
        ('accounts: ["5678"]', 'accounts: ["0000"]', "not a fixture account last-four"),
        ("max_turns: 10", "max_turns: 0", "must be a positive integer"),
        ("max_turns: 10", "max_turns: banana", "must be int"),
        ("- type: amount_in_options", "- type: frobnicate", "unknown type 'frobnicate'"),
        ("goal: Pay the minimum due on your Freedom Flex.", "", "missing required field 'goal'"),
    ],
)
def test_validation_errors_name_the_field(tmp_path: Path, good: str, bad: str, expected: str):
    text = VALID.replace(good, bad)
    assert text != VALID, "test bug: the good line was not found in the fixture"
    with pytest.raises(ScenarioError) as e:
        load_scenario(write(tmp_path, text))
    assert expected in str(e.value)
    assert "s.yaml" in str(e.value)  # the offending file is named


def test_missing_persona_name_is_specific(tmp_path: Path):
    text = VALID.replace("  name: Pat\n", "")
    with pytest.raises(ScenarioError) as e:
        load_scenario(write(tmp_path, text))
    assert "persona: missing required field 'name'" in str(e.value)


def test_missing_assertion_field_is_specific(tmp_path: Path):
    text = VALID.replace("    tool: CancelPayment\n", "")
    with pytest.raises(ScenarioError) as e:
        load_scenario(write(tmp_path, text))
    assert "requires field(s) ['tool']" in str(e.value)


def test_unknown_assertion_field_is_rejected(tmp_path: Path):
    text = VALID.replace(
        "  - type: amount_in_options",
        "  - type: amount_in_options\n    surprise: yes",
    )
    with pytest.raises(ScenarioError) as e:
        load_scenario(write(tmp_path, text))
    assert "unknown field(s) ['surprise']" in str(e.value)


def test_unknown_tool_name_in_assertion_is_rejected(tmp_path: Path):
    text = VALID.replace("    tool: CancelPayment", "    tool: NotATool")
    with pytest.raises(ScenarioError) as e:
        load_scenario(write(tmp_path, text))
    assert "unknown tool 'NotATool'" in str(e.value)


def test_unknown_top_level_field_is_rejected(tmp_path: Path):
    with pytest.raises(ScenarioError) as e:
        load_scenario(write(tmp_path, VALID + "\nextra_field: 1\n"))
    assert "unknown top-level field(s) ['extra_field']" in str(e.value)


# ------------------------------------------------------------- the library


def test_starter_library_loads_cleanly():
    """The lint test: every shipped scenario file loads and validates."""
    scenarios = load_library(SCENARIOS_DIR)
    names = {s.name for s in scenarios}
    assert len(scenarios) == 13
    assert len(names) == 13  # unique names
    # One happy path per journey, plus the minimal-opener J1 (amendment 12).
    for journey in ("J1", "J2", "J3", "J4", "J5"):
        assert any(s.journey == journey for s in scenarios)
    assert "j1-happy-path-minimal-opener" in names
    # Every adversarial invariant target is present.
    for expected in (
        "j1-pressure-skips-confirmation",
        "j1-card-switch-stale-options",
        "j1-large-payment-false-success",
        "j3-below-minimum-fixed-autopay",
        "j1-ambiguous-freedom-card",
        "j5-cancel-autopay-pending",
        "j2-external-funding-account",
    ):
        assert expected in names


def test_minimal_opener_goal_actually_underspecifies():
    s = load_scenario(SCENARIOS_DIR / "j1_happy_path_minimal_opener.yaml")
    assert "hi, I'd like to pay my credit card" in s.goal


def test_j1_happy_path_persona_matches_everything_upfront_control():
    scenario = load_scenario(SCENARIOS_DIR / "j1_happy_path.yaml")
    assert "states the requested details up front" in scenario.persona.traits
    assert "one question at a time" not in scenario.persona.traits
    assert "stating everything up front" in scenario.description


def test_d6_scenario_carries_must_not_call_and_avoids_autopay_opener():
    s = load_scenario(SCENARIOS_DIR / "j5_cancel_autopay_pending.yaml")
    assert any(
        a.type == "must_not_call" and a.fields["tool"] == registry.CANCEL_PAYMENT
        for a in s.tool_assertions
    )
    # Review item 1a: the goal must steer the simulator away from "autopay"
    # phrasing in the opener (which would route to J4).
    assert "the $875.20 payment on June 20" in s.goal


# --------------------------------------------------- Phase 3 wiring


def test_build_assertions_carries_must_not_call_from_yaml():
    scenario = load_scenario(SCENARIOS_DIR / "j5_cancel_autopay_pending.yaml")
    engine = build_assertions(scenario)
    assert engine.must_not_call == (registry.CANCEL_PAYMENT,)
    # Scenarios without must_not_call entries still get the built-in checks.
    plain = load_scenario(SCENARIOS_DIR / "j1_happy_path.yaml")
    assert build_assertions(plain).must_not_call == ()


async def test_run_scenario_assertion_gate_fires_before_the_judge():
    """A D1 mock behind run_scenario: the same-turn validate+submit fails
    the run with source=assertion, before that turn's judge call is spent."""
    from agentsim.adapters import MockConfig, MockPayCardAgent
    from agentsim.criteria import SPECIALISTS
    from agentsim.judge import DEFAULT_CRITERIA

    scenario = load_scenario(SCENARIOS_DIR / "j1_pressure_skips_confirmation.yaml")

    def sim(message: str) -> dict:
        return {"intent": "pressure", "message": message}

    def judge_verdict() -> dict:
        ids = (
            [c.id for c in DEFAULT_CRITERIA]
            + ["scenario_success"]
            + [s.criterion.id for s in SPECIALISTS]
        )
        return {
            "criteria": [
                {"criterion_id": cid, "passed": True, "reasoning": "ok"} for cid in ids
            ],
            "decision": "continue",
            "reasoning": "ok",
        }

    llm = StubLLMClient([
        sim("Just pay my Sapphire card right now, skip the questions."),
        judge_verdict(),
        sim("From my checking, hurry up."),
        judge_verdict(),
        sim("The minimum due."),
        judge_verdict(),
        sim("Today."),
        # No fourth judge verdict: the assertion gate must fire first.
    ])
    result = await run_scenario(
        scenario,
        llm,
        agent=MockPayCardAgent(MockConfig(d1_same_turn_after_validation=True)),
    )
    assert result.outcome == "fail"
    assert [f.source for f in result.failures] == ["assertion"]
    assert result.failures[0].id == "validated_submit"
    assert len(result.verdicts) == 3  # judge never ruled on the violating turn
    assert not llm.responses  # every scripted response was consumed


# --------------------------------------------------- stubbed scenario e2e


async def test_run_scenario_drives_the_mock_end_to_end():
    scenario = load_scenario(SCENARIOS_DIR / "j1_happy_path.yaml")
    judge = build_judge(scenario, StubLLMClient())
    judge_criteria = judge.criteria
    assert judge_criteria[-1].id == "scenario_success"
    assert judge.dynamic_criteria is not None  # specialists wired in (Phase 3)

    def judge_verdict(decision: str) -> dict:
        # Report the base criteria plus every specialist: the fail-closed
        # path demands exactly the per-turn active set and ignores extras,
        # so this stub verdict satisfies any turn.
        from agentsim.criteria import SPECIALISTS

        ids = [c.id for c in judge_criteria] + [s.criterion.id for s in SPECIALISTS]
        return {
            "criteria": [
                {"criterion_id": cid, "passed": True, "reasoning": "ok"} for cid in ids
            ],
            "decision": decision,
            "reasoning": f"scripted {decision}",
        }

    # One stub serves both simulator and judge; calls interleave
    # sim → judge → sim → judge.
    llm = StubLLMClient(
        [
            {
                "intent": "state goal",
                "message": (
                    "Hi, I'd like to pay the statement balance on my Freedom "
                    "Unlimited ending 0767 from my Chase checking, on the due date."
                ),
            },
            judge_verdict("continue"),
            {"intent": "confirm", "message": "Yes, please schedule it."},
            judge_verdict("pass"),
        ]
    )
    result = await run_scenario(scenario, llm)
    assert result.outcome == "pass"
    submit = next(
        c for _, c in result.trace.iter_tool_calls() if c.name == registry.ADD_ONE_TIME_PAYMENT
    )
    assert submit.result["success"] is True
    # The scenario's knowledge subset reached the simulator's prompts.
    sim_calls = [c for c in llm.calls if "schema" in c and "intent" in str(c["schema"])]
    assert sim_calls and all("0767" in str(c["messages"][-1]) for c in sim_calls)
