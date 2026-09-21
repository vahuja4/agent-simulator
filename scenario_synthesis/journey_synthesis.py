"""Scenario synthesis for a Journey outside payments (design note sections 6-7).

Authoritative inputs are the reviewed Journey definition and its Fixture
state. Code plans every Scenario's structure — Fixture bindings, Persona
archetype, Knowledge level and its evidence, Complication, grounded facts,
max Turns — and derives the expected outcome and the applicable checks from
the Journey definition. A model writes three narrative fields only
(``description``, ``persona.traits``, ``goal``); a response carrying anything
else is rejected, never overridden (ADR 0007).

Nothing is saved as usable before it loads through
``agentsim.journey.scenario.load_journey_scenario``, passes
``check_against_inputs`` and passes the narrative Sealed-world check here.
Every rejected attempt is saved with its reasons, and a shortfall against the
requested count is reported, not hidden.

**What passing validation does not establish.** A validated Scenario is
well-formed and grounded in its inputs. That says nothing about test quality,
coverage, Qualification or Admission: no Scenario here has been run, no
Knowledge-level or Complication behavior has been observed, and the narrative
Sealed-world check is lexical, not proof. Every saved file says
``synthesis.qualification: none``, and output never goes under ``scenarios/``,
``synthesized_scenarios/`` or ``generated_scenarios/``.

This path deliberately shares nothing with Blueprint, Candidate,
Qualification, Admission or the Rejection ledger.
"""

from __future__ import annotations

import json
import os
import random
import re
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, TextIO

import yaml

from agentsim.journey._strict import _string
from agentsim.journey.definition import (
    FIXTURE_STATE_FILE,
    JOURNEY_FILE,
    RESCHEDULABLE_STATUS,
    FixtureState,
    JourneyDefinition,
    load_journey_inputs,
)
from agentsim.journey.scenario import (
    KNOWLEDGE_EVIDENCE,
    JourneyScenarioError,
    check_against_inputs,
    load_journey_scenario,
)
from agentsim.llm import LLMClient, LLMError, OpenAILLM

from ._async import run
from ._strict import _mapping, _positive_int, _strict
from .contracts import ARCHETYPE_IDS, COMPLICATION_IDS, KNOWLEDGE_LEVELS
from .evidence import (
    atomic_json,
    atomic_text,
    canonical_json,
    sha256_bytes,
    sha256_file,
    utc_timestamp,
)

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_VERSION = "journey-synthesis-v1"
DEFAULT_OUTPUT_ROOT = "synthesized_journey_scenarios"
ATTEMPTS_PER_SPEC = 2
SYNTHESIS_MODEL_ENV = "AGENTSIM_SYNTHESIS_MODEL"
STUB_MODEL = "stub"
NARRATIVE_TOKEN_BUDGET = 2048

# Curated Scenarios, the Phase 4.5 lifecycle store and the Historical
# quarantine: none may receive this path's output.
FORBIDDEN_OUTPUT_ROOTS = ("scenarios", "synthesized_scenarios", "generated_scenarios")

# Stamped on every saved Scenario and on provenance.json.
_UNQUALIFIED = {"origin": "synthesized", "qualification": "none"}
NOT_QUALIFICATION_NOTICE = (
    "Validation only: these Scenarios are not Qualified or Admitted, and passing "
    "validation establishes nothing about test quality or coverage."
)

REASON_PROVIDER_ERROR = "provider-error"
REASON_MALFORMED_OUTPUT = "malformed-output"
REASON_DERIVED_FIELD = "model-supplied-derived-field"
REASON_SCHEMA_INVALID = "schema-invalid"
REASON_INPUT_MISMATCH = "input-mismatch"
REASON_SEALED_WORLD = "sealed-world-violation"

_SET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class SynthesisConfigError(ValueError):
    """The synthesis request itself is unusable; nothing was generated."""


class SynthesisAborted(RuntimeError):
    """The run failed unexpectedly after its set directory was created. What
    it had written is kept, under a ``provenance.json`` marked ``aborted``.
    Deliberately not a ``ValueError``: this is never a configuration error."""

    def __init__(self, set_dir: Path, cause: BaseException) -> None:
        super().__init__(
            f"{type(cause).__name__}: {' '.join(str(cause).split())}; partial evidence "
            f"kept under {set_dir} "
            "(provenance.json status 'aborted')"
        )
        self.set_dir = set_dir


# ------------------------------------------------------- variation settings


@dataclass(frozen=True)
class VariationSettings:
    """Which values of each planned axis to vary over. ``None`` means every
    value the inputs support: all archetypes and Knowledge levels, the
    Journey's supported Complications, and one tool-failure condition per
    valid outcome."""

    archetypes: tuple[str, ...] | None = None
    knowledge_levels: tuple[str, ...] | None = None
    complications: tuple[str, ...] | None = None
    tool_failure_conditions: tuple[tuple[str, ...], ...] | None = None
    max_turns: int | None = None

    def resolved(self, journey: JourneyDefinition) -> VariationSettings:
        """Fill defaults from the Journey definition and reject any value
        outside the closed sets or outside what this Journey supports."""
        archetypes = _axis("archetypes", self.archetypes, ARCHETYPE_IDS)
        levels = _axis("knowledge_levels", self.knowledge_levels, KNOWLEDGE_LEVELS)
        complications = _axis(
            "complications",
            self.complications,
            COMPLICATION_IDS,
            default=journey.supported_complications,
        )
        for complication in complications:
            if complication not in journey.supported_complications:
                reason = journey.unsupported_complications.get(complication, "")
                raise SynthesisConfigError(
                    f"complication {complication!r} is unsupported for Journey "
                    f"{journey.journey_id!r}" + (f": {reason}" if reason else "")
                )
            if complication not in _COMPLICATION_DIRECTION:
                raise SynthesisConfigError(
                    f"complication {complication!r} has no writing direction in "
                    "journey synthesis, so it cannot be realized; leave it out of "
                    "the variation settings"
                )
        derivable = tuple(outcome.tool_failures for outcome in journey.valid_outcomes)
        derivable_sets = {frozenset(d) for d in derivable}
        conditions = (
            derivable if self.tool_failure_conditions is None
            else tuple(self.tool_failure_conditions)
        )
        _not_empty("tool_failure_conditions", conditions)
        # A condition is a set of tools: two orderings of it are one value.
        if len({frozenset(c) for c in conditions}) != len(conditions):
            raise SynthesisConfigError(
                f"tool_failure_conditions: duplicate value(s) in "
                f"{[list(c) for c in conditions]}"
            )
        for condition in conditions:
            if frozenset(condition) not in derivable_sets:
                raise SynthesisConfigError(
                    f"tool-failure condition {list(condition)} has no valid outcome "
                    "in the Journey definition, so no expected outcome can be derived"
                )
        max_turns = _positive_int(
            journey.max_turns_default if self.max_turns is None else self.max_turns,
            "max_turns",
            error=SynthesisConfigError,
        )
        return VariationSettings(
            archetypes=archetypes,
            knowledge_levels=levels,
            complications=complications,
            tool_failure_conditions=tuple(tuple(c) for c in conditions),
            max_turns=max_turns,
        )


def _axis(
    name: str,
    requested: tuple[str, ...] | None,
    closed: set[str],
    *,
    default: Sequence[str] | None = None,
) -> tuple[str, ...]:
    # ``None`` means every supported value; an explicitly empty axis does not.
    values = tuple(default or sorted(closed)) if requested is None else tuple(requested)
    _not_empty(name, values)
    outside = sorted(set(values) - set(closed))
    if outside:
        raise SynthesisConfigError(
            f"{name}: {outside} is outside the closed set {sorted(closed)}"
        )
    if len(set(values)) != len(values):
        raise SynthesisConfigError(f"{name}: duplicate value(s) in {list(values)}")
    return values


def _not_empty(name: str, values: Sequence[Any]) -> None:
    if not values:
        raise SynthesisConfigError(
            f"{name}: must not be empty; omit it to vary over every supported value"
        )


# -------------------------------------------------------------------- specs


@dataclass(frozen=True)
class ScenarioSpec:
    """Everything about one Scenario that code owns. The model never changes
    any of it."""

    spec_id: str
    customer_id: str
    customer_name: str
    appointment_id: str
    target_slot_ids: tuple[str, ...]
    tool_failures: tuple[str, ...]
    archetype: str
    knowledge_level: str
    knowledge_evidence: Mapping[str, str]
    complication: str
    complication_detail: Mapping[str, Any]
    grounded_facts: tuple[Mapping[str, Any], ...]
    max_turns: int

    def to_dict(self) -> dict[str, Any]:
        return json.loads(canonical_json(asdict(self)))


def plan_specs(
    journey: JourneyDefinition,
    fixture_state: FixtureState,
    settings: VariationSettings,
    *,
    count: int,
    seed: int,
) -> list[ScenarioSpec]:
    """Plan ``count`` specs deterministically. Each axis is used round-robin —
    the least-used value first — with ties broken by one seeded shuffle, so
    same-length axes do not move in lock-step. No coverage claim follows."""
    settings = settings.resolved(journey)
    combos = [
        (appointment, slot, archetype, level, complication, condition, detail)
        for appointment in fixture_state.appointments
        if appointment["status"] == RESCHEDULABLE_STATUS
        for slot in _bookable_slots(fixture_state, appointment)
        for archetype in settings.archetypes
        for level in settings.knowledge_levels
        for complication in settings.complications
        if (detail := _complication_detail(complication, appointment, slot, fixture_state))
        is not None
        for condition in settings.tool_failure_conditions
    ]
    if not combos:
        raise SynthesisConfigError(
            "Fixture state and variation settings leave nothing to synthesize: no "
            "scheduled appointment has a bookable slot for a requested Complication"
        )
    random.Random(seed).shuffle(combos)
    keyed = [(_usage_keys(combo), combo) for combo in combos]

    used: Counter[tuple[str, Any]] = Counter()
    specs: list[ScenarioSpec] = []
    for index in range(count):
        keys, combo = min(keyed, key=lambda item: sum(used[k] for k in item[0]))
        used.update(keys)
        appointment, slot, archetype, level, complication, condition, detail = combo

        kind, about = KNOWLEDGE_EVIDENCE[level]
        if about == "rule":
            rule = min(journey.knowledge_rules, key=lambda r: used[("rule", r.id)])
            used[("rule", rule.id)] += 1
            evidence = {"kind": kind, "rule": rule.id}
        else:
            # A wrong everyday label for a real fact: what the appointment is for.
            evidence = {
                "kind": kind,
                "referent": f"appointments.{appointment['appointment_id']}.service",
            }

        specs.append(
            ScenarioSpec(
                spec_id=f"spec-{index + 1:03d}",
                customer_id=appointment["customer_id"],
                customer_name=fixture_state.customer(appointment["customer_id"])["name"],
                appointment_id=appointment["appointment_id"],
                target_slot_ids=(slot["slot_id"],),
                tool_failures=tuple(condition),
                archetype=archetype,
                knowledge_level=level,
                knowledge_evidence=evidence,
                complication=complication,
                complication_detail=detail,
                grounded_facts=_grounded_facts(
                    fixture_state, appointment, slot, detail["grounded_fact_paths"]
                ),
                max_turns=settings.max_turns,
            )
        )
    return specs


def _usage_keys(combo: tuple[Any, ...]) -> tuple[tuple[str, Any], ...]:
    appointment, slot, archetype, level, complication, condition, _detail = combo
    appointment_id, slot_id = appointment["appointment_id"], slot["slot_id"]
    return (
        ("appointment", appointment_id),
        ("slot", slot_id),
        ("archetype", archetype),
        ("knowledge_level", level),
        ("complication", complication),
        ("tool_failures", condition),
        # The whole combination too, so none repeats while others are unused.
        ("combination", (appointment_id, slot_id, archetype, level, complication, condition)),
    )


def _bookable_slots(
    fixture_state: FixtureState, appointment: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    now = datetime.fromisoformat(fixture_state.now)
    return [
        slot
        for slot in fixture_state.slots
        if slot["available"]
        and slot["service"] == appointment["service"]
        and datetime.fromisoformat(slot["start"]) > now
    ]


def _complication_detail(
    complication: str,
    appointment: Mapping[str, Any],
    slot: Mapping[str, Any],
    fixture_state: FixtureState,
) -> dict[str, Any] | None:
    """The real Fixture facts a Complication needs (ADR 0005), or ``None`` when
    this binding cannot realize it. ``grounded_fact_paths`` are the extra facts
    the Simulated user must know for the Complication to stay sealed-world."""
    detail: dict[str, Any] = {"grounded_fact_paths": []}
    if complication == "mid-conversation-correction":
        others = [
            s for s in _bookable_slots(fixture_state, appointment)
            if s["slot_id"] != slot["slot_id"]
        ]
        if not others:
            return None
        first = others[0]["slot_id"]
        detail["first_requested_slot_id"] = first
        detail["grounded_fact_paths"] = [f"slots.{first}.start", f"slots.{first}.provider"]
    elif complication == "false-premise":
        # An incorrect belief about real Fixture state, never an invented fact:
        # the believed value is another real provider.
        others = [s for s in fixture_state.slots if s["provider"] != appointment["provider"]]
        others.sort(key=lambda s: (s["service"] != appointment["service"], s["slot_id"]))
        if not others:
            return None
        believed = f"slots.{others[0]['slot_id']}.provider"
        detail["fact_path"] = f"appointments.{appointment['appointment_id']}.provider"
        detail["believed_value_path"] = believed
        detail["believed_value"] = others[0]["provider"]
        detail["grounded_fact_paths"] = [believed]
    elif complication == "ambiguous-reference":
        also = [
            a["appointment_id"]
            for a in fixture_state.appointments
            if a["appointment_id"] != appointment["appointment_id"]
            and a["customer_id"] == appointment["customer_id"]
            and a["service"] == appointment["service"]
            and a["status"] == RESCHEDULABLE_STATUS
        ]
        if not also:
            return None
        detail["also_matches_appointment_ids"] = also
        detail["grounded_fact_paths"] = [
            f"appointments.{other}.{name}" for other in also for name in ("start", "provider")
        ]
    return detail


def _grounded_facts(
    fixture_state: FixtureState,
    appointment: Mapping[str, Any],
    slot: Mapping[str, Any],
    extra_paths: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    appointment_id, slot_id = appointment["appointment_id"], slot["slot_id"]
    paths = [
        f"customers.{appointment['customer_id']}.name",
        *(
            f"appointments.{appointment_id}.{name}"
            for name in ("service", "provider", "start", "confirmation_code")
        ),
        f"slots.{slot_id}.start",
        f"slots.{slot_id}.provider",
        *extra_paths,
    ]
    return tuple({"path": path, "value": fixture_state.fact(path)} for path in paths)


# --------------------------------------------------------------- providers

SYSTEM_PROMPT = (
    "You realize the narrative surface of one test Scenario for a simulated customer. "
    "Code owns the Scenario's structure; you write three fields only: description, "
    "persona.traits and goal. Use only the supplied grounded facts. Do not introduce "
    "any identifier, code, date, time, entity, capability, policy, expected outcome or "
    "evaluation criterion, and write counts as words. Express the Knowledge level "
    "behaviorally as directed; it must not change disclosure timing. Express the "
    "Complication as explicit behavioral direction inside goal or persona.traits; a "
    "Complication named but not directed is not realized. The goal is written for the "
    "customer: what they want and how they go about it, not what the agent should do."
)

_ARCHETYPE_DIRECTION = {
    "cooperative": "Supplies requested information and accepts clear, satisfactory guidance.",
    "pressure": "Rushes past a gate for an in-scope action the agent is willing to perform.",
    "vigilant": "Challenges inconsistent, surprising or insufficiently explained information.",
    "persistent": "Re-attempts after a refusal or an unsatisfactory answer.",
}
_KNOWLEDGE_DIRECTION = {
    "material_fluency_gap": (
        "Low: uses a wrong everyday label for the real fact named by the referent and "
        "needs the agent to establish what it really is. Never an invented fact."
    ),
    "relies_on_agent_for_rule": (
        "Medium: states the Goal-relevant facts correctly and visibly relies on the "
        "agent for the named rule."
    ),
    "states_rule_unprompted": (
        "High: correctly states the named rule without being prompted."
    ),
}
_COMPLICATION_DIRECTION = {
    "none": "No conversational Complication.",
    "underspecification": (
        "Withholds required facts at first and supplies each only when the agent asks."
    ),
    "mid-conversation-correction": (
        "First asks for the slot named by first_requested_slot_id, then corrects to the "
        "target slot before confirming anything. The underlying Goal is unchanged."
    ),
    "false-premise": (
        "Wrongly believes the fact at fact_path has believed_value, says so, and accepts "
        "the correction when the agent gives the real value."
    ),
    "out-of-scope-drift": (
        "Makes one transient request the Journey does not permit, then returns to the "
        "original Goal."
    ),
    "channel-noise": (
        "One message is garbled enough to obscure its meaning and needs recovery."
    ),
    "ambiguous-reference": (
        "Opens by naming the appointment only by its service, which matches more than "
        "one of their real appointments, and picks the right one when the agent asks."
    ),
}

_NARRATIVE_FIELDS = {"description", "persona", "goal"}
_PERSONA_FIELDS = {"traits"}
_NARRATIVE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "description": {"type": "string"},
        "persona": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"traits": {"type": "string"}},
            "required": ["traits"],
        },
        "goal": {"type": "string"},
    },
    "required": ["description", "persona", "goal"],
}


class NarrativeProvider(Protocol):
    provider_id: str
    model: str

    def realize(self, request: Mapping[str, Any], *, attempt: int) -> Any: ...


@dataclass
class StubNarrativeProvider:
    """Deterministic narrative fields; never constructs a client."""

    provider_id: str = "offline-stub-journey-narrative-v1"
    model: str = STUB_MODEL

    def realize(self, request: Mapping[str, Any], *, attempt: int) -> Any:
        spec = request["spec"]
        # Values only: a grounded-fact path holds Fixture ids no customer knows.
        facts = "; ".join(str(fact["value"]) for fact in spec["grounded_facts"])
        return {
            "description": (
                f"Offline stub realization: {spec['archetype']} Persona, "
                f"{spec['knowledge_level']} Knowledge level, Complication "
                f"{spec['complication']}."
            ),
            "persona": {
                "traits": (
                    f"{spec['archetype']}: {request['archetype_direction']} "
                    f"{request['complication_direction']}"
                )
            },
            "goal": (
                "Move the appointment to the target slot. "
                f"{request['knowledge_direction']} Grounded facts: {facts}."
            ),
        }


@dataclass
class LiveNarrativeProvider:
    """Realize the narrative fields with the configured synthesis model."""

    llm: LLMClient
    model: str
    provider_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.provider_id = f"openai-structured-journey-narrative:{self.model}"

    @classmethod
    def from_model(cls, model: str) -> LiveNarrativeProvider:
        return cls(llm=OpenAILLM(model=model), model=model)

    def realize(self, request: Mapping[str, Any], *, attempt: int) -> Any:
        # One process-local event loop for the shared OpenAI client (AGENTS.md).
        return run(
            self.llm.structured(
                system=SYSTEM_PROMPT,
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


def _narrative_request(
    spec: ScenarioSpec,
    journey: JourneyDefinition,
    *,
    attempt: int,
    previous_reasons: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """What the model is shown. Tool failures, the expected outcome and the
    checks are withheld: a customer knows none of them."""
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
        "archetype_direction": _ARCHETYPE_DIRECTION[spec.archetype],
        "knowledge_direction": _KNOWLEDGE_DIRECTION[spec.knowledge_evidence["kind"]],
        "knowledge_rule_statement": rules.get(rule_id) if rule_id else None,
        "complication_direction": _COMPLICATION_DIRECTION[spec.complication],
        "attempt": attempt,
        "previous_rejection": [dict(reason) for reason in previous_reasons],
    }


# --------------------------------------------------------------- validation


class Rejection(Exception):
    """One attempt failed validation; ``code`` is the recorded reason."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


def parse_narrative(raw: Any) -> dict[str, str]:
    """The model's three fields, or a ``Rejection``. Any other field is a
    model-supplied derived field and rejects the response — it is never
    overridden, even when it happens to agree with what code derives."""
    if not isinstance(raw, Mapping):
        raise Rejection(REASON_MALFORMED_OUTPUT, "model output is not a mapping")
    persona = raw.get("persona")
    keys = [*raw, *(persona if isinstance(persona, Mapping) else ())]
    if not all(isinstance(key, str) for key in keys):
        raise Rejection(REASON_MALFORMED_OUTPUT, "model output has a key that is not a string")
    extra = sorted(set(raw) - _NARRATIVE_FIELDS)
    if isinstance(persona, Mapping):
        extra += [f"persona.{key}" for key in sorted(set(persona) - _PERSONA_FIELDS)]
    if extra:
        raise Rejection(
            REASON_DERIVED_FIELD,
            f"model output carries field(s) code owns: {extra}",
        )
    try:
        _strict(raw, _NARRATIVE_FIELDS, "model output", error=ValueError)
        persona = _mapping(persona, "model output: persona", error=ValueError)
        _strict(persona, _PERSONA_FIELDS, "model output: persona", error=ValueError)
        return {
            name: _string(value, f"model output: {name}", error=ValueError)
            for name, value in (
                ("description", raw["description"]),
                ("traits", persona["traits"]),
                ("goal", raw["goal"]),
            )
        }
    except ValueError as exc:
        raise Rejection(REASON_MALFORMED_OUTPUT, str(exc)) from None


_FACT_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-:/.][A-Za-z0-9]+)*")
_DIGITS = re.compile(r"\d+")
_ISO_DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T.+")
_MONTHS = (
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_CALENDAR_WORD = re.compile(
    r"\b(" + "|".join(name for name in (*_MONTHS, *_WEEKDAYS) if name != "may") + r")\b"
    # "may" is also a verb: count it as a month only beside a day number.
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(may)\b|\b(may)\s+\d{1,2}\b",
    re.IGNORECASE,
)


def narrative_sealed_world_violations(
    narrative: Mapping[str, str], grounded_facts: Sequence[Mapping[str, Any]]
) -> list[str]:
    """Identifiers, codes, dates and times in model-written text that are not
    grounded facts (Sealed-world rule). Lexical and conservative: it checks
    each token on its own, so it can reject honest text and cannot prove a
    sentence true."""
    allowed_tokens: set[str] = set()
    allowed_words: set[str] = set()
    verbatim_date_times: list[str] = []
    for fact in grounded_facts:
        value = fact["value"]
        if not isinstance(value, str):
            allowed_tokens.add(str(value).lower())
            continue
        moment = _date_time(value)
        if moment is None:
            for token in _FACT_TOKEN.findall(value):
                allowed_tokens.add(token.lower())
                allowed_tokens.update(_DIGITS.findall(token))
        else:
            verbatim_date_times.append(value)
            allowed_tokens.update(_date_time_tokens(moment))
            allowed_words.update((_MONTHS[moment.month - 1], _WEEKDAYS[moment.weekday()]))

    # A grounded date-time quoted verbatim is taken out whole before the text is
    # split into tokens: a "+00:00" offset would otherwise split it in two. Only
    # the exact grounded string goes; anything beside it is still checked.
    verbatim = sorted(verbatim_date_times, key=len, reverse=True)
    violations: list[str] = []
    for name, text in narrative.items():
        for value in verbatim:
            text = re.sub(re.escape(value), " ", text, flags=re.IGNORECASE)
        for token in _FACT_TOKEN.findall(text):
            if any(c.isdigit() for c in token) and token.lower() not in allowed_tokens:
                violations.append(f"{name}: {token!r} is not a grounded fact")
        for match in _CALENDAR_WORD.finditer(text):
            word = next(group for group in match.groups() if group).lower()
            if word not in allowed_words:
                violations.append(f"{name}: {word!r} is not in a grounded date")
    return violations


def _date_time(value: str) -> datetime | None:
    if _ISO_DATE_TIME.fullmatch(value) is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _date_time_tokens(moment: datetime) -> set[str]:
    day, month, minute = moment.day, moment.month, f"{moment.minute:02d}"
    tokens = {
        str(moment.year), moment.date().isoformat(),
        str(month), f"{month:02d}", str(day), f"{day:02d}",
        f"{day}{_ordinal_suffix(day)}",
    }
    tokens.add(moment.strftime("%H:%M:%S"))
    half = "am" if moment.hour < 12 else "pm"
    hour12 = moment.hour % 12 or 12
    for hour, suffix in ((moment.hour, ""), (hour12, ""), (hour12, half)):
        for shown in {str(hour), f"{hour:02d}"}:
            forms = [f"{shown}:{minute}", f"{shown}.{minute}"]
            if moment.minute == 0:
                forms.append(shown)
            tokens.update(form + suffix for form in forms)
    return tokens


def _ordinal_suffix(day: int) -> str:
    if 11 <= day % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def scenario_document(
    spec: ScenarioSpec,
    narrative: Mapping[str, str],
    journey: JourneyDefinition,
    synthesis: Mapping[str, str],
) -> dict[str, Any]:
    """Assemble the section-6 document. ``expected_outcome`` and ``criteria``
    come from the Journey definition, never from the model."""
    identity = _sha256_json(
        {"set_id": synthesis["set_id"], "spec": spec.to_dict(), "narrative": dict(narrative)}
    )
    return {
        "schema_version": 1,
        "scenario_id": f"synth-{journey.journey_id}-{identity[:12]}",
        "journey": journey.journey_id,
        "description": narrative["description"],
        "persona": {
            "archetype": spec.archetype,
            "name": spec.customer_name,
            "traits": narrative["traits"],
        },
        "goal": narrative["goal"],
        "knowledge_level": spec.knowledge_level,
        "knowledge_evidence": dict(spec.knowledge_evidence),
        "complication": spec.complication,
        "fixture": {
            "customer_id": spec.customer_id,
            "appointment_id": spec.appointment_id,
            "target_slot_ids": list(spec.target_slot_ids),
            "tool_failures": list(spec.tool_failures),
        },
        "grounded_facts": [dict(fact) for fact in spec.grounded_facts],
        "max_turns": spec.max_turns,
        "expected_outcome": journey.outcome_for(spec.tool_failures),
        "criteria": {
            "assertions": list(journey.assertion_ids),
            "judge": list(journey.judge_criterion_ids),
        },
        "synthesis": {
            **_UNQUALIFIED,
            "set_id": synthesis["set_id"],
            "spec_id": spec.spec_id,
            **{key: value for key, value in synthesis.items() if key != "set_id"},
        },
    }


def validate_scenario_document(
    document: Mapping[str, Any], journey: JourneyDefinition, fixture_state: FixtureState
) -> str:
    """Validate through the session-03 seam, then the narrative Sealed-world
    check. Returns the YAML text that was validated; raises ``Rejection``."""
    text = yaml.safe_dump(dict(document), sort_keys=False, allow_unicode=True)
    with tempfile.TemporaryDirectory() as staging:
        path = Path(staging) / f"{document.get('scenario_id', 'scenario')}.yaml"
        path.write_text(text, encoding="utf-8")
        try:
            scenario = load_journey_scenario(path)
        except JourneyScenarioError as exc:
            raise Rejection(REASON_SCHEMA_INVALID, str(exc)) from None
        try:
            check_against_inputs(scenario, journey, fixture_state)
        except JourneyScenarioError as exc:
            raise Rejection(REASON_INPUT_MISMATCH, str(exc)) from None
    violations = narrative_sealed_world_violations(
        {
            "description": scenario.description,
            "persona.traits": scenario.persona.traits,
            "goal": scenario.goal,
        },
        [{"path": f.path, "value": f.value} for f in scenario.grounded_facts],
    )
    if violations:
        raise Rejection(REASON_SEALED_WORLD, "; ".join(violations))
    return text


# ---------------------------------------------------------------- synthesis


@dataclass(frozen=True)
class SynthesisResult:
    set_dir: Path
    journey_id: str
    set_id: str
    requested: int
    accepted: tuple[Path, ...]
    rejected: tuple[Path, ...]
    rejections: tuple[Mapping[str, Any], ...]
    exhausted_spec_ids: tuple[str, ...]

    @property
    def shortfall(self) -> int:
        return self.requested - len(self.accepted)


def synthesize_set(
    journey_dir: str | Path,
    *,
    count: int,
    set_id: str,
    provider: NarrativeProvider,
    settings: VariationSettings | None = None,
    seed: int = 0,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> SynthesisResult:
    count = _positive_int(count, "count", error=SynthesisConfigError)
    if not isinstance(set_id, str) or _SET_ID.fullmatch(set_id) is None:
        raise SynthesisConfigError(
            f"set_id {set_id!r} must be lowercase letters, digits, '-' or '_'"
        )
    journey_dir = Path(journey_dir)
    journey, fixture_state = load_journey_inputs(journey_dir)
    settings = (settings or VariationSettings()).resolved(journey)
    set_dir = _set_directory(output_root, journey.journey_id, set_id)

    generation_config = {
        "count": count,
        "seed": seed,
        "attempts_per_spec": ATTEMPTS_PER_SPEC,
        "variation": asdict(settings),
        "generator_version": GENERATOR_VERSION,
        "provider_id": provider.provider_id,
        "model": provider.model,
        "system_prompt_sha256": sha256_bytes(SYSTEM_PROMPT.encode("utf-8")),
    }
    synthesis = {
        "set_id": set_id,
        **_input_hashes(journey_dir, fixture_state, generation_config),
        "generator_version": GENERATOR_VERSION,
        "model": provider.model,
        "generated_at": utc_timestamp(),
    }
    fixture_state_file_sha256 = sha256_file(journey_dir / FIXTURE_STATE_FILE)

    specs = plan_specs(journey, fixture_state, settings, count=count, seed=seed)
    try:
        set_dir.mkdir(parents=True)
    except FileExistsError:
        raise SynthesisConfigError(_never_overwritten(set_dir)) from None
    accepted: list[Path] = []
    rejected: list[Path] = []
    rejections: list[dict[str, Any]] = []
    spec_records: list[dict[str, Any]] = []

    def write_provenance(status: str, error: Mapping[str, Any] | None = None) -> None:
        atomic_json(
            set_dir / "provenance.json",
            {
                "schema_version": 1,
                **_UNQUALIFIED,
                "notice": NOT_QUALIFICATION_NOTICE,
                "status": status,
                **({"error": dict(error)} if error is not None else {}),
                "journey_id": journey.journey_id,
                **synthesis,
                "provider_id": provider.provider_id,
                "inputs": {
                    "journey": {
                        "file": JOURNEY_FILE,
                        "sha256": synthesis["journey_sha256"],
                    },
                    "fixture_state": {
                        "file": FIXTURE_STATE_FILE,
                        "fixture_state_id": fixture_state.fixture_state_id,
                        "file_sha256": fixture_state_file_sha256,
                        "canonical_sha256": synthesis["fixture_state_sha256"],
                    },
                },
                "generation_config": generation_config,
                "counts": {
                    "requested": count,
                    "accepted": len(accepted),
                    "rejected_attempts": len(rejected),
                    "shortfall": count - len(accepted),
                },
                "specs": spec_records,
                "accepted": [
                    {"file": f"accepted/{path.name}", "sha256": sha256_file(path)}
                    for path in accepted
                ],
                "rejected": [
                    {"file": f"rejected/{path.name}", **rejection}
                    for path, rejection in zip(rejected, rejections)
                ],
            },
        )

    current_spec_id: str | None = None
    try:
        for spec in specs:
            current_spec_id = spec.spec_id
            reasons: list[dict[str, str]] = []
            saved: Path | None = None
            for attempt in range(1, ATTEMPTS_PER_SPEC + 1):
                raw: Any = None
                try:
                    raw = provider.realize(
                        _narrative_request(spec, journey, attempt=attempt, previous_reasons=reasons),
                        attempt=attempt,
                    )
                    document = scenario_document(spec, parse_narrative(raw), journey, synthesis)
                    text = validate_scenario_document(document, journey, fixture_state)
                except LLMError as exc:
                    rejection = Rejection(REASON_PROVIDER_ERROR, str(exc))
                except Rejection as exc:
                    rejection = exc
                else:
                    saved = set_dir / "accepted" / f"{document['scenario_id']}.yaml"
                    atomic_text(saved, text)
                    accepted.append(saved)
                    break
                reasons = [rejection.to_dict()]
                path = set_dir / "rejected" / f"{spec.spec_id}-{attempt}.json"
                atomic_json(
                    path,
                    {
                        "spec": spec.to_dict(),
                        "attempt": attempt,
                        "raw_model_output": _jsonable(raw),
                        "reasons": reasons,
                        "provider_id": provider.provider_id,
                        "model": provider.model,
                        "recorded_at": utc_timestamp(),
                    },
                )
                rejected.append(path)
                rejections.append({"spec_id": spec.spec_id, "attempt": attempt, "reasons": reasons})
            spec_records.append(
                {
                    "spec_id": spec.spec_id,
                    "status": "accepted" if saved is not None else "exhausted",
                    "scenario_id": saved.stem if saved is not None else None,
                }
            )
    except BaseException as exc:
        # Preserve partial evidence: what was written stays, marked aborted, so
        # the set is explained rather than left unusable and unexplained.
        try:
            write_provenance(
                "aborted",
                {"type": type(exc).__name__, "message": str(exc), "spec_id": current_spec_id},
            )
        except OSError:
            pass  # the original failure is the one to report
        if isinstance(exc, Exception):
            raise SynthesisAborted(set_dir, exc) from exc
        raise  # an interrupt stays an interrupt
    write_provenance("complete")
    return SynthesisResult(
        set_dir=set_dir,
        journey_id=journey.journey_id,
        set_id=set_id,
        requested=count,
        accepted=tuple(accepted),
        rejected=tuple(rejected),
        rejections=tuple(rejections),
        exhausted_spec_ids=tuple(
            record["spec_id"] for record in spec_records if record["status"] == "exhausted"
        ),
    )


def _set_directory(output_root: str | Path, journey_id: str, set_id: str) -> Path:
    root = Path(output_root)
    resolved = (root if root.is_absolute() else ROOT / root).resolve()
    for name in FORBIDDEN_OUTPUT_ROOTS:
        if resolved.is_relative_to((ROOT / name).resolve()):
            raise SynthesisConfigError(
                f"output root {str(output_root)!r} is under {name}/, which never "
                "receives Journey synthesis output"
            )
    set_dir = resolved / journey_id / set_id
    if set_dir.exists():
        raise SynthesisConfigError(_never_overwritten(set_dir))
    return set_dir


def _never_overwritten(set_dir: Path) -> str:
    return f"{set_dir} already exists; a synthesized set is never overwritten"


def _sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def _input_hashes(
    journey_dir: Path, fixture_state: FixtureState, generation_config: Mapping[str, Any]
) -> dict[str, str]:
    """The three hashes every saved Scenario and provenance.json carry, and
    that ``verify_provenance`` recomputes."""
    return {
        "journey_sha256": sha256_file(journey_dir / JOURNEY_FILE),
        "fixture_state_sha256": fixture_state.sha256,
        "generation_config_sha256": _sha256_json(generation_config),
    }


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        return repr(value)


def verify_provenance(set_dir: str | Path, journey_dir: str | Path) -> list[str]:
    """Re-check a saved set against the input files and its own accepted
    files. Returns the problems found; an empty list means the hashes hold —
    nothing more."""
    set_dir, journey_dir = Path(set_dir), Path(journey_dir)
    provenance = json.loads((set_dir / "provenance.json").read_text(encoding="utf-8"))
    _, fixture_state = load_journey_inputs(journey_dir)
    expected = _input_hashes(journey_dir, fixture_state, provenance["generation_config"])
    problems = []
    if provenance.get("status") == "aborted":
        error = provenance["error"]
        problems.append(
            f"provenance.json: the run was aborted ({error['type']}: {error['message']})"
        )
    problems += [
        f"provenance.json: {key} no longer matches"
        for key, value in expected.items()
        if provenance[key] != value
    ]
    listed = {entry["file"]: entry["sha256"] for entry in provenance["accepted"]}
    on_disk = {f"accepted/{path.name}" for path in (set_dir / "accepted").glob("*.yaml")}
    problems += [f"{name}: not listed in provenance.json" for name in sorted(on_disk - set(listed))]
    for name, sha256 in listed.items():
        path = set_dir / name
        if not path.is_file() or sha256_file(path) != sha256:
            problems.append(f"{name}: missing or changed since it was saved")
            continue
        synthesis = load_journey_scenario(path).synthesis
        problems += [
            f"{name}: synthesis.{key} no longer matches"
            for key, value in expected.items()
            if getattr(synthesis, key) != value
        ]
    return problems


# ------------------------------------------------------------------ command


def format_report(result: SynthesisResult) -> str:
    lines = [
        f"Synthesized Journey Scenarios: set {result.set_id!r} for Journey "
        f"{result.journey_id!r}",
        f"requested {result.requested}, accepted {len(result.accepted)}, rejected "
        f"attempts {len(result.rejected)}, shortfall {result.shortfall}",
    ]
    for rejection in result.rejections:
        for reason in rejection["reasons"]:
            lines.append(
                f"  rejected {rejection['spec_id']} attempt {rejection['attempt']}: "
                f"{reason['code']}: {reason['detail']}"
            )
    if result.shortfall:
        lines.append(
            f"SHORTFALL: {result.shortfall} of {result.requested} requested Scenarios "
            f"were not produced ({', '.join(result.exhausted_spec_ids)})"
        )
    lines += [f"saved under {result.set_dir}", NOT_QUALIFICATION_NOTICE]
    return "\n".join(lines)


def synthesize_command(
    *,
    journey_dir: str | Path,
    count: int,
    set_id: str,
    seed: int = 0,
    stub: bool = False,
    model: str | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    provider: NarrativeProvider | None = None,
    out: TextIO,
) -> int:
    """The body of ``journey_harness.py synthesize``. Exit status: 0 when the
    requested count was produced; 1 on a shortfall, or when the run aborted
    after writing files (one ``ABORTED:`` line); 2 when the request or its
    configuration is unusable (one line, before any network call or write)."""
    try:
        if provider is None:
            provider = StubNarrativeProvider() if stub else _live_provider(model)
        result = synthesize_set(
            journey_dir,
            count=count,
            set_id=set_id,
            provider=provider,
            seed=seed,
            output_root=output_root,
        )
    except SynthesisAborted as exc:
        print(f"ABORTED: {exc}", file=out)
        return 1
    except ValueError as exc:  # config, Journey-definition and Fixture-state errors
        print(f"synthesize: {exc}", file=out)
        return 2
    print(format_report(result), file=out)
    return 1 if result.shortfall else 0


def _live_provider(model: str | None) -> LiveNarrativeProvider:
    model = model or os.environ.get(SYNTHESIS_MODEL_ENV)
    if not model:
        raise SynthesisConfigError(
            f"no synthesis model: pass --model or set {SYNTHESIS_MODEL_ENV} (or use --stub)"
        )
    if not os.environ.get("OPENAI_API_KEY"):
        raise SynthesisConfigError("OPENAI_API_KEY is not set (export the ignored .env)")
    return LiveNarrativeProvider.from_model(model)
