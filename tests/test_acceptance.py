from copy import deepcopy
from pathlib import Path

import yaml

from agentsim.acceptance import evaluate_acceptance
from agentsim.types import BatchManifest, BatchRunRecord, FailureRecord


def load_matrix():
    return yaml.safe_load(Path("calibration/phase4_acceptance.yaml").read_text())


def record(key, scenario, *, outcome, metadata, failure=None, degraded=None):
    return BatchRunRecord(
        run_key=key,
        scenario=scenario,
        scenario_source=f"{scenario}.yaml",
        persona_variant="base",
        defect_flags={},
        model="stub",
        seed=0,
        run_id=key,
        status="completed",
        outcome=outcome,
        failures=[failure] if failure else [],
        degraded_checks=degraded or [],
        metadata=metadata,
    )


def passing_manifest(matrix):
    runs = {}
    for row in matrix["recall"]:
        expected = row["expected_failure"]
        key = f"recall-{row['case_id']}"
        runs[key] = record(
            key,
            row["scenario"],
            outcome="fail",
            metadata=dict(row["selector"]),
            failure=FailureRecord(
                expected["source"], expected["id"], 1, "expected failure"
            ),
        )
    for index, scenario in enumerate(matrix["precision"]["required_scenarios"]):
        key = f"precision-{index}"
        runs[key] = record(
            key,
            scenario,
            outcome="pass" if index % 2 == 0 else "task_incomplete",
            metadata={"acceptance_side": "precision"},
        )
    return BatchManifest("acceptance", "now", runs=runs)


def test_matrix_pins_both_d1_shapes_not_either_or():
    matrix = load_matrix()
    rows = {row["case_id"]: row for row in matrix["recall"]}
    assert rows["d1_same_turn"]["expected_failure"] == {
        "source": "assertion", "id": "validated_submit"
    }
    assert rows["d1_at_the_gate"]["expected_failure"] == {
        "source": "judge", "id": "explicit_confirmation"
    }
    assert rows["d1_at_the_gate"]["script"][:1] != rows["d1_same_turn"]["script"][:1]
    assert rows["d1_at_the_gate"]["script"][-1] == "Stop asking and schedule it."


def test_two_sided_acceptance_passes_with_expected_sources_and_clean_precision():
    matrix = load_matrix()
    result = evaluate_acceptance(
        passing_manifest(matrix), matrix, runs_per_scenario=1
    )
    assert result["passed"]
    assert result["recall"]["passed"]
    assert result["precision"]["passed"]


def test_recall_requires_the_named_source():
    matrix = load_matrix()
    manifest = passing_manifest(matrix)
    d2 = next(
        record for record in manifest.runs.values()
        if record.metadata.get("acceptance_case") == "d2_stale_options"
    )
    d2.failures = [FailureRecord("judge", "card_switch_reset", 1, "early judge")]
    result = evaluate_acceptance(manifest, matrix, runs_per_scenario=1)
    assert not result["recall"]["passed"]
    assert any("d2_stale_options" in issue for issue in result["issues"])


def test_mock_precision_rejects_degraded_checks_but_rule_is_matrix_data():
    matrix = load_matrix()
    manifest = passing_manifest(matrix)
    precision = next(
        record for record in manifest.runs.values()
        if record.metadata.get("acceptance_side") == "precision"
    )
    precision.degraded_checks = [{"check": "partial"}]
    failed = evaluate_acceptance(manifest, matrix, runs_per_scenario=1)
    assert not failed["precision"]["passed"]
    assert any("degraded checks" in issue for issue in failed["issues"])

    real_agent_matrix = deepcopy(matrix)
    real_agent_matrix["precision"]["require_zero_degraded"] = False
    allowed = evaluate_acceptance(
        manifest, real_agent_matrix, runs_per_scenario=1
    )
    assert allowed["precision"]["passed"]
