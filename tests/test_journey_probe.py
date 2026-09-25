"""Openings: the shapes are found over a Fixture state, the committed dental
Fixture state's Openings are pinned, and a specification that does not describe
its Journey definition is refused rather than silently skipped."""

import copy
from pathlib import Path

import pytest
import yaml

from agentsim.journey.definition import (
    FixtureState,
    load_fixture_state,
    load_journey_definition,
    load_journey_inputs,
)
from agentsim.journey.probe import (
    COLLISION,
    DECISIVE_FIELD,
    DISQUALIFIED,
    FORCED_FAILURE,
    NEAR_COLLISION,
    JOURNEY_SPECS,
    OpeningSpec,
    ProbeError,
    _one_edit_apart,
    openings,
    rules_without_openings,
)

JOURNEY_DIR = Path("journeys/appointment_rescheduling")
FIXTURE_RAW = yaml.safe_load((JOURNEY_DIR / "fixture_state.yaml").read_text())
JOURNEY_RAW = yaml.safe_load((JOURNEY_DIR / "journey.yaml").read_text())


def _fixture(tmp_path, mutate):
    raw = copy.deepcopy(FIXTURE_RAW)
    mutate(raw)
    path = tmp_path / "fixture_state.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_fixture_state(path)


def _journey(tmp_path, mutate):
    raw = copy.deepcopy(JOURNEY_RAW)
    mutate(raw)
    path = tmp_path / "journey.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_journey_definition(path)


def _by_kind(found, kind):
    return [opening for opening in found if opening.kind == kind]


# --------------------------------------------- the committed Fixture state


def test_committed_fixture_state_openings_are_what_a_probe_may_aim_at():
    """Pins the derived targets for the dental Journey. A Fixture state edit
    that adds or removes an Opening changes where a Probe can aim, so it should
    fail here and be read rather than pass quietly."""
    journey, fixture = load_journey_inputs(JOURNEY_DIR)
    found = openings(journey, fixture)

    assert [(o.rule_id, o.kind, o.rows) for o in found] == [
        ("identify_existing_appointment", COLLISION, ("A-1001", "A-1002")),
        ("identify_existing_appointment", NEAR_COLLISION, ("A-1001", "A-1002")),
        ("offer_only_real_slots", DISQUALIFIED, ("S-104",)),
        ("offer_only_real_slots", DISQUALIFIED, ("S-203",)),
        ("change_only_what_was_asked", DECISIVE_FIELD, ("S-103", "S-201")),
        ("report_update_result_accurately", FORCED_FAILURE, ()),
    ]


def test_confirm_before_changing_has_no_fixture_state_opening():
    """It binds in every conversation, so Rung 1 arranges nothing for it. That
    is an absence worth naming, not an empty list to be mistaken for coverage."""
    journey, fixture = load_journey_inputs(JOURNEY_DIR)
    assert rules_without_openings(journey, openings(journey, fixture)) == (
        "confirm_before_changing",
    )


def test_collision_is_the_two_cleanings_the_fixture_state_planted_on_purpose():
    journey, fixture = load_journey_inputs(JOURNEY_DIR)
    (collision,) = _by_kind(openings(journey, fixture), COLLISION)
    assert collision.detail["describe_by"] == {
        "customer_id": "C-100",
        "service": "dental cleaning",
    }


def test_near_collision_reports_the_codes_and_not_a_wider_pair():
    """HSD-4821/HSD-4822 differ by one character; Priya's HSD-6650/HSD-6611
    differ by two and are not a near collision."""
    journey, fixture = load_journey_inputs(JOURNEY_DIR)
    (near,) = _by_kind(openings(journey, fixture), NEAR_COLLISION)
    assert near.detail == {"field": "confirmation_code", "values": ["HSD-4821", "HSD-4822"]}


# ------------------------------------------------------------- the shapes


def test_collision_needs_two_rows_a_single_phrase_describes(tmp_path):
    journey = load_journey_definition(JOURNEY_DIR / "journey.yaml")
    fixture = _fixture(
        tmp_path,
        lambda raw: raw["appointments"].__setitem__(
            1, {**raw["appointments"][1], "service": "orthodontic check"}
        ),
    )
    assert _by_kind(openings(journey, fixture), COLLISION) == []


def test_collision_ignores_rows_the_where_clause_excludes(tmp_path):
    """Priya's completed appointment never joins a collision: a customer cannot
    be asked to choose between appointments one of which cannot be moved."""
    journey = load_journey_definition(JOURNEY_DIR / "journey.yaml")

    def add_completed_twin(raw):
        twin = dict(raw["appointments"][4])
        twin.update(appointment_id="A-3003", service="dental cleaning")
        raw["appointments"].append(twin)

    fixture = _fixture(tmp_path, add_completed_twin)
    rows = {opening.rows for opening in _by_kind(openings(journey, fixture), COLLISION)}
    assert rows == {("A-1001", "A-1002")}


def test_disqualified_finds_a_row_that_is_real_but_ruled_out(tmp_path):
    journey = load_journey_definition(JOURNEY_DIR / "journey.yaml")
    fixture = _fixture(
        tmp_path,
        lambda raw: [slot.__setitem__("available", True) for slot in raw["slots"]],
    )
    assert _by_kind(openings(journey, fixture), DISQUALIFIED) == []


def test_decisive_field_needs_the_shared_field_and_the_differing_one(tmp_path):
    """S-103 and S-201 are both Dr. Chen's and only the service separates them.
    Give them different providers and the pair stops being a look-alike."""
    journey = load_journey_definition(JOURNEY_DIR / "journey.yaml")
    fixture = _fixture(
        tmp_path,
        lambda raw: raw["slots"].__setitem__(4, {**raw["slots"][4], "provider": "Dr. Patel"}),
    )
    assert _by_kind(openings(journey, fixture), DECISIVE_FIELD) == []


def test_forced_failure_is_reported_without_a_fixture_state_row():
    journey, fixture = load_journey_inputs(JOURNEY_DIR)
    (forced,) = _by_kind(openings(journey, fixture), FORCED_FAILURE)
    assert forced.rows == ()
    assert forced.detail == {"tool": "update_appointment"}


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("HSD-4821", "HSD-4822", True),
        ("HSD-6650", "HSD-6611", False),
        ("HSD-4821", "HSD-4821", False),  # identical is a collision, not a near miss
        ("HSD-482", "HSD-4821", True),  # one character dropped
        ("HSD-4821", "HSD-48210", True),
        ("HSD-4821", "HSD-481", True),  # the '2' dropped, still one edit
        ("HSD-4821", "HSD-4899", False),  # two substitutions
        ("HSD-4821", "HSD-48", False),  # two deletions
        ("", "A", True),
    ],
)
def test_one_edit_apart(left, right, expected):
    assert _one_edit_apart(left, right) is expected
    assert _one_edit_apart(right, left) is expected


# ------------------------------------------------------------- refusals


def test_a_journey_without_a_specification_is_refused():
    journey, fixture = load_journey_inputs(JOURNEY_DIR)
    object.__setattr__(journey, "journey_id", "no-such-journey")
    with pytest.raises(ProbeError, match="no Opening specification"):
        openings(journey, fixture)


def test_a_specification_naming_an_unrequired_rule_is_refused(tmp_path, monkeypatch):
    journey, fixture = load_journey_inputs(JOURNEY_DIR)
    monkeypatch.setitem(
        JOURNEY_SPECS,
        journey.journey_id,
        (
            OpeningSpec(
                rule_id="not_a_required_rule",
                kind=COLLISION,
                collection="appointments",
                id_field="appointment_id",
                params={"describe_by": ("service",)},
            ),
        ),
    )
    with pytest.raises(ProbeError, match="which Journey .* does not require"):
        openings(journey, fixture)


def test_a_missing_collection_is_refused_rather_than_read_as_empty():
    """``load_fixture_state`` already requires every collection, so this can
    only be reached by a Fixture state built in code. It still refuses rather
    than reporting a rule as having no Opening."""
    journey = load_journey_definition(JOURNEY_DIR / "journey.yaml")
    without_slots = FixtureState(
        data={key: value for key, value in FIXTURE_RAW.items() if key != "slots"},
        source="built in a test",
    )
    with pytest.raises(ProbeError, match="no 'slots' collection"):
        openings(journey, without_slots)


def test_a_collection_that_is_not_a_list_of_rows_is_refused():
    journey = load_journey_definition(JOURNEY_DIR / "journey.yaml")
    not_rows = FixtureState(
        data={**FIXTURE_RAW, "slots": "S-101"}, source="built in a test"
    )
    with pytest.raises(ProbeError, match="is not a list of rows"):
        openings(journey, not_rows)


def test_an_unknown_kind_is_refused(monkeypatch):
    journey, fixture = load_journey_inputs(JOURNEY_DIR)
    monkeypatch.setitem(
        JOURNEY_SPECS,
        journey.journey_id,
        (
            OpeningSpec(
                rule_id="identify_existing_appointment",
                kind="invented",
                collection="appointments",
                id_field="appointment_id",
            ),
        ),
    )
    with pytest.raises(ProbeError, match="unknown Opening kind"):
        openings(journey, fixture)
