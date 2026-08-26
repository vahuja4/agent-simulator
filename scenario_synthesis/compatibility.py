"""Read-only access to pre-Phase-4.5 prototype evidence for reconciliation."""

from __future__ import annotations

import json
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .blueprint import Blueprint as LegacyBlueprint
from .blueprint import _load_legacy_blueprint as load_legacy_blueprint
from .enumerate import _enumerate_blueprints
from .validator import BlueprintValidator

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_ROOT = ROOT / "generated_scenarios"


@dataclass(frozen=True)
class HistoricalQuarantineSummary:
    historical_blueprint_files: int
    historical_scenario_files: int
    manifest_counts: dict[str, int]
    candidate_count: int = 0
    admission_count: int = 0
    fitness_evidence_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "historical_blueprint_files": self.historical_blueprint_files,
            "historical_scenario_files": self.historical_scenario_files,
            "manifest_counts": dict(self.manifest_counts),
            "candidate_count": self.candidate_count,
            "admission_count": self.admission_count,
            "fitness_evidence_count": self.fitness_evidence_count,
        }


def read_historical_quarantine(
    root: str | Path = HISTORICAL_ROOT,
) -> HistoricalQuarantineSummary:
    """Inspect history without returning candidate/admission/fitness objects."""
    root = Path(root)
    manifest_path = root / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    counts = raw.get("counts", {}) if isinstance(raw, dict) else {}
    safe_counts = {
        key: int(value)
        for key, value in counts.items()
        if key in {"deduped_space", "behavioral_classes", "sample"}
        and isinstance(value, int)
        and not isinstance(value, bool)
    }
    return HistoricalQuarantineSummary(
        historical_blueprint_files=len(tuple((root / "blueprints").glob("*.yaml"))),
        historical_scenario_files=len(tuple((root / "yaml").glob("*.yaml"))),
        manifest_counts=safe_counts,
    )


@lru_cache(maxsize=1)
def prototype_unemittable_pairs() -> tuple[tuple[str, str], ...]:
    """Reproduce the prototype's policy×perturbation holes for reconciliation only."""
    validator = BlueprintValidator()
    before = _enumerate_blueprints(
        validator=validator, seed=0, include_non_executable=True
    )
    after = _enumerate_blueprints(validator=validator, seed=0)
    return tuple(sorted(_legacy_pairs(before) - _legacy_pairs(after)))


def _legacy_pairs(blueprints: tuple[LegacyBlueprint, ...]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for blueprint in blueprints:
        policies = blueprint.policies or ("none",)
        perturbations = tuple(item.type for item in blueprint.perturbations) or ("none",)
        result.update((policy, perturbation) for policy in policies for perturbation in perturbations)
    return result
