"""Clause-by-clause Phase 4.5 completion evaluation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .contracts import ROOT, load_reviewed_contracts
from .evidence import (
    atomic_json,
    atomic_text,
    evidence_reference,
    sha256_file,
    validate_evidence_reference,
)
from .reporting import generate_coverage_report, render_coverage_markdown

REQUIRED_DEFINITION_TESTS = (
    "goal-shift",
    "multi-intent-turn",
    "out-of-scope-drift",
    "channel-noise",
)


def check_completion(
    output_root: str | Path,
    *,
    report_id: str = "slice-4-current",
    repository_root: str | Path = ROOT,
) -> tuple[Path, dict[str, Any]]:
    output_root = Path(output_root)
    bundle = generate_coverage_report(
        output_root, report_id=report_id, repository_root=repository_root
    )
    coverage = json.loads((bundle / "coverage.json").read_text())
    result = evaluate_completion(
        coverage, output_root=output_root, repository_root=repository_root
    )
    atomic_json(bundle / "completion.json", result)
    atomic_text(bundle / "completion.md", render_completion_markdown(result))
    return bundle, result


def evaluate_completion(
    coverage: Mapping[str, Any],
    *,
    output_root: str | Path,
    repository_root: str | Path = ROOT,
) -> dict[str, Any]:
    output_root = Path(output_root)
    repository_root = Path(repository_root)
    clauses = [
        _eligibility_reconciliation(repository_root, output_root),
        _definition_tests(coverage, output_root),
        _fitness_contracts(coverage),
        _reporting_artifacts(coverage, output_root),
        _curated_suite(output_root, repository_root),
    ]
    gaps = [gap for clause in clauses for gap in clause["gaps"]]
    return {
        "schema_version": 1,
        "claim": "Phase 4.5 completion",
        "passed": all(clause["passed"] for clause in clauses),
        "coverage_report": {
            "report_id": coverage["report_id"],
            "content_hash": coverage["content_hash"],
        },
        "clauses": clauses,
        "gaps": gaps,
    }


def _eligibility_reconciliation(
    repository_root: Path, output_root: Path
) -> dict[str, Any]:
    reviewed_path = output_root / "completion/eligibility-reconciliation.json"
    path = (
        reviewed_path
        if reviewed_path.is_file()
        else repository_root / "synthesized_scenarios/reports/slice-2-closeout-plan/coverage.json"
    )
    gaps: list[str] = []
    evidence: list[Mapping[str, str]] = []
    try:
        record = json.loads(path.read_text())
        contracts = load_reviewed_contracts(root=repository_root)
        baseline_path = repository_root / "synthesized_scenarios/reports/slice-2-closeout-plan/coverage.json"
        baseline = json.loads(baseline_path.read_text())
        if path == reviewed_path and record.get("review_status") != "approved":
            gaps.append("eligibility reconciliation has not received explicit approval")
        if record.get("contract_hashes") != contracts.hashes:
            gaps.append("eligibility reconciliation is stale against reviewed contract hashes")
        if record.get("proposed_exclusions"):
            gaps.append("eligibility reconciliation still contains unreviewed proposed exclusions")
        reconciliation = record.get("prototype_eligibility_reconciliation", [])
        if not reconciliation:
            gaps.append("prototype-unemittable pair reconciliation evidence is absent")
        elif any(
            item.get("classification") not in {
                "excluded-with-adr-0004-code", "BLOCKED", "eligible-and-owed"
            }
            for item in reconciliation
        ):
            gaps.append("eligibility reconciliation contains an unsupported classification")
        expected_pair_ids = {
            item["pair_id"]
            for item in baseline.get("prototype_eligibility_reconciliation", [])
        }
        if {item.get("pair_id") for item in reconciliation} != expected_pair_ids:
            gaps.append("eligibility reconciliation does not classify every committed prototype-unemittable pair")
        evidence.append(
            {
                "path": str(
                    path.relative_to(output_root if path == reviewed_path else repository_root)
                ),
                "sha256": sha256_file(path),
            }
        )
    except (OSError, ValueError, KeyError) as exc:
        gaps.append(f"eligibility reconciliation cannot be verified: {exc}")
    return _clause(1, "Every prototype-unemittable pair is reconciled", gaps, evidence)


def _definition_tests(
    coverage: Mapping[str, Any], output_root: Path
) -> dict[str, Any]:
    admitted_by_complication: dict[str, dict[str, Mapping[str, Any]]] = {}
    for admission in coverage.get("admissions", []):
        admitted_by_complication.setdefault(
            str(admission["axes"]["complication"]), {}
        )[str(admission["candidate_id"])] = admission
    evidence_path = output_root / "completion/definition-tests.json"
    accepted: dict[str, str] = {}
    evidence: list[Mapping[str, str]] = []
    artifact_error: str | None = None
    if evidence_path.is_file():
        try:
            artifact = json.loads(evidence_path.read_text())
            if artifact.get("schema_version") != 1 or not isinstance(artifact.get("tests"), list):
                raise ValueError("definition-test evidence schema is invalid")
            for item in artifact["tests"]:
                reference = item["evidence"]
                validate_evidence_reference(reference, root=output_root)
                complication = str(item["complication"])
                candidate_id = str(item["candidate_id"])
                admission = admitted_by_complication.get(complication, {}).get(candidate_id)
                if (
                    item.get("passed") is True
                    and admission is not None
                    and admission.get("candidate_ordinal") == 0
                    and item.get("candidate_ordinal") == 0
                    and item.get("production_command_id")
                    == admission.get("production_command_id")
                ):
                    accepted[complication] = candidate_id
            evidence.append(evidence_reference(evidence_path, root=output_root))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            artifact_error = str(exc)
    gaps: list[str] = []
    if artifact_error:
        gaps.append(f"definition-test evidence is invalid: {artifact_error}")
    for complication in REQUIRED_DEFINITION_TESTS:
        if not admitted_by_complication.get(complication):
            if complication in {"goal-shift", "multi-intent-turn"}:
                gaps.append(
                    f"{complication}: no admitted synthesized Scenario; pre-pilot J1 graph semantics remain pending"
                )
            else:
                gaps.append(f"{complication}: no admitted synthesized Scenario")
        elif complication not in accepted:
            gaps.append(
                f"{complication}: ordinal-zero first-realization definition test "
                "lacks valid passing evidence"
            )
    return _clause(
        2,
        "Required previously-unpopulated Complications are admitted and definition-tested",
        gaps,
        evidence,
    )


def _fitness_contracts(coverage: Mapping[str, Any]) -> dict[str, Any]:
    gaps: list[str] = []
    if coverage.get("report_status") != "current":
        gaps.append("coverage report contains stale evidence")
    invalid = coverage.get("invalid_admissions", [])
    if invalid:
        gaps.extend(
            f"{item.get('candidate_id', 'unknown')}: admission claim invalid ({item.get('reason', 'unknown')})"
            for item in invalid
        )
    evidence = [
        item["admission_evidence"] for item in coverage.get("admissions", [])
    ]
    return _clause(3, "Every admitted synthesized Scenario holds its fitness contract", gaps, evidence)


def _reporting_artifacts(
    coverage: Mapping[str, Any], output_root: Path
) -> dict[str, Any]:
    gaps: list[str] = []
    ledger = coverage.get("rejection_ledger", {})
    if not ledger.get("exists"):
        gaps.append("append-only rejection ledger has not been produced")
    elif not ledger.get("valid"):
        gaps.append(f"rejection ledger is invalid: {ledger.get('error')}")
    elif ledger.get("current_contracts") is not True:
        gaps.append("rejection ledger is stale against reviewed contract hashes")
    for status in ("covered", "BLOCKED", "UNCOVERED", "excluded"):
        if status not in coverage.get("aggregate_counts", {}):
            gaps.append(f"coverage report does not separate {status}")
    if "regeneration_exhaustion" not in coverage:
        gaps.append("coverage report does not report regeneration exhaustion separately")
    eligible_pairs = [
        item
        for item in coverage.get("obligations", [])
        if item.get("kind") == "pair" and item.get("status") != "excluded"
    ]
    blocked_pairs = sum(item.get("status") == "BLOCKED" for item in eligible_pairs)
    uncovered_pairs = sum(item.get("status") == "UNCOVERED" for item in eligible_pairs)
    other_pairs = sum(
        item.get("status") not in {"covered", "BLOCKED", "UNCOVERED"}
        for item in eligible_pairs
    )
    if blocked_pairs or uncovered_pairs or other_pairs:
        gaps.append(
            "eligible-pair gate incomplete: "
            f"{blocked_pairs} BLOCKED, {uncovered_pairs} UNCOVERED, "
            f"{other_pairs} invalid-status out of {len(eligible_pairs)} eligible pairs"
        )
    report_bundle = output_root / "reports" / str(coverage["report_id"])
    report_path = report_bundle / "coverage.json"
    markdown_path = report_bundle / "coverage.md"
    evidence: list[Mapping[str, str]] = []
    if report_path.is_file():
        persisted = json.loads(report_path.read_text())
        if persisted != coverage:
            gaps.append("persisted coverage report does not match the evaluated report")
        evidence.append(evidence_reference(report_path, root=output_root))
        if not markdown_path.is_file():
            gaps.append("coverage.md has not been produced")
        elif markdown_path.read_text() != render_coverage_markdown(persisted):
            gaps.append("coverage.md is not the projection of persisted coverage.json")
        else:
            evidence.append(evidence_reference(markdown_path, root=output_root))
    else:
        gaps.append("coverage.json has not been produced")
    return _clause(
        4,
        "Rejection ledger, pairwise gate, and separated coverage reporting are produced",
        gaps,
        evidence,
    )


def _curated_suite(output_root: Path, repository_root: Path) -> dict[str, Any]:
    path = output_root / "completion/curated-suite.json"
    gaps: list[str] = []
    evidence: list[Mapping[str, str]] = []
    try:
        record = json.loads(path.read_text())
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repository_root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        if record.get("schema_version") != 1:
            gaps.append("curated-suite evidence schema is invalid")
        if record.get("passed") is not True:
            gaps.append("curated suite evidence does not record a passing run")
        if record.get("repository_revision") != revision:
            gaps.append("curated suite evidence is stale for the current repository revision")
        if record.get("command") != ".venv/bin/python -m pytest":
            gaps.append("curated suite evidence did not run the required full offline suite")
        validate_evidence_reference(record["evidence"], root=output_root)
        evidence.append(evidence_reference(path, root=output_root))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        gaps.append(f"current curated-suite passing evidence is absent or invalid: {exc}")
    return _clause(5, "The curated suite remains green", gaps, evidence)


def _clause(
    number: int,
    condition: str,
    gaps: list[str],
    evidence: list[Mapping[str, str]],
) -> dict[str, Any]:
    return {
        "clause": number,
        "condition": condition,
        "passed": not gaps,
        "evidence": [dict(item) for item in evidence],
        "gaps": gaps,
    }


def render_completion_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 4.5 completion check",
        "",
        f"Overall: **{'PASS' if result['passed'] else 'FAIL'}**.",
        "",
        "| Clause | Result | Condition |",
        "|---:|---|---|",
        *[
            f"| {item['clause']} | {'PASS' if item['passed'] else 'FAIL'} | {item['condition']} |"
            for item in result["clauses"]
        ],
        "",
        "## Gaps",
        "",
        *([f"- {gap}" for gap in result["gaps"]] or ["- None."]),
        "",
    ]
    return "\n".join(lines)
