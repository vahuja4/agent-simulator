from __future__ import annotations

import json
from pathlib import Path

from scenario_synthesis.enumerate import (
    CARD_SWITCH_EDGE,
    enumerate_blueprints,
    write_generation,
)
from scenario_synthesis.policies import POLICIES
from scenario_synthesis.sample import (
    behavioral_class_key,
    behavioral_representatives,
    sample_blueprints,
)
from scenario_synthesis.validator import BlueprintValidator


def test_enumeration_is_valid_deduped_and_loop_bounded() -> None:
    validator = BlueprintValidator()
    blueprints = enumerate_blueprints(validator=validator)

    assert blueprints
    assert len({blueprint.id for blueprint in blueprints}) == len(blueprints)
    for blueprint in blueprints:
        validator.validate(blueprint)
        edges = tuple(zip(blueprint.procedure_path, blueprint.procedure_path[1:]))
        assert edges.count(CARD_SWITCH_EDGE) <= 1
        assert len(blueprint.perturbations) <= 2


def test_every_graph_edge_and_policy_is_covered() -> None:
    validator = BlueprintValidator()
    blueprints = enumerate_blueprints(validator=validator)
    covered_edges = {
        edge
        for blueprint in blueprints
        for edge in zip(blueprint.procedure_path, blueprint.procedure_path[1:])
    }
    declared_edges = {
        (edge["from"], edge["to"]) for edge in validator.graph["edges"]
    }
    covered_policies = {
        policy for blueprint in blueprints for policy in blueprint.policies
    }

    assert covered_edges == declared_edges
    assert covered_policies == set(POLICIES)


def test_two_writes_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert write_generation(output_root=first, seed=1729) == write_generation(
        output_root=second, seed=1729
    )

    first_files = {
        path.relative_to(first): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files


def test_manifest_sample_is_reproduced_from_seed(tmp_path: Path) -> None:
    root = tmp_path / "generated"
    manifest = write_generation(output_root=root, seed=42, per_stratum=2)
    loaded = json.loads((root / "manifest.json").read_text())
    blueprints = enumerate_blueprints(seed=loaded["seed"])
    reproduced = sample_blueprints(
        blueprints,
        seed=loaded["seed"],
        per_stratum=loaded["sample_per_stratum"],
    )

    assert loaded == manifest
    assert [blueprint.id for blueprint in reproduced] == loaded["sample_ids"]
    assert loaded["counts"]["deduped_space"] == len(blueprints)
    assert loaded["counts"]["behavioral_classes"] == len(
        behavioral_representatives(blueprints)
    )
    assert loaded["sampling_unit"] == "behavioral_class"
    assert len({behavioral_class_key(item) for item in reproduced}) == len(reproduced)


def test_behavioral_classes_choose_maximal_policy_representatives() -> None:
    blueprints = enumerate_blueprints()
    representatives = behavioral_representatives(blueprints)
    policies_by_class: dict[str, list[tuple[str, ...]]] = {}
    for blueprint in blueprints:
        policies_by_class.setdefault(behavioral_class_key(blueprint), []).append(
            blueprint.policies
        )

    assert len(blueprints) == 3748
    assert len(representatives) == 353
    for representative in representatives:
        policies = policies_by_class[behavioral_class_key(representative)]
        assert len(representative.policies) == max(map(len, policies))
