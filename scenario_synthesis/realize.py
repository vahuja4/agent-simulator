"""Structured, guarded realization of approved blueprints into scenario YAML."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from agentsim import registry
from agentsim.llm import LLMClient, LLMTruncationError
from agentsim.scenario import ScenarioError, load_scenario

from .blueprint import Blueprint
from .sample import behavioral_class_key, behavioral_representatives

ROOT = Path(__file__).resolve().parents[1]
TRAIT_FILE = Path(__file__).with_name("persona_traits.yaml")
DEFAULT_YAML_DIR = ROOT / "generated_scenarios" / "yaml"
DEFAULT_MANIFEST = ROOT / "generated_scenarios" / "manifest.json"


class RealizationError(ValueError):
    """The model output is not a fact-equivalent scenario realization."""


@dataclass(frozen=True)
class RealizationSummary:
    realized: int
    reused: int
    retried: int
    failed: int
    preserved: int

    def __str__(self) -> str:
        return (
            "realization summary: "
            f"realized={self.realized} reused={self.reused} retried={self.retried} "
            f"failed={self.failed} preserved={self.preserved}"
        )


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
    scenario, _attempt_count = await _realize_blueprint_with_attempts(
        blueprint, llm, trait_path=trait_path
    )
    return scenario


async def _realize_blueprint_with_attempts(
    blueprint: Blueprint,
    llm: LLMClient,
    *,
    trait_path: str | Path = TRAIT_FILE,
) -> tuple[dict[str, Any], int]:
    whitelist = load_trait_whitelist(trait_path)
    schema = realization_schema(whitelist)
    rejection: str | None = None
    for attempt in range(2):
        prompt = _prompt(blueprint)
        if rejection is not None:
            prompt += f"\nThe prior output was rejected: {rejection}. Correct it."
        try:
            raw = await llm.structured(
                system=(
                    "Realize only the supplied scenario facts. Do not invent numbers, "
                    "identifiers, dates, accounts, amounts, tools, or persona traits."
                ),
                messages=[{"role": "user", "content": prompt}],
                schema=schema,
                effort="none",
                max_tokens=8192 if attempt == 0 else 16384,
            )
            return build_scenario(blueprint, raw, whitelist=whitelist), attempt + 1
        except (RealizationError, LLMTruncationError) as exc:
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
    """Create a realization without overwriting any existing artifact."""
    DEFAULT_YAML_DIR.mkdir(parents=True, exist_ok=True)
    target = DEFAULT_YAML_DIR / f"{blueprint.id}.yaml"
    with target.open("x") as stream:
        stream.write(yaml.safe_dump(dict(scenario), sort_keys=False))
    return target


async def realize_catalog(
    blueprints: Sequence[Blueprint],
    llm: LLMClient,
    *,
    report: Callable[[str], None] | None = None,
) -> tuple[Path, ...]:
    """Realize missing representatives while preserving prior batches."""
    representatives = behavioral_representatives(blueprints)
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    entries = list(manifest.get("realized_scenarios", []))
    if not all(isinstance(entry, dict) for entry in entries):
        raise RealizationError("manifest realized_scenarios must be a list of records")

    candidate_ids = {blueprint.id for blueprint in representatives}
    preserved = sum(
        entry.get("blueprint_id") not in candidate_ids for entry in entries
    )
    paths: list[Path] = []
    realized = reused = retried = failed = 0

    for blueprint in representatives:
        existing_index = next(
            (
                index
                for index, entry in enumerate(entries)
                if entry.get("blueprint_id") == blueprint.id
            ),
            None,
        )
        existing = entries[existing_index] if existing_index is not None else None
        reusable_path = _reusable_path(existing, blueprint)
        if reusable_path is not None:
            paths.append(reusable_path)
            reused += 1
            if report is not None:
                report(f"reused {blueprint.id}: {reusable_path}")
            continue

        target = DEFAULT_YAML_DIR / f"{blueprint.id}.yaml"
        if target.exists():
            record: dict[str, Any] = {
                "blueprint_id": blueprint.id,
                "behavioral_class_key": behavioral_class_key(blueprint),
                "status": "failed_closed",
                "attempt_count": 0,
                "realization_outcome": "failed_closed",
                "error": "existing YAML is not reusable and was not overwritten",
            }
            failed += 1
        else:
            try:
                scenario, attempt_count = await _realize_blueprint_with_attempts(
                    blueprint, llm
                )
            except (RealizationError, LLMTruncationError) as exc:
                record = {
                    "blueprint_id": blueprint.id,
                    "behavioral_class_key": behavioral_class_key(blueprint),
                    "status": "failed_closed",
                    "attempt_count": 2,
                    "realization_outcome": "failed_closed",
                    "error": str(exc),
                }
                failed += 1
            else:
                paths.append(write_scenario(scenario, blueprint))
                record = {
                    "scenario_id": blueprint.id,
                    "blueprint_id": blueprint.id,
                    "behavioral_class_key": behavioral_class_key(blueprint),
                    "attempt_count": attempt_count,
                    "realization_outcome": (
                        "first_try_success" if attempt_count == 1 else "retried_once"
                    ),
                }
                realized += 1
                retried += attempt_count == 2

        if existing_index is None:
            entries.append(record)
        else:
            entries[existing_index] = record

    manifest["realized_scenarios"] = entries
    DEFAULT_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    summary = RealizationSummary(
        realized=realized,
        reused=reused,
        retried=retried,
        failed=failed,
        preserved=preserved,
    )
    if report is not None:
        report(str(summary))
    return tuple(paths)


def _reusable_path(
    entry: Mapping[str, Any] | None, blueprint: Blueprint
) -> Path | None:
    if entry is None or "status" in entry:
        return None
    if (
        entry.get("scenario_id") != blueprint.id
        or entry.get("behavioral_class_key") != behavioral_class_key(blueprint)
    ):
        return None
    path = DEFAULT_YAML_DIR / f"{blueprint.id}.yaml"
    try:
        scenario = load_scenario(path)
        raw = yaml.safe_load(path.read_text())
    except (OSError, ScenarioError, yaml.YAMLError):
        return None
    if not isinstance(raw, Mapping):
        return None
    expected_assertions = [
        (assertion.type, assertion.fields) for assertion in blueprint.tool_assertions
    ]
    actual_assertions = [
        (assertion.type, assertion.fields) for assertion in scenario.tool_assertions
    ]
    if (
        scenario.name != blueprint.id
        or scenario.journey != blueprint.journey
        or tuple(card.last_four for card in scenario.knowledge_cards)
        != blueprint.fixture_bindings.cards
        or tuple(account.last_four for account in scenario.knowledge_accounts)
        != blueprint.fixture_bindings.accounts
        or scenario.max_turns != blueprint.max_turns
        or actual_assertions != expected_assertions
    ):
        return None
    prose = "\n".join(
        [
            str(raw.get("description", "")),
            str(raw.get("persona", {}).get("name", "")),
            str(raw.get("persona", {}).get("traits", "")),
            str(raw.get("goal", "")),
            *(str(item) for item in raw.get("success_criteria", [])),
        ]
    )
    try:
        _check_equivalence(blueprint, prose)
    except RealizationError:
        return None
    return path


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
