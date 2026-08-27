from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from agentsim.scenario import ScenarioError, load_scenario
from scenario_synthesis.blueprint import (
    BlueprintError,
    CoverageBlueprint,
    CoverageCell,
    FixtureBindings,
    GenerationProvenance,
    canonical_cell_id,
    canonical_coverage_blueprint_id,
    load_coverage_blueprint,
    same_cell,
)
from scenario_synthesis.generator import generate_blueprints
from scenario_synthesis.enumerate import write_generation
from scenario_synthesis.validator import BlueprintValidationError, CoverageBlueprintValidator


def _blueprint() -> CoverageBlueprint:
    return generate_blueprints()[0]


def test_mid_conversation_correction_can_change_amount_on_one_card() -> None:
    blueprint = next(
        item
        for item in generate_blueprints()
        if item.complication == "mid-conversation-correction"
        and len(item.fixture_bindings.cards) == 1
    )
    assert blueprint.goal_facts["correction"] == {
        "parameter": "amount_type",
        "from": "statement_balance",
        "to": "minimum_due",
    }


def test_goal_shift_and_multi_intent_encode_complete_payment_instructions() -> None:
    blueprints = generate_blueprints()
    goal_shift = next(item for item in blueprints if item.complication == "goal-shift")
    shift = goal_shift.goal_facts["goal_shift"]
    assert shift["abandonment"] == "explicit"
    assert shift["state_transition"] == "discard-abandoned-instruction"
    assert set(shift["original_payment_instruction"]) == {
        "card_last_four", "account_last_four", "amount_type", "date"
    }
    assert set(shift["replacement_payment_instruction"]) == {
        "card_last_four", "account_last_four", "amount_type", "date"
    }
    assert shift["original_payment_instruction"] != shift["replacement_payment_instruction"]

    multi = next(
        item for item in blueprints if item.complication == "multi-intent-turn"
    )
    instructions = multi.goal_facts["payment_instructions_in_one_turn"]
    assert len(instructions) == 2
    assert instructions[0] != instructions[1]
    assert all(
        {"card_last_four", "account_last_four", "amount_type", "date"} <= set(item)
        for item in instructions
    )
    assert goal_shift.max_turns % 2 == 0
    assert multi.max_turns % 2 == 0


def test_cell_identity_has_a_fixed_full_sha256_vector() -> None:
    cell = CoverageCell(
        journey_path_id="j1-path-example",
        persona_archetype="cooperative",
        knowledge_level="medium",
        complication="none",
        fixture_state_class_id="j1-single-card",
        fitness_target_id="d1",
        fitness_shape_id="same-turn",
    )
    assert canonical_cell_id(cell) == (
        "cell-b66a74266349254cdd018c593ea0724051dc302d19531bd1edda524ec63fa61c"
    )


def test_same_cell_uses_only_the_six_canonical_axes() -> None:
    blueprint = _blueprint()
    changed_surface = replace(
        blueprint,
        goal_facts={**blueprint.goal_facts, "surface_hint": "different"},
        provenance=replace(blueprint.provenance, generated_at="2030-01-01T00:00:00Z"),
    )
    assert same_cell(blueprint, changed_surface)
    assert blueprint.cell_id == changed_surface.cell_id


def test_blueprint_identity_excludes_only_provenance_timestamp() -> None:
    blueprint = _blueprint()
    later = replace(
        blueprint,
        provenance=replace(blueprint.provenance, generated_at="2030-01-01T00:00:00Z"),
    )
    semantic_change = replace(blueprint, max_turns=blueprint.max_turns + 1)
    assert canonical_coverage_blueprint_id(later) == blueprint.blueprint_id
    assert canonical_coverage_blueprint_id(semantic_change) != blueprint.blueprint_id


def test_strict_versioned_blueprint_round_trip_and_unknown_field_rejection(
    tmp_path: Path,
) -> None:
    blueprint = _blueprint()
    target = tmp_path / "blueprint.yaml"
    target.write_text(yaml.safe_dump(blueprint.to_dict(), sort_keys=False))
    assert load_coverage_blueprint(target) == blueprint

    raw = blueprint.to_dict()
    raw["legacy_strata"] = []
    target.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(BlueprintError, match="unknown field"):
        load_coverage_blueprint(target)

    legacy = Path("scenario_synthesis/blueprints/j1_happy_path.yaml")
    with pytest.raises(BlueprintError, match="missing field"):
        load_coverage_blueprint(legacy)


def test_generated_blueprints_use_edge_paths_and_validate_contracts() -> None:
    blueprints = generate_blueprints()
    validator = CoverageBlueprintValidator()
    assert blueprints
    assert all(item.journey_edge_ids[0].startswith("j1-") for item in blueprints)
    validator.validate(blueprints[0])

    disconnected = replace(
        blueprints[0],
        journey_edge_ids=(blueprints[0].journey_edge_ids[0], "j1-confirm-submit"),
    )
    with pytest.raises(BlueprintValidationError, match="disconnected"):
        validator.validate(disconnected)


def test_blueprint_validation_fails_closed_on_sealed_world_and_contract_drift() -> None:
    blueprint = _blueprint()
    validator = CoverageBlueprintValidator()
    invented = replace(
        blueprint,
        goal_facts={**blueprint.goal_facts, "invented_card_last_four": "0000"},
    )
    with pytest.raises(BlueprintValidationError, match="Sealed-world"):
        validator.validate(invented)

    drifted_hashes = dict(blueprint.provenance.source_hashes)
    drifted_hashes["fixture"] = "0" * 64
    drifted = replace(
        blueprint,
        provenance=replace(blueprint.provenance, source_hashes=drifted_hashes),
    )
    with pytest.raises(BlueprintValidationError, match="contract drift"):
        validator.validate(drifted)


def test_synthesized_scenario_metadata_is_strict_and_runtime_neutral(tmp_path: Path) -> None:
    blueprint = _blueprint()
    raw = {
        "name": "synthesized-example",
        "journey": "J1",
        "description": "A generated example.",
        "persona": {"name": "Pat", "traits": "calm"},
        "goal": "Pay the card from the bound account.",
        "knowledge": {
            "cards": list(blueprint.fixture_bindings.cards),
            "accounts": list(blueprint.fixture_bindings.accounts),
        },
        "success_criteria": ["The payment is handled truthfully."],
        "max_turns": blueprint.max_turns,
        "tool_assertions": [
            {"type": item.type, **item.fields}
            for item in blueprint.required_assertions
        ],
        "synthesis": {
            "schema_version": 1,
            "origin": "synthesized",
            "candidate_id": "candidate-" + "1" * 64,
            "blueprint_id": blueprint.blueprint_id,
            "cell_id": blueprint.cell_id,
            "blueprint_content_hash": blueprint.blueprint_id.removeprefix("blueprint-"),
        },
    }
    target = tmp_path / "scenario.yaml"
    target.write_text(yaml.safe_dump(raw, sort_keys=False))
    scenario = load_scenario(target)
    assert scenario.synthesis is not None
    assert scenario.synthesis.cell_id == blueprint.cell_id
    assert scenario.render_knowledge()

    raw["synthesis"]["unknown"] = True
    target.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(ScenarioError, match="unknown field"):
        load_scenario(target)


def test_generation_provenance_has_every_required_source_hash() -> None:
    provenance = _blueprint().provenance
    assert isinstance(provenance, GenerationProvenance)
    assert set(provenance.source_hashes) == {
        "journey_graph",
        "fixture",
        "persona_archetypes",
        "complication_applicability",
        "pair_exclusions",
        "fixture_state_classes",
        "fitness_targets",
    }


def test_historical_generation_quarantine_is_read_only() -> None:
    manifest = Path("generated_scenarios/manifest.json")
    before = manifest.read_bytes()
    with pytest.raises(RuntimeError, match="read-only historical quarantine"):
        write_generation()
    assert manifest.read_bytes() == before
