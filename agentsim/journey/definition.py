"""Strict loaders for a Journey's two authoritative inputs: the Journey
definition (``journey.yaml``) and its Fixture state (``fixture_state.yaml``).

Both fail loudly — unknown fields, dangling ids and unknown check references
are errors that name the file and field, never warnings. Neither file knows
anything about the agent's implementation: the Journey definition states
permitted behavior, required rules, valid outcomes, which Assertions apply and
the Judge criteria in full — their wording and the tools each is about; the
Fixture state is plain synthetic data.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..judge import Criterion
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

JOURNEY_FILE = "journey.yaml"
FIXTURE_STATE_FILE = "fixture_state.yaml"

# The shared closed Complication axis (CONTEXT.md). The reviewed contract
# constants live in ``scenario_synthesis.contracts``, which this package cannot
# import; a test pins the two equal.
COMPLICATION_IDS: frozenset[str] = frozenset(
    {
        "none",
        "underspecification",
        "mid-conversation-correction",
        "goal-shift",
        "multi-intent-turn",
        "false-premise",
        "out-of-scope-drift",
        "channel-noise",
        "ambiguous-reference",
    }
)

# The only controlled tool failure the agent service supports.
SUPPORTED_TOOL_FAILURES: frozenset[str] = frozenset({checks.UPDATE_APPOINTMENT})

APPOINTMENT_STATUSES: frozenset[str] = frozenset({"scheduled", "completed", "cancelled"})
RESCHEDULABLE_STATUS = "scheduled"

_JOURNEY_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_CHECK_KINDS = ("assertion", "judge")


class JourneyDefinitionError(ValueError):
    """A Journey definition file failed validation."""


class FixtureStateError(ValueError):
    """A Fixture state file failed validation."""


# ----------------------------------------------------- Journey definition


@dataclass(frozen=True)
class RequiredRule:
    id: str
    statement: str
    checks: tuple[str, ...]  # "assertion:<id>" / "judge:<id>"


@dataclass(frozen=True)
class ValidOutcome:
    id: str
    description: str
    tool_failures: tuple[str, ...]  # the Fixture condition under which it is expected


@dataclass(frozen=True)
class KnowledgeRule:
    id: str
    statement: str


@dataclass(frozen=True)
class JudgeCriterion:
    id: str
    statement: str  # the wording the Judge is shown
    tools: tuple[str, ...]  # the tools whose actions the criterion is about


@dataclass(frozen=True)
class JourneyDefinition:
    journey_id: str
    title: str
    agent_role: str
    tools: tuple[str, ...]
    permitted_behavior: tuple[str, ...]
    required_rules: tuple[RequiredRule, ...]
    valid_outcomes: tuple[ValidOutcome, ...]
    assertion_ids: tuple[str, ...]
    judge_criteria: tuple[JudgeCriterion, ...]
    knowledge_rules: tuple[KnowledgeRule, ...]
    supported_complications: tuple[str, ...]
    unsupported_complications: Mapping[str, str]  # id -> recorded reason
    max_turns_default: int
    source: str

    @property
    def judge_criterion_ids(self) -> tuple[str, ...]:
        return tuple(criterion.id for criterion in self.judge_criteria)

    def judge_criterion(self, criterion_id: str) -> JudgeCriterion:
        """The Judge criterion with this id. An id the definition does not
        define is an error, never a criterion with no tools."""
        for criterion in self.judge_criteria:
            if criterion.id == criterion_id:
                return criterion
        raise JourneyDefinitionError(
            f"{Path(self.source).name}: Journey {self.journey_id!r} defines no Judge "
            f"criterion {criterion_id!r} (defined: {sorted(self.judge_criterion_ids)})"
        )

    def knowledge_rule(self, rule_id: str) -> KnowledgeRule:
        """The knowledge rule with this id. An id the definition does not
        define is an error, never a customer built without the rule."""
        for rule in self.knowledge_rules:
            if rule.id == rule_id:
                return rule
        raise JourneyDefinitionError(
            f"{Path(self.source).name}: Journey {self.journey_id!r} defines no knowledge "
            f"rule {rule_id!r} (defined: {sorted(r.id for r in self.knowledge_rules)})"
        )

    def criteria_for_judge(self, criterion_ids: Iterable[str]) -> tuple[Criterion, ...]:
        """The ``agentsim.judge.Criterion`` objects the Judge is handed, in the
        requested order."""
        return tuple(
            Criterion(criterion.id, criterion.statement)
            for criterion in map(self.judge_criterion, criterion_ids)
        )

    def outcome_for(self, tool_failures: tuple[str, ...]) -> str:
        """The valid outcome expected under a controlled-tool-failure condition."""
        wanted = frozenset(tool_failures)
        for outcome in self.valid_outcomes:
            if frozenset(outcome.tool_failures) == wanted:
                return outcome.id
        raise JourneyDefinitionError(
            f"{Path(self.source).name}: no valid outcome is defined for "
            f"tool_failures {sorted(wanted)}"
        )


def load_journey_definition(path: str | Path) -> JourneyDefinition:
    path = Path(path)
    where = path.name
    error = JourneyDefinitionError
    raw = _load_yaml(path, error=error)
    _strict(
        raw,
        {
            "schema_version", "journey_id", "title", "agent_role", "tools",
            "permitted_behavior", "required_rules", "valid_outcomes", "criteria",
            "knowledge_rules", "complications", "max_turns_default",
        },
        where,
        error=error,
    )
    _schema_version(raw["schema_version"], where, error=error)

    journey_id = _string(raw["journey_id"], f"{where}: journey_id", error=error)
    if _JOURNEY_ID.fullmatch(journey_id) is None or re.fullmatch(r"j\d+", journey_id):
        raise error(
            f"{where}: journey_id {journey_id!r} must be a lowercase hyphenated name, "
            "never a payments 'J<n>' id"
        )

    tools = _unique_strings(raw["tools"], f"{where}: tools", error=error)
    assertion_ids, judge_criteria = _parse_criteria(raw["criteria"], tools, where)
    complications = _parse_complications(raw["complications"], where)

    return JourneyDefinition(
        journey_id=journey_id,
        title=_string(raw["title"], f"{where}: title", error=error),
        agent_role=_string(raw["agent_role"], f"{where}: agent_role", error=error),
        tools=tools,
        permitted_behavior=_unique_strings(
            raw["permitted_behavior"], f"{where}: permitted_behavior", error=error
        ),
        required_rules=_parse_required_rules(
            raw["required_rules"],
            assertion_ids,
            tuple(criterion.id for criterion in judge_criteria),
            where,
        ),
        valid_outcomes=_parse_valid_outcomes(raw["valid_outcomes"], tools, where),
        assertion_ids=assertion_ids,
        judge_criteria=judge_criteria,
        knowledge_rules=_parse_knowledge_rules(raw["knowledge_rules"], where),
        supported_complications=complications[0],
        unsupported_complications=complications[1],
        max_turns_default=_positive_int(
            raw["max_turns_default"], f"{where}: max_turns_default", error=error
        ),
        source=str(path),
    )


def _parse_criteria(
    raw: Any, tools: tuple[str, ...], where: str
) -> tuple[tuple[str, ...], tuple[JudgeCriterion, ...]]:
    error = JourneyDefinitionError
    spot = f"{where}: criteria"
    criteria = _mapping(raw, spot, error=error)
    _strict(criteria, {"assertions", "judge"}, spot, error=error)
    assertion_ids = _unique_strings(
        criteria["assertions"], f"{spot}.assertions", error=error
    )
    for assertion_id in assertion_ids:
        if assertion_id not in checks.ASSERTIONS:
            raise error(
                f"{spot}.assertions: unknown Assertion {assertion_id!r} "
                f"(known: {sorted(checks.ASSERTIONS)})"
            )
        unread = set(checks.ASSERTIONS[assertion_id].tools) - set(tools)
        if unread:
            raise error(
                f"{spot}.assertions: {assertion_id!r} reads tool(s) {sorted(unread)} "
                "that the Journey's tools do not list"
            )
    return assertion_ids, _parse_judge_criteria(criteria["judge"], tools, spot)


def _parse_judge_criteria(
    raw: Any, tools: tuple[str, ...], where: str
) -> tuple[JudgeCriterion, ...]:
    error = JourneyDefinitionError
    judge_criteria: list[JudgeCriterion] = []
    for i, item in enumerate(_list(raw, f"{where}.judge", error=error)):
        spot = f"{where}.judge[{i}]"
        criterion = _mapping(item, spot, error=error)
        _strict(criterion, {"id", "statement", "tools"}, spot, error=error)
        # A criterion about the conversation rather than a tool says so with
        # an empty list; the field is never left out.
        criterion_tools = _unique_strings(
            criterion["tools"], f"{spot}.tools", error=error, allow_empty=True
        )
        unlisted = sorted(set(criterion_tools) - set(tools))
        if unlisted:
            raise error(
                f"{spot}.tools: {unlisted} are not among the Journey's tools "
                f"({sorted(tools)})"
            )
        judge_criteria.append(
            JudgeCriterion(
                id=_string(criterion["id"], f"{spot}.id", error=error),
                statement=_string(criterion["statement"], f"{spot}.statement", error=error),
                tools=criterion_tools,
            )
        )
    _require_unique_ids([c.id for c in judge_criteria], f"{where}.judge", error)
    return tuple(judge_criteria)


def _parse_required_rules(
    raw: Any, assertion_ids: tuple[str, ...], judge_ids: tuple[str, ...], where: str
) -> tuple[RequiredRule, ...]:
    error = JourneyDefinitionError
    applied = {"assertion": set(assertion_ids), "judge": set(judge_ids)}
    rules: list[RequiredRule] = []
    for i, item in enumerate(_list(raw, f"{where}: required_rules", error=error)):
        spot = f"{where}: required_rules[{i}]"
        rule = _mapping(item, spot, error=error)
        _strict(rule, {"id", "statement", "checks"}, spot, error=error)
        references = _unique_strings(rule["checks"], f"{spot}.checks", error=error)
        for reference in references:
            kind, _, check_id = reference.partition(":")
            if kind not in _CHECK_KINDS or not check_id:
                raise error(
                    f"{spot}.checks: {reference!r} must be written "
                    "'assertion:<id>' or 'judge:<id>'"
                )
            if check_id not in applied[kind]:
                raise error(
                    f"{spot}.checks: {reference!r} is not listed under criteria, "
                    "so the rule would go unchecked"
                )
        rules.append(
            RequiredRule(
                id=_string(rule["id"], f"{spot}.id", error=error),
                statement=_string(rule["statement"], f"{spot}.statement", error=error),
                checks=references,
            )
        )
    _require_unique_ids([r.id for r in rules], f"{where}: required_rules", error)
    return tuple(rules)


def _parse_valid_outcomes(
    raw: Any, tools: tuple[str, ...], where: str
) -> tuple[ValidOutcome, ...]:
    error = JourneyDefinitionError
    outcomes: list[ValidOutcome] = []
    for i, item in enumerate(_list(raw, f"{where}: valid_outcomes", error=error)):
        spot = f"{where}: valid_outcomes[{i}]"
        outcome = _mapping(item, spot, error=error)
        _strict(outcome, {"id", "description", "when"}, spot, error=error)
        outcome_id = _string(outcome["id"], f"{spot}.id", error=error)
        if outcome_id not in checks.OUTCOME_IDS:
            raise error(
                f"{spot}.id: {outcome_id!r} has no {checks.EXPECTED_OUTCOME_EVIDENCED} "
                f"rule (known: {sorted(checks.OUTCOME_IDS)})"
            )
        when = _mapping(outcome["when"], f"{spot}.when", error=error)
        _strict(when, {"tool_failures"}, f"{spot}.when", error=error)
        tool_failures = _unique_strings(
            when["tool_failures"], f"{spot}.when.tool_failures", error=error,
            allow_empty=True,
        )
        for tool in tool_failures:
            if tool not in tools or tool not in SUPPORTED_TOOL_FAILURES:
                raise error(
                    f"{spot}.when.tool_failures: {tool!r} is not a Journey tool with a "
                    f"supported controlled failure ({sorted(SUPPORTED_TOOL_FAILURES)})"
                )
        outcomes.append(
            ValidOutcome(
                id=outcome_id,
                description=_string(
                    outcome["description"], f"{spot}.description", error=error
                ),
                tool_failures=tool_failures,
            )
        )
    _require_unique_ids([o.id for o in outcomes], f"{where}: valid_outcomes", error)
    conditions = [frozenset(o.tool_failures) for o in outcomes]
    if len(set(conditions)) != len(conditions):
        raise error(
            f"{where}: valid_outcomes: two outcomes share one 'when' condition, so the "
            "expected outcome cannot be derived"
        )
    return tuple(outcomes)


def _parse_knowledge_rules(raw: Any, where: str) -> tuple[KnowledgeRule, ...]:
    error = JourneyDefinitionError
    rules: list[KnowledgeRule] = []
    for i, item in enumerate(_list(raw, f"{where}: knowledge_rules", error=error)):
        spot = f"{where}: knowledge_rules[{i}]"
        rule = _mapping(item, spot, error=error)
        _strict(rule, {"id", "statement"}, spot, error=error)
        rules.append(
            KnowledgeRule(
                id=_string(rule["id"], f"{spot}.id", error=error),
                statement=_string(rule["statement"], f"{spot}.statement", error=error),
            )
        )
    _require_unique_ids([r.id for r in rules], f"{where}: knowledge_rules", error)
    return tuple(rules)


def _parse_complications(
    raw: Any, where: str
) -> tuple[tuple[str, ...], Mapping[str, str]]:
    error = JourneyDefinitionError
    spot = f"{where}: complications"
    complications = _mapping(raw, spot, error=error)
    _strict(complications, {"supported", "unsupported"}, spot, error=error)
    supported = _unique_strings(
        complications["supported"], f"{spot}.supported", error=error
    )
    unsupported = {
        _string(key, f"{spot}.unsupported key", error=error): _string(
            reason, f"{spot}.unsupported[{key!r}]", error=error
        )
        for key, reason in _mapping(
            complications["unsupported"], f"{spot}.unsupported", error=error
        ).items()
    }
    both = set(supported) & set(unsupported)
    if both:
        raise error(f"{spot}: {sorted(both)} listed as both supported and unsupported")
    accounted = set(supported) | set(unsupported)
    if accounted != COMPLICATION_IDS:
        raise error(
            f"{spot}: every Complication must appear exactly once; "
            f"missing {sorted(COMPLICATION_IDS - accounted)}, "
            f"unknown {sorted(accounted - COMPLICATION_IDS)}"
        )
    return supported, unsupported


def _require_unique_ids(ids: list[str], where: str, error: type[Exception]) -> None:
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise error(f"{where}: duplicate id(s) {duplicates}")
    if not ids:
        raise error(f"{where} must not be empty")


# ----------------------------------------------------------- Fixture state

_CUSTOMER_FIELDS = {"customer_id", "name"}
_APPOINTMENT_FIELDS = {
    "appointment_id", "customer_id", "confirmation_code", "service", "provider",
    "start", "status",
}
_SLOT_FIELDS = {"slot_id", "service", "provider", "start", "available"}
_COLLECTION_ID_FIELDS = {
    "customers": "customer_id",
    "appointments": "appointment_id",
    "slots": "slot_id",
}


def canonical_json(value: Any) -> bytes:
    """The byte form both the harness and the agent service hash (design note
    section 3): sorted keys, no whitespace, UTF-8."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


@dataclass(frozen=True)
class FixtureState:
    """The grounded domain data available at the start of an Episode. Treat
    ``data`` as read-only; ``to_payload()`` is the copy that leaves."""

    data: Mapping[str, Any]
    source: str

    @property
    def fixture_state_id(self) -> str:
        return self.data["fixture_state_id"]

    @property
    def now(self) -> str:
        return self.data["now"]

    @property
    def customers(self) -> list[dict[str, Any]]:
        return self.data["customers"]

    @property
    def appointments(self) -> list[dict[str, Any]]:
        return self.data["appointments"]

    @property
    def slots(self) -> list[dict[str, Any]]:
        return self.data["slots"]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.data)).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        """A detached copy to send inline when a conversation starts."""
        return copy.deepcopy(dict(self.data))

    def customer(self, customer_id: str) -> dict[str, Any] | None:
        return self._row("customers", customer_id)

    def appointment(self, appointment_id: str) -> dict[str, Any] | None:
        return self._row("appointments", appointment_id)

    def slot(self, slot_id: str) -> dict[str, Any] | None:
        return self._row("slots", slot_id)

    def fact(self, path: str) -> Any:
        """Resolve a grounded-fact path, ``<collection>.<id>.<field>`` (for
        example ``appointments.A-1001.start``). Ids and field names hold no
        dots. Raises ``FixtureStateError`` when the path names nothing."""
        parts = path.split(".")
        if len(parts) != 3 or parts[0] not in _COLLECTION_ID_FIELDS:
            raise FixtureStateError(
                f"grounded-fact path {path!r} must be '<collection>.<id>.<field>' "
                f"with a collection from {sorted(_COLLECTION_ID_FIELDS)}"
            )
        row = self._row(parts[0], parts[1])
        if row is None or parts[2] not in row:
            raise FixtureStateError(
                f"grounded-fact path {path!r} names nothing in Fixture state "
                f"{self.fixture_state_id!r}"
            )
        return row[parts[2]]

    def _row(self, collection: str, row_id: str) -> dict[str, Any] | None:
        id_field = _COLLECTION_ID_FIELDS[collection]
        for row in self.data[collection]:
            if row[id_field] == row_id:
                return row
        return None


def load_fixture_state(path: str | Path) -> FixtureState:
    path = Path(path)
    where = path.name
    error = FixtureStateError
    raw = _load_yaml(path, error=error)
    _strict(
        raw,
        {"schema_version", "fixture_state_id", "now", "customers", "appointments", "slots"},
        where,
        error=error,
    )
    _schema_version(raw["schema_version"], where, error=error)
    _string(raw["fixture_state_id"], f"{where}: fixture_state_id", error=error)

    customers = _rows(raw, "customers", _CUSTOMER_FIELDS, where)
    appointments = _rows(raw, "appointments", _APPOINTMENT_FIELDS, where)
    slots = _rows(raw, "slots", _SLOT_FIELDS, where)

    customer_ids = {c["customer_id"] for c in customers}
    for appointment in appointments:
        spot = f"{where}: appointment {appointment['appointment_id']!r}"
        if appointment["customer_id"] not in customer_ids:
            raise error(
                f"{spot} references unknown customer {appointment['customer_id']!r}"
            )
        if appointment["status"] not in APPOINTMENT_STATUSES:
            raise error(
                f"{spot}: status must be one of {sorted(APPOINTMENT_STATUSES)}, "
                f"got {appointment['status']!r}"
            )

    # Times are compared by the agent's tools, so they must all parse and
    # agree on carrying a UTC offset or not.
    times = [(f"{where}: now", raw["now"])]
    times += [(f"{where}: appointment {a['appointment_id']!r}", a["start"]) for a in appointments]
    times += [(f"{where}: slot {s['slot_id']!r}", s["start"]) for s in slots]
    offsets = set()
    for label, value in times:
        _date_time(value, label)
        try:
            offsets.add(datetime.fromisoformat(value).tzinfo is not None)
        except ValueError:
            raise error(f"{label}: {value!r} is not an ISO 8601 date-time") from None
    if len(offsets) > 1:
        raise error(
            f"{where}: date-times must either all carry a UTC offset or all omit it"
        )

    return FixtureState(data=copy.deepcopy(dict(raw)), source=str(path))


def _date_time(value: Any, where: str) -> None:
    # PyYAML turns an unquoted timestamp into a datetime, which cannot be hashed
    # as canonical JSON or sent inline.
    if not isinstance(value, str) or not value:
        raise FixtureStateError(
            f"{where}: date-time must be a quoted ISO 8601 string, "
            f"got {type(value).__name__}"
        )


def _rows(
    raw: Mapping[str, Any], key: str, fields: set[str], where: str
) -> list[dict[str, Any]]:
    error = FixtureStateError
    id_field = _COLLECTION_ID_FIELDS[key]
    rows = _list(raw[key], f"{where}: {key}", error=error)
    if not rows:
        raise error(f"{where}: {key} must not be empty")
    seen: set[str] = set()
    for i, row in enumerate(rows):
        spot = f"{where}: {key}[{i}]"
        _strict(_mapping(row, spot, error=error), fields, spot, error=error)
        for field in sorted(fields - {"available", "start"}):
            if not isinstance(row[field], str) or not row[field].strip():
                raise error(f"{spot}.{field} must be a non-empty string")
        if "." in row[id_field]:
            raise error(
                f"{spot}.{id_field} must not contain '.': grounded-fact paths split on it"
            )
        if "available" in fields and not isinstance(row["available"], bool):
            raise error(f"{spot}.available must be true or false")
        if row[id_field] in seen:
            raise error(f"{spot}: duplicate {id_field} {row[id_field]!r}")
        seen.add(row[id_field])
    return rows


def load_journey_inputs(directory: str | Path) -> tuple[JourneyDefinition, FixtureState]:
    """Load a Journey directory: ``journey.yaml`` plus ``fixture_state.yaml``."""
    directory = Path(directory)
    return (
        load_journey_definition(directory / JOURNEY_FILE),
        load_fixture_state(directory / FIXTURE_STATE_FILE),
    )
