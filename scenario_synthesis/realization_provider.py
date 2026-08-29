"""Offline realization provider seam and deterministic Slice-3 stub."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from agentsim.llm import LLMClient, LLMError, OpenAILLM

from ._async import run
from .blueprint import CoverageBlueprint
from .config import load_config


class RealizationError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code


class RealizationProvider(Protocol):
    provider_id: str

    def realize(
        self, blueprint: CoverageBlueprint, *, candidate_ordinal: int, attempt: int
    ) -> Mapping[str, Any]: ...


@dataclass
class StubRealizationProvider:
    """Produces deterministic narrative fields and never constructs a client."""

    failure_modes: Mapping[tuple[int, int], str] = field(default_factory=dict)
    provider_id: str = "offline-stub-realization-v1"

    def realize(
        self, blueprint: CoverageBlueprint, *, candidate_ordinal: int, attempt: int
    ) -> Mapping[str, Any]:
        mode = self.failure_modes.get((candidate_ordinal, attempt))
        facts = json.dumps(blueprint.goal_facts, sort_keys=True, ensure_ascii=False)
        bindings = ", ".join((*blueprint.fixture_bindings.cards, *blueprint.fixture_bindings.accounts))
        surface: dict[str, Any] = {
            "description": (
                f"Offline realization for {blueprint.persona_archetype} / "
                f"{blueprint.knowledge_level}; fixture bindings: {bindings}."
            ),
            "persona": {
                "name": "Stub Customer",
                "traits": (
                    f"{blueprint.persona_archetype}; {blueprint.knowledge_level} relevant "
                    f"fluency; complication={blueprint.complication}"
                ),
            },
            "goal": f"Complete the journey using these blueprint facts: {facts}",
            "success_criteria": [
                f"Satisfy required criterion {criterion}."
                for criterion in blueprint.required_criteria
            ] or ["Complete the grounded goal without unrelated failures."],
        }
        if mode == "schema-invalid-output":
            surface.pop("persona")
        elif mode == "sealed-world-violation":
            surface["description"] += " The private verification code is 999999."
        elif mode == "fact-drift":
            required = _required_fact_tokens(blueprint)
            if required:
                surface["goal"] = str(surface["goal"]).replace(required[0], "0000", 1)
            else:
                surface["goal"] += " Use card 0000."
        elif mode is not None:
            raise ValueError(f"unknown stub realization failure mode {mode!r}")
        return surface


@dataclass
class LiveRealizationProvider:
    """Realize reviewed Blueprint narrative fields with the configured simulator."""

    llm: LLMClient
    system_prompt: str
    token_budget: int
    provider_id: str

    @classmethod
    def from_config(cls) -> LiveRealizationProvider:
        config = load_config()
        model = str(config.content["models"]["simulator"])
        prompt_path = Path(config.path).parents[1] / str(
            config.content["paths"]["prompts"]["realization-system"]
        )
        return cls(
            llm=OpenAILLM(model=model),
            system_prompt=prompt_path.read_text(encoding="utf-8").strip(),
            token_budget=int(config.content["limits"]["realization_token_budget"]),
            provider_id=f"openai-structured-realization:{model}",
        )

    def realize(
        self, blueprint: CoverageBlueprint, *, candidate_ordinal: int, attempt: int
    ) -> Mapping[str, Any]:
        prompt = {
            "instruction": (
                "Return only narrative surface fields. Preserve every supplied fact and "
                "do not introduce any fact, number, identifier, policy, or behavior."
            ),
            "candidate_ordinal": candidate_ordinal,
            "corrective_attempt": attempt,
            "blueprint": blueprint.to_dict(),
        }
        try:
            return run(
                self.llm.structured(
                    system=self.system_prompt,
                    messages=[
                        {
                            "role": "user",
                            "content": json.dumps(prompt, sort_keys=True, ensure_ascii=False),
                        }
                    ],
                    schema=_live_realization_schema(),
                    effort="none",
                    max_tokens=self.token_budget,
                )
            )
        except LLMError as exc:
            raise RealizationError(
                "schema-failure", f"realization provider failed: {exc}"
            ) from exc


def _live_realization_schema() -> dict[str, Any]:
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
                    "traits": {"type": "string"},
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


def validate_surface(
    blueprint: CoverageBlueprint, surface: Mapping[str, Any]
) -> dict[str, Any]:
    fields = {"description", "persona", "goal", "success_criteria"}
    if not isinstance(surface, Mapping) or set(surface) != fields:
        raise RealizationError("schema-failure", "realization response schema is invalid")
    persona = surface.get("persona")
    if not isinstance(persona, Mapping) or set(persona) != {"name", "traits"}:
        raise RealizationError("schema-failure", "realization persona schema is invalid")
    strings = [surface.get("description"), surface.get("goal"), persona.get("name"), persona.get("traits")]
    criteria = surface.get("success_criteria")
    if (
        not all(isinstance(value, str) and value.strip() for value in strings)
        or not isinstance(criteria, list)
        or not criteria
        or not all(isinstance(value, str) and value.strip() for value in criteria)
    ):
        raise RealizationError("schema-failure", "realization narrative fields are invalid")
    narrative = " ".join([*(str(value) for value in strings), *criteria])
    missing = [
        token
        for token in _required_fact_tokens(blueprint)
        if token not in str(surface["goal"])
    ]
    if missing:
        raise RealizationError(
            "fact-equivalence-failure", f"realization drifted from blueprint fact {missing[0]!r}"
        )
    allowed = set(_required_fact_tokens(blueprint)) | set(blueprint.fixture_bindings.cards) | set(
        blueprint.fixture_bindings.accounts
    )
    numeric_claims = set(re.findall(r"(?<!\d)\d{4,}(?!\d)", narrative))
    invented = sorted(numeric_claims - allowed)
    if invented:
        raise RealizationError(
            "sealed-world-violation", f"realization introduced ungrounded fact {invented[0]!r}"
        )
    return {
        "description": str(surface["description"]),
        "persona": {"name": str(persona["name"]), "traits": str(persona["traits"])},
        "goal": str(surface["goal"]),
        "success_criteria": list(criteria),
    }


def _required_fact_tokens(blueprint: CoverageBlueprint) -> list[str]:
    tokens: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for nested in value.values():
                visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)
        elif isinstance(value, str) and re.fullmatch(r"\d{4,}", value):
            tokens.append(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            integer = str(value).split(".", 1)[0]
            if re.fullmatch(r"\d{4,}", integer):
                tokens.append(integer)

    visit(blueprint.goal_facts)
    return sorted(set(tokens))
