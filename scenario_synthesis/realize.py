"""Structured, guarded realization of approved blueprints into scenario YAML."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from agentsim import registry
from agentsim.llm import LLMClient

from .blueprint import Blueprint
from .sample import behavioral_class_key, behavioral_representatives

ROOT = Path(__file__).resolve().parents[1]
TRAIT_FILE = Path(__file__).with_name("persona_traits.yaml")
DEFAULT_YAML_DIR = ROOT / "generated_scenarios" / "yaml"
DEFAULT_MANIFEST = ROOT / "generated_scenarios" / "manifest.json"


class RealizationError(ValueError):
    """The model output is not a fact-equivalent scenario realization."""


def load_trait_whitelist(path: str | Path = TRAIT_FILE) -> dict[str, tuple[str, ...]]:
    raw = yaml.safe_load(Path(path).read_text())
    dimensions = raw.get("dimensions") if isinstance(raw, dict) else None
    if not isinstance(dimensions, dict) or not dimensions:
        raise RealizationError("persona trait whitelist must define dimensions")
    result: dict[str, tuple[str, ...]] = {}
    for dimension, values in dimensions.items():
        if not isinstance(dimension, str) or not isinstance(values, list) or not values:
            raise RealizationError("persona trait whitelist has an invalid dimension")
        if not all(isinstance(value, str) and value for value in values):
            raise RealizationError(f"persona trait dimension {dimension!r} has invalid values")
        result[dimension] = tuple(values)
    return result


def realization_schema(
    whitelist: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    trait_properties = {
        dimension: {"type": "string", "enum": list(values)}
        for dimension, values in whitelist.items()
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "description": {"type": "string"},
            "persona": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "traits": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": trait_properties,
                        "required": list(whitelist),
                    },
                },
                "required": ["name", "traits"],
            },
            "goal": {"type": "string"},
            "success_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
        },
        "required": ["description", "persona", "goal", "success_criteria"],
    }


async def realize_blueprint(
    blueprint: Blueprint,
    llm: LLMClient,
    *,
    trait_path: str | Path = TRAIT_FILE,
) -> dict[str, Any]:
    """Realize once, retrying exactly once after a rejected model response."""
    whitelist = load_trait_whitelist(trait_path)
    schema = realization_schema(whitelist)
    rejection: str | None = None
    for attempt in range(2):
        prompt = _prompt(blueprint)
        if rejection is not None:
            prompt += f"\nThe prior output was rejected: {rejection}. Correct it."
        raw = await llm.structured(
            system=(
                "Realize only the supplied scenario facts. Do not invent numbers, "
                "identifiers, dates, accounts, amounts, tools, or persona traits."
            ),
            messages=[{"role": "user", "content": prompt}],
            schema=schema,
            effort="high",
            max_tokens=2048,
        )
        try:
            return build_scenario(blueprint, raw, whitelist=whitelist)
        except RealizationError as exc:
            rejection = str(exc)
            if attempt == 1:
                raise
    raise AssertionError("unreachable")


def build_scenario(
    blueprint: Blueprint,
    raw: Mapping[str, Any],
    *,
    whitelist: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    whitelist = dict(whitelist or load_trait_whitelist())
    _validate_output_shape(raw, whitelist)
    prose = _generated_prose(raw)
    _check_equivalence(blueprint, prose)
    traits = raw["persona"]["traits"]
    return {
        "name": blueprint.id,
        "journey": blueprint.journey,
        "description": raw["description"].strip(),
        "persona": {
            "name": raw["persona"]["name"].strip(),
            "traits": ", ".join(str(traits[key]).replace("_", " ") for key in whitelist),
        },
        "goal": raw["goal"].strip(),
        "knowledge": {
            "cards": list(blueprint.fixture_bindings.cards),
            "accounts": list(blueprint.fixture_bindings.accounts),
        },
        "success_criteria": [item.strip() for item in raw["success_criteria"]],
        "max_turns": blueprint.max_turns,
        "tool_assertions": [
            {"type": assertion.type, **assertion.fields}
            for assertion in blueprint.tool_assertions
        ],
    }


def write_scenario(scenario: Mapping[str, Any], blueprint: Blueprint) -> Path:
    """Write a realization to the sole production output directory."""
    DEFAULT_YAML_DIR.mkdir(parents=True, exist_ok=True)
    target = DEFAULT_YAML_DIR / f"{blueprint.id}.yaml"
    target.write_text(yaml.safe_dump(dict(scenario), sort_keys=False))
    return target


async def realize_catalog(
    blueprints: Sequence[Blueprint], llm: LLMClient
) -> tuple[Path, ...]:
    """Realize exactly one maximal-policy member of every behavior class."""
    representatives = behavioral_representatives(blueprints)
    entries: list[dict[str, str]] = []
    paths: list[Path] = []
    for blueprint in representatives:
        scenario = await realize_blueprint(blueprint, llm)
        paths.append(write_scenario(scenario, blueprint))
        entries.append(
            {
                "scenario_id": blueprint.id,
                "blueprint_id": blueprint.id,
                "behavioral_class_key": behavioral_class_key(blueprint),
            }
        )
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    manifest["realized_scenarios"] = entries
    DEFAULT_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return tuple(paths)


def _prompt(blueprint: Blueprint) -> str:
    supplied = {
        "id": blueprint.id,
        "journey": blueprint.journey,
        "procedure_path": list(blueprint.procedure_path),
        "policies": list(blueprint.policies),
        "fixture_bindings": {
            "cards": list(blueprint.fixture_bindings.cards),
            "accounts": list(blueprint.fixture_bindings.accounts),
        },
        "goal_facts": dict(blueprint.goal_facts),
        "perturbations": [
            {"type": item.type, "position": item.position}
            for item in blueprint.perturbations
        ],
        "tool_assertions": [
            {"type": item.type, **item.fields} for item in blueprint.tool_assertions
        ],
    }
    return "Produce the four requested prose fields from this blueprint:\n" + json.dumps(
        supplied, sort_keys=True
    )


def _validate_output_shape(
    raw: Mapping[str, Any], whitelist: Mapping[str, Sequence[str]]
) -> None:
    if not isinstance(raw, Mapping):
        raise RealizationError("output must be a mapping")
    if set(raw) != {"description", "persona", "goal", "success_criteria"}:
        raise RealizationError("output has missing or extra top-level fields")
    persona = raw.get("persona")
    if not isinstance(persona, Mapping) or set(persona) != {"name", "traits"}:
        raise RealizationError("persona must contain only name and traits")
    traits = persona.get("traits")
    if not isinstance(traits, Mapping) or set(traits) != set(whitelist):
        raise RealizationError("persona traits must contain every reviewed dimension")
    for dimension, allowed in whitelist.items():
        if traits[dimension] not in allowed:
            raise RealizationError(
                f"persona trait {dimension!r} is not on the reviewed whitelist"
            )
    strings = [raw.get("description"), persona.get("name"), raw.get("goal")]
    criteria = raw.get("success_criteria")
    if not all(isinstance(item, str) and item.strip() for item in strings):
        raise RealizationError("description, persona name, and goal must be non-empty strings")
    if not isinstance(criteria, list) or not criteria or not all(
        isinstance(item, str) and item.strip() for item in criteria
    ):
        raise RealizationError("success_criteria must be a non-empty string list")


def _generated_prose(raw: Mapping[str, Any]) -> str:
    persona = raw["persona"]
    return "\n".join(
        [
            raw["description"],
            persona["name"],
            *persona["traits"].values(),
            raw["goal"],
            *raw["success_criteria"],
        ]
    )


def _check_equivalence(blueprint: Blueprint, prose: str) -> None:
    serialized = json.dumps(blueprint.to_dict(), sort_keys=True)
    violations: set[str] = set()
    tokens = set(re.findall(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])", prose))
    tokens.update(re.findall(r"\$\s*\d+(?:,\d{3})*(?:\.\d{1,2})?", prose))
    tokens.update(
        re.findall(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", prose)
    )
    for token in tokens:
        normalized = token.replace("$", "").replace(",", "").strip()
        if token not in serialized and normalized not in serialized:
            violations.add(token)
    for tool_name in registry.ALL_TOOLS:
        if re.search(rf"\b{re.escape(tool_name)}\b", prose) and tool_name not in serialized:
            violations.add(tool_name)
    if violations:
        raise RealizationError(
            "generated prose contains facts absent from blueprint: "
            + ", ".join(sorted(violations))
        )
