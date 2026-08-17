"""Deterministic validation for scenario blueprints."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import yaml

from agentsim import registry
from agentsim.scenario import _ASSERTION_TYPES
from fixtures.paycard import CARDS, FUNDING_ACCOUNTS, Card

from .blueprint import Blueprint
from .policies import POLICIES, Policy

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH = Path(__file__).with_name("procedures") / "j1.yaml"
REGISTRY_SOURCE = _ROOT / "agentsim" / "registry.py"
FIXTURE_SOURCE = _ROOT / "fixtures" / "paycard.py"


class BlueprintValidationError(ValueError):
    """One or more deterministic blueprint checks failed."""


class BlueprintValidator:
    def __init__(
        self,
        graph_path: str | Path = DEFAULT_GRAPH,
        *,
        policy_catalog: Mapping[str, Policy] = POLICIES,
        registry_path: str | Path = REGISTRY_SOURCE,
        fixture_path: str | Path = FIXTURE_SOURCE,
    ) -> None:
        self.graph_path = Path(graph_path)
        self.registry_path = Path(registry_path)
        self.fixture_path = Path(fixture_path)
        self.policy_catalog = policy_catalog
        try:
            self.graph = yaml.safe_load(self.graph_path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise BlueprintValidationError(f"cannot load procedure graph: {exc}") from exc
        if not isinstance(self.graph, dict):
            raise BlueprintValidationError("procedure graph must be a mapping")
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
        self._check_perturbations(blueprint, traversed, errors)
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
        nodes = self.graph.get("nodes", {})
        starts = self.graph.get("start_nodes", [])
        terminals = self.graph.get("terminal_nodes", [])
        if blueprint.journey != self.graph.get("journey"):
            errors.append(f"journey {blueprint.journey!r} does not match graph")
        if len(path) < 2:
            errors.append("procedure_path must contain at least two nodes")
            return []
        unknown = [node for node in path if node not in nodes]
        if unknown:
            errors.append(f"procedure_path has unknown node(s) {unknown}")
        if path[0] not in starts:
            errors.append(f"procedure_path must start at one of {starts}")
        if path[-1] not in terminals:
            errors.append(f"procedure_path must terminate at one of {terminals}")

        edge_index = {
            (edge.get("from"), edge.get("to")): edge
            for edge in self.graph.get("edges", [])
            if isinstance(edge, dict)
        }
        traversed: list[dict[str, Any]] = []
        for pair in zip(path, path[1:]):
            edge = edge_index.get(pair)
            if edge is None:
                errors.append(f"procedure_path is disconnected at {pair[0]} -> {pair[1]}")
            else:
                traversed.append(edge)
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
            if not policy.tool_assertions and not policy.judge_hooks:
                errors.append(f"orphan policy {policy_id!r} has no assertion or judge hook")
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
            (kind, position)
            for edge in edges
            for kind, position in edge.get("valid_perturbations", {}).items()
        }
        for perturbation in blueprint.perturbations:
            if (perturbation.type, perturbation.position) not in declared:
                errors.append(
                    f"perturbation {perturbation.type!r} is invalid at "
                    f"{perturbation.position!r}"
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
