from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from scenario_synthesis.blueprint import (
    canonical_blueprint_id,
    dump_blueprint,
    load_blueprint,
)
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
        assert blueprint.procedure_path.count(CARD_SWITCH_EDGE) <= 1
        assert len(blueprint.perturbations) <= 2


def test_blueprint_identity_includes_goal_facts_but_behavioral_class_does_not() -> None:
    blueprint = load_blueprint("scenario_synthesis/blueprints/j1_submission_failure.yaml")
    corrected_facts = {**blueprint.goal_facts, "amount_type": "custom", "amount": 6000}
    corrected = replace(blueprint, goal_facts=corrected_facts)

    assert canonical_blueprint_id(blueprint) != canonical_blueprint_id(corrected)
    assert behavioral_class_key(blueprint) == behavioral_class_key(corrected)


def test_every_graph_edge_and_policy_is_covered() -> None:
    validator = BlueprintValidator()
    blueprints = enumerate_blueprints(validator=validator)
    covered_edges = {
        edge
        for blueprint in blueprints
        for edge in blueprint.procedure_path
    }
    declared_edges = {
        edge["id"]
        for edge in validator.graph["edges"]
        if edge.get("non_executable_against") != "mock"
    }
    covered_policies = {
        policy for blueprint in blueprints for policy in blueprint.policies
    }

    assert covered_edges == declared_edges
    assert covered_policies == set(POLICIES)


def test_mock_non_executable_graph_elements_are_excluded_and_logged(
    tmp_path: Path,
) -> None:
    manifest = write_generation(output_root=tmp_path / "generated", seed=0)
    audit = manifest["executable_space_audit"]

    assert audit["environment"] == "mock"
    assert audit["deduped_space_before"] == 3748
    assert audit["deduped_space_after"] == 740
    assert audit["deduped_space_excluded"] == 3008
    assert audit["behavioral_classes_before"] == 353
    assert audit["behavioral_classes_after"] == 69
    assert audit["behavioral_classes_excluded"] == 284
    assert set(audit["excluded"]["perturbations"]) == {
        "validation_warning",
        "validation_block",
        "validation_retry",
    }
    assert set(audit["excluded"]["edges"]) == {"validate->validate"}
    assert all(
        item["behavioral_classes"] > 0
        for category in audit["excluded"].values()
        for item in category.values()
    )

    blueprints = enumerate_blueprints()
    assert not any(
        item.type.startswith("validation_")
        for blueprint in blueprints
        for item in blueprint.perturbations
    )
    assert not any(
        "j1-validate-retry" in blueprint.procedure_path
        for blueprint in blueprints
    )


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


def test_regeneration_archives_unexecutable_artifact_without_mutating_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "generated"
    blueprint = load_blueprint("scenario_synthesis/blueprints/j1_submission_failure.yaml")
    facts = dict(blueprint.goal_facts)
    facts.pop("amount")
    legacy = replace(blueprint, id="legacy-realized", goal_facts=facts)
    dump_blueprint(legacy, root / "blueprints" / "legacy-realized.yaml")
    yaml_path = root / "yaml" / "legacy-realized.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text("name: legacy-realized\n")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "realized_scenarios": [
                    {
                        "scenario_id": "legacy-realized",
                        "blueprint_id": "legacy-realized",
                    }
                ],
                "dry_runs": [
                    {
                        "candidate_id": "legacy-realized",
                        "blueprint_id": "legacy-realized",
                        "runs": [],
                    }
                ],
            }
        )
    )

    manifest = write_generation(output_root=root)

    assert manifest["realized_scenarios"] == [
        {"scenario_id": "legacy-realized", "blueprint_id": "legacy-realized"}
    ]
    assert manifest["dry_runs"] == [
        {"candidate_id": "legacy-realized", "blueprint_id": "legacy-realized", "runs": []}
    ]
    assert yaml_path.exists()
    assert (root / "unexecutable_blueprints" / "legacy-realized.yaml").exists()


def test_behavioral_classes_choose_maximal_policy_representatives() -> None:
    blueprints = enumerate_blueprints()
    representatives = behavioral_representatives(blueprints)
    policies_by_class: dict[str, list[tuple[str, ...]]] = {}
    for blueprint in blueprints:
        policies_by_class.setdefault(behavioral_class_key(blueprint), []).append(
            blueprint.policies
        )

    assert len(blueprints) == 740
    assert len(representatives) == 69
    for representative in representatives:
        policies = policies_by_class[behavioral_class_key(representative)]
        assert len(representative.policies) == max(map(len, policies))
