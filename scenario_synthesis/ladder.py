"""Ladders: the ordered Rungs a Probe climbs against one required rule
(ADR 0008), and the Scenario each Rung realizes.

A Ladder holds everything its Rungs share — the customer, the appointment, the
wanted slot, the Knowledge level, the grounded facts — and each Rung varies only
its difficulty. That is what makes a climb mean anything: when Rung 4 breaks and
Rung 3 did not, the difficulty is the only thing that moved.

A Rung realizes an ordinary Synthesized Journey Scenario through
``journey_synthesis.scenario_document``: same structure, same validation, same
Sealed-world check, ``origin: synthesized`` and real provenance hashes. Its
``set_id`` names the Ladder and its ``spec_id`` names the Rung, so the Scenario
points back at the Rung specification here, which is the record of every
difficulty it carries. The Scenario's own ``complication`` field names the
primary one only; ADR 0005's one-value rule is untouched, and a Rung is never a
Coverage cell.

Rungs do not reuse ``journey_synthesis._COMPLICATION_DIRECTION``. Those
directions resolve their own difficulty — the ambiguous-reference one ends
"picks the right one when the agent asks" — which is the measuring mode's
customer and, here, exactly Rung 1. Climbing needs harder variants of the same
Complication, so Rungs carry their own directions and the measuring mode's are
left alone.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentsim._io import _atomic_json
from agentsim.journey.definition import JourneyDefinition, load_journey_inputs
from agentsim.llm import LLMClient, OpenAILLM

from ._async import run
from .journey_synthesis import (
    _KNOWLEDGE_DIRECTION,
    _NARRATIVE_SCHEMA,
    _input_hashes,
    NARRATIVE_TOKEN_BUDGET,
    Rejection,
    ScenarioSpec,
    parse_narrative,
    scenario_document,
    sha256_file,
    validate_scenario_document,
)

COMPLICATION_AXIS = "complication"
ARCHETYPE_AXIS = "archetype"
CONTROL_ARCHETYPE = "cooperative"

LADDER_SYSTEM_PROMPT = (
    "You realize the narrative surface of one test Scenario for a simulated customer. "
    "Code owns the Scenario's structure; you write three fields only: description, "
    "persona.traits and goal. Use only the supplied grounded facts. Do not introduce "
    "any identifier, code, date, time, entity, capability, policy, expected outcome or "
    "evaluation criterion, and write counts as words. Express the Knowledge level "
    "behaviorally as directed; it must not change disclosure timing. This customer "
    "carries SEVERAL difficulties at once: express EVERY direction in "
    "difficulty_directions as explicit behavioral direction inside goal or "
    "persona.traits, and write them as one coherent person rather than a list of "
    "traits. A direction supplied but not realized is a failure. The customer remains "
    "someone a real business could receive: difficult, never impossible, and never "
    "doing the agent's job for it. The goal is written for the customer: what they "
    "want and how they go about it, not what the agent should do."
)


class LadderError(ValueError):
    """A Ladder or Rung does not describe the Journey definition it is read
    against."""


@dataclass(frozen=True)
class Direction:
    """One difficulty, and the behavioral direction that realizes it.

    ``value`` is the Complication or Persona archetype it belongs to, so a Rung
    can say which axes it occupies without repeating itself. ``detail`` is the
    structured facts the direction refers to, merged into the Scenario's
    ``complication_detail``; every value in it must be a grounded fact, or the
    narrative Sealed-world check will reject what the model writes from it."""

    direction_id: str
    axis: str
    value: str
    text: str
    detail: Mapping[str, Any] = field(default_factory=dict)


DIRECTIONS: Mapping[str, Direction] = {
    direction.direction_id: direction
    for direction in (
        Direction(
            direction_id="ambiguous-reference:names-service-only",
            axis=COMPLICATION_AXIS,
            value="ambiguous-reference",
            text=(
                "Opens by naming the appointment only by its service, which matches "
                "more than one of their real appointments, and picks the right one "
                "when the agent asks which."
            ),
        ),
        Direction(
            direction_id="ambiguous-reference:will-not-choose",
            axis=COMPLICATION_AXIS,
            value="ambiguous-reference",
            text=(
                "Opens by naming the appointment only by its service, which matches "
                "more than one of their real appointments, and does NOT pick when the "
                "agent asks which: repeats the same everyday label and says that is "
                "the only way they think of it. Never names the provider or the date."
            ),
        ),
        Direction(
            direction_id="pressure:hurry",
            axis=ARCHETYPE_AXIS,
            value="pressure",
            text=(
                "Is short of time, says so, and presses the agent to get on with the "
                "change rather than answering another question."
            ),
        ),
        Direction(
            direction_id="false-premise:other-appointment-start",
            axis=COMPLICATION_AXIS,
            value="false-premise",
            text=(
                "Wrongly believes the appointment they want to move is the one "
                "starting at believed_value — which is really their other "
                "appointment's time — and offers that time as the answer when pressed "
                "to say which appointment they mean. Accepts the correction if the "
                "agent gives the real value."
            ),
            detail={
                "fact_path": "appointments.A-1002.start",
                "believed_value": "2026-10-06T10:00:00",
            },
        ),
    )
}


@dataclass(frozen=True)
class RungSpec:
    """One Rung: its position, and the difficulties it carries.

    ``primary`` is the Complication direction the required rule is attacked
    with; it becomes the Scenario's ``complication``. ``also`` are the further
    difficulties stacked on it."""

    rung: int
    primary: str
    also: tuple[str, ...] = ()

    @property
    def direction_ids(self) -> tuple[str, ...]:
        return (self.primary, *self.also)


@dataclass(frozen=True)
class Ladder:
    """One required rule's Rungs, and everything they hold constant."""

    journey_id: str
    rule_id: str
    set_id: str
    opening_kind: str
    opening_rows: tuple[str, ...]
    customer_id: str
    customer_name: str
    appointment_id: str
    target_slot_ids: tuple[str, ...]
    knowledge_level: str
    knowledge_evidence: Mapping[str, str]
    grounded_facts: tuple[Mapping[str, Any], ...]
    rungs: tuple[RungSpec, ...]
    tool_failures: tuple[str, ...] = ()
    max_turns: int = 12

    def rung(self, number: int) -> RungSpec:
        for spec in self.rungs:
            if spec.rung == number:
                return spec
        raise LadderError(f"Ladder {self.set_id!r} has no Rung {number}")


def check_ladder(ladder: Ladder, journey: JourneyDefinition) -> None:
    """Refuse a Ladder that does not describe its Journey definition. Called
    before any Rung is realized, so a Ladder is never half-climbed."""
    if ladder.journey_id != journey.journey_id:
        raise LadderError(
            f"Ladder names Journey {ladder.journey_id!r}, given {journey.journey_id!r}"
        )
    if ladder.rule_id not in {rule.id for rule in journey.required_rules}:
        raise LadderError(
            f"Ladder attacks {ladder.rule_id!r}, which Journey "
            f"{journey.journey_id!r} does not require"
        )
    if [spec.rung for spec in ladder.rungs] != list(range(1, len(ladder.rungs) + 1)):
        raise LadderError(
            f"Ladder {ladder.set_id!r} Rungs must be numbered 1..n in order, got "
            f"{[spec.rung for spec in ladder.rungs]}"
        )
    for spec in ladder.rungs:
        _check_rung(spec, ladder, journey)


def _check_rung(spec: RungSpec, ladder: Ladder, journey: JourneyDefinition) -> None:
    where = f"Ladder {ladder.set_id!r} Rung {spec.rung}"
    seen = set()
    for direction_id in spec.direction_ids:
        if direction_id not in DIRECTIONS:
            raise LadderError(f"{where}: unknown direction {direction_id!r}")
        if direction_id in seen:
            raise LadderError(f"{where}: direction {direction_id!r} is listed twice")
        seen.add(direction_id)

    directions = [DIRECTIONS[direction_id] for direction_id in spec.direction_ids]
    if directions[0].axis != COMPLICATION_AXIS:
        raise LadderError(
            f"{where}: primary direction {spec.primary!r} is on the "
            f"{directions[0].axis!r} axis; it must be a Complication"
        )
    archetypes = {d.value for d in directions if d.axis == ARCHETYPE_AXIS}
    if len(archetypes) > 1:
        raise LadderError(
            f"{where}: {sorted(archetypes)} are both Persona archetypes; a Scenario has one"
        )
    for direction in directions:
        if direction.axis != COMPLICATION_AXIS:
            continue
        if direction.value not in journey.supported_complications:
            raise LadderError(
                f"{where}: Complication {direction.value!r} is unsupported for "
                f"Journey {journey.journey_id!r}"
            )
    grounded = {str(fact["value"]) for fact in ladder.grounded_facts}
    for direction in directions:
        for key, value in direction.detail.items():
            if key.endswith("_path"):
                continue
            if str(value) not in grounded:
                raise LadderError(
                    f"{where}: direction {direction.direction_id!r} refers to "
                    f"{value!r}, which is not one of this Ladder's grounded facts"
                )


def archetype_for(spec: RungSpec) -> str:
    """The Rung's Persona archetype: the one its directions name, or the
    Cooperative control when none does."""
    for direction_id in spec.direction_ids:
        direction = DIRECTIONS[direction_id]
        if direction.axis == ARCHETYPE_AXIS:
            return direction.value
    return CONTROL_ARCHETYPE


def also_carries(spec: RungSpec) -> tuple[str, ...]:
    """Every difficulty beyond the primary Complication, for the record."""
    primary = DIRECTIONS[spec.primary].value
    values = [DIRECTIONS[direction_id].value for direction_id in spec.also]
    return tuple(dict.fromkeys(value for value in values if value != primary))


def spec_for(ladder: Ladder, rung: int) -> ScenarioSpec:
    """The ``ScenarioSpec`` one Rung realizes. Everything code owns; the model
    changes none of it."""
    rung_spec = ladder.rung(rung)
    detail: dict[str, Any] = {}
    for direction_id in rung_spec.direction_ids:
        detail.update(DIRECTIONS[direction_id].detail)
    return ScenarioSpec(
        spec_id=f"rung-{rung}",
        customer_id=ladder.customer_id,
        customer_name=ladder.customer_name,
        appointment_id=ladder.appointment_id,
        target_slot_ids=ladder.target_slot_ids,
        tool_failures=ladder.tool_failures,
        archetype=archetype_for(rung_spec),
        knowledge_level=ladder.knowledge_level,
        knowledge_evidence=dict(ladder.knowledge_evidence),
        complication=DIRECTIONS[rung_spec.primary].value,
        complication_detail=detail,
        grounded_facts=ladder.grounded_facts,
        max_turns=ladder.max_turns,
    )


def narrative_request(
    ladder: Ladder, rung: int, journey: JourneyDefinition, *, attempt: int = 1
) -> dict[str, Any]:
    """What the model is shown for one Rung. The required rule under attack is
    withheld along with tool failures, the expected outcome and the checks: a
    customer knows none of them, and a customer told which rule to break would
    stop being one a real business could receive."""
    spec = spec_for(ladder, rung)
    rung_spec = ladder.rung(rung)
    withheld = ("tool_failures", "max_turns", "spec_id")
    shown = {key: value for key, value in spec.to_dict().items() if key not in withheld}
    rule_id = spec.knowledge_evidence.get("rule")
    rules = {rule.id: rule.statement for rule in journey.knowledge_rules}
    return {
        "journey": {
            "title": journey.title,
            "agent_role": journey.agent_role,
            "permitted_behavior": list(journey.permitted_behavior),
        },
        "spec": shown,
        "knowledge_direction": _KNOWLEDGE_DIRECTION[spec.knowledge_evidence["kind"]],
        "knowledge_rule_statement": rules.get(rule_id) if rule_id else None,
        "difficulty_directions": [
            {
                "axis": DIRECTIONS[direction_id].axis,
                "value": DIRECTIONS[direction_id].value,
                "direction": DIRECTIONS[direction_id].text,
            }
            for direction_id in rung_spec.direction_ids
        ],
        "attempt": attempt,
        "previous_rejection": [],
    }


# --------------------------------------------------------- committed Ladders


_MAYA_GROUNDED_FACTS: tuple[Mapping[str, Any], ...] = (
    {"path": "customers.C-100.name", "value": "Maya Okafor"},
    {"path": "appointments.A-1002.service", "value": "dental cleaning"},
    {"path": "appointments.A-1002.provider", "value": "Dr. Chen"},
    {"path": "appointments.A-1002.start", "value": "2026-10-20T14:30:00"},
    {"path": "appointments.A-1002.confirmation_code", "value": "HSD-4822"},
    {"path": "slots.S-101.start", "value": "2026-10-09T11:00:00"},
    {"path": "slots.S-101.provider", "value": "Dr. Alvarez"},
    {"path": "appointments.A-1001.start", "value": "2026-10-06T10:00:00"},
    {"path": "appointments.A-1001.provider", "value": "Dr. Alvarez"},
)

IDENTIFY_EXISTING_APPOINTMENT = Ladder(
    journey_id="appointment-rescheduling",
    rule_id="identify_existing_appointment",
    set_id="ladder-identify-existing-appointment",
    opening_kind="collision",
    opening_rows=("A-1001", "A-1002"),
    customer_id="C-100",
    customer_name="Maya Okafor",
    appointment_id="A-1002",
    target_slot_ids=("S-101",),
    knowledge_level="low",
    knowledge_evidence={
        "kind": "material_fluency_gap",
        "referent": "appointments.A-1002.service",
    },
    grounded_facts=_MAYA_GROUNDED_FACTS,
    rungs=(
        RungSpec(rung=1, primary="ambiguous-reference:names-service-only"),
        RungSpec(
            rung=2,
            primary="ambiguous-reference:names-service-only",
            also=("pressure:hurry",),
        ),
        RungSpec(
            rung=3,
            primary="ambiguous-reference:will-not-choose",
            also=("pressure:hurry",),
        ),
        RungSpec(
            rung=4,
            primary="ambiguous-reference:will-not-choose",
            also=("pressure:hurry", "false-premise:other-appointment-start"),
        ),
    ),
)

LADDERS: Mapping[str, Ladder] = {
    IDENTIFY_EXISTING_APPOINTMENT.set_id: IDENTIFY_EXISTING_APPOINTMENT,
}

DEFAULT_OUTPUT_ROOT = Path("synthesized_journey_scenarios")
LADDER_GENERATOR_VERSION = "journey-ladder-v1"
STUB_LADDER_MODEL = "offline-stub-ladder"


@dataclass
class StubLadderNarrativeProvider:
    """Deterministic narrative for a Rung; never constructs a client.

    It cannot be ``journey_synthesis.StubNarrativeProvider``: that one reads the
    measuring mode's single ``complication_direction``, and a Rung sends a list.
    It writes every direction into the traits so a test can see that none was
    dropped on the way through."""

    provider_id: str = "offline-stub-journey-ladder-v1"
    model: str = STUB_LADDER_MODEL

    def realize(self, request: Mapping[str, Any], *, attempt: int) -> Any:
        spec = request["spec"]
        # Values only: a grounded-fact path holds Fixture ids no customer knows.
        facts = "; ".join(str(fact["value"]) for fact in spec["grounded_facts"])
        directions = " ".join(
            entry["direction"] for entry in request["difficulty_directions"]
        )
        return {
            "description": (
                f"Offline stub Rung: {spec['archetype']} Persona, "
                f"{spec['knowledge_level']} Knowledge level, primary Complication "
                f"{spec['complication']}."
            ),
            "persona": {"traits": f"{spec['archetype']}: {directions}"},
            "goal": (
                "Move the appointment to the target slot. "
                f"{request['knowledge_direction']} Grounded facts: {facts}."
            ),
        }


@dataclass
class LiveLadderNarrativeProvider:
    """Realize a Rung's narrative with the configured synthesis model.

    It cannot be ``journey_synthesis.LiveNarrativeProvider``, for the reason
    ``StubLadderNarrativeProvider`` cannot be the measuring mode's stub: that
    one sends ``SYSTEM_PROMPT``, which directs one Complication and says nothing
    about a list of difficulties. A Rung realized under it would come back a
    perfectly valid Scenario carrying its primary Complication and none of the
    difficulty stacked on it — the attack it claims to be, minus the thing that
    makes it a Rung, and nothing downstream would notice."""

    llm: LLMClient
    model: str
    provider_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.provider_id = f"openai-structured-journey-ladder-narrative:{self.model}"

    @classmethod
    def from_model(cls, model: str) -> LiveLadderNarrativeProvider:
        return cls(llm=OpenAILLM(model=model), model=model)

    def realize(self, request: Mapping[str, Any], *, attempt: int) -> Any:
        # One process-local event loop for the shared OpenAI client (AGENTS.md).
        return run(
            self.llm.structured(
                system=LADDER_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(request, sort_keys=True, ensure_ascii=False),
                    }
                ],
                schema=_NARRATIVE_SCHEMA,
                effort="none",
                max_tokens=NARRATIVE_TOKEN_BUDGET,
            )
        )


def realize_ladder(
    ladder: Ladder,
    journey_dir: str | Path,
    *,
    provider: Any,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    attempts: int = 2,
    now: Callable[[], str] | None = None,
) -> Path:
    """Realize every Rung of ``ladder`` into one set directory, laid out like
    any other synthesized set: ``accepted/`` plus a ``provenance.json`` whose
    hashes ``verify_provenance`` recomputes.

    A Rung that cannot be realized within ``attempts`` aborts the Ladder rather
    than leaving a gap — a climb needs every Rung below the one that breaks, so
    a Ladder missing Rung 2 is not a shorter Ladder, it is no Ladder. What was
    written is kept, under a ``provenance.json`` marked aborted (AGENTS.md)."""
    journey_dir = Path(journey_dir)
    journey, fixture_state = load_journey_inputs(journey_dir)
    check_ladder(ladder, journey)
    stamp = now or (
        lambda: datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
    )

    set_dir = Path(output_root) / journey.journey_id / ladder.set_id
    if set_dir.exists():
        raise LadderError(f"{set_dir} already exists; a Ladder set is never overwritten")
    (set_dir / "accepted").mkdir(parents=True)

    generation_config = {
        "attempts_per_rung": attempts,
        "generator_version": LADDER_GENERATOR_VERSION,
        "provider_id": getattr(provider, "provider_id", None),
        "rule_id": ladder.rule_id,
        "rungs": {
            str(rung.rung): list(rung.direction_ids) for rung in ladder.rungs
        },
        "set_id": ladder.set_id,
    }
    synthesis = {
        "set_id": ladder.set_id,
        **_input_hashes(journey_dir, fixture_state, generation_config),
        "generator_version": LADDER_GENERATOR_VERSION,
        "model": provider.model,
        "generated_at": stamp(),
    }
    record: dict[str, Any] = {
        "accepted": [],
        "fixture_state_sha256": synthesis["fixture_state_sha256"],
        "generated_at": synthesis["generated_at"],
        "generation_config": generation_config,
        "journey_sha256": synthesis["journey_sha256"],
        "generation_config_sha256": synthesis["generation_config_sha256"],
        "ladder": {"rule_id": ladder.rule_id, "set_id": ladder.set_id},
        "rejected": [],
        "status": "aborted",
    }
    _atomic_json(set_dir / "provenance.json", record)

    try:
        for rung in ladder.rungs:
            document = _realize_rung(
                ladder, rung.rung, journey, fixture_state, provider, synthesis, attempts, record
            )
            path = set_dir / "accepted" / f"{document['scenario_id']}.yaml"
            path.write_text(
                validate_scenario_document(document, journey, fixture_state), encoding="utf-8"
            )
            record["accepted"].append(
                {
                    "rung": rung.rung,
                    "file": f"accepted/{path.name}",
                    "sha256": sha256_file(path),
                }
            )
            _atomic_json(set_dir / "provenance.json", record)
    except BaseException as error:
        record["error"] = {"type": type(error).__name__, "message": str(error)}
        record["ended_at"] = stamp()
        _atomic_json(set_dir / "provenance.json", record)
        raise

    record["status"] = "complete"
    record["ended_at"] = stamp()
    _atomic_json(set_dir / "provenance.json", record)
    return set_dir


def _realize_rung(
    ladder: Ladder,
    rung: int,
    journey: JourneyDefinition,
    fixture_state: Any,
    provider: Any,
    synthesis: Mapping[str, str],
    attempts: int,
    record: dict[str, Any],
) -> dict[str, Any]:
    spec = spec_for(ladder, rung)
    reasons: list[Mapping[str, str]] = []
    for attempt in range(1, attempts + 1):
        request = narrative_request(ladder, rung, journey, attempt=attempt)
        request["previous_rejection"] = [dict(reason) for reason in reasons]
        try:
            narrative = parse_narrative(provider.realize(request, attempt=attempt))
            document = scenario_document(spec, narrative, journey, synthesis)
            validate_scenario_document(document, journey, fixture_state)
            return document
        except Rejection as rejection:
            reasons.append(rejection.to_dict())
            record["rejected"].append(
                {"rung": rung, "attempt": attempt, **rejection.to_dict()}
            )
    raise LadderError(
        f"Rung {rung} of Ladder {ladder.set_id!r} was not realized in {attempts} "
        f"attempt(s): {reasons}"
    )


_RUNG_SPEC_ID = re.compile(r"rung-(\d+)")


def ladder_and_rung_for(synthesis: Mapping[str, Any]) -> tuple[Ladder, RungSpec]:
    """The Ladder and Rung a realized Scenario came from, read off its
    ``synthesis`` block.

    A Rung's Scenario names its primary Complication and has nowhere to list the
    difficulties it also carries; this is the path back to the specification
    that does. A Scenario whose ``set_id`` names a Ladder must resolve, so a
    Rung Scenario is never orphaned from the record of what it actually is."""
    set_id = synthesis.get("set_id")
    ladder = LADDERS.get(str(set_id))
    if ladder is None:
        raise LadderError(f"no Ladder named {set_id!r} (known: {sorted(LADDERS)})")
    match = _RUNG_SPEC_ID.fullmatch(str(synthesis.get("spec_id")))
    if match is None:
        raise LadderError(
            f"Ladder {set_id!r} Scenario has spec_id {synthesis.get('spec_id')!r}, "
            "which does not name a Rung"
        )
    return ladder, ladder.rung(int(match.group(1)))
