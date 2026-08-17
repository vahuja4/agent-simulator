"""Deterministic stratified sampling of scenario blueprints."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from .blueprint import Blueprint

NONE = "none"


def blueprint_strata(blueprint: Blueprint) -> tuple[str, ...]:
    """Return the policy-by-perturbation strata containing ``blueprint``."""
    policies = blueprint.policies or (NONE,)
    perturbation_types = (
        tuple(dict.fromkeys(item.type for item in blueprint.perturbations)) or (NONE,)
    )
    return tuple(
        f"policy={policy}|perturbation={perturbation}"
        for policy in policies
        for perturbation in perturbation_types
    )


def stratum_counts(blueprints: Iterable[Blueprint]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for blueprint in blueprints:
        for stratum in blueprint_strata(blueprint):
            counts[stratum] += 1
    return dict(sorted(counts.items()))


def sample_blueprints(
    blueprints: Sequence[Blueprint], *, seed: int, per_stratum: int = 1
) -> tuple[Blueprint, ...]:
    """Select a stable seeded sample from every observed stratum.

    A blueprint can cover multiple strata. The returned sample is the deduplicated
    union of each stratum's selections, sorted by blueprint ID.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    if isinstance(per_stratum, bool) or not isinstance(per_stratum, int) or per_stratum < 1:
        raise ValueError("per_stratum must be a positive integer")

    grouped: dict[str, list[Blueprint]] = defaultdict(list)
    for blueprint in blueprints:
        for stratum in blueprint_strata(blueprint):
            grouped[stratum].append(blueprint)

    selected: dict[str, Blueprint] = {}
    for stratum, members in sorted(grouped.items()):
        ranked = sorted(
            members,
            key=lambda item: (_seeded_rank(seed, stratum, item.id), item.id),
        )
        for blueprint in ranked[:per_stratum]:
            selected[blueprint.id] = blueprint
    return tuple(selected[key] for key in sorted(selected))


def _seeded_rank(seed: int, stratum: str, blueprint_id: str) -> bytes:
    material = f"{seed}\0{stratum}\0{blueprint_id}".encode()
    return hashlib.sha256(material).digest()
