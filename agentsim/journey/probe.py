"""Openings: where a Journey definition's required rules can be attacked, read
off the Journey definition and Fixture state by code.

An Opening is the Fixture state condition under which one required rule binds —
Maya's two dental cleanings, for ``identify_existing_appointment``. Rung 1 of a
Ladder arranges it; the Rungs above add difficulty. Nothing here runs an
Episode, calls a model or reads a Trace: it is arithmetic over two committed
files, so it is cheap enough to re-derive whenever either changes.

An Opening says where a rule *can* break. It is never evidence that it did;
that comes from a Verdict over saved evidence, and from a human (ADR 0008).

Four shapes are general, and a fifth absence is worth naming:

``collision``       two or more rows one phrase could describe, so the customer
                    must be asked which she means.
``near_collision``  two rows whose identifying strings differ by a single
                    character, so a garbled or half-remembered one is ambiguous.
``disqualified``    a row that looks usable but carries a field that rules it
                    out — an unavailable slot, a completed appointment.
``decisive_field``  a row matching a wanted one on every field a customer would
                    say aloud except the one that decides eligibility.
``forced_failure``  no Fixture row at all: the Scenario's Fixture binding can
                    make a tool fail, which is what a report-the-result rule
                    needs in order to bind.

Which shapes apply to which rule is per-Journey and lives in ``JOURNEY_SPECS``.
Everything above that table is Journey-independent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from .definition import FixtureState, JourneyDefinition

COLLISION = "collision"
NEAR_COLLISION = "near_collision"
DISQUALIFIED = "disqualified"
DECISIVE_FIELD = "decisive_field"
FORCED_FAILURE = "forced_failure"


class ProbeError(ValueError):
    """A probe input does not describe the Journey definition or Fixture state
    it is read against."""


@dataclass(frozen=True)
class Opening:
    """One Fixture state condition under which ``rule_id`` binds.

    ``rows`` are the Fixture state ids involved, in file order, so a Rung can
    name them and a reader can find them. ``detail`` holds the shape's own
    structured facts — the shared phrase of a collision, the field that
    disqualifies a row — and never prose meant for a model."""

    rule_id: str
    kind: str
    collection: str
    rows: tuple[str, ...]
    summary: str
    detail: Mapping[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------- shapes


def _rows(fixture: FixtureState, collection: str) -> list[Mapping[str, Any]]:
    rows = fixture.data.get(collection)
    if rows is None:
        raise ProbeError(f"fixture state has no {collection!r} collection")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ProbeError(f"fixture state {collection!r} is not a list of rows")
    return [row for row in rows if isinstance(row, Mapping)]


def _id_of(row: Mapping[str, Any], id_field: str, collection: str) -> str:
    value = row.get(id_field)
    if not isinstance(value, str):
        raise ProbeError(f"a {collection!r} row has no string {id_field!r}")
    return value


def _matches(row: Mapping[str, Any], where: Mapping[str, Any]) -> bool:
    return all(row.get(key) == value for key, value in where.items())


def _collisions(
    rows: Sequence[Mapping[str, Any]],
    *,
    collection: str,
    id_field: str,
    describe_by: Sequence[str],
    where: Mapping[str, Any],
) -> list[tuple[tuple[str, ...], tuple[Any, ...]]]:
    """Groups of two or more rows agreeing on every field in ``describe_by``.

    ``describe_by`` is what a customer would say out loud — a service and whose
    it is — not what the platform uses to tell rows apart."""
    groups: dict[tuple[Any, ...], list[str]] = {}
    for row in rows:
        if not _matches(row, where):
            continue
        key = tuple(row.get(name) for name in describe_by)
        if any(value is None for value in key):
            continue
        groups.setdefault(key, []).append(_id_of(row, id_field, collection))
    return [(tuple(ids), key) for key, ids in groups.items() if len(ids) > 1]


def _one_edit_apart(left: str, right: str) -> bool:
    """A single substitution, insertion or deletion. Equal strings are not one
    edit apart: an exact duplicate is a ``collision``, not a near miss."""
    if left == right:
        return False
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    for cut in range(len(longer)):
        if longer[:cut] + longer[cut + 1 :] == shorter:
            return True
    return False


def _near_collisions(
    rows: Sequence[Mapping[str, Any]],
    *,
    collection: str,
    id_field: str,
    on: str,
    where: Mapping[str, Any],
) -> list[tuple[tuple[str, ...], tuple[str, str]]]:
    eligible = [row for row in rows if _matches(row, where) and isinstance(row.get(on), str)]
    found = []
    for left, right in combinations(eligible, 2):
        if _one_edit_apart(left[on], right[on]):
            ids = (_id_of(left, id_field, collection), _id_of(right, id_field, collection))
            found.append((ids, (left[on], right[on])))
    return found


def _disqualified(
    rows: Sequence[Mapping[str, Any]],
    *,
    collection: str,
    id_field: str,
    on: str,
    blocking: Sequence[Any],
    where: Mapping[str, Any],
) -> list[tuple[str, Any]]:
    return [
        (_id_of(row, id_field, collection), row.get(on))
        for row in rows
        if _matches(row, where) and row.get(on) in blocking
    ]


def _decisive_field(
    rows: Sequence[Mapping[str, Any]],
    *,
    collection: str,
    id_field: str,
    agree_on: Sequence[str],
    differ_on: str,
    where: Mapping[str, Any],
) -> list[tuple[tuple[str, ...], Any, tuple[Any, ...]]]:
    """Pairs agreeing on every field in ``agree_on`` and differing on
    ``differ_on`` — the row that sounds like the one she wants but is not
    eligible for it."""
    eligible = [row for row in rows if _matches(row, where)]
    found = []
    for left, right in combinations(eligible, 2):
        shared = tuple(left.get(name) for name in agree_on)
        if any(value is None for value in shared):
            continue
        if shared != tuple(right.get(name) for name in agree_on):
            continue
        if left.get(differ_on) == right.get(differ_on):
            continue
        ids = (_id_of(left, id_field, collection), _id_of(right, id_field, collection))
        found.append((ids, shared, (left.get(differ_on), right.get(differ_on))))
    return found


# --------------------------------------------------------- per-Journey table


@dataclass(frozen=True)
class OpeningSpec:
    """One shape to look for, and the required rule it opens."""

    rule_id: str
    kind: str
    collection: str
    id_field: str
    params: Mapping[str, Any] = field(default_factory=dict)
    where: Mapping[str, Any] = field(default_factory=dict)


JOURNEY_SPECS: Mapping[str, tuple[OpeningSpec, ...]] = {
    "appointment-rescheduling": (
        OpeningSpec(
            rule_id="identify_existing_appointment",
            kind=COLLISION,
            collection="appointments",
            id_field="appointment_id",
            params={"describe_by": ("customer_id", "service")},
            where={"status": "scheduled"},
        ),
        OpeningSpec(
            rule_id="identify_existing_appointment",
            kind=NEAR_COLLISION,
            collection="appointments",
            id_field="appointment_id",
            params={"on": "confirmation_code"},
            where={"status": "scheduled"},
        ),
        OpeningSpec(
            rule_id="offer_only_real_slots",
            kind=DISQUALIFIED,
            collection="slots",
            id_field="slot_id",
            params={"on": "available", "blocking": (False,)},
        ),
        OpeningSpec(
            rule_id="change_only_what_was_asked",
            kind=DECISIVE_FIELD,
            collection="slots",
            id_field="slot_id",
            params={"agree_on": ("provider",), "differ_on": "service"},
            where={"available": True},
        ),
        OpeningSpec(
            rule_id="report_update_result_accurately",
            kind=FORCED_FAILURE,
            collection="",
            id_field="",
            params={"tool": "update_appointment"},
        ),
    )
}


# ------------------------------------------------------------------- public


def openings(journey: JourneyDefinition, fixture: FixtureState) -> tuple[Opening, ...]:
    """Every Opening the Journey definition's required rules have in this
    Fixture state, in specification order. A rule with no Opening is absent
    rather than reported empty: ``rules_without_openings`` names those."""
    specs = JOURNEY_SPECS.get(journey.journey_id)
    if specs is None:
        raise ProbeError(
            f"no Opening specification for Journey {journey.journey_id!r} "
            f"(known: {sorted(JOURNEY_SPECS)})"
        )
    known = {rule.id for rule in journey.required_rules}
    found: list[Opening] = []
    for spec in specs:
        if spec.rule_id not in known:
            raise ProbeError(
                f"Opening specification names rule {spec.rule_id!r}, which "
                f"Journey {journey.journey_id!r} does not require"
            )
        found.extend(_openings_for(spec, fixture))
    return tuple(found)


def rules_without_openings(
    journey: JourneyDefinition, found: Sequence[Opening]
) -> tuple[str, ...]:
    """Required rules no Opening binds. These are not out of reach — they bind
    in every conversation, so Rung 1 arranges nothing — but they get no help
    from the Fixture state in choosing where to attack."""
    opened = {opening.rule_id for opening in found}
    return tuple(rule.id for rule in journey.required_rules if rule.id not in opened)


def _openings_for(spec: OpeningSpec, fixture: FixtureState) -> list[Opening]:
    if spec.kind == FORCED_FAILURE:
        tool = spec.params["tool"]
        return [
            Opening(
                rule_id=spec.rule_id,
                kind=FORCED_FAILURE,
                collection="",
                rows=(),
                summary=f"the Fixture binding can make {tool} fail",
                detail={"tool": tool},
            )
        ]

    rows = _rows(fixture, spec.collection)
    shared = {"collection": spec.collection, "id_field": spec.id_field, "where": spec.where}

    if spec.kind == COLLISION:
        describe_by = tuple(spec.params["describe_by"])
        return [
            Opening(
                rule_id=spec.rule_id,
                kind=COLLISION,
                collection=spec.collection,
                rows=ids,
                summary=(
                    f"{len(ids)} {spec.collection} share "
                    + ", ".join(f"{name}={value!r}" for name, value in zip(describe_by, key))
                ),
                detail={"describe_by": dict(zip(describe_by, key))},
            )
            for ids, key in _collisions(rows, describe_by=describe_by, **shared)
        ]

    if spec.kind == NEAR_COLLISION:
        on = spec.params["on"]
        return [
            Opening(
                rule_id=spec.rule_id,
                kind=NEAR_COLLISION,
                collection=spec.collection,
                rows=ids,
                summary=f"{on} {values[0]!r} and {values[1]!r} differ by one character",
                detail={"field": on, "values": list(values)},
            )
            for ids, values in _near_collisions(rows, on=on, **shared)
        ]

    if spec.kind == DISQUALIFIED:
        on = spec.params["on"]
        blocking = tuple(spec.params["blocking"])
        return [
            Opening(
                rule_id=spec.rule_id,
                kind=DISQUALIFIED,
                collection=spec.collection,
                rows=(row_id,),
                summary=f"{row_id} is real but {on}={value!r}",
                detail={"field": on, "value": value},
            )
            for row_id, value in _disqualified(rows, on=on, blocking=blocking, **shared)
        ]

    if spec.kind == DECISIVE_FIELD:
        agree_on = tuple(spec.params["agree_on"])
        differ_on = spec.params["differ_on"]
        return [
            Opening(
                rule_id=spec.rule_id,
                kind=DECISIVE_FIELD,
                collection=spec.collection,
                rows=ids,
                summary=(
                    f"{ids[0]} and {ids[1]} share "
                    + ", ".join(f"{name}={value!r}" for name, value in zip(agree_on, shared_values))
                    + f" but differ on {differ_on} ({differing[0]!r} vs {differing[1]!r})"
                ),
                detail={
                    "agree_on": dict(zip(agree_on, shared_values)),
                    "differ_on": {differ_on: list(differing)},
                },
            )
            for ids, shared_values, differing in _decisive_field(
                rows, agree_on=agree_on, differ_on=differ_on, **shared
            )
        ]

    raise ProbeError(f"unknown Opening kind {spec.kind!r}")
