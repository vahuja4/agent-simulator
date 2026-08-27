"""The stable, YAML-serializable input to scenario synthesis."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from agentsim.scenario import ToolAssertion
from ._strict import _mapping as _shared_mapping


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
    """LEGACY — replaced by Phase 4.5 scenario synthesis; delete at cutover. Do not add features here."""

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


def _load_legacy_blueprint(path: str | Path) -> Blueprint:
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


def canonical_blueprint_id(blueprint: Blueprint) -> str:
    """Hash the complete canonical blueprint content, excluding only its ID."""
    material = blueprint.to_dict()
    material.pop("id")
    encoded = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    return f"{blueprint.journey.lower()}-{digest}"


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    return _shared_mapping(value, where, error=BlueprintError)


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


# Phase 4.5 qualification blueprints.  The legacy ``Blueprint`` above remains
# readable by the prototype reconciliation only; it is not a qualification
# identity and is never converted into this schema implicitly.
QUALIFICATION_BLUEPRINT_SCHEMA_VERSION = 1
SOURCE_HASH_KEYS = {
    "journey_graph",
    "fixture",
    "persona_archetypes",
    "complication_applicability",
    "pair_exclusions",
    "fixture_state_classes",
    "fitness_targets",
}


@dataclass(frozen=True)
class CoverageCell:
    """The six canonical axes; target shape is part of the Fitness axis."""

    journey_path_id: str
    persona_archetype: str
    knowledge_level: str
    complication: str
    fixture_state_class_id: str
    fitness_target_id: str | None
    fitness_shape_id: str | None


@dataclass(frozen=True)
class GenerationProvenance:
    generator_version: str
    config_hash: str
    source_hashes: Mapping[str, str]
    generated_at: str


@dataclass(frozen=True)
class CoverageBlueprint:
    schema_version: int
    blueprint_id: str
    cell_id: str
    journey_path_id: str
    persona_archetype: str
    knowledge_level: str
    complication: str
    fixture_state_class_id: str
    fitness_target_id: str | None
    fitness_shape_id: str | None
    journey_edge_ids: tuple[str, ...]
    fixture_bindings: FixtureBindings
    goal_facts: Mapping[str, Any]
    required_assertions: tuple[ToolAssertion, ...]
    required_criteria: tuple[str, ...]
    max_turns: int
    provenance: GenerationProvenance

    @property
    def cell(self) -> CoverageCell:
        return CoverageCell(
            self.journey_path_id,
            self.persona_archetype,
            self.knowledge_level,
            self.complication,
            self.fixture_state_class_id,
            self.fitness_target_id,
            self.fitness_shape_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "blueprint_id": self.blueprint_id,
            "cell_id": self.cell_id,
            "journey_path_id": self.journey_path_id,
            "persona_archetype": self.persona_archetype,
            "knowledge_level": self.knowledge_level,
            "complication": self.complication,
            "fixture_state_class_id": self.fixture_state_class_id,
            "fitness_target_id": self.fitness_target_id,
            "fitness_shape_id": self.fitness_shape_id,
            "journey_edge_ids": list(self.journey_edge_ids),
            "fixture_bindings": {
                "cards": list(self.fixture_bindings.cards),
                "accounts": list(self.fixture_bindings.accounts),
            },
            "goal_facts": dict(self.goal_facts),
            "required_assertions": [
                {"type": assertion.type, **assertion.fields}
                for assertion in self.required_assertions
            ],
            "required_criteria": list(self.required_criteria),
            "max_turns": self.max_turns,
            "provenance": {
                "generator_version": self.provenance.generator_version,
                "config_hash": self.provenance.config_hash,
                "source_hashes": dict(self.provenance.source_hashes),
                "generated_at": self.provenance.generated_at,
            },
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CoverageBlueprint:
        if not isinstance(raw, Mapping):
            raise BlueprintError("coverage blueprint must be a mapping")
        fields = {
            "schema_version", "blueprint_id", "cell_id", "journey_path_id",
            "persona_archetype", "knowledge_level", "complication",
            "fixture_state_class_id", "fitness_target_id", "fitness_shape_id",
            "journey_edge_ids", "fixture_bindings", "goal_facts",
            "required_assertions", "required_criteria", "max_turns", "provenance",
        }
        _strict_blueprint(raw, fields, "coverage blueprint")
        version = raw["schema_version"]
        if version != QUALIFICATION_BLUEPRINT_SCHEMA_VERSION or isinstance(version, bool):
            raise BlueprintError(f"unsupported coverage blueprint schema_version {version!r}")
        target = raw["fitness_target_id"]
        shape = raw["fitness_shape_id"]
        if target is not None and (not isinstance(target, str) or not target):
            raise BlueprintError("fitness_target_id must be null or a non-empty string")
        if (target is None) != (shape is None):
            raise BlueprintError("fitness_target_id and fitness_shape_id must both be null or set")
        if shape is not None and (not isinstance(shape, str) or not shape):
            raise BlueprintError("fitness_shape_id must be null or a non-empty string")
        bindings = _mapping(raw["fixture_bindings"], "fixture_bindings")
        _strict_blueprint(bindings, {"cards", "accounts"}, "fixture_bindings")
        provenance = _mapping(raw["provenance"], "provenance")
        _strict_blueprint(
            provenance,
            {"generator_version", "config_hash", "source_hashes", "generated_at"},
            "provenance",
        )
        source_hashes = _mapping(provenance["source_hashes"], "provenance.source_hashes")
        if set(source_hashes) != SOURCE_HASH_KEYS:
            raise BlueprintError(
                "provenance.source_hashes must contain exactly "
                f"{sorted(SOURCE_HASH_KEYS)}"
            )
        assertions = tuple(
            ToolAssertion(
                type=_required_string(item, "type", f"required_assertions[{index}]"),
                fields={str(key): str(value) for key, value in item.items() if key != "type"},
            )
            for index, item in enumerate(
                _mapping_list(raw["required_assertions"], "required_assertions")
            )
        )
        max_turns = raw["max_turns"]
        if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns <= 0:
            raise BlueprintError("max_turns must be a positive integer")
        result = cls(
            schema_version=version,
            blueprint_id=_required_string(raw, "blueprint_id", "coverage blueprint"),
            cell_id=_required_string(raw, "cell_id", "coverage blueprint"),
            journey_path_id=_required_string(raw, "journey_path_id", "coverage blueprint"),
            persona_archetype=_required_string(raw, "persona_archetype", "coverage blueprint"),
            knowledge_level=_required_string(raw, "knowledge_level", "coverage blueprint"),
            complication=_required_string(raw, "complication", "coverage blueprint"),
            fixture_state_class_id=_required_string(raw, "fixture_state_class_id", "coverage blueprint"),
            fitness_target_id=target,
            fitness_shape_id=shape,
            journey_edge_ids=_strings(raw["journey_edge_ids"], "journey_edge_ids"),
            fixture_bindings=FixtureBindings(
                cards=_strings(bindings["cards"], "fixture_bindings.cards"),
                accounts=_strings(bindings["accounts"], "fixture_bindings.accounts"),
            ),
            goal_facts=dict(_mapping(raw["goal_facts"], "goal_facts")),
            required_assertions=assertions,
            required_criteria=_strings(raw["required_criteria"], "required_criteria"),
            max_turns=max_turns,
            provenance=GenerationProvenance(
                generator_version=_required_string(provenance, "generator_version", "provenance"),
                config_hash=_sha256_value(provenance["config_hash"], "provenance.config_hash"),
                source_hashes={
                    str(key): _sha256_value(value, f"provenance.source_hashes.{key}")
                    for key, value in source_hashes.items()
                },
                generated_at=_required_string(provenance, "generated_at", "provenance"),
            ),
        )
        if result.cell_id != canonical_cell_id(result.cell):
            raise BlueprintError("cell_id does not match the canonical six-axis tuple")
        if result.blueprint_id != canonical_coverage_blueprint_id(result):
            raise BlueprintError("blueprint_id does not match semantic blueprint content")
        return result


def canonical_cell_id(value: CoverageCell | CoverageBlueprint) -> str:
    """The sole Same-cell identity implementation."""
    cell = value.cell if isinstance(value, CoverageBlueprint) else value
    fitness = (
        None
        if cell.fitness_target_id is None
        else {"shape_id": cell.fitness_shape_id, "target_id": cell.fitness_target_id}
    )
    material = [
        cell.journey_path_id,
        cell.persona_archetype,
        cell.knowledge_level,
        cell.complication,
        cell.fixture_state_class_id,
        fitness,
    ]
    encoded = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "cell-" + hashlib.sha256(encoded).hexdigest()


def canonical_journey_path_id(journey: str, edge_ids: tuple[str, ...]) -> str:
    encoded = json.dumps(
        list(edge_ids), separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"{journey.lower()}-path-" + hashlib.sha256(encoded).hexdigest()[:16]


def same_cell(left: CoverageCell | CoverageBlueprint, right: CoverageCell | CoverageBlueprint) -> bool:
    return canonical_cell_id(left) == canonical_cell_id(right)


def canonical_coverage_blueprint_id(blueprint: CoverageBlueprint) -> str:
    material = blueprint.to_dict()
    material.pop("blueprint_id")
    provenance = dict(material["provenance"])
    provenance.pop("generated_at")
    material["provenance"] = provenance
    encoded = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "blueprint-" + hashlib.sha256(encoded).hexdigest()


def load_coverage_blueprint(path: str | Path) -> CoverageBlueprint:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BlueprintError(f"{path}: cannot load coverage blueprint: {exc}") from exc
    return CoverageBlueprint.from_dict(raw)


def dump_coverage_blueprint(blueprint: CoverageBlueprint, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(blueprint.to_dict(), sort_keys=False), encoding="utf-8"
    )


def _strict_blueprint(raw: Mapping[str, Any], fields: set[str], where: str) -> None:
    missing = fields - set(raw)
    unknown = set(raw) - fields
    if missing:
        raise BlueprintError(f"{where}: missing field(s) {sorted(missing)}")
    if unknown:
        raise BlueprintError(f"{where}: unknown field(s) {sorted(unknown)}")


def _sha256_value(value: Any, where: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BlueprintError(f"{where} must be a lowercase SHA-256 digest")
    return value


# The unqualified public loader is the strict Phase 4.5 schema.  Historical
# callers must opt into ``compatibility.load_legacy_blueprint`` explicitly.
load_blueprint = load_coverage_blueprint
