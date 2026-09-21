"""Journey definition and Fixture state: the committed files load, and
malformed versions are rejected with a message that names the file and field."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from agentsim.journey import checks
from agentsim.journey.definition import (
    COMPLICATION_IDS,
    FixtureStateError,
    JourneyDefinitionError,
    load_fixture_state,
    load_journey_definition,
    load_journey_inputs,
)

JOURNEY_DIR = Path("journeys/appointment_rescheduling")
JOURNEY_RAW = yaml.safe_load((JOURNEY_DIR / "journey.yaml").read_text())
FIXTURE_RAW = yaml.safe_load((JOURNEY_DIR / "fixture_state.yaml").read_text())


def _journey(tmp_path, mutate):
    raw = copy.deepcopy(JOURNEY_RAW)
    mutate(raw)
    path = tmp_path / "journey.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_journey_definition(path)


def _fixture(tmp_path, mutate):
    raw = copy.deepcopy(FIXTURE_RAW)
    mutate(raw)
    path = tmp_path / "fixture_state.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_fixture_state(path)


# ------------------------------------------------------ Journey definition


def test_committed_journey_definition_loads():
    journey, fixture_state = load_journey_inputs(JOURNEY_DIR)
    assert journey.journey_id == "appointment-rescheduling"
    assert journey.tools == (
        "lookup_appointments", "find_available_slots", "update_appointment",
    )
    assert journey.max_turns_default == 12
    assert journey.source.endswith("journey.yaml")
    assert fixture_state.fixture_state_id == "harbor-street-dental-2026-10"


def test_journey_states_the_three_required_rules_each_with_a_check():
    journey = load_journey_definition(JOURNEY_DIR / "journey.yaml")
    rules = {rule.id: rule for rule in journey.required_rules}
    assert {
        "identify_existing_appointment",
        "confirm_before_changing",
        "report_update_result_accurately",
    } <= set(rules)
    assert all(rule.checks for rule in rules.values())
    assert "judge:update_result_reported_accurately" in (
        rules["report_update_result_accurately"].checks
    )


def test_every_check_the_journey_references_exists():
    journey = load_journey_definition(JOURNEY_DIR / "journey.yaml")
    assert set(journey.assertion_ids) <= set(checks.ASSERTIONS)
    assert set(journey.judge_criterion_ids) <= set(checks.JUDGE_CRITERIA)
    # The committed Journey applies every check this module defines.
    assert set(journey.assertion_ids) == set(checks.ASSERTIONS)
    assert set(journey.judge_criterion_ids) == set(checks.JUDGE_CRITERIA)


def test_expected_outcome_is_derived_from_the_tool_failure_condition():
    journey = load_journey_definition(JOURNEY_DIR / "journey.yaml")
    assert journey.outcome_for(()) == "rescheduled"
    assert journey.outcome_for(("update_appointment",)) == "update_failed_reported"
    assert {o.id for o in journey.valid_outcomes} == checks.OUTCOME_IDS


def test_all_nine_complications_are_accounted_for_exactly_once():
    journey = load_journey_definition(JOURNEY_DIR / "journey.yaml")
    accounted = list(journey.supported_complications) + list(
        journey.unsupported_complications
    )
    assert sorted(accounted) == sorted(COMPLICATION_IDS)
    assert set(journey.unsupported_complications) == {"goal-shift", "multi-intent-turn"}
    assert all(journey.unsupported_complications.values())


def test_complication_ids_equal_the_reviewed_contract_constants():
    from scenario_synthesis import contracts

    assert COMPLICATION_IDS == contracts.COMPLICATION_IDS


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda r: r.update(surprise=1), "unknown field(s) ['surprise']"),
        (lambda r: r.pop("valid_outcomes"), "missing field(s) ['valid_outcomes']"),
        (lambda r: r.update(schema_version=2), "schema_version must be 1"),
        (lambda r: r.update(journey_id="J1"), "never a payments 'J<n>' id"),
        (lambda r: r.update(max_turns_default=0), "max_turns_default must be a positive"),
        (lambda r: r.update(tools=["lookup_appointments", "lookup_appointments"]),
         "duplicate value(s)"),
        (lambda r: r["criteria"]["assertions"].append("validated_submit"),
         "unknown Assertion 'validated_submit'"),
        (lambda r: r["criteria"]["judge"].append("goal_completion"),
         "unknown Judge criterion 'goal_completion'"),
        (lambda r: r["required_rules"][0]["checks"].append("judge:no_such_criterion"),
         "'judge:no_such_criterion' is not listed under criteria"),
        (lambda r: r["required_rules"][0]["checks"].append("appointment_identified"),
         "must be written 'assertion:<id>' or 'judge:<id>'"),
        (lambda r: r["required_rules"][0].update(checks=[]), "checks must not be empty"),
        (lambda r: r["required_rules"].append(copy.deepcopy(r["required_rules"][0])),
         "duplicate id(s) ['identify_existing_appointment']"),
        (lambda r: r["valid_outcomes"][0].update(id="cancelled"),
         "'cancelled' has no expected_outcome_evidenced rule"),
        (lambda r: r["valid_outcomes"][1]["when"].update(tool_failures=[]),
         "two outcomes share one 'when' condition"),
        (lambda r: r["valid_outcomes"][1]["when"].update(
            tool_failures=["lookup_appointments"]),
         "supported controlled failure"),
        (lambda r: r["complications"]["supported"].remove("channel-noise"),
         "missing ['channel-noise']"),
        (lambda r: r["complications"]["supported"].append("goal-shift"),
         "listed as both supported and unsupported"),
        (lambda r: r["complications"]["unsupported"].update(perturbation="x"),
         "unknown ['perturbation']"),
        (lambda r: r.update(agent_role="  "), "agent_role must be a non-empty string"),
    ],
)
def test_malformed_journey_definition_is_rejected(tmp_path, mutate, fragment):
    with pytest.raises(JourneyDefinitionError) as excinfo:
        _journey(tmp_path, mutate)
    assert fragment in str(excinfo.value)
    assert str(excinfo.value).startswith("journey.yaml")


def test_an_assertion_reading_an_unlisted_tool_is_rejected(tmp_path):
    with pytest.raises(JourneyDefinitionError, match="reads tool"):
        _journey(tmp_path, lambda r: r["tools"].remove("find_available_slots"))


def test_journey_definition_that_is_not_yaml_or_not_a_mapping_is_rejected(tmp_path):
    path = tmp_path / "journey.yaml"
    path.write_text("tools: [unclosed")
    with pytest.raises(JourneyDefinitionError, match="invalid YAML"):
        load_journey_definition(path)
    path.write_text("- just\n- a list\n")
    with pytest.raises(JourneyDefinitionError, match="must be a mapping"):
        load_journey_definition(path)
    with pytest.raises(JourneyDefinitionError, match="cannot read file"):
        load_journey_definition(tmp_path / "absent.yaml")


# ----------------------------------------------------------- Fixture state


def test_committed_fixture_state_loads_and_resolves_facts():
    fixture_state = load_fixture_state(JOURNEY_DIR / "fixture_state.yaml")
    assert fixture_state.appointment("A-1001")["confirmation_code"] == "HSD-4821"
    assert fixture_state.slot("S-104")["available"] is False
    assert fixture_state.customer("C-999") is None
    assert fixture_state.fact("appointments.A-1001.start") == "2026-10-06T10:00:00"
    assert fixture_state.fact("slots.S-101.available") is True
    for path in ("appointments.A-9.start", "appointments.A-1001.colour", "A-1001.start"):
        with pytest.raises(FixtureStateError):
            fixture_state.fact(path)


def test_one_customer_holds_two_appointments_for_the_same_service():
    fixture_state = load_fixture_state(JOURNEY_DIR / "fixture_state.yaml")
    pairs = [(a["customer_id"], a["service"]) for a in fixture_state.appointments]
    assert any(pairs.count(pair) == 2 for pair in pairs)


def test_fixture_state_hash_is_the_canonical_json_sha256():
    fixture_state = load_fixture_state(JOURNEY_DIR / "fixture_state.yaml")
    canonical = json.dumps(
        FIXTURE_RAW, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert fixture_state.sha256 == hashlib.sha256(canonical).hexdigest()


def test_fixture_state_payload_is_a_detached_json_copy():
    fixture_state = load_fixture_state(JOURNEY_DIR / "fixture_state.yaml")
    before = fixture_state.sha256
    payload = fixture_state.to_payload()
    assert json.loads(json.dumps(payload)) == FIXTURE_RAW
    payload["slots"][0]["available"] = False
    assert fixture_state.sha256 == before


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda r: r.update(agent_prompt="x"), "unknown field(s) ['agent_prompt']"),
        (lambda r: r.pop("now"), "missing field(s) ['now']"),
        (lambda r: r.update(schema_version="1"), "schema_version must be 1"),
        (lambda r: r.update(slots=[]), "slots must not be empty"),
        (lambda r: r["appointments"][0].update(customer_id="C-999"),
         "references unknown customer 'C-999'"),
        (lambda r: r["appointments"][0].update(status="pending"), "status must be one of"),
        (lambda r: r["appointments"][1].update(appointment_id="A-1001"),
         "duplicate appointment_id 'A-1001'"),
        (lambda r: r["appointments"][0].update(notes="x"), "unknown field(s) ['notes']"),
        (lambda r: r["slots"][0].pop("provider"), "missing field(s) ['provider']"),
        (lambda r: r["slots"][0].update(available="yes"), "available must be true or false"),
        (lambda r: r["slots"][0].update(slot_id="S.101"), "must not contain '.'"),
        (lambda r: r["slots"][0].update(service=""), "service must be a non-empty string"),
        (lambda r: r["slots"][0].update(start="next Tuesday"), "not an ISO 8601 date-time"),
        (lambda r: r["slots"][0].update(start="2026-10-09T11:00:00+00:00"),
         "all carry a UTC offset or all omit it"),
    ],
)
def test_malformed_fixture_state_is_rejected(tmp_path, mutate, fragment):
    with pytest.raises(FixtureStateError) as excinfo:
        _fixture(tmp_path, mutate)
    assert fragment in str(excinfo.value)
    assert str(excinfo.value).startswith("fixture_state.yaml")


def test_an_unquoted_yaml_timestamp_is_rejected_because_it_cannot_be_hashed(tmp_path):
    text = (JOURNEY_DIR / "fixture_state.yaml").read_text()
    path = tmp_path / "fixture_state.yaml"
    path.write_text(text.replace('now: "2026-10-01T09:00:00"', "now: 2026-10-01T09:00:00"))
    with pytest.raises(FixtureStateError, match="quoted ISO 8601 string"):
        load_fixture_state(path)
