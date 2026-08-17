"""Exhaustive, deterministic enumeration of valid J1 blueprints."""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from agentsim.scenario import ToolAssertion
from fixtures.paycard import CARDS, FUNDING_ACCOUNTS

from .blueprint import Blueprint, FixtureBindings, Perturbation, Provenance, dump_blueprint
from .policies import POLICIES, Policy
from .sample import sample_blueprints, stratum_counts
from .validator import BlueprintValidationError, BlueprintValidator, _fixture_predicate

GENERATOR_VERSION = "phase-2-v1"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "generated_scenarios"
CARD_SWITCH_EDGE = ("fetch_options", "select_card")
MAX_PERTURBATIONS = 2


def enumerate_blueprints(
    *, validator: BlueprintValidator | None = None, seed: int = 0
) -> tuple[Blueprint, ...]:
    """Return every deduplicated valid J1 blueprint in canonical order."""
    validator = validator or BlueprintValidator()
    graph = validator.graph
    predicate_names = _predicate_names(graph, validator.policy_catalog)
    fixture_classes = _fixture_equivalence_classes(predicate_names)
    candidates: dict[tuple[Any, ...], Blueprint] = {}

    for path, edges in _procedure_paths(graph):
        applicable = {
            policy_id
            for edge in edges
            for policy_id in edge.get("applicable_policies", [])
        }
        for policies in _compatible_policy_sets(applicable, validator.policy_catalog):
            assertions = _tool_assertions(policies, validator.policy_catalog)
            for perturbations in _perturbation_variants(edges):
                for fixture_class, bindings in fixture_classes:
                    blueprint = Blueprint(
                        id="pending",
                        journey=str(graph["journey"]),
                        procedure_path=path,
                        policies=policies,
                        fixture_bindings=bindings,
                        goal_facts=_goal_facts(path, bindings),
                        perturbations=perturbations,
                        tool_assertions=assertions,
                        max_turns=sum(int(edge.get("worst_case_turn_cost", 0)) for edge in edges),
                        provenance=Provenance(
                            generator_version=GENERATOR_VERSION,
                            seed=seed,
                            graph_hash=validator.graph_hash,
                            fixture_hash=validator.fixture_hash,
                        ),
                    )
                    key = canonical_key(blueprint, fixture_class=fixture_class)
                    if key in candidates:
                        continue
                    blueprint = _with_canonical_id(blueprint, key)
                    try:
                        validator.validate(blueprint)
                    except BlueprintValidationError as exc:
                        if "drift:" in str(exc):
                            raise
                        continue
                    candidates[key] = blueprint

    return tuple(candidates[key] for key in sorted(candidates, key=_sortable_key))


def canonical_key(
    blueprint: Blueprint, *, fixture_class: Sequence[str]
) -> tuple[Any, ...]:
    """Return the Phase 2 canonical deduplication form."""
    return (
        blueprint.journey,
        blueprint.procedure_path,
        frozenset(blueprint.policies),
        tuple((item.type, item.position) for item in blueprint.perturbations),
        tuple(fixture_class),
    )


def write_generation(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    seed: int = 0,
    per_stratum: int = 1,
    validator: BlueprintValidator | None = None,
) -> dict[str, Any]:
    """Enumerate J1, write all blueprints, and record a reproducible sample."""
    validator = validator or BlueprintValidator()
    blueprints = enumerate_blueprints(validator=validator, seed=seed)
    sample = sample_blueprints(blueprints, seed=seed, per_stratum=per_stratum)
    root = Path(output_root)
    blueprint_dir = root / "blueprints"
    blueprint_dir.mkdir(parents=True, exist_ok=True)
    expected_names = {f"{blueprint.id}.yaml" for blueprint in blueprints}
    for stale in sorted(blueprint_dir.glob("*.yaml")):
        if stale.name not in expected_names:
            stale.unlink()
    for blueprint in blueprints:
        dump_blueprint(blueprint, blueprint_dir / f"{blueprint.id}.yaml")

    counts = stratum_counts(blueprints)
    manifest: dict[str, Any] = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "graph_hash": validator.graph_hash,
        "fixture_hash": validator.fixture_hash,
        "loop_limits": {"fetch_options->select_card": 1},
        "max_perturbations_per_blueprint": MAX_PERTURBATIONS,
        "counts": {
            "deduped_space": len(blueprints),
            "sample": len(sample),
        },
        "per_stratum_counts": counts,
        "sample_per_stratum": per_stratum,
        "sample_ids": [blueprint.id for blueprint in sample],
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def _procedure_paths(
    graph: Mapping[str, Any],
) -> Iterator[tuple[tuple[str, ...], tuple[Mapping[str, Any], ...]]]:
    adjacency: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []):
        adjacency[str(edge["from"])].append(edge)
    terminals = set(graph.get("terminal_nodes", []))
    cyclic_edges = {CARD_SWITCH_EDGE, ("validate", "validate")}

    def walk(
        node: str,
        path: tuple[str, ...],
        traversed: tuple[Mapping[str, Any], ...],
        cycle_counts: Mapping[tuple[str, str], int],
    ) -> Iterator[tuple[tuple[str, ...], tuple[Mapping[str, Any], ...]]]:
        if node in terminals:
            yield path, traversed
            return
        for edge in adjacency.get(node, []):
            pair = (str(edge["from"]), str(edge["to"]))
            if pair in cyclic_edges and cycle_counts.get(pair, 0) >= 1:
                continue
            next_counts = dict(cycle_counts)
            if pair in cyclic_edges:
                next_counts[pair] = next_counts.get(pair, 0) + 1
            yield from walk(
                pair[1], path + (pair[1],), traversed + (edge,), next_counts
            )

    for start in graph.get("start_nodes", []):
        yield from walk(str(start), (str(start),), (), {})


def _compatible_policy_sets(
    applicable: set[str], catalog: Mapping[str, Policy]
) -> Iterator[tuple[str, ...]]:
    ordered = tuple(policy_id for policy_id in catalog if policy_id in applicable)
    for size in range(len(ordered) + 1):
        for chosen in itertools.combinations(ordered, size):
            chosen_set = set(chosen)
            if all(
                not chosen_set.intersection(catalog[item].incompatible_with)
                and chosen_set - {item}
                <= set(catalog[item].compatible_with) | set(catalog[item].incompatible_with)
                for item in chosen
            ):
                yield chosen


def _perturbation_variants(
    edges: Iterable[Mapping[str, Any]],
) -> tuple[tuple[Perturbation, ...], ...]:
    placements: list[Perturbation] = []
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        for kind, position in edge.get("valid_perturbations", {}).items():
            pair = (str(kind), str(position))
            if pair not in seen:
                placements.append(Perturbation(*pair))
                seen.add(pair)
    variants: list[tuple[Perturbation, ...]] = []
    for size in range(min(MAX_PERTURBATIONS, len(placements)) + 1):
        for chosen in itertools.combinations(placements, size):
            if len({item.position for item in chosen}) == len(chosen):
                variants.append(chosen)
    return tuple(variants)


def _predicate_names(
    graph: Mapping[str, Any], catalog: Mapping[str, Policy]
) -> tuple[str, ...]:
    names = {
        str(predicate)
        for edge in graph.get("edges", [])
        for predicate in edge.get("required_fixture_predicates", [])
    }
    names.update(
        predicate
        for policy in catalog.values()
        for predicate in policy.required_fixture_predicates
    )
    return tuple(sorted(names))


def _fixture_equivalence_classes(
    predicate_names: Sequence[str],
) -> tuple[tuple[tuple[str, ...], FixtureBindings], ...]:
    representatives: dict[tuple[str, ...], FixtureBindings] = {}
    card_subsets = itertools.chain.from_iterable(
        itertools.combinations(CARDS, size) for size in range(1, len(CARDS) + 1)
    )
    account_subsets = tuple(
        itertools.chain.from_iterable(
            itertools.combinations(FUNDING_ACCOUNTS, size)
            for size in range(1, len(FUNDING_ACCOUNTS) + 1)
        )
    )
    for cards in card_subsets:
        for accounts in account_subsets:
            fixture_class = tuple(
                name
                for name in predicate_names
                if _fixture_predicate(name, list(cards), len(accounts))
            )
            binding = FixtureBindings(
                cards=tuple(card.last_four for card in cards),
                accounts=tuple(account.last_four for account in accounts),
            )
            current = representatives.get(fixture_class)
            if current is None or (binding.cards, binding.accounts) < (
                current.cards,
                current.accounts,
            ):
                representatives[fixture_class] = binding
    return tuple(sorted(representatives.items()))


def _tool_assertions(
    policies: Sequence[str], catalog: Mapping[str, Policy]
) -> tuple[ToolAssertion, ...]:
    assertion_types = dict.fromkeys(
        assertion
        for policy_id in policies
        for assertion in catalog[policy_id].tool_assertions
    )
    assertions: list[ToolAssertion] = []
    for assertion_type in assertion_types:
        fields = (
            {"submit": "AddOneTimePayment", "validate": "AddValidateOneTimePayment"}
            if assertion_type == "validated_submit"
            else {}
        )
        assertions.append(ToolAssertion(type=assertion_type, fields=fields))
    return tuple(assertions)


def _goal_facts(path: Sequence[str], bindings: FixtureBindings) -> dict[str, str]:
    facts = {
        "card_last_four": bindings.cards[0],
        "account_last_four": bindings.accounts[0],
        "amount_type": "statement_balance",
        "date": "due_date",
    }
    if CARD_SWITCH_EDGE in set(zip(path, path[1:])) and len(bindings.cards) > 1:
        facts["initial_card_last_four"] = bindings.cards[0]
        facts["final_card_last_four"] = bindings.cards[1]
    if "handle_failure" in path:
        facts["expected_outcome"] = "submission_failure_reported_truthfully"
    return facts


def _with_canonical_id(blueprint: Blueprint, key: tuple[Any, ...]) -> Blueprint:
    from dataclasses import replace

    digest = hashlib.sha256(repr(_sortable_key(key)).encode()).hexdigest()[:16]
    return replace(blueprint, id=f"j1-{digest}")


def _sortable_key(key: tuple[Any, ...]) -> tuple[Any, ...]:
    journey, path, policies, perturbations, fixture_class = key
    return journey, path, tuple(sorted(policies)), perturbations, fixture_class


if __name__ == "__main__":
    write_generation()
