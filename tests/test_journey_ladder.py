"""Ladders: the committed Rungs hold everything but difficulty constant, a
Rung realizes an ordinary Synthesized Journey Scenario, and a Ladder that does
not describe its Journey definition is refused before any Rung is climbed."""

import dataclasses
import json
from pathlib import Path

import pytest

from agentsim.journey.definition import load_journey_inputs
from agentsim.journey.probe import openings
import scenario_synthesis.ladder as ladder_module
from agentsim.journey.scenario import load_journey_scenario
from scenario_synthesis.journey_synthesis import (
    StubNarrativeProvider,
    parse_narrative,
    scenario_document,
    validate_scenario_document,
    verify_provenance,
)
from scenario_synthesis.ladder import (
    ARCHETYPE_AXIS,
    CONTROL_ARCHETYPE,
    DIRECTIONS,
    IDENTIFY_EXISTING_APPOINTMENT,
    LADDERS,
    Ladder,
    LadderError,
    RungSpec,
    also_carries,
    archetype_for,
    StubLadderNarrativeProvider,
    check_ladder,
    ladder_and_rung_for,
    narrative_request,
    realize_ladder,
    spec_for,
)

JOURNEY_DIR = Path("journeys/appointment_rescheduling")
SYNTHESIS = {
    "set_id": "ladder-identify-existing-appointment",
    "journey_sha256": "0" * 64,
    "fixture_state_sha256": "1" * 64,
    "generation_config_sha256": "2" * 64,
    "generator_version": "journey-ladder-v1",
    "model": "offline-stub",
    "generated_at": "2026-09-25T00:00:00Z",
}


@pytest.fixture(scope="module")
def journey_inputs():
    return load_journey_inputs(JOURNEY_DIR)


# ------------------------------------------------- the committed Ladder


def test_every_committed_ladder_describes_its_journey(journey_inputs):
    journey, _ = journey_inputs
    for ladder in LADDERS.values():
        check_ladder(ladder, journey)


def test_the_ladder_attacks_an_opening_the_fixture_state_actually_has(journey_inputs):
    """A Ladder aimed at a condition the Fixture state does not hold would climb
    against nothing."""
    journey, fixture = journey_inputs
    found = {
        (opening.rule_id, opening.kind, opening.rows) for opening in openings(journey, fixture)
    }
    for ladder in LADDERS.values():
        assert (ladder.rule_id, ladder.opening_kind, ladder.opening_rows) in found


def test_rungs_vary_only_difficulty(journey_inputs):
    """The whole claim of a climb: when a Rung breaks and the one below did
    not, difficulty is the only thing that moved."""
    specs = [
        spec_for(IDENTIFY_EXISTING_APPOINTMENT, rung.rung)
        for rung in IDENTIFY_EXISTING_APPOINTMENT.rungs
    ]
    constant = [
        dataclasses.replace(
            spec,
            spec_id="",
            archetype="",
            complication="",
            complication_detail={},
        )
        for spec in specs
    ]
    assert all(spec == constant[0] for spec in constant)


def test_the_ladder_gets_harder_and_rung_one_is_the_control(journey_inputs):
    ladder = IDENTIFY_EXISTING_APPOINTMENT
    counts = [len(rung.direction_ids) for rung in ladder.rungs]
    assert counts == sorted(counts), "a Rung never carries fewer difficulties than the one below"
    assert archetype_for(ladder.rung(1)) == CONTROL_ARCHETYPE
    assert also_carries(ladder.rung(1)) == ()
    assert also_carries(ladder.rung(4)) == ("pressure", "false-premise")


def test_rung_three_stops_resolving_the_ambiguity_rung_one_resolves(journey_inputs):
    """Rung 1 and Rung 3 are the same Complication at two difficulties: the
    reason Rungs do not reuse the measuring mode's direction."""
    ladder = IDENTIFY_EXISTING_APPOINTMENT
    assert spec_for(ladder, 1).complication == spec_for(ladder, 3).complication
    assert "picks the right one" in DIRECTIONS[ladder.rung(1).primary].text
    assert "does NOT pick" in DIRECTIONS[ladder.rung(3).primary].text


# ----------------------------------------------------- realizing a Rung


def test_a_rung_realizes_a_loadable_synthesized_scenario(journey_inputs, tmp_path):
    """The Scenario a Rung produces loads through the ordinary strict loader:
    origin synthesized, real provenance, nothing widened for a Probe."""
    journey, fixture = journey_inputs
    spec = spec_for(IDENTIFY_EXISTING_APPOINTMENT, 4)
    request = narrative_request(IDENTIFY_EXISTING_APPOINTMENT, 4, journey)
    narrative = parse_narrative(
        StubNarrativeProvider().realize(
            {
                **request,
                "archetype_direction": "stub",
                "complication_direction": "stub",
            },
            attempt=1,
        )
    )
    document = scenario_document(spec, narrative, journey, SYNTHESIS)
    assert document["synthesis"]["origin"] == "synthesized"
    assert document["synthesis"]["spec_id"] == "rung-4"
    assert document["synthesis"]["set_id"] == "ladder-identify-existing-appointment"
    assert document["complication"] == "ambiguous-reference"

    path = tmp_path / "rung-4.yaml"
    path.write_text(validate_scenario_document(document, journey, fixture))
    assert load_journey_scenario(path).persona.archetype == "pressure"


def test_the_request_carries_every_difficulty_and_withholds_the_rule(journey_inputs):
    """The customer is never told which required rule the Probe is attacking."""
    journey, _ = journey_inputs
    request = narrative_request(IDENTIFY_EXISTING_APPOINTMENT, 4, journey)
    values = [entry["value"] for entry in request["difficulty_directions"]]
    assert values == ["ambiguous-reference", "pressure", "false-premise"]
    rendered = repr(request)
    assert "identify_existing_appointment" not in rendered
    assert "update_matches_goal" not in rendered
    assert "expected_outcome" not in rendered


def test_a_realized_rung_scenario_leads_back_to_every_difficulty_it_carries(
    journey_inputs,
):
    """The Scenario names its primary Complication and cannot list the rest, so
    the way back to the Rung specification has to hold."""
    journey, _ = journey_inputs
    spec = spec_for(IDENTIFY_EXISTING_APPOINTMENT, 4)
    document = scenario_document(
        spec, {"description": "d", "traits": "t", "goal": "g"}, journey, SYNTHESIS
    )
    ladder, rung = ladder_and_rung_for(document["synthesis"])
    assert ladder is IDENTIFY_EXISTING_APPOINTMENT
    assert rung.rung == 4
    assert also_carries(rung) == ("pressure", "false-premise")


@pytest.mark.parametrize(
    "synthesis,message",
    [
        ({"set_id": "ladder-invented", "spec_id": "rung-1"}, "no Ladder named"),
        (
            {"set_id": "ladder-identify-existing-appointment", "spec_id": "spec-003"},
            "does not name a Rung",
        ),
        (
            {"set_id": "ladder-identify-existing-appointment", "spec_id": "rung-9"},
            "has no Rung 9",
        ),
    ],
)
def test_a_scenario_that_cannot_lead_back_to_its_rung_is_refused(synthesis, message):
    with pytest.raises(LadderError, match=message):
        ladder_and_rung_for(synthesis)


def test_the_false_premise_value_is_a_grounded_fact(journey_inputs):
    """She is wrong about which appointment, using a real time she was given —
    not an invented one. The Sealed-world rule holds without special handling."""
    detail = spec_for(IDENTIFY_EXISTING_APPOINTMENT, 4).complication_detail
    grounded = {
        str(fact["value"]) for fact in IDENTIFY_EXISTING_APPOINTMENT.grounded_facts
    }
    assert detail["believed_value"] in grounded


# --------------------------------------------------------- realization


def _realize(tmp_path, provider=None, **kwargs):
    return realize_ladder(
        IDENTIFY_EXISTING_APPOINTMENT,
        JOURNEY_DIR,
        provider=provider or StubLadderNarrativeProvider(),
        output_root=tmp_path / "sets",
        **kwargs,
    )


def test_realizing_a_ladder_writes_one_loadable_scenario_per_rung(tmp_path):
    set_dir = _realize(tmp_path)
    record = json.loads((set_dir / "provenance.json").read_text())
    assert record["status"] == "complete"
    assert [entry["rung"] for entry in record["accepted"]] == [1, 2, 3, 4]

    for entry in record["accepted"]:
        scenario = load_journey_scenario(set_dir / entry["file"])
        ladder, rung = ladder_and_rung_for({"set_id": "ladder-identify-existing-appointment",
                                            "spec_id": f"rung-{entry['rung']}"})
        assert rung.rung == entry["rung"]
        assert scenario.complication == DIRECTIONS[rung.primary].value


def test_a_realized_ladder_passes_the_ordinary_provenance_check(tmp_path):
    """It is an ordinary synthesized set, so the existing checker must accept
    it without knowing anything about Ladders."""
    set_dir = _realize(tmp_path)
    assert verify_provenance(set_dir, JOURNEY_DIR) == []


def test_every_direction_reaches_the_narrative(tmp_path):
    """Rung 4 carries three directions. A Rung that silently dropped one would
    still be a valid Scenario — just not the attack it claims to be."""
    set_dir = _realize(tmp_path)
    record = json.loads((set_dir / "provenance.json").read_text())
    entry = next(entry for entry in record["accepted"] if entry["rung"] == 4)
    traits = load_journey_scenario(set_dir / entry["file"]).persona.traits
    for direction_id in IDENTIFY_EXISTING_APPOINTMENT.rung(4).direction_ids:
        assert DIRECTIONS[direction_id].text in traits


def test_a_set_directory_is_never_overwritten(tmp_path):
    _realize(tmp_path)
    with pytest.raises(LadderError, match="never overwritten"):
        _realize(tmp_path)


def test_a_rung_that_cannot_be_realized_aborts_the_whole_ladder(tmp_path):
    """A Ladder missing Rung 2 is not a shorter Ladder; a climb needs every
    Rung below the one that breaks."""

    class _FailsOnRungTwo:
        provider_id = "test"
        model = "test"

        def realize(self, request, *, attempt):
            if request["spec"]["archetype"] == "pressure":
                return {"description": "d", "persona": {"traits": "t"}, "goal": "HSD-9999"}
            return StubLadderNarrativeProvider().realize(request, attempt=attempt)

    with pytest.raises(LadderError, match="was not realized in"):
        _realize(tmp_path, provider=_FailsOnRungTwo(), attempts=2)

    set_dir = tmp_path / "sets" / "appointment-rescheduling" / "ladder-identify-existing-appointment"
    record = json.loads((set_dir / "provenance.json").read_text())
    assert record["status"] == "aborted"
    assert [entry["rung"] for entry in record["accepted"]] == [1], "Rung 1 is kept"
    assert {entry["rung"] for entry in record["rejected"]} == {2}
    assert record["error"]["type"] == "LadderError"


def test_a_rejected_attempt_is_retried_with_its_reason(tmp_path):
    seen = []

    class _FailsOnce:
        provider_id = "test"
        model = "test"

        def realize(self, request, *, attempt):
            seen.append((request["spec"]["complication"], attempt,
                         len(request["previous_rejection"])))
            if attempt == 1:
                return {"description": "d", "persona": {"traits": "t"}, "goal": "HSD-9999"}
            return StubLadderNarrativeProvider().realize(request, attempt=attempt)

    _realize(tmp_path, provider=_FailsOnce(), attempts=2)
    assert seen[0][1:] == (1, 0)
    assert seen[1][1:] == (2, 1), "the second attempt is told why the first was rejected"


# ------------------------------------------------------------- refusals


def _ladder(**changes) -> Ladder:
    return dataclasses.replace(IDENTIFY_EXISTING_APPOINTMENT, **changes)


def test_a_ladder_for_another_journey_is_refused(journey_inputs):
    journey, _ = journey_inputs
    with pytest.raises(LadderError, match="names Journey"):
        check_ladder(_ladder(journey_id="payments"), journey)


def test_a_ladder_attacking_an_unrequired_rule_is_refused(journey_inputs):
    journey, _ = journey_inputs
    with pytest.raises(LadderError, match="does not require"):
        check_ladder(_ladder(rule_id="be_nice"), journey)


def test_rungs_must_be_numbered_in_order(journey_inputs):
    journey, _ = journey_inputs
    rungs = (RungSpec(rung=2, primary="ambiguous-reference:names-service-only"),)
    with pytest.raises(LadderError, match="numbered 1..n"):
        check_ladder(_ladder(rungs=rungs), journey)


def test_an_unknown_direction_is_refused(journey_inputs):
    journey, _ = journey_inputs
    rungs = (RungSpec(rung=1, primary="ambiguous-reference:invented"),)
    with pytest.raises(LadderError, match="unknown direction"):
        check_ladder(_ladder(rungs=rungs), journey)


def test_a_primary_direction_must_be_a_complication(journey_inputs):
    journey, _ = journey_inputs
    rungs = (RungSpec(rung=1, primary="pressure:hurry"),)
    with pytest.raises(LadderError, match="must be a Complication"):
        check_ladder(_ladder(rungs=rungs), journey)


def _with_direction(monkeypatch, direction_id, **changes):
    """Add one Direction for the duration of a test, without editing the
    committed table."""
    base = DIRECTIONS["ambiguous-reference:names-service-only"]
    extra = dataclasses.replace(base, direction_id=direction_id, **changes)
    monkeypatch.setattr(ladder_module, "DIRECTIONS", {**DIRECTIONS, direction_id: extra})


def test_two_archetypes_in_one_rung_are_refused(journey_inputs, monkeypatch):
    journey, _ = journey_inputs
    _with_direction(monkeypatch, "persistent:retries", axis=ARCHETYPE_AXIS, value="persistent")
    rungs = (
        RungSpec(
            rung=1,
            primary="ambiguous-reference:names-service-only",
            also=("pressure:hurry", "persistent:retries"),
        ),
    )
    with pytest.raises(LadderError, match="Persona archetypes"):
        check_ladder(_ladder(rungs=rungs), journey)


def test_a_repeated_direction_is_refused(journey_inputs):
    journey, _ = journey_inputs
    rungs = (
        RungSpec(
            rung=1,
            primary="ambiguous-reference:names-service-only",
            also=("ambiguous-reference:names-service-only",),
        ),
    )
    with pytest.raises(LadderError, match="listed twice"):
        check_ladder(_ladder(rungs=rungs), journey)


def test_an_unsupported_complication_is_refused(journey_inputs, monkeypatch):
    """goal-shift is one of the nine Complications but this Journey records it
    as unsupported; a Ladder may not reach past that."""
    journey, _ = journey_inputs
    _with_direction(monkeypatch, "goal-shift:swaps", value="goal-shift")
    rungs = (RungSpec(rung=1, primary="goal-shift:swaps"),)
    with pytest.raises(LadderError, match="unsupported for Journey"):
        check_ladder(_ladder(rungs=rungs), journey)


def test_a_direction_referring_to_an_ungrounded_value_is_refused(journey_inputs):
    """A direction is the model's instruction; a value it names that the
    customer was never given would be an invented fact."""
    journey, _ = journey_inputs
    facts = tuple(
        fact
        for fact in IDENTIFY_EXISTING_APPOINTMENT.grounded_facts
        if fact["value"] != "2026-10-06T10:00:00"
    )
    with pytest.raises(LadderError, match="not one of this Ladder's grounded facts"):
        check_ladder(_ladder(grounded_facts=facts), journey)
