"""The Scenario seam for Journeys outside payments: a parallel strict loader
for the synthesized Scenario schema (design note section 6).

``agentsim/scenario.py`` is not edited. Its closed ``JOURNEYS`` rejects these
files, and this loader rejects payments files, so neither path can pick up the
other's Scenarios. ``JourneyScenario`` exposes ``name`` and ``source``, which is
all ``BatchRunSpec`` reads.

``load_journey_scenario`` validates the file on its own. Whether the Scenario
still fits the Journey definition and Fixture state it is about to run against
is ``check_against_inputs`` — a Scenario whose Fixture bindings dangle would
otherwise surface as an agent failure. Neither establishes Qualification or
Admission; ``synthesis.qualification`` says ``none``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import checks
from ._strict import (
    _list,
    _load_yaml,
    _mapping,
    _positive_int,
    _schema_version,
    _strict,
    _string,
    _unique_strings,
)
from .definition import (
    COMPLICATION_IDS,
    RESCHEDULABLE_STATUS,
    SUPPORTED_TOOL_FAILURES,
    FixtureState,
    FixtureStateError,
    JourneyDefinition,
)

# Shared closed sets (CONTEXT.md); pinned equal to the reviewed contract
# constants in ``scenario_synthesis.contracts`` by a test.
ARCHETYPE_IDS: frozenset[str] = frozenset(
    {"cooperative", "pressure", "vigilant", "persistent"}
)
KNOWLEDGE_LEVELS: frozenset[str] = frozenset({"low", "medium", "high"})

_PAYMENTS_JOURNEY = re.compile(r"^J\d+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SYNTHESIS_HASHES = (
    "journey_sha256", "fixture_state_sha256", "generation_config_sha256",
)
_SYNTHESIS_STRINGS = ("set_id", "spec_id", "generator_version", "model", "generated_at")


class JourneyScenarioError(ValueError):
    """A Journey Scenario file failed validation."""


@dataclass(frozen=True)
class JourneyPersona:
    archetype: str
    name: str
    traits: str


@dataclass(frozen=True)
class KnowledgeEvidence:
    """What this Scenario's Knowledge level is to be evidenced by: a Journey
    ``knowledge_rules`` id or a Fixture referent, never both (ADR 0006)."""

    kind: str
    rule: str | None
    referent: str | None


@dataclass(frozen=True)
class FixtureBinding:
    customer_id: str
    appointment_id: str
    target_slot_ids: tuple[str, ...]
    tool_failures: tuple[str, ...]


@dataclass(frozen=True)
class GroundedFact:
    path: str
    value: Any


@dataclass(frozen=True)
class JourneySynthesis:
    set_id: str
    spec_id: str
    journey_sha256: str
    fixture_state_sha256: str
    generation_config_sha256: str
    generator_version: str
    model: str
    generated_at: str
    origin: str = "synthesized"
    qualification: str = "none"


@dataclass(frozen=True)
class JourneyScenario:
    scenario_id: str
    journey: str
    description: str
    persona: JourneyPersona
    goal: str
    knowledge_level: str
    knowledge_evidence: KnowledgeEvidence
    complication: str
    fixture: FixtureBinding
    grounded_facts: tuple[GroundedFact, ...]
    max_turns: int
    expected_outcome: str
    assertion_ids: tuple[str, ...]
    judge_criterion_ids: tuple[str, ...]
    synthesis: JourneySynthesis
    source: str  # the file it was loaded from, for error/report context

    @property
    def name(self) -> str:
        return self.scenario_id


def load_journey_scenario(path: str | Path) -> JourneyScenario:
    path = Path(path)
    where = path.name
    error = JourneyScenarioError
    raw = _load_yaml(path, error=error)
    journey = raw.get("journey")
    if isinstance(journey, str) and _PAYMENTS_JOURNEY.fullmatch(journey):
        raise error(
            f"{where}: journey {journey!r} is a payments Scenario; "
            "load it with agentsim.scenario"
        )
    _strict(
        raw,
        {
            "schema_version", "scenario_id", "journey", "description", "persona",
            "goal", "knowledge_level", "knowledge_evidence", "complication",
            "fixture", "grounded_facts", "max_turns", "expected_outcome",
            "criteria", "synthesis",
        },
        where,
        error=error,
    )
    _schema_version(raw["schema_version"], where, error=error)

    journey = _string(journey, f"{where}: journey", error=error)
    scenario_id = _string(raw["scenario_id"], f"{where}: scenario_id", error=error)
    if re.fullmatch(rf"synth-{re.escape(journey)}-[0-9a-f]{{12}}", scenario_id) is None:
        raise error(
            f"{where}: scenario_id {scenario_id!r} must be "
            f"'synth-{journey}-<12 hex>'"
        )

    expected_outcome = _string(
        raw["expected_outcome"], f"{where}: expected_outcome", error=error
    )
    if expected_outcome not in checks.OUTCOME_IDS:
        raise error(
            f"{where}: unknown expected_outcome {expected_outcome!r} "
            f"(known: {sorted(checks.OUTCOME_IDS)})"
        )
    assertion_ids, judge_ids = _parse_criteria(raw["criteria"], where)

    return JourneyScenario(
        scenario_id=scenario_id,
        journey=journey,
        description=_string(raw["description"], f"{where}: description", error=error),
        persona=_parse_persona(raw["persona"], where),
        goal=_string(raw["goal"], f"{where}: goal", error=error),
        knowledge_level=_closed(
            raw["knowledge_level"], KNOWLEDGE_LEVELS, f"{where}: knowledge_level"
        ),
        knowledge_evidence=_parse_knowledge_evidence(raw["knowledge_evidence"], where),
        complication=_closed(
            raw["complication"], COMPLICATION_IDS, f"{where}: complication"
        ),
        fixture=_parse_fixture(raw["fixture"], where),
        grounded_facts=_parse_grounded_facts(raw["grounded_facts"], where),
        max_turns=_positive_int(raw["max_turns"], f"{where}: max_turns", error=error),
        expected_outcome=expected_outcome,
        assertion_ids=assertion_ids,
        judge_criterion_ids=judge_ids,
        synthesis=_parse_synthesis(raw["synthesis"], where),
        source=str(path),
    )


def _closed(value: Any, allowed: frozenset[str], where: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise JourneyScenarioError(
            f"{where} must be one of {sorted(allowed)}, got {value!r}"
        )
    return value


def _parse_persona(raw: Any, where: str) -> JourneyPersona:
    error = JourneyScenarioError
    spot = f"{where}: persona"
    persona = _mapping(raw, spot, error=error)
    _strict(persona, {"archetype", "name", "traits"}, spot, error=error)
    return JourneyPersona(
        archetype=_closed(persona["archetype"], ARCHETYPE_IDS, f"{spot}.archetype"),
        name=_string(persona["name"], f"{spot}.name", error=error),
        traits=_string(persona["traits"], f"{spot}.traits", error=error),
    )


def _parse_knowledge_evidence(raw: Any, where: str) -> KnowledgeEvidence:
    error = JourneyScenarioError
    spot = f"{where}: knowledge_evidence"
    evidence = _mapping(raw, spot, error=error)
    _strict(
        evidence, {"kind"}, spot, error=error, optional=frozenset({"rule", "referent"})
    )
    if ("rule" in evidence) == ("referent" in evidence):
        raise error(f"{spot} must carry exactly one of 'rule' or 'referent'")
    return KnowledgeEvidence(
        kind=_string(evidence["kind"], f"{spot}.kind", error=error),
        rule=(
            _string(evidence["rule"], f"{spot}.rule", error=error)
            if "rule" in evidence
            else None
        ),
        referent=(
            _string(evidence["referent"], f"{spot}.referent", error=error)
            if "referent" in evidence
            else None
        ),
    )


def _parse_fixture(raw: Any, where: str) -> FixtureBinding:
    error = JourneyScenarioError
    spot = f"{where}: fixture"
    fixture = _mapping(raw, spot, error=error)
    _strict(
        fixture,
        {"customer_id", "appointment_id", "target_slot_ids", "tool_failures"},
        spot,
        error=error,
    )
    tool_failures = _unique_strings(
        fixture["tool_failures"], f"{spot}.tool_failures", error=error, allow_empty=True
    )
    unsupported = set(tool_failures) - SUPPORTED_TOOL_FAILURES
    if unsupported:
        raise error(
            f"{spot}.tool_failures: {sorted(unsupported)} has no supported controlled "
            f"failure (supported: {sorted(SUPPORTED_TOOL_FAILURES)})"
        )
    return FixtureBinding(
        customer_id=_string(fixture["customer_id"], f"{spot}.customer_id", error=error),
        appointment_id=_string(
            fixture["appointment_id"], f"{spot}.appointment_id", error=error
        ),
        target_slot_ids=_unique_strings(
            fixture["target_slot_ids"], f"{spot}.target_slot_ids", error=error
        ),
        tool_failures=tool_failures,
    )


def _parse_grounded_facts(raw: Any, where: str) -> tuple[GroundedFact, ...]:
    error = JourneyScenarioError
    facts: list[GroundedFact] = []
    for i, item in enumerate(_list(raw, f"{where}: grounded_facts", error=error)):
        spot = f"{where}: grounded_facts[{i}]"
        fact = _mapping(item, spot, error=error)
        _strict(fact, {"path", "value"}, spot, error=error)
        facts.append(
            GroundedFact(
                path=_string(fact["path"], f"{spot}.path", error=error),
                value=fact["value"],
            )
        )
    return tuple(facts)


def _parse_criteria(raw: Any, where: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    error = JourneyScenarioError
    spot = f"{where}: criteria"
    criteria = _mapping(raw, spot, error=error)
    _strict(criteria, {"assertions", "judge"}, spot, error=error)
    assertion_ids = _unique_strings(
        criteria["assertions"], f"{spot}.assertions", error=error
    )
    judge_ids = _unique_strings(criteria["judge"], f"{spot}.judge", error=error)
    unknown = sorted(set(assertion_ids) - set(checks.ASSERTIONS))
    if unknown:
        raise error(
            f"{spot}.assertions: unknown Assertion(s) {unknown} "
            f"(known: {sorted(checks.ASSERTIONS)})"
        )
    unknown = sorted(set(judge_ids) - set(checks.JUDGE_CRITERIA))
    if unknown:
        raise error(
            f"{spot}.judge: unknown Judge criterion(s) {unknown} "
            f"(known: {sorted(checks.JUDGE_CRITERIA)})"
        )
    return assertion_ids, judge_ids


def _parse_synthesis(raw: Any, where: str) -> JourneySynthesis:
    error = JourneyScenarioError
    spot = f"{where}: synthesis"
    synthesis = _mapping(raw, spot, error=error)
    _strict(
        synthesis,
        {"origin", "qualification", *_SYNTHESIS_HASHES, *_SYNTHESIS_STRINGS},
        spot,
        error=error,
    )
    if synthesis["origin"] != "synthesized":
        raise error(f"{spot}.origin must be 'synthesized'")
    if synthesis["qualification"] != "none":
        raise error(
            f"{spot}.qualification must be 'none': validation is not Qualification "
            "or Admission"
        )
    for key in _SYNTHESIS_HASHES:
        value = synthesis[key]
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise error(f"{spot}.{key} must be a lowercase SHA-256 digest")
    return JourneySynthesis(
        **{key: synthesis[key] for key in _SYNTHESIS_HASHES},
        **{
            key: _string(synthesis[key], f"{spot}.{key}", error=error)
            for key in _SYNTHESIS_STRINGS
        },
    )


# ------------------------------------------- fit against the current inputs


def check_against_inputs(
    scenario: JourneyScenario, journey: JourneyDefinition, fixture_state: FixtureState
) -> None:
    """Raise ``JourneyScenarioError`` unless the Scenario fits this Journey
    definition and Fixture state: every id resolves, the bindings belong to
    the Scenario's customer, the target slots can actually be booked, every
    grounded fact equals Fixture state, and the derived fields are what the
    Journey definition derives."""
    where = Path(scenario.source).name

    def fail(message: str) -> JourneyScenarioError:
        return JourneyScenarioError(f"{where}: {message}")

    if scenario.journey != journey.journey_id:
        raise fail(
            f"journey {scenario.journey!r} is not the Journey definition's "
            f"{journey.journey_id!r}"
        )
    if scenario.complication not in journey.supported_complications:
        reason = journey.unsupported_complications.get(scenario.complication, "")
        raise fail(
            f"complication {scenario.complication!r} is unsupported for this Journey"
            + (f": {reason}" if reason else "")
        )

    binding = scenario.fixture
    customer = fixture_state.customer(binding.customer_id)
    if customer is None:
        raise fail(f"fixture.customer_id {binding.customer_id!r} is not in Fixture state")
    if scenario.persona.name != customer["name"]:
        raise fail(
            f"persona.name {scenario.persona.name!r} is not the Fixture customer's "
            f"name {customer['name']!r}"
        )
    appointment = fixture_state.appointment(binding.appointment_id)
    if appointment is None:
        raise fail(
            f"fixture.appointment_id {binding.appointment_id!r} is not in Fixture state"
        )
    if appointment["customer_id"] != binding.customer_id:
        raise fail(
            f"appointment {binding.appointment_id!r} does not belong to customer "
            f"{binding.customer_id!r}"
        )
    if appointment["status"] != RESCHEDULABLE_STATUS:
        raise fail(
            f"appointment {binding.appointment_id!r} is {appointment['status']!r}, "
            "so it cannot be rescheduled"
        )
    now = datetime.fromisoformat(fixture_state.now)
    for slot_id in binding.target_slot_ids:
        slot = fixture_state.slot(slot_id)
        if slot is None:
            raise fail(f"fixture.target_slot_ids: {slot_id!r} is not in Fixture state")
        if not slot["available"] or datetime.fromisoformat(slot["start"]) <= now:
            raise fail(f"target slot {slot_id!r} is not open for booking")
        if slot["service"] != appointment["service"]:
            raise fail(
                f"target slot {slot_id!r} is for {slot['service']!r}, not the "
                f"appointment's {appointment['service']!r}"
            )

    for fact in scenario.grounded_facts:
        try:
            actual = fixture_state.fact(fact.path)
        except FixtureStateError as exc:
            raise fail(f"grounded_facts: {exc}") from None
        if actual != fact.value or type(actual) is not type(fact.value):
            raise fail(
                f"grounded fact {fact.path!r} is {fact.value!r} in the Scenario but "
                f"{actual!r} in Fixture state"
            )

    rule = scenario.knowledge_evidence.rule
    if rule is not None and rule not in {r.id for r in journey.knowledge_rules}:
        raise fail(f"knowledge_evidence.rule {rule!r} is not a Journey knowledge rule")

    expected = journey.outcome_for(binding.tool_failures)
    if scenario.expected_outcome != expected:
        raise fail(
            f"expected_outcome {scenario.expected_outcome!r} is not what the Journey "
            f"definition derives for tool_failures {list(binding.tool_failures)}: "
            f"{expected!r}"
        )
    if scenario.assertion_ids != journey.assertion_ids:
        raise fail("criteria.assertions differ from the Journey definition's")
    if scenario.judge_criterion_ids != journey.judge_criterion_ids:
        raise fail("criteria.judge differ from the Journey definition's")
