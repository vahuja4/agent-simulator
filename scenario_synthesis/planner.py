"""Coverage obligation planning and the Slice-2 reconciliation report."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from agentsim.scenario import JOURNEYS

from .blueprint import CoverageCell, canonical_cell_id, canonical_journey_path_id
from .compatibility import prototype_unemittable_pairs, read_historical_quarantine
from .config import create_config_snapshot, load_config
from .contracts import AXIS_ORDER, ContractSet, canonical_sha256, load_reviewed_contracts
from .generator import BLOCKED_COMPLICATIONS, EligibleCellSpec, enumerate_eligible_cell_specs

STATUSES = {"covered", "excluded", "BLOCKED", "UNCOVERED"}


@dataclass(frozen=True)
class Obligation:
    obligation_id: str
    kind: str
    axes: Mapping[str, str]
    status: str
    admitted_scenario_ids: tuple[str, ...] = ()
    exclusion: Mapping[str, Any] | None = None
    blocked_reason: str | None = None
    rejection_event_ids: tuple[str, ...] = ()
    regeneration_exhausted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "axes": dict(self.axes),
            "status": self.status,
            "admitted_scenario_ids": list(self.admitted_scenario_ids),
            "exclusion": None if self.exclusion is None else dict(self.exclusion),
            "blocked_reason": self.blocked_reason,
            "rejection_event_ids": list(self.rejection_event_ids),
            "regeneration_exhausted": self.regeneration_exhausted,
        }


@dataclass(frozen=True)
class ReconciliationRecord:
    pair_id: str
    legacy_policy: str
    legacy_perturbation: str
    classification: str
    reason_code: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "legacy_policy": self.legacy_policy,
            "legacy_perturbation": self.legacy_perturbation,
            "classification": self.classification,
            "reason_code": self.reason_code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CoveragePlan:
    report_id: str
    generated_at: str
    snapshot_hash: str
    config_hash: str
    contract_hashes: Mapping[str, str]
    source_hashes: Mapping[str, str]
    journey_paths: Mapping[str, tuple[str, ...]]
    obligations: tuple[Obligation, ...]
    prototype_reconciliation: tuple[ReconciliationRecord, ...]
    proposed_exclusions: tuple[Mapping[str, Any], ...]
    historical_quarantine: Mapping[str, Any]

    @property
    def eligible_cell_count(self) -> int:
        return sum(item.kind == "eligible-cell" for item in self.obligations)

    @property
    def counts(self) -> dict[str, int]:
        return {
            status: sum(item.status == status for item in self.obligations)
            for status in ("covered", "BLOCKED", "UNCOVERED", "excluded")
        }

    def to_dict(self) -> dict[str, Any]:
        denominators = {
            "eligible_axis": sum(
                item.kind == "axis" and item.status != "excluded" for item in self.obligations
            ),
            "eligible_pair": sum(
                item.kind == "pair" and item.status != "excluded" for item in self.obligations
            ),
            "journey_edge": sum(item.kind == "journey-edge" for item in self.obligations),
            "known_defect": sum(item.kind == "known-defect" for item in self.obligations),
            "eligible_cell": self.eligible_cell_count,
        }
        return {
            "schema_version": 1,
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "snapshot_hash": self.snapshot_hash,
            "config_hash": self.config_hash,
            "contract_hashes": dict(self.contract_hashes),
            "source_hashes": dict(self.source_hashes),
            "journey_paths": {
                path_id: list(edge_ids)
                for path_id, edge_ids in sorted(self.journey_paths.items())
            },
            "denominators": denominators,
            "eligible_cell_count": self.eligible_cell_count,
            "eligible_cell_denominator_scope": (
                "Cells enumerable from the authored J1 graph; J2-J5 graph-dependent "
                "expansions are explicit BLOCKED axis obligations."
            ),
            "obligations": [item.to_dict() for item in self.obligations],
            "aggregate_counts": self.counts,
            "admitted_counts_by_axis": {},
            "admitted_counts_by_fitness_target": {},
            "detection_unproven": {"count": 0, "cell_ids": []},
            "curated_distribution": {
                "baseline_reference": "docs/plans/phase-4.5-spec-input.md#library-budget",
                "scenario_count": 13,
                "complication": {"none": 9, "non_none": 4},
            },
            "synthesized_distribution": {"scenario_count": 0},
            "prototype_eligibility_reconciliation": [
                item.to_dict() for item in self.prototype_reconciliation
            ],
            "proposed_exclusions": [dict(item) for item in self.proposed_exclusions],
            "historical_quarantine": dict(self.historical_quarantine),
            "completion_claim_conditions": [
                {
                    "condition": 1,
                    "passed": True,
                    "evidence": "prototype_eligibility_reconciliation",
                },
                *(
                    {"condition": number, "passed": False, "evidence": None}
                    for number in range(2, 6)
                ),
            ],
        }


def build_plan(
    *,
    report_id: str = "slice-2-first-plan",
    generated_at: str | None = None,
    contracts: ContractSet | None = None,
) -> CoveragePlan:
    contracts = contracts or load_reviewed_contracts()
    config = load_config()
    snapshot = create_config_snapshot(config=config, contracts=contracts)
    timestamp = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    specs = enumerate_eligible_cell_specs(contracts=contracts)
    axis_values = _axis_values(contracts, specs)
    reviewed_exclusions = _reviewed_exclusions(contracts)
    obligations: list[Obligation] = []
    obligations.extend(_axis_obligations(axis_values, specs))
    pair_obligations, proposed = _pair_obligations(
        axis_values, specs, reviewed_exclusions
    )
    obligations.extend(pair_obligations)
    obligations.extend(_edge_obligations(contracts, specs))
    obligations.extend(_defect_obligations(contracts, specs))
    obligations.extend(_cell_obligations(specs))
    reconciled = tuple(
        ReconciliationRecord(
            pair_id=f"legacy-policy={policy}|legacy-perturbation={perturbation}",
            legacy_policy=policy,
            legacy_perturbation=perturbation,
            classification="excluded-with-adr-0004-code",
            reason_code="approved-contract-contradiction",
            reason=(
                f"{perturbation} is a validation outcome/procedure branch, not one of "
                "the nine Complication values under ADR 0005."
            ),
        )
        for policy, perturbation in prototype_unemittable_pairs()
    )
    graph_hash = canonical_sha256(contracts.graph)
    historical = read_historical_quarantine().to_dict()
    return CoveragePlan(
        report_id=report_id,
        generated_at=timestamp,
        snapshot_hash=snapshot.sha256,
        config_hash=config.sha256,
        contract_hashes=contracts.hashes,
        source_hashes={
            "journey_graph": graph_hash,
            "fixture": snapshot.content["fixture"]["sha256"],
            **{f"contract:{key}": value for key, value in contracts.hashes.items()},
        },
        journey_paths={
            canonical_journey_path_id(str(contracts.graph["journey"]), spec.edge_ids): spec.edge_ids
            for spec in specs
        },
        obligations=tuple(
            sorted(obligations, key=lambda item: (item.kind, item.obligation_id))
        ),
        prototype_reconciliation=reconciled,
        proposed_exclusions=tuple(sorted(proposed, key=lambda item: item["pair_id"])),
        historical_quarantine=historical,
    )


def write_plan_report(
    output_root: str | Path,
    *,
    report_id: str = "slice-2-first-plan",
    generated_at: str | None = None,
) -> Path:
    plan = build_plan(report_id=report_id, generated_at=generated_at)
    bundle = Path(output_root) / report_id
    bundle.mkdir(parents=True, exist_ok=False)
    coverage = plan.to_dict()
    (bundle / "coverage.json").write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (bundle / "coverage.md").write_text(_markdown(coverage), encoding="utf-8")
    snapshot = create_config_snapshot(destination=bundle / "config-snapshot.yaml")
    if snapshot.sha256 != plan.snapshot_hash:
        raise RuntimeError("configuration changed while writing the plan report")
    return bundle


def _axis_values(
    contracts: ContractSet, specs: tuple[EligibleCellSpec, ...]
) -> dict[str, tuple[str, ...]]:
    graph = contracts.graph
    path_values = tuple(
        sorted(
            {
                canonical_journey_path_id(str(graph["journey"]), spec.edge_ids)
                for spec in specs
            }
        )
    )
    targets = contracts.contracts["fitness-targets"].content["targets"]
    return {
        "journey-path": path_values,
        "persona-archetype": tuple(
            sorted(item["id"] for item in contracts.contracts["persona-archetypes"].content["archetypes"])
        ),
        "knowledge-level": ("high", "low", "medium"),
        "complication": tuple(
            sorted(item["id"] for item in contracts.contracts["complication-applicability"].content["complications"])
        ),
        "fixture-state-class": tuple(
            sorted(item["id"] for item in contracts.contracts["fixture-state-classes"].content["classes"])
        ),
        "fitness-target": ("none",) + tuple(
            sorted(_fitness_value(item) for item in targets)
        ),
    }


def _cell_axes(cell: CoverageCell) -> dict[str, str]:
    return {
        "journey-path": cell.journey_path_id,
        "persona-archetype": cell.persona_archetype,
        "knowledge-level": cell.knowledge_level,
        "complication": cell.complication,
        "fixture-state-class": cell.fixture_state_class_id,
        "fitness-target": (
            "none"
            if cell.fitness_target_id is None
            else f"{cell.fitness_target_id}-{cell.fitness_shape_id}"
        ),
    }


def _fitness_value(target: Mapping[str, Any]) -> str:
    return f"{target['target_id']}-{target['shape_id']}"


def _axis_obligations(
    axis_values: Mapping[str, tuple[str, ...]], specs: tuple[EligibleCellSpec, ...]
) -> list[Obligation]:
    result: list[Obligation] = []
    for axis in AXIS_ORDER:
        for value in axis_values[axis]:
            support = [spec for spec in specs if _cell_axes(spec.cell)[axis] == value]
            unblocked = [spec for spec in support if spec.blocked_reason is None]
            reason = None
            status = "UNCOVERED"
            if not unblocked:
                status = "BLOCKED"
                reason = _no_support_reason(axis, value, support)
            result.append(
                Obligation(
                    obligation_id=f"axis:{axis}={value}",
                    kind="axis",
                    axes={axis: value},
                    status=status,
                    blocked_reason=reason,
                )
            )
    authored_journey = "J1"
    for journey in JOURNEYS:
        if journey == authored_journey:
            continue
        result.append(
            Obligation(
                obligation_id=f"axis:journey-path:{journey}:graph-not-authored",
                kind="axis",
                axes={"journey": journey, "journey-path": "graph-not-authored"},
                status="BLOCKED",
                blocked_reason=(
                    f"{journey} journey graph is not authored in Slice 2; path, edge, "
                    "pair, and cell expansions cannot be enumerated without inventing IDs."
                ),
            )
        )
    return result


def _reviewed_exclusions(contracts: ContractSet) -> dict[tuple[str, str, str, str], Mapping[str, Any]]:
    return {
        (item["axis_a"], item["value_a"], item["axis_b"], item["value_b"]): item
        for item in contracts.contracts["pair-exclusions"].content["exclusions"]
    }


def _pair_obligations(
    axis_values: Mapping[str, tuple[str, ...]],
    specs: tuple[EligibleCellSpec, ...],
    reviewed: Mapping[tuple[str, str, str, str], Mapping[str, Any]],
) -> tuple[list[Obligation], list[Mapping[str, Any]]]:
    obligations: list[Obligation] = []
    proposed: list[Mapping[str, Any]] = []
    for axis_a, axis_b in itertools.combinations(AXIS_ORDER, 2):
        for value_a in axis_values[axis_a]:
            for value_b in axis_values[axis_b]:
                pair_id = f"pair:{axis_a}={value_a}|{axis_b}={value_b}"
                axes = {axis_a: value_a, axis_b: value_b}
                exclusion = reviewed.get((axis_a, value_a, axis_b, value_b))
                if exclusion is not None:
                    obligations.append(
                        Obligation(pair_id, "pair", axes, "excluded", exclusion=exclusion)
                    )
                    continue
                support = [
                    spec
                    for spec in specs
                    if all(_cell_axes(spec.cell)[axis] == value for axis, value in axes.items())
                ]
                unblocked = [spec for spec in support if spec.blocked_reason is None]
                if unblocked:
                    obligations.append(Obligation(pair_id, "pair", axes, "UNCOVERED"))
                    continue
                reason = _no_support_reason("pair", pair_id, support)
                obligations.append(
                    Obligation(pair_id, "pair", axes, "BLOCKED", blocked_reason=reason)
                )
                proposal = _proposed_exclusion(axis_a, value_a, axis_b, value_b, support)
                if proposal is not None:
                    proposed.append(proposal)
    return obligations, proposed


def _edge_obligations(
    contracts: ContractSet, specs: tuple[EligibleCellSpec, ...]
) -> list[Obligation]:
    result: list[Obligation] = []
    for edge in contracts.graph["edges"]:
        blocked = edge.get("non_executable_against") == "mock"
        result.append(
            Obligation(
                obligation_id=f"edge:{edge['id']}",
                kind="journey-edge",
                axes={"journey-edge": edge["id"]},
                status="BLOCKED" if blocked else "UNCOVERED",
                blocked_reason=(
                    "The approved edge is declared non-executable against the current mock."
                    if blocked else None
                ),
            )
        )
    return result


def _defect_obligations(
    contracts: ContractSet, specs: tuple[EligibleCellSpec, ...]
) -> list[Obligation]:
    result: list[Obligation] = []
    for target in contracts.contracts["fitness-targets"].content["targets"]:
        value = _fitness_value(target)
        support = [spec for spec in specs if _cell_axes(spec.cell)["fitness-target"] == value]
        blocked = not any(spec.blocked_reason is None for spec in support)
        result.append(
            Obligation(
                obligation_id=f"defect:{value}",
                kind="known-defect",
                axes={"fitness-target": value},
                status="BLOCKED" if blocked else "UNCOVERED",
                blocked_reason=(
                    _no_support_reason("fitness-target", value, support) if blocked else None
                ),
            )
        )
    return result


def _cell_obligations(specs: tuple[EligibleCellSpec, ...]) -> list[Obligation]:
    return [
        Obligation(
            obligation_id=canonical_cell_id(spec.cell),
            kind="eligible-cell",
            axes=_cell_axes(spec.cell),
            status="BLOCKED" if spec.blocked_reason else "UNCOVERED",
            blocked_reason=spec.blocked_reason,
        )
        for spec in specs
    ]


def _no_support_reason(
    axis: str, value: str, support: list[EligibleCellSpec]
) -> str:
    if support:
        reasons = sorted({spec.blocked_reason for spec in support if spec.blocked_reason})
        return "; ".join(reason for reason in reasons if reason)
    if axis == "fitness-target" or any(
        target in value
        for target in (
            "d4-default", "d6-default", "d7-default",
        )
    ):
        return (
            "No reviewed journey graph and fixture-state classes are available for this "
            "Fitness target's declared Journey/applicability."
        )
    return (
        "The reviewed applicability contracts permit no eligible cell for this obligation, "
        "but pair-exclusions.yaml has no reviewed ADR 0004 entry."
    )


def _proposed_exclusion(
    axis_a: str,
    value_a: str,
    axis_b: str,
    value_b: str,
    support: list[EligibleCellSpec],
) -> Mapping[str, Any] | None:
    if support:
        return None
    pair = {axis_a, axis_b}
    if "journey-path" not in pair and pair not in (
        {"complication", "fixture-state-class"},
        {"fitness-target", "fixture-state-class"},
    ):
        return None
    reason_code = (
        "fixture-domain-impossibility"
        if pair == {"journey-path", "fixture-state-class"}
        else "approved-axis-non-applicability"
    )
    return {
        "pair_id": f"pair:{axis_a}={value_a}|{axis_b}={value_b}",
        "axis_a": axis_a,
        "value_a": value_a,
        "axis_b": axis_b,
        "value_b": value_b,
        "reason_code": reason_code,
        "rationale": (
            "Derived from reviewed graph/axis applicability; requires human review and an "
            "entry in pair-exclusions.yaml before it can be excluded."
        ),
    }


def _markdown(coverage: Mapping[str, Any]) -> str:
    counts = coverage["aggregate_counts"]
    blocked = [item for item in coverage["obligations"] if item["status"] == "BLOCKED"]
    lines = [
        f"# Coverage plan: {coverage['report_id']}",
        "",
        f"Authoritative eligible-cell count: **{coverage['eligible_cell_count']}**.",
        "",
        "## Status counts",
        "",
        "| Status | Count |",
        "|---|---:|",
        *[f"| {status} | {counts[status]} |" for status in ("covered", "BLOCKED", "UNCOVERED", "excluded")],
        "",
        "## BLOCKED obligations",
        "",
        "| Obligation ID | Kind | Reason |",
        "|---|---|---|",
        *[
            f"| `{item['obligation_id']}` | {item['kind']} | {item['blocked_reason']} |"
            for item in blocked
        ],
        "",
        "## Prototype eligibility reconciliation",
        "",
        "| Legacy pair | Classification | ADR 0004 code | Reason |",
        "|---|---|---|---|",
        *[
            f"| `{item['pair_id']}` | {item['classification']} | {item['reason_code']} | {item['reason']} |"
            for item in coverage["prototype_eligibility_reconciliation"]
        ],
        "",
        "## Proposed exclusions (not yet reviewed)",
        "",
        "| Pair | ADR 0004 reason code |",
        "|---|---|",
        *[
            f"| `{item['pair_id']}` | {item['reason_code']} |"
            for item in coverage["proposed_exclusions"]
        ],
        "",
        "Historical prototype counts are reconciliation context only and are not denominators.",
        "",
    ]
    return "\n".join(lines)
