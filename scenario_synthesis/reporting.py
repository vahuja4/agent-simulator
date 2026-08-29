"""Fail-closed reporting over the persisted synthesis lifecycle state."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .candidate import CandidateError, load_candidate
from .config import create_config_snapshot, load_config
from .contracts import ROOT, canonical_sha256, load_reviewed_contracts
from .evidence import (
    EvidenceReferenceError,
    atomic_json,
    atomic_text,
    evidence_reference,
    sha256_file,
    validate_evidence_reference,
)
from .ledger import (
    LedgerError,
    RejectionLedger,
    qualification_admission_is_invalidated,
)
from .planner import Obligation, build_obligation_inventory, coverage_cell_axes
from .qualification import _validate_admission_evidence

DECISION_PATHS = (
    "docs/adrs/0002-use-constrained-interaction-coverage-for-synthesis.md",
    "docs/adrs/0004-default-pairs-to-eligible-with-reviewed-exclusions.md",
    "docs/adrs/0005-use-a-closed-complication-taxonomy.md",
    "docs/adrs/0007-close-the-phase-4.5-design-frontier-with-defaults.md",
    "docs/plans/phase-4.5-spec-input.md",
)


class ReportingError(RuntimeError):
    """Persisted state cannot support a trustworthy report."""


def generate_coverage_report(
    output_root: str | Path,
    *,
    report_id: str = "slice-4-current",
    generated_at: str | None = None,
    repository_root: str | Path = ROOT,
) -> Path:
    root = Path(output_root)
    coverage = build_coverage(
        root,
        report_id=report_id,
        generated_at=generated_at,
        repository_root=repository_root,
    )
    bundle = root / "reports" / report_id
    bundle.mkdir(parents=True, exist_ok=True)
    atomic_json(bundle / "coverage.json", coverage)
    atomic_text(bundle / "coverage.md", render_coverage_markdown(coverage))
    return bundle


def build_coverage(
    output_root: str | Path,
    *,
    report_id: str = "slice-4-current",
    generated_at: str | None = None,
    repository_root: str | Path = ROOT,
) -> dict[str, Any]:
    """Compute current coverage without consulting Historical quarantine."""
    output_root = Path(output_root)
    repository_root = Path(repository_root)
    contracts = load_reviewed_contracts(root=repository_root)
    config = load_config(repository_root / "scenario_synthesis/config.yaml", root=repository_root)
    snapshot = create_config_snapshot(
        config=config, contracts=contracts, root=repository_root
    )
    inventory = build_obligation_inventory(contracts=contracts)
    valid_cells = {
        obligation.obligation_id: obligation
        for obligation in inventory.obligations
        if obligation.kind == "eligible-cell"
    }
    ledger_records, ledger_error = _ledger_records(output_root)
    if ledger_error is None:
        admissions, invalid_admissions = _validated_admissions(
            output_root, contracts, config, valid_cells, ledger_records
        )
    else:
        admissions = []
        invalid_admissions = [{
            "candidate_id": "<lifecycle>",
            "reason": "invalid-rejection-ledger",
        }]
    ledger_exists = (output_root / "ledger/rejections.jsonl").is_file()
    stale_ledger_event_ids = [
        str(item["event_id"])
        for item in ledger_records
        if item.get("contract_hashes") != contracts.hashes
    ]
    ledger_trusted = (
        ledger_exists and ledger_error is None and not stale_ledger_event_ids
    )
    trusted_ledger_records = ledger_records if ledger_trusted else ()
    exhaustion = (
        set()
        if not ledger_trusted
        else _exhaustion(trusted_ledger_records, output_root)
    )

    rendered = [
        _apply_state(item, admissions, exhaustion, trusted_ledger_records)
        for item in inventory.obligations
    ]
    counts = Counter(item["status"] for item in rendered)
    by_kind: dict[str, dict[str, int]] = {}
    for kind in sorted({item["kind"] for item in rendered}):
        kind_items = [item for item in rendered if item["kind"] == kind]
        by_kind[kind] = {
            status: sum(item["status"] == status for item in kind_items)
            for status in ("covered", "excluded", "BLOCKED", "UNCOVERED")
        }
    stale_reasons = [
        item for item in invalid_admissions if item["reason"] == "contract-hash-mismatch"
    ]
    if ledger_error is not None:
        stale_reasons.append({"reason": "invalid-rejection-ledger", "detail": ledger_error})
    if stale_ledger_event_ids:
        stale_reasons.append(
            {
                "reason": "stale-rejection-ledger-contract-hashes",
                "event_ids": stale_ledger_event_ids,
            }
        )
    eligible_pairs = [
        item for item in rendered if item["kind"] == "pair" and item["status"] != "excluded"
    ]
    eligible_cells = [item for item in rendered if item["kind"] == "eligible-cell"]
    health = _synthesis_health(
        trusted_ledger_records, output_root, ledger_error=ledger_error
    )
    health_trusted = ledger_trusted
    if not health_trusted:
        health["rejection_rates"] = {
            "production": _rate(0, 0),
            "candidate_qualification": _rate(0, 0),
        }
    timestamp = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_id": report_id,
        "generated_at": timestamp,
        "report_status": "stale-evidence" if stale_reasons else "current",
        "stale_reasons": stale_reasons,
        "contract_bindings": {
            "config_hash": config.sha256,
            "contract_hashes": contracts.hashes,
            "snapshot_hash": snapshot.sha256,
            "decision_hashes": {
                path: sha256_file(repository_root / path) for path in DECISION_PATHS
            },
        },
        "coverage_semantics": {
            "acceptance_gate_unit": "eligible-pair",
            "reporting_denominator": "eligible-cell",
            "regeneration_exhausted_status": "UNCOVERED",
        },
        "denominators": {
            "eligible_pair": len(eligible_pairs),
            "excluded_pair": sum(
                item["kind"] == "pair" and item["status"] == "excluded"
                for item in rendered
            ),
            "eligible_cell": len(eligible_cells),
        },
        "aggregate_counts": {
            status: counts[status]
            for status in ("covered", "excluded", "BLOCKED", "UNCOVERED")
        },
        "counts_by_kind": by_kind,
        "obligations": rendered,
        "admissions": admissions,
        "invalid_admissions": invalid_admissions,
        "regeneration_exhaustion": {
            "count": len(exhaustion), "cell_ids": sorted(exhaustion)
        },
        "rejection_ledger": {
            "path": health["path"],
            "exists": health["exists"],
            "valid": health["valid"],
            "error": health["error"],
            "event_count": len(ledger_records),
            "current_contracts": not stale_ledger_event_ids,
            "stale_event_ids": stale_ledger_event_ids,
        },
        "synthesis_health": {
            "trusted": health_trusted,
            "rejection_rates": health["rejection_rates"],
            "regeneration_budget": {
                "post_fitness_replacements_per_cell": 2,
                "exhaustion_trusted": health_trusted,
                "exhausted_cell_count": len(exhaustion),
                "exhausted_cell_ids": sorted(exhaustion),
            },
            "per_side_attribution": health["per_side_attribution"],
        },
        "proposed_exclusions": [
            dict(item) for item in inventory.proposed_exclusions
        ],
    }
    report["content_hash"] = canonical_sha256(report)
    return report


def _validated_admissions(
    root: Path,
    contracts: Any,
    config: Any,
    valid_cells: Mapping[str, Any],
    ledger_records: tuple[Mapping[str, Any], ...],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    admitted: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    for terminal_path in sorted((root / "candidates").glob("candidate-*/terminal.json")):
        candidate_id = terminal_path.parent.name
        try:
            terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid.append({"candidate_id": candidate_id, "reason": "invalid-terminal"})
            continue
        if terminal.get("status") != "admitted":
            continue
        if qualification_admission_is_invalidated(
            ledger_records, str(terminal.get("qualification_id", ""))
        ):
            continue
        try:
            candidate = load_candidate(root, candidate_id)
            qualification_id = str(terminal["qualification_id"])
            admission_path = root / "runs" / qualification_id / "admission.json"
            admission = json.loads(admission_path.read_text(encoding="utf-8"))
            if terminal.get("admission_sha256") != sha256_file(admission_path):
                raise ReportingError("admission-hash-mismatch")
            if admission.get("status") != "admitted":
                raise ReportingError("admission-status-mismatch")
            if (
                admission.get("candidate_id") != candidate_id
                or admission.get("cell_id") != candidate.cell_id
                or admission.get("qualification_id") != qualification_id
            ):
                raise ReportingError("admission-identity-mismatch")
            if candidate.cell_id not in valid_cells:
                raise ReportingError("ineligible-cell")
            if admission.get("contract_hashes") != contracts.hashes:
                raise ReportingError("contract-hash-mismatch")
            production = json.loads((candidate.bundle / "production.json").read_text())
            if production.get("contract_hashes") != contracts.hashes:
                raise ReportingError("contract-hash-mismatch")
            if candidate.blueprint.provenance.config_hash != config.sha256:
                raise ReportingError("config-hash-mismatch")
            evidence = admission.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ReportingError("missing-admission-evidence")
            for reference in evidence:
                _verify_reference(root, reference)
                if str(reference["path"]).endswith(".json") and "episodes/" in str(reference["path"]):
                    episode = json.loads((root / reference["path"]).read_text())
                    for key in ("transcript", "trace", "assertion_results", "judge_rulings"):
                        _verify_reference(root, episode[key])
            _validate_admission_evidence(
                candidate,
                admission_path.parent,
                root,
                config,
                contracts,
                allow_repository_state_drift=True,
            )
            library_path = root / str(terminal["library_path"])
            if not library_path.is_file() or library_path.read_bytes() != candidate.scenario_path.read_bytes():
                raise ReportingError("library-evidence-mismatch")
            admission_ref = evidence_reference(admission_path, root=root)
            admitted.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_ordinal": candidate.ordinal,
                    "production_command_id": production["production_command_id"],
                    "qualification_id": qualification_id,
                    "cell_id": candidate.cell_id,
                    "axes": coverage_cell_axes(candidate.blueprint.cell),
                    "journey_edge_ids": list(candidate.blueprint.journey_edge_ids),
                    "detection_unproven": bool(admission.get("detection_unproven")),
                    "admission_evidence": admission_ref,
                    "qualification_evidence": evidence_reference(
                        root / "runs" / qualification_id / "qualification.json",
                        root=root,
                    ),
                    "production_evidence": evidence_reference(
                        candidate.bundle / "production.json", root=root
                    ),
                    "library_evidence": evidence_reference(library_path, root=root),
                }
            )
        except (CandidateError, ReportingError, KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            invalid.append({"candidate_id": candidate_id, "reason": str(exc)})
    return sorted(admitted, key=lambda item: item["candidate_id"]), invalid


def _verify_reference(root: Path, reference: Mapping[str, Any]) -> None:
    try:
        validate_evidence_reference(reference, root=root)
    except EvidenceReferenceError as exc:
        if str(exc) == "evidence hash mismatch":
            raise ReportingError("admission-evidence-hash-mismatch") from exc
        raise ReportingError(str(exc)) from exc


def _apply_state(
    obligation: Obligation,
    admissions: list[dict[str, Any]],
    exhausted_cells: set[str],
    ledger_records: tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    matched: list[dict[str, Any]] = []
    if obligation.status not in {"excluded", "BLOCKED"}:
        for admission in admissions:
            axes = admission["axes"]
            if obligation.kind in {"axis", "pair"} and all(
                axes.get(key) == value for key, value in obligation.axes.items()
            ):
                matched.append(admission)
            elif obligation.kind == "eligible-cell" and admission["cell_id"] == obligation.obligation_id:
                matched.append(admission)
            elif obligation.kind == "journey-edge" and obligation.axes["journey-edge"] in admission["journey_edge_ids"]:
                matched.append(admission)
            elif obligation.kind == "known-defect" and axes["fitness-target"] == obligation.axes["fitness-target"]:
                matched.append(admission)
    exhausted = (
        obligation.kind == "eligible-cell" and obligation.obligation_id in exhausted_cells
    )
    result = obligation.to_dict()
    if matched:
        result["status"] = "covered"
    result["admitted_scenario_ids"] = [item["candidate_id"] for item in matched]
    result["admission_evidence"] = [
        {
            "candidate_id": item["candidate_id"],
            "qualification_id": item["qualification_id"],
            "admission": item["admission_evidence"],
            "library": item["library_evidence"],
        }
        for item in matched
    ]
    if obligation.kind == "eligible-cell":
        result["rejection_event_ids"] = [
            str(item["event_id"])
            for item in ledger_records
            if item["cell_id"] == obligation.obligation_id
        ]
    result["regeneration_exhausted"] = exhausted
    return result


def _ledger_records(root: Path) -> tuple[tuple[Mapping[str, Any], ...], str | None]:
    try:
        return RejectionLedger(root).records(), None
    except LedgerError as exc:
        return (), str(exc)


def _exhaustion(records: tuple[Mapping[str, Any], ...], root: Path) -> set[str]:
    cells = {
        str(item["cell_id"])
        for item in records
        if item["subject_type"] == "candidate" and item["candidate_ordinal"] == 2
    }
    for terminal_path in (root / "candidates").glob("candidate-*/terminal.json"):
        try:
            terminal = json.loads(terminal_path.read_text())
            if terminal.get("status") == "rejected" and terminal.get("regeneration_exhausted"):
                production = json.loads((terminal_path.parent / "production.json").read_text())
                cells.add(str(production["cell_id"]))
        except (OSError, ValueError, KeyError):
            continue
    return cells


def _synthesis_health(
    records: tuple[Mapping[str, Any], ...], root: Path, *, ledger_error: str | None
) -> dict[str, Any]:
    sides: Counter[str] = Counter()
    checks: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        for attribution in record["attribution"]:
            side = str(attribution.get("side", "unknown"))
            check = str(attribution.get("check", "unknown"))
            sides[side] += 1
            checks[side][check] += 1
    successful_productions = len(list((root / "candidates").glob("candidate-*/production.json")))
    failed_productions = sum(item["lifecycle_stage"] == "production" for item in records)
    terminal_candidates = len(list((root / "candidates").glob("candidate-*/terminal.json")))
    rejected_candidates = sum(
        item["subject_type"] == "candidate" and item["lifecycle_stage"] == "qualification"
        for item in records
    )
    return {
        "path": "ledger/rejections.jsonl",
        "exists": (root / "ledger/rejections.jsonl").is_file(),
        "valid": ledger_error is None,
        "error": ledger_error,
        "event_count": len(records),
        "rejection_rates": {
            "production": _rate(failed_productions, failed_productions + successful_productions),
            "candidate_qualification": _rate(rejected_candidates, terminal_candidates),
        },
        "per_side_attribution": {
            side: {"count": count, "checks": dict(sorted(checks[side].items()))}
            for side, count in sorted(sides.items())
        },
    }


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": None if denominator == 0 else numerator / denominator,
    }


def render_coverage_markdown(coverage: Mapping[str, Any]) -> str:
    """Pure deterministic projection of coverage.json."""
    denominators = coverage["denominators"]
    health = coverage["synthesis_health"]
    lines = [
        f"# Coverage report: {coverage['report_id']}",
        "",
        f"Report status: **{coverage['report_status']}**.",
        "",
        f"Eligible cells (reporting denominator): **{denominators['eligible_cell']}**.",
        f"Eligible pairs (acceptance-gate unit): **{denominators['eligible_pair']}**.",
        "",
        "## Status counts by obligation kind",
        "",
        "Unlike obligation kinds are not pooled in this table.",
        "",
        "| Obligation kind | covered | excluded | BLOCKED | UNCOVERED |",
        "|---|---:|---:|---:|---:|",
        *[
            f"| {kind} | {kind_counts['covered']} | {kind_counts['excluded']} | "
            f"{kind_counts['BLOCKED']} | {kind_counts['UNCOVERED']} |"
            for kind, kind_counts in sorted(coverage["counts_by_kind"].items())
        ],
        "",
        "## Regeneration exhaustion",
        "",
        f"Exhausted cells (still UNCOVERED): **{coverage['regeneration_exhaustion']['count']}**.",
        "",
        "## Rejection ledger and synthesis health",
        "",
        f"Ledger events: **{coverage['rejection_ledger']['event_count']}**; "
        f"valid: **{str(coverage['rejection_ledger']['valid']).lower()}**.",
        "",
        "| Rejection rate | Numerator | Denominator | Rate |",
        "|---|---:|---:|---:|",
        *[
            f"| {name} | {rate['numerator']} | {rate['denominator']} | "
            f"{'n/a' if rate['rate'] is None else format(rate['rate'], '.3f')} |"
            for name, rate in sorted(health["rejection_rates"].items())
        ],
        "",
        "### Per-side attribution",
        "",
        "| Side | Attributions | Checks |",
        "|---|---:|---|",
        *(
            [
                f"| {side} | {summary['count']} | "
                + ", ".join(
                    f"{check}={count}"
                    for check, count in summary["checks"].items()
                )
                + " |"
                for side, summary in health["per_side_attribution"].items()
            ]
            or ["| — | 0 | — |"]
        ),
        "",
        "## Gaps",
        "",
    ]
    gaps = [
        item for item in coverage["obligations"]
        if item["status"] in {"BLOCKED", "UNCOVERED"}
    ]
    lines.extend(
        f"- `{item['obligation_id']}` — {item['status']}"
        + (f": {item['blocked_reason']}" if item.get("blocked_reason") else "")
        for item in gaps
    )
    lines.append("")
    return "\n".join(lines)
