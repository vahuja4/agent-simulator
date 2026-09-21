"""The Scenario seam: a Journey Scenario loads and is checked without
``fixtures.paycard``, and neither loader accepts the other path's files.

Loading and checking a Scenario is validation only. It is not Qualification
or Admission, and the file says so (``synthesis.qualification: none``).
"""

import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from agentsim.batch import BatchRunSpec
from agentsim.journey import checks
from agentsim.journey.definition import load_journey_inputs
from agentsim.journey.scenario import (
    ARCHETYPE_IDS,
    KNOWLEDGE_LEVELS,
    JourneyScenarioError,
    check_against_inputs,
    load_journey_scenario,
)

JOURNEY_DIR = Path("journeys/appointment_rescheduling")
SCENARIO_ID = "synth-appointment-rescheduling-0123456789ab"

SCENARIO_RAW = {
    "schema_version": 1,
    "scenario_id": SCENARIO_ID,
    "journey": "appointment-rescheduling",
    "description": "A customer moves a dental cleaning to later in the week.",
    "persona": {
        "archetype": "cooperative",
        "name": "Maya Okafor",
        "traits": "polite, brief, answers what is asked",
    },
    "goal": "Move the dental cleaning on 6 October to 9 October at 11:00.",
    "knowledge_level": "medium",
    "knowledge_evidence": {"kind": "relies_on_agent_for_rule", "rule": "same_service_only"},
    "complication": "none",
    "fixture": {
        "customer_id": "C-100",
        "appointment_id": "A-1001",
        "target_slot_ids": ["S-101"],
        "tool_failures": [],
    },
    "grounded_facts": [
        {"path": "appointments.A-1001.start", "value": "2026-10-06T10:00:00"},
        {"path": "slots.S-101.start", "value": "2026-10-09T11:00:00"},
    ],
    "max_turns": 12,
    "expected_outcome": "rescheduled",
    "criteria": {
        "assertions": list(checks.ASSERTIONS),
        "judge": list(load_journey_inputs(JOURNEY_DIR)[0].judge_criterion_ids),
    },
    "synthesis": {
        "origin": "synthesized",
        "qualification": "none",
        "set_id": "set-1",
        "spec_id": "spec-001",
        "journey_sha256": "a" * 64,
        "fixture_state_sha256": "b" * 64,
        "generation_config_sha256": "c" * 64,
        "generator_version": "test",
        "model": "stub",
        "generated_at": "2026-09-21T00:00:00Z",
    },
}


def _load(tmp_path, mutate=lambda raw: None):
    raw = copy.deepcopy(SCENARIO_RAW)
    mutate(raw)
    path = tmp_path / f"{SCENARIO_ID}.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_journey_scenario(path)


# ------------------------------------------------------------------ loading


def test_a_journey_scenario_loads(tmp_path):
    scenario = _load(tmp_path)
    assert scenario.name == scenario.scenario_id == SCENARIO_ID
    assert scenario.source.endswith(f"{SCENARIO_ID}.yaml")
    assert scenario.persona.archetype == "cooperative"
    assert scenario.knowledge_evidence.rule == "same_service_only"
    assert scenario.knowledge_evidence.referent is None
    assert scenario.fixture.target_slot_ids == ("S-101",)
    assert scenario.fixture.tool_failures == ()
    assert scenario.assertion_ids == tuple(checks.ASSERTIONS)
    assert scenario.synthesis.origin == "synthesized"
    assert scenario.synthesis.qualification == "none"


def test_batch_run_spec_accepts_a_journey_scenario(tmp_path):
    spec = BatchRunSpec(scenario=_load(tmp_path), run_id="run-1")
    assert spec.run_key.startswith("synth-appointment-rescheduling-0123456789ab-run-1-")


def test_a_loaded_scenario_runs_through_the_assertions(tmp_path):
    from journey_trace_builder import confirmed_reschedule

    scenario = _load(tmp_path)
    trace = confirmed_reschedule().build()
    results = checks.run_assertions(scenario.assertion_ids, trace, scenario)
    assert {r.status for r in results} == {"passed"}
    assert checks.expected_outcome_evidenced(trace, scenario).evidenced
    journey, _ = load_journey_inputs(JOURNEY_DIR)
    assert len(journey.criteria_for_judge(scenario.judge_criterion_ids)) == 5


def test_each_knowledge_level_loads_with_the_one_kind_that_evidences_it(tmp_path):
    from agentsim.journey.scenario import KNOWLEDGE_EVIDENCE

    assert set(KNOWLEDGE_EVIDENCE) == KNOWLEDGE_LEVELS
    for level, (kind, about) in KNOWLEDGE_EVIDENCE.items():
        value = "same_service_only" if about == "rule" else "appointments.A-1001.start"

        def mutate(raw, level=level, kind=kind, about=about, value=value):
            raw["knowledge_level"] = level
            raw["knowledge_evidence"] = {"kind": kind, about: value}

        evidence = _load(tmp_path, mutate).knowledge_evidence
        assert (evidence.kind, getattr(evidence, about)) == (kind, value)


def test_closed_sets_equal_the_reviewed_contract_constants():
    from scenario_synthesis import contracts

    assert ARCHETYPE_IDS == contracts.ARCHETYPE_IDS
    assert KNOWLEDGE_LEVELS == contracts.KNOWLEDGE_LEVELS


def test_knowledge_evidence_kinds_are_the_phase_4_5_names():
    """One vocabulary for ADR 0006 evidence across both synthesis paths."""
    from agentsim.journey.scenario import KNOWLEDGE_EVIDENCE
    from scenario_synthesis.generator import _knowledge_evidence

    for level, (kind, about) in KNOWLEDGE_EVIDENCE.items():
        phase_4_5 = _knowledge_evidence(level)
        assert phase_4_5["kind"] == kind and about in phase_4_5


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda r: r.update(success_criteria=["x"]), "unknown field(s) ['success_criteria']"),
        (lambda r: r.pop("synthesis"), "missing field(s) ['synthesis']"),
        (lambda r: r.update(schema_version=True), "schema_version must be 1"),
        (lambda r: r.update(scenario_id="reschedule-happy-path"), "must be 'synth-"),
        (lambda r: r.update(knowledge_level="expert"), "knowledge_level must be one of"),
        (lambda r: r.update(complication="perturbation"), "complication must be one of"),
        (lambda r: r["persona"].update(archetype="angry"), "persona.archetype must be one of"),
        (lambda r: r["persona"].pop("traits"), "persona: missing field(s) ['traits']"),
        (lambda r: r.update(goal=" "), "goal must be a non-empty string"),
        (lambda r: r.update(max_turns=0), "max_turns must be a positive integer"),
        (lambda r: r.update(expected_outcome="cancelled"), "unknown expected_outcome"),
        (lambda r: r["knowledge_evidence"].update(referent="appointments.A-1001"),
         "exactly one of 'rule' or 'referent'"),
        (lambda r: r["knowledge_evidence"].pop("rule"), "exactly one of 'rule' or 'referent'"),
        (lambda r: r["knowledge_evidence"].update(kind="relies_on_agent"),
         "knowledge_evidence.kind must be one of"),
        (lambda r: r["knowledge_evidence"].update(kind="states_rule_unprompted"),
         "does not evidence knowledge_level 'medium'"),
        (lambda r: r.update(knowledge_evidence={
            "kind": "relies_on_agent_for_rule", "referent": "appointments.A-1001.start"}),
         "names a 'rule'"),
        (lambda r: r.update(knowledge_level="low", knowledge_evidence={
            "kind": "material_fluency_gap", "referent": "appointments.A-1001.service"}),
         "is not the path of one of the Scenario's grounded facts"),
        (lambda r: r["fixture"].update(target_slot_ids=[]), "target_slot_ids must not be empty"),
        (lambda r: r["fixture"].update(tool_failures=["lookup_appointments"]),
         "no supported controlled failure"),
        (lambda r: r["fixture"].update(card="1234"), "fixture: unknown field(s) ['card']"),
        (lambda r: r["grounded_facts"][0].pop("value"), "missing field(s) ['value']"),
        (lambda r: r["criteria"]["assertions"].append("validated_submit"),
         "unknown Assertion(s) ['validated_submit']"),
        (lambda r: r["synthesis"].update(origin="curated"), "origin must be 'synthesized'"),
        (lambda r: r["synthesis"].update(qualification="admitted"),
         "qualification must be 'none'"),
        (lambda r: r["synthesis"].update(journey_sha256="abc"), "lowercase SHA-256 digest"),
        (lambda r: r["synthesis"].update(candidate_id="candidate-1"),
         "synthesis: unknown field(s) ['candidate_id']"),
    ],
)
def test_malformed_journey_scenario_is_rejected(tmp_path, mutate, fragment):
    with pytest.raises(JourneyScenarioError) as excinfo:
        _load(tmp_path, mutate)
    assert fragment in str(excinfo.value)
    assert str(excinfo.value).startswith(f"{SCENARIO_ID}.yaml")


# ------------------------------------------------- the two paths stay apart


def test_the_journey_loader_rejects_every_payments_scenario():
    payments_files = sorted(Path("scenarios").glob("*.yaml"))
    assert payments_files
    for path in payments_files:
        with pytest.raises(JourneyScenarioError, match="payments Scenario"):
            load_journey_scenario(path)


def test_the_payments_loaders_reject_a_journey_scenario(tmp_path):
    from agentsim.scenario import ScenarioError, load_scenario, load_synthesized_scenario

    _load(tmp_path)
    path = tmp_path / f"{SCENARIO_ID}.yaml"
    for loader in (load_scenario, load_synthesized_scenario):
        with pytest.raises(ScenarioError):
            loader(path)


def test_the_journey_package_loads_and_checks_without_the_payments_fixtures(tmp_path):
    """The narrow seam: load the Journey inputs and a Scenario, check it, run
    the Assertions — in a fresh interpreter, so this process's own imports of
    the payments path cannot hide a dependency."""
    _load(tmp_path)
    script = f"""
import sys
from agentsim.journey import checks
from agentsim.journey.definition import load_journey_inputs
from agentsim.journey.normalized_trace import Evidence, NormalizedTrace
from agentsim.journey.scenario import check_against_inputs, load_journey_scenario

journey, fixture_state = load_journey_inputs({str(JOURNEY_DIR)!r})
scenario = load_journey_scenario({str(tmp_path / (SCENARIO_ID + '.yaml'))!r})
check_against_inputs(scenario, journey, fixture_state)
trace = NormalizedTrace("c", "p", None, (), Evidence("available", "available"))
assert all(r.status == "passed" for r in checks.run_assertions(scenario.assertion_ids, trace, scenario))
loaded = [m for m in sys.modules if m.split(".")[0] in ("fixtures", "scenario_synthesis", "langgraph", "langchain")]
loaded += [m for m in ("agentsim.scenario", "agentsim.simulator", "agentsim.criteria") if m in sys.modules]
assert not loaded, loaded
print("ok")
"""
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, cwd=Path.cwd()
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


# ---------------------------------------------- fit against current inputs


def test_a_scenario_that_fits_the_journey_inputs_is_accepted(tmp_path):
    journey, fixture_state = load_journey_inputs(JOURNEY_DIR)
    check_against_inputs(_load(tmp_path), journey, fixture_state)


def test_the_controlled_failure_scenario_fits_with_its_derived_outcome(tmp_path):
    journey, fixture_state = load_journey_inputs(JOURNEY_DIR)

    def controlled_failure(raw):
        raw["fixture"]["tool_failures"] = ["update_appointment"]
        raw["expected_outcome"] = "update_failed_reported"

    check_against_inputs(_load(tmp_path, controlled_failure), journey, fixture_state)


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda r: r.update(
            journey="appointment-booking",
            scenario_id="synth-appointment-booking-0123456789ab"),
         "is not the Journey definition's"),
        (lambda r: r.update(complication="goal-shift"), "unsupported for this Journey"),
        (lambda r: r["fixture"].update(customer_id="C-999"), "'C-999' is not in Fixture state"),
        (lambda r: r["persona"].update(name="Someone Else"), "not the Fixture customer's"),
        (lambda r: r["fixture"].update(appointment_id="A-9999"),
         "'A-9999' is not in Fixture state"),
        (lambda r: r["fixture"].update(appointment_id="A-2001"), "does not belong to customer"),
        (lambda r: r["fixture"].update(target_slot_ids=["S-999"]),
         "'S-999' is not in Fixture state"),
        (lambda r: r["fixture"].update(target_slot_ids=["S-104"]), "not open for booking"),
        (lambda r: r["fixture"].update(target_slot_ids=["S-201"]),
         "is for 'orthodontic check'"),
        (lambda r: r["grounded_facts"][0].update(value="2026-10-06T10:30:00"),
         "in the Scenario but"),
        (lambda r: r["grounded_facts"][0].update(path="appointments.A-1001.room"),
         "names nothing in Fixture state"),
        (lambda r: r["knowledge_evidence"].update(rule="made_up_rule"),
         "not a Journey knowledge rule"),
        (lambda r: r.update(expected_outcome="update_failed_reported"),
         "is not what the Journey definition derives"),
        (lambda r: r["criteria"]["assertions"].pop(), "criteria.assertions differ"),
        (lambda r: r["criteria"]["judge"].pop(), "criteria.judge differ"),
        # The loader has no Journey definition, so a Judge criterion id nobody
        # defines loads; this is where it is caught.
        (lambda r: r["criteria"]["judge"].append("goal_completion"),
         "criteria.judge differ"),
    ],
)
def test_a_scenario_that_does_not_fit_the_inputs_is_rejected(tmp_path, mutate, fragment):
    journey, fixture_state = load_journey_inputs(JOURNEY_DIR)
    scenario = _load(tmp_path, mutate)
    with pytest.raises(JourneyScenarioError) as excinfo:
        check_against_inputs(scenario, journey, fixture_state)
    assert fragment in str(excinfo.value)


def test_a_completed_appointment_cannot_be_a_scenario_goal(tmp_path):
    journey, fixture_state = load_journey_inputs(JOURNEY_DIR)

    def completed(raw):
        raw["persona"]["name"] = "Priya Natarajan"
        raw["fixture"].update(
            customer_id="C-300", appointment_id="A-3002", target_slot_ids=["S-201"]
        )
        raw["grounded_facts"] = []

    with pytest.raises(JourneyScenarioError, match="cannot be rescheduled"):
        check_against_inputs(_load(tmp_path, completed), journey, fixture_state)
