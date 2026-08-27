"""Deterministic Phase 4.5 Coverage-cell and blueprint generation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from agentsim.scenario import ToolAssertion
from fixtures.paycard import CARDS, LARGE_PAYMENT_THRESHOLD

from .blueprint import (
    QUALIFICATION_BLUEPRINT_SCHEMA_VERSION,
    CoverageBlueprint,
    CoverageCell,
    FixtureBindings,
    GenerationProvenance,
    canonical_cell_id,
    canonical_coverage_blueprint_id,
    canonical_journey_path_id,
)
from .config import load_config
from .contracts import ARCHETYPE_IDS, KNOWLEDGE_LEVELS, ContractSet, load_reviewed_contracts
from .validator import CoverageBlueprintValidator


@dataclass(frozen=True)
class EligibleCellSpec:
    cell: CoverageCell
    edge_ids: tuple[str, ...]
    fixture_bindings: FixtureBindings
    fixture_predicates: Mapping[str, bool]
    fitness_entry: Mapping[str, Any] | None
    blocked_reason: str | None
    path_application_count: int


def enumerate_eligible_cell_specs(
    *, contracts: ContractSet | None = None
) -> tuple[EligibleCellSpec, ...]:
    """Enumerate eligibility from reviewed contracts, never generator reachability."""
    contracts = contracts or load_reviewed_contracts()
    graph = contracts.graph
    fixture_classes = contracts.contracts["fixture-state-classes"].content["classes"]
    complications = contracts.contracts["complication-applicability"].content["complications"]
    targets = contracts.contracts["fitness-targets"].content["targets"]
    event_index = {item["id"]: item for item in graph["events"]}
    represented_events = set(event_index)
    result: list[EligibleCellSpec] = []
    for edge_ids, edges in _procedure_paths(graph):
        path_id = canonical_journey_path_id(str(graph["journey"]), edge_ids)
        path_predicates = {
            predicate
            for edge in edges
            for predicate in edge.get("required_fixture_predicates", [])
        }
        for fixture_class in fixture_classes:
            predicates = dict(fixture_class["predicates"])
            available = {key for key, value in predicates.items() if value} | {
                "has_real_fixture_fact"
            }
            if path_predicates - available:
                continue
            binding = fixture_class["bindings"][0]
            fixture_bindings = FixtureBindings(
                cards=tuple(binding["cards"]), accounts=tuple(binding["accounts"])
            )
            applicable_complications = [
                item
                for item in complications
                if set(item["required_edge_ids"]) <= set(edge_ids)
                and set(item["required_event_ids"]) <= represented_events
                and set(item["fixture_predicates"]) <= available
            ]
            applicable_targets: list[Mapping[str, Any] | None] = [None]
            applicable_targets.extend(
                target
                for target in targets
                if graph["journey"] in target["applicability"]["journey_ids"]
                and set(target["applicability"]["required_edge_ids"]) <= set(edge_ids)
                and set(target["applicability"]["fixture_predicates"]) <= available
            )
            for persona in sorted(ARCHETYPE_IDS):
                for knowledge in sorted(KNOWLEDGE_LEVELS):
                    for complication in sorted(
                        applicable_complications, key=lambda item: item["id"]
                    ):
                        for target in sorted(
                            applicable_targets,
                            key=lambda item: (
                                "" if item is None else item["target_id"],
                                "" if item is None else item["shape_id"],
                            ),
                        ):
                            cell = CoverageCell(
                                journey_path_id=path_id,
                                persona_archetype=persona,
                                knowledge_level=knowledge,
                                complication=complication["id"],
                                fixture_state_class_id=fixture_class["id"],
                                fitness_target_id=(None if target is None else target["target_id"]),
                                fitness_shape_id=(None if target is None else target["shape_id"]),
                            )
                            result.append(
                                EligibleCellSpec(
                                    cell=cell,
                                    edge_ids=edge_ids,
                                    fixture_bindings=fixture_bindings,
                                    fixture_predicates=predicates,
                                    fitness_entry=target,
                                    blocked_reason=None,
                                    path_application_count=max(
                                        (
                                            int(event_index[event_id]["path_application_count"])
                                            for event_id in complication["required_event_ids"]
                                        ),
                                        default=1,
                                    ),
                                )
                            )
    return tuple(sorted(result, key=lambda item: canonical_cell_id(item.cell)))


def generate_blueprints(
    *,
    generated_at: str | None = None,
    contracts: ContractSet | None = None,
) -> tuple[CoverageBlueprint, ...]:
    """Generate every currently realizable eligible blueprint; fail on any invalid one."""
    contracts = contracts or load_reviewed_contracts()
    config = load_config()
    validator = CoverageBlueprintValidator(contracts=contracts)
    timestamp = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    generated: list[CoverageBlueprint] = []
    for spec in enumerate_eligible_cell_specs(contracts=contracts):
        if spec.blocked_reason is not None:
            continue
        goal_facts = _goal_facts(spec)
        assertions, criteria = _required_checks(spec)
        edges = [validator.edge_index[edge_id] for edge_id in spec.edge_ids]
        provisional = CoverageBlueprint(
            schema_version=QUALIFICATION_BLUEPRINT_SCHEMA_VERSION,
            blueprint_id="blueprint-" + "0" * 64,
            cell_id=canonical_cell_id(spec.cell),
            journey_path_id=spec.cell.journey_path_id,
            persona_archetype=spec.cell.persona_archetype,
            knowledge_level=spec.cell.knowledge_level,
            complication=spec.cell.complication,
            fixture_state_class_id=spec.cell.fixture_state_class_id,
            fitness_target_id=spec.cell.fitness_target_id,
            fitness_shape_id=spec.cell.fitness_shape_id,
            journey_edge_ids=spec.edge_ids,
            fixture_bindings=spec.fixture_bindings,
            goal_facts=goal_facts,
            required_assertions=assertions,
            required_criteria=criteria,
            max_turns=(
                sum(int(edge.get("worst_case_turn_cost", 0)) for edge in edges)
                * spec.path_application_count
            ),
            provenance=GenerationProvenance(
                generator_version=str(config.content["versions"]["generator"]),
                config_hash=config.sha256,
                source_hashes=validator.source_hashes,
                generated_at=timestamp,
            ),
        )
        blueprint = replace(
            provisional, blueprint_id=canonical_coverage_blueprint_id(provisional)
        )
        validator.validate(blueprint)  # validation failures are never skipped
        generated.append(blueprint)
    return tuple(generated)


def _procedure_paths(
    graph: Mapping[str, Any],
) -> Iterator[tuple[tuple[str, ...], tuple[Mapping[str, Any], ...]]]:
    adjacency: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for edge in graph["edges"]:
        adjacency[edge["from"]].append(edge)
    terminals = set(graph["terminal_nodes"])
    cyclic = {"j1-fetch-options-select-card"}

    def walk(
        node: str,
        edge_ids: tuple[str, ...],
        edges: tuple[Mapping[str, Any], ...],
        counts: Mapping[str, int],
    ) -> Iterator[tuple[tuple[str, ...], tuple[Mapping[str, Any], ...]]]:
        if node in terminals:
            yield edge_ids, edges
            return
        for edge in sorted(adjacency.get(node, []), key=lambda item: item["id"]):
            if edge.get("non_executable_against") == "mock":
                continue
            edge_id = edge["id"]
            if edge_id in cyclic and counts.get(edge_id, 0) >= 1:
                continue
            next_counts = dict(counts)
            if edge_id in cyclic:
                next_counts[edge_id] = next_counts.get(edge_id, 0) + 1
            yield from walk(
                edge["to"], edge_ids + (edge_id,), edges + (edge,), next_counts
            )

    found = [
        item
        for start in graph["start_nodes"]
        for item in walk(start, (), (), {})
    ]
    yield from sorted(found, key=lambda item: item[0])


def _goal_facts(spec: EligibleCellSpec) -> dict[str, Any]:
    cards = spec.fixture_bindings.cards
    facts: dict[str, Any] = {
        "card_last_four": cards[0],
        "account_last_four": spec.fixture_bindings.accounts[0],
        "amount_type": "statement_balance",
        "date": "due_date",
        "knowledge_evidence": _knowledge_evidence(spec.cell.knowledge_level),
    }
    if "j1-fetch-options-select-card" in spec.edge_ids:
        facts["initial_card_last_four"] = cards[0]
        facts["final_card_last_four"] = cards[1]
    if "j1-submit-handle-failure" in spec.edge_ids:
        facts.update(
            amount_type="custom",
            amount=LARGE_PAYMENT_THRESHOLD + 1000.0,
            expected_outcome="submission_failure_reported_truthfully",
        )
    complication = spec.cell.complication
    if complication == "underspecification":
        facts["disclosure_style"] = "one_fact_at_a_time"
    elif complication == "mid-conversation-correction":
        facts["correction"] = {
            "parameter": "amount_type",
            "from": "statement_balance",
            "to": "minimum_due",
        }
    elif complication == "false-premise":
        card = next(card for card in CARDS if card.last_four == cards[0])
        facts["false_premise"] = {
            "card_last_four": card.last_four,
            "claimed_balance_state": "no_balance",
            "actual_current_balance": card.current_balance,
        }
    elif complication == "out-of-scope-drift":
        facts["transient_out_of_scope_intent"] = "change_autopay"
    elif complication == "channel-noise":
        facts["recovery_requirement"] = "material_channel_noise"
    elif complication == "ambiguous-reference":
        facts["ambiguous_card_reference"] = "Freedom"
    elif complication == "goal-shift":
        replacement = _payment_instruction(facts)
        original = dict(replacement)
        original["amount_type"] = (
            "minimum_due"
            if replacement["amount_type"] != "minimum_due"
            else "statement_balance"
        )
        original.pop("amount", None)
        facts["goal_shift"] = {
            "abandonment": "explicit",
            "original_payment_instruction": original,
            "replacement_payment_instruction": replacement,
            "state_transition": "discard-abandoned-instruction",
        }
    elif complication == "multi-intent-turn":
        first = _payment_instruction(facts)
        second = dict(first)
        second["amount_type"] = (
            "minimum_due"
            if first["amount_type"] != "minimum_due"
            else "statement_balance"
        )
        second.pop("amount", None)
        facts["payment_instructions_in_one_turn"] = [first, second]
    return facts


def _payment_instruction(facts: Mapping[str, Any]) -> dict[str, Any]:
    instruction = {
        "card_last_four": facts["card_last_four"],
        "account_last_four": facts["account_last_four"],
        "amount_type": facts["amount_type"],
        "date": facts["date"],
    }
    if "amount" in facts:
        instruction["amount"] = facts["amount"]
    return instruction


def _knowledge_evidence(level: str) -> dict[str, str]:
    if level == "low":
        return {"kind": "material_fluency_gap", "referent": "payment_amount_type"}
    if level == "medium":
        return {"kind": "relies_on_agent_for_rule", "rule": "explicit_confirmation"}
    return {"kind": "states_rule_unprompted", "rule": "explicit_confirmation"}


def _required_checks(
    spec: EligibleCellSpec,
) -> tuple[tuple[ToolAssertion, ...], tuple[str, ...]]:
    assertions: dict[str, ToolAssertion] = {
        "amount_in_options": ToolAssertion("amount_in_options"),
        "validated_submit": ToolAssertion(
            "validated_submit",
            {"submit": "AddOneTimePayment", "validate": "AddValidateOneTimePayment"},
        ),
    }
    if "j1-fetch-options-select-card" in spec.edge_ids:
        assertions["refetch_after_card_switch"] = ToolAssertion(
            "refetch_after_card_switch"
        )
    criteria: set[str] = set()
    if spec.fitness_entry is not None:
        failure = spec.fitness_entry["expected_failure"]
        if failure["source"] == "assertion":
            assertions.setdefault(failure["id"], ToolAssertion(failure["id"]))
        else:
            criteria.add(failure["id"])
    return (
        tuple(assertions[key] for key in sorted(assertions)),
        tuple(sorted(criteria)),
    )
