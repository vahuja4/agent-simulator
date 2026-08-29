"""Deterministic validation for scenario blueprints."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import yaml

from agentsim import registry
from agentsim.criteria import SPECIALISTS
from agentsim.judge import DEFAULT_CRITERIA
from agentsim.scenario import _ASSERTION_TYPES
from fixtures.paycard import CARDS, FUNDING_ACCOUNTS, LARGE_PAYMENT_THRESHOLD, Card

from .blueprint import (
    Blueprint,
    CoverageBlueprint,
    canonical_cell_id,
    canonical_coverage_blueprint_id,
    canonical_journey_path_id,
)
from .config import load_config
from .contracts import (
    ARCHETYPE_IDS,
    COMPLICATION_IDS,
    KNOWLEDGE_LEVELS,
    ContractSet,
    canonical_sha256,
    fitness_checks_for_policies,
    load_reviewed_contracts,
)
from .policies import POLICIES, Policy

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH = Path(__file__).with_name("procedures") / "j1.yaml"
REGISTRY_SOURCE = _ROOT / "agentsim" / "registry.py"
FIXTURE_SOURCE = _ROOT / "fixtures" / "paycard.py"


class BlueprintValidationError(ValueError):
    """One or more deterministic blueprint checks failed."""


class BlueprintValidator:
    """LEGACY — replaced by Phase 4.5 scenario synthesis; delete at cutover. Do not add features here."""

    def __init__(
        self,
        graph_path: str | Path = DEFAULT_GRAPH,
        *,
        policy_catalog: Mapping[str, Policy] = POLICIES,
        registry_path: str | Path = REGISTRY_SOURCE,
        fixture_path: str | Path = FIXTURE_SOURCE,
        contracts: ContractSet | None = None,
    ) -> None:
        self.graph_path = Path(graph_path)
        self.registry_path = Path(registry_path)
        self.fixture_path = Path(fixture_path)
        self.policy_catalog = policy_catalog
        self.contracts = contracts or load_reviewed_contracts()
        try:
            self.graph = yaml.safe_load(self.graph_path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise BlueprintValidationError(f"cannot load procedure graph: {exc}") from exc
        if not isinstance(self.graph, dict):
            raise BlueprintValidationError("procedure graph must be a mapping")
        edge_ids = [edge.get("id") for edge in self.graph.get("edges", [])]
        if not edge_ids or not all(isinstance(edge_id, str) and edge_id for edge_id in edge_ids):
            raise BlueprintValidationError("procedure graph edges must have stable IDs")
        if len(edge_ids) != len(set(edge_ids)):
            raise BlueprintValidationError("procedure graph edge IDs must be unique")
        self.graph_hash = _sha256(self.graph_path)
        self.fixture_hash = _sha256(self.fixture_path)

    def validate(self, blueprint: Blueprint) -> None:
        errors: list[str] = []
        self._check_drift(blueprint, errors)
        traversed = self._check_path(blueprint, errors)
        self._check_tools(blueprint, traversed, errors)
        self._check_bindings(blueprint, traversed, errors)
        self._check_policies(blueprint, traversed, errors)
        self._check_turns(blueprint, traversed, errors)
        self._check_edge_triggers(blueprint, traversed, errors)
        self._check_perturbations(blueprint, traversed, errors)
        if errors:
            raise BlueprintValidationError("; ".join(errors))

    def executability_errors(self, blueprint: Blueprint) -> tuple[str, ...]:
        """Return graph-trigger failures without applying provenance drift guards."""
        errors: list[str] = []
        traversed = self._check_path(blueprint, errors)
        self._check_edge_triggers(blueprint, traversed, errors)
        self._check_perturbations(blueprint, traversed, errors)
        return tuple(errors)

    def validate_without_executability(self, blueprint: Blueprint) -> None:
        """Apply the pre-Phase-4.1 structural checks for audit comparisons."""
        errors: list[str] = []
        self._check_drift(blueprint, errors)
        traversed = self._check_path(blueprint, errors)
        self._check_tools(blueprint, traversed, errors)
        self._check_bindings(blueprint, traversed, errors)
        self._check_policies(blueprint, traversed, errors)
        self._check_turns(blueprint, traversed, errors)
        if errors:
            raise BlueprintValidationError("; ".join(errors))

    def _check_drift(self, blueprint: Blueprint, errors: list[str]) -> None:
        recorded = self.graph.get("source_hashes", {})
        actual_registry = _sha256(self.registry_path)
        actual_fixture = _sha256(self.fixture_path)
        if recorded.get("registry") != actual_registry:
            errors.append("registry drift: graph hash does not match agentsim/registry.py")
        if recorded.get("fixtures") != actual_fixture:
            errors.append("fixture drift: graph hash does not match fixtures/paycard.py")
        if blueprint.provenance.graph_hash != self.graph_hash:
            errors.append("provenance.graph_hash does not match the J1 graph")
        if blueprint.provenance.fixture_hash != actual_fixture:
            errors.append("provenance.fixture_hash does not match fixtures/paycard.py")

    def _check_path(self, blueprint: Blueprint, errors: list[str]) -> list[dict[str, Any]]:
        path = blueprint.procedure_path
        starts = self.graph.get("start_nodes", [])
        terminals = self.graph.get("terminal_nodes", [])
        if blueprint.journey != self.graph.get("journey"):
            errors.append(f"journey {blueprint.journey!r} does not match graph")
        if not path:
            errors.append("procedure_path must contain at least one edge ID")
            return []
        edge_index = {
            str(edge.get("id")): edge
            for edge in self.graph.get("edges", [])
            if isinstance(edge, dict) and edge.get("id")
        }
        unknown = [edge_id for edge_id in path if edge_id not in edge_index]
        if unknown:
            errors.append(f"procedure_path has unknown edge ID(s) {unknown}")
            return []
        traversed = [edge_index[edge_id] for edge_id in path]
        if traversed[0].get("from") not in starts:
            errors.append(f"procedure_path must start at one of {starts}")
        if traversed[-1].get("to") not in terminals:
            errors.append(f"procedure_path must terminate at one of {terminals}")
        for left, right in zip(traversed, traversed[1:]):
            if left.get("to") != right.get("from"):
                errors.append(
                    "procedure_path is disconnected between edge IDs "
                    f"{left.get('id')!r} and {right.get('id')!r}"
                )
        return traversed

    def _check_tools(
        self, blueprint: Blueprint, edges: list[dict[str, Any]], errors: list[str]
    ) -> None:
        for edge in edges:
            for tool in edge.get("required_tools", []):
                if tool not in registry.ALL_TOOLS:
                    errors.append(f"graph edge names unknown registry tool {tool!r}")
        for index, assertion in enumerate(blueprint.tool_assertions):
            spec = _ASSERTION_TYPES.get(assertion.type)
            if spec is None:
                errors.append(f"tool_assertions[{index}] has unknown type {assertion.type!r}")
                continue
            required, tool_fields = spec
            keys = assertion.fields.keys()
            if required - keys:
                errors.append(
                    f"tool_assertions[{index}] missing field(s) {sorted(required - keys)}"
                )
            if keys - required:
                errors.append(
                    f"tool_assertions[{index}] has unknown field(s) {sorted(keys - required)}"
                )
            for field in tool_fields:
                if assertion.fields.get(field) not in registry.ALL_TOOLS:
                    errors.append(
                        f"tool_assertions[{index}].{field} names unknown tool "
                        f"{assertion.fields.get(field)!r}"
                    )

    def _check_bindings(
        self, blueprint: Blueprint, edges: list[dict[str, Any]], errors: list[str]
    ) -> None:
        cards_by_four = {card.last_four: card for card in CARDS}
        accounts_by_four = {account.last_four: account for account in FUNDING_ACCOUNTS}
        unknown_cards = [x for x in blueprint.fixture_bindings.cards if x not in cards_by_four]
        unknown_accounts = [
            x for x in blueprint.fixture_bindings.accounts if x not in accounts_by_four
        ]
        if unknown_cards:
            errors.append(f"unsatisfiable card binding(s) {unknown_cards}")
        if unknown_accounts:
            errors.append(f"unsatisfiable account binding(s) {unknown_accounts}")
        if unknown_cards or unknown_accounts:
            return
        cards = [cards_by_four[x] for x in blueprint.fixture_bindings.cards]
        predicates = {
            predicate
            for edge in edges
            for predicate in edge.get("required_fixture_predicates", [])
        }
        for policy_id in blueprint.policies:
            policy = self.policy_catalog.get(policy_id)
            if policy:
                predicates.update(policy.required_fixture_predicates)
        for predicate in sorted(predicates):
            if not _fixture_predicate(
                predicate, cards, len(blueprint.fixture_bindings.accounts)
            ):
                errors.append(f"fixture bindings do not satisfy predicate {predicate!r}")

    def _check_policies(
        self, blueprint: Blueprint, edges: list[dict[str, Any]], errors: list[str]
    ) -> None:
        applicable = {
            policy
            for edge in edges
            for policy in edge.get("applicable_policies", [])
        }
        chosen = set(blueprint.policies)
        for policy_id in blueprint.policies:
            policy = self.policy_catalog.get(policy_id)
            if policy is None:
                errors.append(f"orphan policy {policy_id!r}")
                continue
            if blueprint.journey not in policy.journeys:
                errors.append(f"policy {policy_id!r} does not apply to {blueprint.journey}")
            if policy_id not in applicable:
                errors.append(f"policy {policy_id!r} is not applicable on this path")
            assertions, criteria = fitness_checks_for_policies(
                (policy_id,), contracts=self.contracts
            )
            if not assertions and not criteria:
                errors.append(
                    f"orphan policy {policy_id!r} has no fitness-target enforcement hook"
                )
            conflicts = chosen.intersection(policy.incompatible_with)
            if conflicts:
                errors.append(f"policy {policy_id!r} conflicts with {sorted(conflicts)}")
            undeclared = chosen - {policy_id} - set(policy.compatible_with) - set(
                policy.incompatible_with
            )
            if undeclared:
                errors.append(
                    f"policy {policy_id!r} has no compatibility declaration for {sorted(undeclared)}"
                )

    def _check_turns(
        self, blueprint: Blueprint, edges: list[dict[str, Any]], errors: list[str]
    ) -> None:
        if isinstance(blueprint.max_turns, bool) or blueprint.max_turns <= 0:
            errors.append("max_turns must be a positive integer")
            return
        worst = sum(edge.get("worst_case_turn_cost", 0) for edge in edges)
        if worst > blueprint.max_turns:
            errors.append(
                f"worst-case path cost {worst} exceeds max_turns {blueprint.max_turns}"
            )

    def _check_perturbations(
        self, blueprint: Blueprint, edges: list[dict[str, Any]], errors: list[str]
    ) -> None:
        declared = {
            (kind, spec["position"]): spec
            for edge in edges
            for kind, spec in _perturbation_specs(edge).items()
        }
        for perturbation in blueprint.perturbations:
            spec = declared.get((perturbation.type, perturbation.position))
            if spec is None:
                errors.append(
                    f"perturbation {perturbation.type!r} is invalid at "
                    f"{perturbation.position!r}"
                )
                continue
            if spec.get("non_executable_against") == "mock":
                errors.append(
                    f"perturbation {perturbation.type!r} is non-executable against mock"
                )
                continue
            trigger = spec.get("executable_trigger")
            if not isinstance(trigger, Mapping):
                errors.append(
                    f"perturbation {perturbation.type!r} has no executable trigger"
                )
                continue
            _check_trigger(
                blueprint,
                trigger,
                f"perturbation {perturbation.type!r}",
                errors,
            )

    def _check_edge_triggers(
        self, blueprint: Blueprint, edges: list[dict[str, Any]], errors: list[str]
    ) -> None:
        for edge in edges:
            label = f"edge {edge.get('from')} -> {edge.get('to')}"
            if edge.get("non_executable_against") == "mock":
                errors.append(f"{label} is non-executable against mock")
                continue
            trigger = edge.get("executable_trigger")
            if trigger is not None:
                if not isinstance(trigger, Mapping):
                    errors.append(f"{label} has an invalid executable trigger")
                    continue
                _check_trigger(blueprint, trigger, label, errors)


def _perturbation_specs(edge: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for kind, raw in edge.get("valid_perturbations", {}).items():
        if isinstance(raw, str):
            specs[str(kind)] = {"position": raw}
        elif isinstance(raw, Mapping):
            specs[str(kind)] = dict(raw)
    return specs


def _check_trigger(
    blueprint: Blueprint,
    trigger: Mapping[str, Any],
    label: str,
    errors: list[str],
) -> None:
    facts = trigger.get("goal_facts", {})
    if not isinstance(facts, Mapping):
        errors.append(f"{label} executable trigger goal_facts must be a mapping")
        return
    for fact, expected in facts.items():
        actual = blueprint.goal_facts.get(fact)
        if isinstance(expected, Mapping):
            constant_name = expected.get("greater_than_fixture_constant")
            if constant_name != "LARGE_PAYMENT_THRESHOLD":
                errors.append(f"{label} has unknown trigger constant {constant_name!r}")
            elif (
                isinstance(actual, bool)
                or not isinstance(actual, (int, float))
                or actual <= LARGE_PAYMENT_THRESHOLD
            ):
                errors.append(
                    f"{label} requires goal_facts.{fact} greater than "
                    "LARGE_PAYMENT_THRESHOLD"
                )
        elif actual != expected:
            errors.append(f"{label} requires goal_facts.{fact}={expected!r}")

    condition = trigger.get("binding_condition")
    if condition is None:
        return
    if condition != "distinct_goal_fact_cards":
        errors.append(f"{label} has unknown binding condition {condition!r}")
        return
    initial = blueprint.goal_facts.get("initial_card_last_four")
    final = blueprint.goal_facts.get("final_card_last_four")
    bound_cards = set(blueprint.fixture_bindings.cards)
    if (
        not isinstance(initial, str)
        or not isinstance(final, str)
        or initial == final
        or initial not in bound_cards
        or final not in bound_cards
    ):
        errors.append(
            f"{label} requires distinct bound initial_card_last_four and "
            "final_card_last_four goal facts"
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_predicate(name: str, cards: list[Card], account_count: int) -> bool:
    if name == "has_card":
        return bool(cards)
    if name == "has_account":
        return account_count > 0
    if name == "multiple_cards":
        return len(cards) >= 2
    if name == "distinguishable_card_amounts":
        signatures = {
            (card.minimum_due, card.statement_balance, card.current_balance)
            for card in cards
        }
        return len(signatures) == len(cards) and len(cards) >= 2
    if name == "ambiguous_card_names":
        tokens = [
            {token.lower() for token in card.name.split() if token.lower() != "chase"}
            for card in cards
        ]
        return any(left & right for index, left in enumerate(tokens) for right in tokens[index + 1 :])
    raise BlueprintValidationError(f"unknown fixture predicate {name!r}")


class CoverageBlueprintValidator:
    """Fail-closed validation of Phase 4.5 qualification blueprints."""

    def __init__(self, *, contracts: ContractSet | None = None) -> None:
        self.contracts = contracts or load_reviewed_contracts()
        self.graph = self.contracts.graph
        self.config = load_config()
        self.edge_index = {edge["id"]: edge for edge in self.graph["edges"]}
        fixture_hash = hashlib.sha256(FIXTURE_SOURCE.read_bytes()).hexdigest()
        self.source_hashes = {
            "journey_graph": canonical_sha256(self.graph),
            "fixture": fixture_hash,
            "persona_archetypes": self.contracts.hashes["persona-archetypes"],
            "complication_applicability": self.contracts.hashes["complication-applicability"],
            "pair_exclusions": self.contracts.hashes["pair-exclusions"],
            "fixture_state_classes": self.contracts.hashes["fixture-state-classes"],
            "fitness_targets": self.contracts.hashes["fitness-targets"],
        }

    def validate(self, blueprint: CoverageBlueprint) -> None:
        errors: list[str] = []
        if blueprint.cell_id != canonical_cell_id(blueprint):
            errors.append("cell_id does not match the canonical six-axis tuple")
        if blueprint.blueprint_id != canonical_coverage_blueprint_id(blueprint):
            errors.append("blueprint_id does not match semantic content")
        if blueprint.provenance.config_hash != self.config.sha256:
            errors.append("contract drift: config_hash does not match")
        if dict(blueprint.provenance.source_hashes) != self.source_hashes:
            errors.append("contract drift: source_hashes do not match reviewed inputs")
        if blueprint.persona_archetype not in ARCHETYPE_IDS:
            errors.append(f"unknown Persona archetype {blueprint.persona_archetype!r}")
        if blueprint.knowledge_level not in KNOWLEDGE_LEVELS:
            errors.append(f"unknown Knowledge level {blueprint.knowledge_level!r}")
        if blueprint.complication not in COMPLICATION_IDS:
            errors.append(f"unknown Complication {blueprint.complication!r}")
        traversed = self._path(blueprint, errors)
        fixture_predicates = self._fixture(blueprint, errors)
        self._applicability(blueprint, traversed, fixture_predicates, errors)
        self._checks(blueprint, errors)
        self._sealed_world(blueprint, errors)
        worst = sum(int(edge.get("worst_case_turn_cost", 0)) for edge in traversed)
        if blueprint.max_turns < worst:
            errors.append(
                f"worst-case path cost {worst} exceeds max_turns {blueprint.max_turns}"
            )
        if errors:
            raise BlueprintValidationError("; ".join(errors))

    def _path(
        self, blueprint: CoverageBlueprint, errors: list[str]
    ) -> list[Mapping[str, Any]]:
        unknown = [edge for edge in blueprint.journey_edge_ids if edge not in self.edge_index]
        if unknown:
            errors.append(f"journey_edge_ids has unknown edge ID(s) {unknown}")
            return []
        traversed = [self.edge_index[edge] for edge in blueprint.journey_edge_ids]
        if not traversed:
            errors.append("journey_edge_ids must not be empty")
            return []
        if traversed[0]["from"] not in self.graph["start_nodes"]:
            errors.append("journey path does not start at an approved start node")
        if traversed[-1]["to"] not in self.graph["terminal_nodes"]:
            errors.append("journey path does not terminate at an approved terminal node")
        for left, right in zip(traversed, traversed[1:]):
            if left["to"] != right["from"]:
                errors.append(
                    f"journey path is disconnected between {left['id']!r} and {right['id']!r}"
                )
        expected_path_id = canonical_journey_path_id(
            str(self.graph["journey"]), blueprint.journey_edge_ids
        )
        if blueprint.journey_path_id != expected_path_id:
            errors.append("journey_path_id does not match the ordered edge IDs")
        return traversed

    def _fixture(
        self, blueprint: CoverageBlueprint, errors: list[str]
    ) -> dict[str, bool]:
        classes = self.contracts.contracts["fixture-state-classes"].content["classes"]
        fixture_class = next(
            (item for item in classes if item["id"] == blueprint.fixture_state_class_id),
            None,
        )
        if fixture_class is None:
            errors.append(
                f"unknown fixture-state class {blueprint.fixture_state_class_id!r}"
            )
            return {}
        binding = {
            "cards": list(blueprint.fixture_bindings.cards),
            "accounts": list(blueprint.fixture_bindings.accounts),
        }
        if binding not in fixture_class["bindings"]:
            errors.append("Fixture bindings are not a member of the declared class")
        return dict(fixture_class["predicates"])

    def _applicability(
        self,
        blueprint: CoverageBlueprint,
        traversed: list[Mapping[str, Any]],
        fixture_predicates: Mapping[str, bool],
        errors: list[str],
    ) -> None:
        edge_ids = set(blueprint.journey_edge_ids)
        available_predicates = {
            key for key, value in fixture_predicates.items() if value
        } | {"has_real_fixture_fact"}
        for edge in traversed:
            missing = set(edge.get("required_fixture_predicates", [])) - available_predicates
            if missing:
                errors.append(f"Fixture class misses path predicate(s) {sorted(missing)}")
        complications = {
            item["id"]: item
            for item in self.contracts.contracts["complication-applicability"].content["complications"]
        }
        complication = complications[blueprint.complication]
        if set(complication["required_edge_ids"]) - edge_ids:
            errors.append("Complication is not applicable to the journey path")
        if set(complication["fixture_predicates"]) - available_predicates:
            errors.append("Complication is not applicable to the Fixture class")
        represented_events = {item["id"] for item in self.graph["events"]}
        if set(complication["required_event_ids"]) - represented_events:
            errors.append("Complication event is not represented by the Journey graph")
        if blueprint.fitness_target_id is None:
            return
        targets = self.contracts.contracts["fitness-targets"].content["targets"]
        target = next(
            (
                item for item in targets
                if item["target_id"] == blueprint.fitness_target_id
                and item["shape_id"] == blueprint.fitness_shape_id
            ),
            None,
        )
        if target is None:
            errors.append("unknown Fitness target/shape")
            return
        applicability = target["applicability"]
        if self.graph["journey"] not in applicability["journey_ids"]:
            errors.append("Fitness target is not applicable to this Journey")
        if set(applicability["required_edge_ids"]) - edge_ids:
            errors.append("Fitness target is not applicable to the journey path")
        if set(applicability["fixture_predicates"]) - available_predicates:
            errors.append("Fitness target is not applicable to the Fixture class")

    def _checks(self, blueprint: CoverageBlueprint, errors: list[str]) -> None:
        for index, assertion in enumerate(blueprint.required_assertions):
            spec = _ASSERTION_TYPES.get(assertion.type)
            if spec is None:
                errors.append(f"required_assertions[{index}] has unknown type")
                continue
            required, tool_fields = spec
            if set(assertion.fields) != required:
                errors.append(f"required_assertions[{index}] fields do not match registry")
            for field in tool_fields:
                if assertion.fields.get(field) not in registry.ALL_TOOLS:
                    errors.append(f"required_assertions[{index}] names unknown tool")
        known_criteria = {criterion.id for criterion in DEFAULT_CRITERIA} | {
            specialist.criterion.id for specialist in SPECIALISTS
        }
        unknown_criteria = set(blueprint.required_criteria) - known_criteria
        if unknown_criteria:
            errors.append(f"required_criteria has unknown ID(s) {sorted(unknown_criteria)}")
        missing_base = {criterion.id for criterion in DEFAULT_CRITERIA} - set(
            blueprint.required_criteria
        )
        if missing_base:
            errors.append(
                f"required_criteria is missing curated base ID(s) {sorted(missing_base)}"
            )

    def _sealed_world(self, blueprint: CoverageBlueprint, errors: list[str]) -> None:
        bound = set(blueprint.fixture_bindings.cards) | set(
            blueprint.fixture_bindings.accounts
        )

        def walk(value: Any, key: str = "") -> None:
            if isinstance(value, Mapping):
                for child_key, child in value.items():
                    walk(child, str(child_key))
            elif isinstance(value, list):
                for child in value:
                    walk(child, key)
            elif key.endswith("last_four") and (not isinstance(value, str) or value not in bound):
                errors.append(
                    f"Sealed-world violation: {key}={value!r} is not a bound Fixture fact"
                )

        walk(blueprint.goal_facts)
