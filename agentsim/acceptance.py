"""Generic, data-driven recall and precision evaluation for batch artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from .types import BatchManifest, BatchRunRecord

ACCEPTANCE_SCHEMA_VERSION = "1.0"


def _record_value(record: BatchRunRecord, key: str) -> Any:
    if key in record.metadata:
        return record.metadata[key]
    if hasattr(record, key):
        return getattr(record, key)
    return None


def _matches(record: BatchRunRecord, selector: dict[str, Any]) -> bool:
    return all(_record_value(record, key) == value for key, value in selector.items())


def evaluate_acceptance(
    manifest: BatchManifest,
    matrix: dict[str, Any],
    *,
    runs_per_scenario: int,
) -> dict[str, Any]:
    if matrix.get("schema_version") != ACCEPTANCE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported acceptance schema {matrix.get('schema_version')!r}"
        )
    if runs_per_scenario <= 0:
        raise ValueError("runs_per_scenario must be positive")

    issues: list[str] = []
    recall_cases: list[dict[str, Any]] = []
    for expectation in matrix.get("recall", []):
        case_id = str(expectation["case_id"])
        selector = dict(expectation.get("selector", {}))
        expected = dict(expectation["expected_failure"])
        matched = [
            record for record in manifest.runs.values() if _matches(record, selector)
        ]
        satisfying = [
            record
            for record in matched
            if record.status == "completed"
            and record.outcome == "fail"
            and any(
                failure.source == expected.get("source")
                and failure.id == expected.get("id")
                for failure in record.failures
            )
        ]
        errors = [record.run_key for record in matched if record.outcome == "error"]
        passed = bool(satisfying) and not errors
        if not matched:
            issues.append(f"recall {case_id}: no run matched selector {selector}")
        elif not satisfying:
            observed = sorted(
                {
                    f"{failure.source}:{failure.id}"
                    for record in matched
                    for failure in record.failures
                }
            )
            issues.append(
                f"recall {case_id}: expected {expected.get('source')}:{expected.get('id')}; "
                f"observed {observed or ['no matching failure']}"
            )
        if errors:
            issues.append(f"recall {case_id}: harness error in {errors}")
        recall_cases.append(
            {
                "case_id": case_id,
                "passed": passed,
                "matched_runs": sorted(record.run_key for record in matched),
                "satisfying_runs": sorted(record.run_key for record in satisfying),
                "expected_failure": expected,
            }
        )

    precision_spec = dict(matrix.get("precision", {}))
    precision_selector = dict(precision_spec.get("selector", {}))
    precision_runs = [
        record
        for record in manifest.runs.values()
        if _matches(record, precision_selector)
    ]
    allowed = set(precision_spec.get("allowed_outcomes", ["pass", "task_incomplete"]))
    require_zero_degraded = bool(precision_spec.get("require_zero_degraded", False))
    required_scenarios = [str(name) for name in precision_spec.get("required_scenarios", [])]
    precision_issues: list[str] = []

    for record in precision_runs:
        if record.status != "completed":
            precision_issues.append(f"precision run {record.run_key} is not completed")
        elif record.outcome not in allowed:
            precision_issues.append(
                f"precision run {record.run_key} has disallowed outcome {record.outcome}"
            )
        if require_zero_degraded and record.degraded_checks:
            precision_issues.append(
                f"precision run {record.run_key} has degraded checks"
            )

    counts = Counter(record.scenario for record in precision_runs)
    for scenario in required_scenarios:
        if counts[scenario] != runs_per_scenario:
            precision_issues.append(
                f"precision scenario {scenario} has {counts[scenario]} runs; "
                f"expected {runs_per_scenario}"
            )
    unexpected = sorted(set(counts) - set(required_scenarios))
    if required_scenarios and unexpected:
        precision_issues.append(f"precision has unexpected scenarios {unexpected}")
    if not precision_runs:
        precision_issues.append("precision selector matched no runs")

    issues.extend(precision_issues)
    recall_passed = bool(recall_cases) and all(case["passed"] for case in recall_cases)
    precision_passed = not precision_issues
    return {
        "schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "passed": recall_passed and precision_passed,
        "recall": {"passed": recall_passed, "cases": recall_cases},
        "precision": {
            "passed": precision_passed,
            "matched_runs": len(precision_runs),
            "allowed_outcomes": sorted(allowed),
            "require_zero_degraded": require_zero_degraded,
            "scenario_counts": dict(sorted(counts.items())),
            "issues": precision_issues,
        },
        "issues": issues,
    }


def evaluate_batch_acceptance(
    batch_dir: str | Path,
    matrix: dict[str, Any],
    *,
    runs_per_scenario: int,
) -> dict[str, Any]:
    batch_dir = Path(batch_dir)
    manifest = BatchManifest.from_dict(
        json.loads((batch_dir / "manifest.json").read_text())
    )
    result = evaluate_acceptance(
        manifest, matrix, runs_per_scenario=runs_per_scenario
    )
    output = batch_dir / "acceptance.json"
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=batch_dir, delete=False
    )
    try:
        with handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(handle.name, output)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)
    return result
