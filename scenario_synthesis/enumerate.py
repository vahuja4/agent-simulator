"""Exhaustive, deterministic enumeration of valid J1 blueprints."""

from __future__ import annotations

import itertools
import json
import shutil
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from agentsim.scenario import ToolAssertion
from fixtures.paycard import CARDS, FUNDING_ACCOUNTS, LARGE_PAYMENT_THRESHOLD

from .blueprint import (
    Blueprint,
    FixtureBindings,
    Perturbation,
    Provenance,
    canonical_blueprint_id,
    dump_blueprint,
    _load_legacy_blueprint,
)
from .contracts import fitness_checks_for_policies
from .policies import POLICIES, Policy
from .sample import behavioral_representatives, sample_blueprints, stratum_counts
from .validator import (
    BlueprintValidationError,
    BlueprintValidator,
    _fixture_predicate,
    _perturbation_specs,
)

GENERATOR_VERSION = "phase-4.1-v1"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "generated_scenarios"
CARD_SWITCH_EDGE = "j1-fetch-options-select-card"
VALIDATION_RETRY_EDGE = "j1-validate-retry"
MAX_PERTURBATIONS = 2


def enumerate_blueprints(
    *, validator: BlueprintValidator | None = None, seed: int = 0
) -> tuple[Blueprint, ...]:
    """Return every deduplicated valid J1 blueprint in canonical order."""
    validator = validator or BlueprintValidator()
    return _enumerate_blueprints(validator=validator, seed=seed)


def _enumerate_blueprints(
    *,
    validator: BlueprintValidator,
    seed: int,
    include_non_executable: bool = False,
) -> tuple[Blueprint, ...]:
    graph = validator.graph
    predicate_names = _predicate_names(graph, validator.policy_catalog)
    fixture_classes = _fixture_equivalence_classes(predicate_names)
    candidates: dict[tuple[Any, ...], Blueprint] = {}

    for path, edges in _procedure_paths(
        graph, include_non_executable=include_non_executable
    ):
        applicable = {
            policy_id
            for edge in edges
            for policy_id in edge.get("applicable_policies", [])
        }
        for policies in _compatible_policy_sets(applicable, validator.policy_catalog):
            assertions = _tool_assertions(policies, validator)
            for perturbations in _perturbation_variants(
                edges, include_non_executable=include_non_executable
            ):
                for fixture_class, bindings in fixture_classes:
                    blueprint = Blueprint(
                        id="pending",
                        journey=str(graph["journey"]),
                        procedure_path=path,
                        policies=policies,
                        fixture_bindings=bindings,
                        goal_facts=_goal_facts(path, bindings, perturbations),
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
                        if include_non_executable:
                            validator.validate_without_executability(blueprint)
                        else:
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
    root = Path(output_root)
    if root.resolve() == DEFAULT_OUTPUT_ROOT.resolve():
        raise RuntimeError(
            "generated_scenarios is a read-only historical quarantine; "
            "use the Phase 4.5 planner/generator"
        )
    existing_manifest = _load_existing_manifest(root / "manifest.json")
    artifact_statuses = _existing_artifact_statuses(
        root, existing_manifest, validator
    )
    _archive_unexecutable_blueprints(root, artifact_statuses)
    blueprints = enumerate_blueprints(validator=validator, seed=seed)
    pre_filter = _enumerate_blueprints(
        validator=validator, seed=seed, include_non_executable=True
    )
    representatives = behavioral_representatives(blueprints)
    pre_filter_representatives = behavioral_representatives(pre_filter)
    sample = sample_blueprints(blueprints, seed=seed, per_stratum=per_stratum)
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
            "behavioral_classes": len(representatives),
            "sample": len(sample),
        },
        "executable_space_audit": {
            "environment": "mock",
            "deduped_space_before": len(pre_filter),
            "deduped_space_after": len(blueprints),
            "deduped_space_excluded": len(pre_filter) - len(blueprints),
            "behavioral_classes_before": len(pre_filter_representatives),
            "behavioral_classes_after": len(representatives),
            "behavioral_classes_excluded": len(pre_filter_representatives)
            - len(representatives),
            "excluded": _exclusion_counts(pre_filter, validator),
        },
        "sampling_unit": "behavioral_class",
        "per_stratum_counts": counts,
        "sample_per_stratum": per_stratum,
        "sample_ids": [blueprint.id for blueprint in sample],
        "realized_scenarios": list(existing_manifest.get("realized_scenarios", [])),
    }
    for preserved in ("dry_run_summary", "dry_runs"):
        if preserved in existing_manifest:
            value = existing_manifest[preserved]
            manifest[preserved] = value
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def _load_existing_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text())
    return loaded if isinstance(loaded, dict) else {}


def _existing_artifact_statuses(
    root: Path,
    manifest: Mapping[str, Any],
    validator: BlueprintValidator,
) -> dict[str, tuple[str, ...]]:
    statuses: dict[str, tuple[str, ...]] = {}
    records = list(manifest.get("realized_scenarios", [])) + list(
        manifest.get("dry_runs", [])
    )
    for record in records:
        if not isinstance(record, Mapping):
            continue
        blueprint_id = record.get("blueprint_id")
        if not isinstance(blueprint_id, str):
            continue
        previous = record.get("unexecutable_reasons", [])
        if record.get("status") == "unexecutable_blueprint" and isinstance(
            previous, list
        ):
            statuses[blueprint_id] = tuple(str(item) for item in previous)
            continue
        path = root / "blueprints" / f"{blueprint_id}.yaml"
        if not path.exists():
            continue
        errors = validator.executability_errors(_load_legacy_blueprint(path))
        if errors:
            statuses[blueprint_id] = errors
    return statuses


def _archive_unexecutable_blueprints(
    root: Path, statuses: Mapping[str, tuple[str, ...]]
) -> None:
    archive = root / "unexecutable_blueprints"
    for blueprint_id in sorted(statuses):
        source = root / "blueprints" / f"{blueprint_id}.yaml"
        target = archive / source.name
        if source.exists() and not target.exists():
            archive.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def _procedure_paths(
    graph: Mapping[str, Any],
    *,
    include_non_executable: bool = False,
) -> Iterator[tuple[tuple[str, ...], tuple[Mapping[str, Any], ...]]]:
    adjacency: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []):
        adjacency[str(edge["from"])].append(edge)
    terminals = set(graph.get("terminal_nodes", []))
    cyclic_edges = {CARD_SWITCH_EDGE, VALIDATION_RETRY_EDGE}

    def walk(
        node: str,
        path: tuple[str, ...],
        traversed: tuple[Mapping[str, Any], ...],
        cycle_counts: Mapping[str, int],
    ) -> Iterator[tuple[tuple[str, ...], tuple[Mapping[str, Any], ...]]]:
        if node in terminals:
            yield path, traversed
            return
        for edge in adjacency.get(node, []):
            if (
                not include_non_executable
                and edge.get("non_executable_against") == "mock"
            ):
                continue
            edge_id = str(edge["id"])
            if edge_id in cyclic_edges and cycle_counts.get(edge_id, 0) >= 1:
                continue
            next_counts = dict(cycle_counts)
            if edge_id in cyclic_edges:
                next_counts[edge_id] = next_counts.get(edge_id, 0) + 1
            yield from walk(
                str(edge["to"]), path + (edge_id,), traversed + (edge,), next_counts
            )

    for start in graph.get("start_nodes", []):
        yield from walk(str(start), (), (), {})


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
    *,
    include_non_executable: bool = False,
) -> tuple[tuple[Perturbation, ...], ...]:
    placements: list[Perturbation] = []
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        for kind, spec in _perturbation_specs(edge).items():
            if (
                not include_non_executable
                and spec.get("non_executable_against") == "mock"
            ):
                continue
            position = spec["position"]
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
    policies: Sequence[str], validator: BlueprintValidator
) -> tuple[ToolAssertion, ...]:
    assertion_types, _criteria = fitness_checks_for_policies(
        policies, contracts=validator.contracts
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


def _goal_facts(
    path: Sequence[str],
    bindings: FixtureBindings,
    perturbations: Sequence[Perturbation],
) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "card_last_four": bindings.cards[0],
        "account_last_four": bindings.accounts[0],
        "amount_type": "statement_balance",
        "date": "due_date",
    }
    if CARD_SWITCH_EDGE in path and len(bindings.cards) > 1:
        facts["initial_card_last_four"] = bindings.cards[0]
        facts["final_card_last_four"] = bindings.cards[1]
    perturbation_types = {item.type for item in perturbations}
    if "partial_disclosure" in perturbation_types:
        facts["disclosure_style"] = "one_fact_at_a_time"
    if "submission_failure" in perturbation_types or "j1-submit-handle-failure" in path:
        facts["amount_type"] = "custom"
        facts["amount"] = LARGE_PAYMENT_THRESHOLD + 1000.0
    if "j1-submit-handle-failure" in path:
        facts["expected_outcome"] = "submission_failure_reported_truthfully"
    return facts


def _exclusion_counts(
    pre_filter: Sequence[Blueprint], validator: BlueprintValidator
) -> dict[str, Any]:
    edge_index = {str(edge["id"]): edge for edge in validator.graph.get("edges", [])}

    def reasons(blueprint: Blueprint) -> tuple[tuple[str, str], ...]:
        found: set[tuple[str, str]] = set()
        edges = [edge_index[edge_id] for edge_id in blueprint.procedure_path]
        for edge in edges:
            if edge.get("non_executable_against") == "mock":
                found.add(("edges", f"{edge['from']}->{edge['to']}"))
        declarations = {
            (kind, spec["position"]): spec
            for edge in edges
            for kind, spec in _perturbation_specs(edge).items()
        }
        for perturbation in blueprint.perturbations:
            spec = declarations.get((perturbation.type, perturbation.position), {})
            if spec.get("non_executable_against") == "mock":
                found.add(("perturbations", perturbation.type))
        return tuple(sorted(found))

    deduped: Counter[tuple[str, str]] = Counter()
    for blueprint in pre_filter:
        deduped.update(reasons(blueprint))
    classes: Counter[tuple[str, str]] = Counter()
    for blueprint in behavioral_representatives(pre_filter):
        classes.update(reasons(blueprint))

    result: dict[str, dict[str, dict[str, int]]] = {
        "perturbations": {},
        "edges": {},
    }
    for category, name in sorted(set(deduped) | set(classes)):
        result[category][name] = {
            "deduped_blueprints": deduped[(category, name)],
            "behavioral_classes": classes[(category, name)],
        }
    return result


def _with_canonical_id(blueprint: Blueprint, key: tuple[Any, ...]) -> Blueprint:
    from dataclasses import replace

    del key  # Deduplication and identity intentionally use different material.
    return replace(blueprint, id=canonical_blueprint_id(blueprint))


def _sortable_key(key: tuple[Any, ...]) -> tuple[Any, ...]:
    journey, path, policies, perturbations, fixture_class = key
    return journey, path, tuple(sorted(policies)), perturbations, fixture_class


if __name__ == "__main__":
    write_generation()
