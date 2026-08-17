"""The stable, YAML-serializable input to scenario synthesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from agentsim.scenario import ToolAssertion


class BlueprintError(ValueError):
    """A blueprint cannot be decoded from its serialized representation."""


@dataclass(frozen=True)
class FixtureBindings:
    cards: tuple[str, ...]
    accounts: tuple[str, ...]


@dataclass(frozen=True)
class Perturbation:
    type: str
    position: str


@dataclass(frozen=True)
class Provenance:
    generator_version: str
    seed: int
    graph_hash: str
    fixture_hash: str


@dataclass(frozen=True)
class Blueprint:
    id: str
    journey: str
    procedure_path: tuple[str, ...]
    policies: tuple[str, ...]
    fixture_bindings: FixtureBindings
    goal_facts: Mapping[str, Any]
    perturbations: tuple[Perturbation, ...]
    tool_assertions: tuple[ToolAssertion, ...]
    max_turns: int
    provenance: Provenance

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Blueprint:
        if not isinstance(raw, Mapping):
            raise BlueprintError("blueprint must be a mapping")
        expected = {
            "id",
            "journey",
            "procedure_path",
            "policies",
            "fixture_bindings",
            "goal_facts",
            "perturbations",
            "tool_assertions",
            "max_turns",
            "provenance",
        }
        missing = expected - raw.keys()
        unknown = raw.keys() - expected
        if missing:
            raise BlueprintError(f"missing field(s): {sorted(missing)}")
        if unknown:
            raise BlueprintError(f"unknown field(s): {sorted(unknown)}")

        bindings = _mapping(raw["fixture_bindings"], "fixture_bindings")
        provenance = _mapping(raw["provenance"], "provenance")
        facts = _mapping(raw["goal_facts"], "goal_facts")
        perturbations = tuple(
            Perturbation(
                type=_string(item, "type", f"perturbations[{index}]"),
                position=_string(item, "position", f"perturbations[{index}]"),
            )
            for index, item in enumerate(_list(raw["perturbations"], "perturbations"))
        )
        assertions = tuple(
            ToolAssertion(
                type=_string(item, "type", f"tool_assertions[{index}]"),
                fields={str(k): str(v) for k, v in item.items() if k != "type"},
            )
            for index, item in enumerate(_mapping_list(raw["tool_assertions"], "tool_assertions"))
        )
        max_turns = raw["max_turns"]
        seed = provenance.get("seed")
        if isinstance(max_turns, bool) or not isinstance(max_turns, int):
            raise BlueprintError("max_turns must be an integer")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise BlueprintError("provenance.seed must be an integer")

        return cls(
            id=_required_string(raw, "id", "blueprint"),
            journey=_required_string(raw, "journey", "blueprint"),
            procedure_path=_strings(raw["procedure_path"], "procedure_path"),
            policies=_strings(raw["policies"], "policies"),
            fixture_bindings=FixtureBindings(
                cards=_strings(bindings.get("cards"), "fixture_bindings.cards"),
                accounts=_strings(bindings.get("accounts"), "fixture_bindings.accounts"),
            ),
            goal_facts=dict(facts),
            perturbations=perturbations,
            tool_assertions=assertions,
            max_turns=max_turns,
            provenance=Provenance(
                generator_version=_required_string(provenance, "generator_version", "provenance"),
                seed=seed,
                graph_hash=_required_string(provenance, "graph_hash", "provenance"),
                fixture_hash=_required_string(provenance, "fixture_hash", "provenance"),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "journey": self.journey,
            "procedure_path": list(self.procedure_path),
            "policies": list(self.policies),
            "fixture_bindings": {
                "cards": list(self.fixture_bindings.cards),
                "accounts": list(self.fixture_bindings.accounts),
            },
            "goal_facts": dict(self.goal_facts),
            "perturbations": [
                {"type": item.type, "position": item.position}
                for item in self.perturbations
            ],
            "tool_assertions": [
                {"type": item.type, **item.fields} for item in self.tool_assertions
            ],
            "max_turns": self.max_turns,
            "provenance": {
                "generator_version": self.provenance.generator_version,
                "seed": self.provenance.seed,
                "graph_hash": self.provenance.graph_hash,
                "fixture_hash": self.provenance.fixture_hash,
            },
        }


def load_blueprint(path: str | Path) -> Blueprint:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise BlueprintError(f"{path}: cannot load blueprint: {exc}") from exc
    return Blueprint.from_dict(raw)


def dump_blueprint(blueprint: Blueprint, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(blueprint.to_dict(), sort_keys=False))


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BlueprintError(f"{where} must be a mapping")
    return value


def _list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise BlueprintError(f"{where} must be a list")
    return value


def _mapping_list(value: Any, where: str) -> list[Mapping[str, Any]]:
    items = _list(value, where)
    if not all(isinstance(item, Mapping) for item in items):
        raise BlueprintError(f"{where} entries must be mappings")
    return items


def _strings(value: Any, where: str) -> tuple[str, ...]:
    items = _list(value, where)
    if not all(isinstance(item, str) and item for item in items):
        raise BlueprintError(f"{where} entries must be non-empty strings")
    return tuple(items)


def _required_string(raw: Mapping[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise BlueprintError(f"{where}.{key} must be a non-empty string")
    return value


def _string(raw: Any, key: str, where: str) -> str:
    return _required_string(_mapping(raw, where), key, where)
