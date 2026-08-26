from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from agentsim.scenario import ToolAssertion
from scenario_synthesis.blueprint import Perturbation, dump_blueprint
from scenario_synthesis.compatibility import load_legacy_blueprint as load_blueprint
from scenario_synthesis.policies import POLICIES, Policy
from scenario_synthesis.validator import (
    DEFAULT_GRAPH,
    BlueprintValidationError,
    BlueprintValidator,
    _perturbation_specs,
)


BLUEPRINTS = Path("scenario_synthesis/blueprints")


@pytest.fixture(scope="module")
def validator() -> BlueprintValidator:
    return BlueprintValidator()


@pytest.mark.parametrize(
    "filename",
    [
        "j1_happy_path.yaml",
        "j1_partial_disclosure.yaml",
        "j1_card_switch.yaml",
        "j1_last_four_disambiguation.yaml",
        "j1_submission_failure.yaml",
    ],
)
def test_five_handwritten_j1_semantics_validate(
    filename: str, validator: BlueprintValidator
) -> None:
    validator.validate(load_blueprint(BLUEPRINTS / filename))


def test_every_j1_perturbation_declares_an_executable_trigger(
    validator: BlueprintValidator,
) -> None:
    declarations = [
        spec
        for edge in validator.graph["edges"]
        for spec in _perturbation_specs(edge).values()
    ]
    assert declarations
    assert all("executable_trigger" in spec for spec in declarations)


def test_blueprint_yaml_round_trip(tmp_path: Path) -> None:
    original = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    target = tmp_path / "round-trip.yaml"
    dump_blueprint(original, target)
    assert load_blueprint(target) == original


def test_rejects_bad_tool(validator: BlueprintValidator) -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    bad = replace(
        blueprint,
        tool_assertions=(
            ToolAssertion(
                type="validated_submit",
                fields={"submit": "InventedTool", "validate": "AddValidateOneTimePayment"},
            ),
        ),
    )
    with pytest.raises(BlueprintValidationError, match="unknown tool"):
        validator.validate(bad)


def test_rejects_unsatisfiable_binding(validator: BlueprintValidator) -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    bindings = replace(blueprint.fixture_bindings, cards=("0000",))
    with pytest.raises(BlueprintValidationError, match="unsatisfiable card"):
        validator.validate(replace(blueprint, fixture_bindings=bindings))


def test_rejects_orphan_policy(validator: BlueprintValidator) -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    with pytest.raises(BlueprintValidationError, match="orphan policy"):
        validator.validate(replace(blueprint, policies=("unmapped_policy",)))


def test_rejects_catalog_policy_without_enforcement_hook() -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    orphan = Policy(
        id="orphan",
        journeys=("J1",),
        required_fixture_predicates=(),
        compatible_with=(),
        incompatible_with=(),
    )
    validator = BlueprintValidator(policy_catalog={**POLICIES, "orphan": orphan})
    with pytest.raises(BlueprintValidationError, match="no fitness-target enforcement hook"):
        validator.validate(replace(blueprint, policies=("orphan",)))


def test_rejects_turn_overflow(validator: BlueprintValidator) -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    with pytest.raises(BlueprintValidationError, match="exceeds max_turns"):
        validator.validate(replace(blueprint, max_turns=9))


def test_rejects_misplaced_perturbation(validator: BlueprintValidator) -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    bad = replace(
        blueprint,
        perturbations=(Perturbation(type="card_switch", position="after_disclosure"),),
    )
    with pytest.raises(BlueprintValidationError, match="invalid at"):
        validator.validate(bad)


@pytest.mark.parametrize(
    ("filename", "fact", "message"),
    [
        ("j1_partial_disclosure.yaml", "disclosure_style", "requires goal_facts"),
        ("j1_submission_failure.yaml", "amount", "LARGE_PAYMENT_THRESHOLD"),
    ],
)
def test_rejects_perturbation_without_executable_goal_fact(
    filename: str, fact: str, message: str, validator: BlueprintValidator
) -> None:
    blueprint = load_blueprint(BLUEPRINTS / filename)
    facts = dict(blueprint.goal_facts)
    facts.pop(fact)
    with pytest.raises(BlueprintValidationError, match=message):
        validator.validate(replace(blueprint, goal_facts=facts))


def test_rejects_card_switch_without_distinct_bound_goal_cards(
    validator: BlueprintValidator,
) -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_card_switch.yaml")
    facts = dict(blueprint.goal_facts)
    facts["final_card_last_four"] = facts["initial_card_last_four"]
    with pytest.raises(BlueprintValidationError, match="distinct bound"):
        validator.validate(replace(blueprint, goal_facts=facts))


@pytest.mark.parametrize(
    ("kind", "position"),
    [
        ("validation_warning", "at_validation"),
        ("validation_block", "at_validation"),
    ],
)
def test_rejects_mock_non_executable_validation_perturbations(
    kind: str, position: str, validator: BlueprintValidator
) -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    bad = replace(
        blueprint,
        perturbations=(Perturbation(type=kind, position=position),),
    )
    with pytest.raises(BlueprintValidationError, match="non-executable against mock"):
        validator.validate(bad)


def test_rejects_mock_non_executable_validation_retry_edge(
    validator: BlueprintValidator,
) -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    path = list(blueprint.procedure_path)
    path.insert(path.index("j1-validate-confirm"), "j1-validate-retry")
    with pytest.raises(BlueprintValidationError, match="validate -> validate"):
        validator.validate(replace(blueprint, procedure_path=tuple(path), max_turns=13))


def test_handle_failure_edge_requires_large_custom_amount(
    validator: BlueprintValidator,
) -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_submission_failure.yaml")
    facts = dict(blueprint.goal_facts)
    facts["amount"] = 875.20
    with pytest.raises(BlueprintValidationError, match="edge submit -> handle_failure"):
        validator.validate(replace(blueprint, goal_facts=facts, perturbations=()))


def test_rejects_disconnected_path(validator: BlueprintValidator) -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    bad = replace(
        blueprint,
        procedure_path=(
            "j1-disclose-select-card",
            "j1-fetch-options-validate",
            "j1-validate-confirm",
            "j1-confirm-submit",
            "j1-submit-terminate",
        ),
    )
    with pytest.raises(BlueprintValidationError, match="disconnected"):
        validator.validate(bad)


def test_rejects_registry_drift(tmp_path: Path) -> None:
    graph = yaml.safe_load(DEFAULT_GRAPH.read_text())
    graph["source_hashes"]["registry"] = "0" * 64
    drifted_graph = tmp_path / "j1.yaml"
    drifted_graph.write_text(yaml.safe_dump(graph, sort_keys=False))
    validator = BlueprintValidator(graph_path=drifted_graph)
    blueprint = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    blueprint = replace(
        blueprint,
        provenance=replace(blueprint.provenance, graph_hash=validator.graph_hash),
    )
    with pytest.raises(BlueprintValidationError, match="registry drift"):
        validator.validate(blueprint)


def test_j1_edge_ids_are_unique_and_paths_are_continuous(
    validator: BlueprintValidator,
) -> None:
    edges = validator.graph["edges"]
    edge_ids = [edge["id"] for edge in edges]
    assert len(edge_ids) == len(set(edge_ids))
    edge_index = {edge["id"]: edge for edge in edges}
    for path in sorted(BLUEPRINTS.glob("*.yaml")):
        blueprint = load_blueprint(path)
        traversed = [edge_index[edge_id] for edge_id in blueprint.procedure_path]
        assert all(
            left["to"] == right["from"]
            for left, right in zip(traversed, traversed[1:])
        )
