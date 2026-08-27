from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scenario_synthesis import cli
from scenario_synthesis.candidate import produce_candidate
from scenario_synthesis.completion import evaluate_completion, render_completion_markdown
from scenario_synthesis.contracts import load_reviewed_contracts
from scenario_synthesis.evidence import (
    EvidenceReferenceError,
    atomic_json,
    evidence_reference,
    sha256_file,
    validate_evidence_reference,
)
from scenario_synthesis.generator import generate_blueprints
from scenario_synthesis.ledger import RejectionLedger
from scenario_synthesis.qualification import StubQualificationRunner, qualify_candidate
from scenario_synthesis.realization_provider import StubRealizationProvider
from scenario_synthesis.reporting import build_coverage, render_coverage_markdown


def _targeted_blueprint():
    return next(item for item in generate_blueprints() if item.fitness_target_id)


def _admit(root: Path):
    candidate = produce_candidate(
        _targeted_blueprint(), output_root=root, provider=StubRealizationProvider()
    )
    assert candidate is not None
    result = qualify_candidate(
        candidate.candidate_id,
        output_root=root,
        runner=StubQualificationRunner(),
    )
    assert result.decision.admitted
    return candidate, result


def _contrived_passing_completion_state(tmp_path: Path) -> dict:
    coverage = build_coverage(tmp_path, report_id="contrived-pass")
    coverage["admissions"] = [
        {
            "candidate_id": f"candidate-{index}",
            "candidate_ordinal": 0,
            "production_command_id": f"production-{index}",
            "axes": {"complication": complication},
            "admission_evidence": {
                "path": f"admission-{index}.json",
                "sha256": "a" * 64,
            },
        }
        for index, complication in enumerate(
            ("goal-shift", "multi-intent-turn", "out-of-scope-drift", "channel-noise")
        )
    ]
    for obligation in coverage["obligations"]:
        if obligation["kind"] == "pair" and obligation["status"] != "excluded":
            obligation["status"] = "covered"
    coverage["rejection_ledger"].update(
        exists=True, valid=True, current_contracts=True
    )
    coverage["invalid_admissions"] = []
    bundle = tmp_path / "reports/contrived-pass"
    bundle.mkdir(parents=True)
    atomic_json(bundle / "coverage.json", coverage)
    (bundle / "coverage.md").write_text(render_coverage_markdown(coverage))

    evidence_dir = tmp_path / "completion/evidence"
    evidence_dir.mkdir(parents=True)
    definition_tests = []
    for index, complication in enumerate(
        ("goal-shift", "multi-intent-turn", "out-of-scope-drift", "channel-noise")
    ):
        path = evidence_dir / f"definition-{index}.txt"
        path.write_text("passed\n")
        definition_tests.append(
            {
                "complication": complication,
                "candidate_id": f"candidate-{index}",
                "candidate_ordinal": 0,
                "production_command_id": f"production-{index}",
                "passed": True,
                "evidence": evidence_reference(path, root=tmp_path),
            }
        )
    atomic_json(
        tmp_path / "completion/definition-tests.json",
        {"schema_version": 1, "tests": definition_tests},
    )
    baseline = json.loads(
        Path("synthesized_scenarios/reports/slice-2-closeout-plan/coverage.json").read_text()
    )
    atomic_json(
        tmp_path / "completion/eligibility-reconciliation.json",
        {
            "schema_version": 1,
            "review_status": "approved",
            "contract_hashes": load_reviewed_contracts().hashes,
            "prototype_eligibility_reconciliation": baseline[
                "prototype_eligibility_reconciliation"
            ],
            "proposed_exclusions": [],
        },
    )
    suite_log = evidence_dir / "curated-suite.txt"
    suite_log.write_text("suite passed\n")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    atomic_json(
        tmp_path / "completion/curated-suite.json",
        {
            "schema_version": 1,
            "passed": True,
            "repository_revision": revision,
            "command": ".venv/bin/python -m pytest",
            "evidence": evidence_reference(suite_log, root=tmp_path),
        },
    )
    return coverage


def test_report_cli_writes_authoritative_json_and_markdown_projection(
    tmp_path: Path, capsys
) -> None:
    assert cli.main(
        [
            "report",
            "--output-root",
            str(tmp_path),
            "--report-id",
            "current",
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    bundle = tmp_path / "reports/current"
    coverage = json.loads((bundle / "coverage.json").read_text())

    assert result["status"] == "reported"
    assert coverage["denominators"]["eligible_cell"] == 4368
    assert coverage["denominators"]["eligible_pair"] == 374
    assert coverage["denominators"]["excluded_pair"] == 32
    assert coverage["aggregate_counts"]["covered"] == 0
    assert coverage["aggregate_counts"]["BLOCKED"] > 0
    assert coverage["aggregate_counts"]["UNCOVERED"] > 0
    assert coverage["aggregate_counts"]["excluded"] == 32
    assert coverage["regeneration_exhaustion"]["count"] == 0
    markdown = (bundle / "coverage.md").read_text()
    assert markdown == render_coverage_markdown(coverage)
    assert "Status counts by obligation kind" in markdown
    assert "| eligible-cell |" in markdown
    assert "| pair |" in markdown
    assert "Unlike obligation kinds are not pooled" in markdown


def test_admitted_scenario_covers_its_cell_and_pairs_with_hashed_evidence(
    tmp_path: Path,
) -> None:
    candidate, result = _admit(tmp_path)
    coverage = build_coverage(tmp_path, generated_at="2026-08-27T00:00:00Z")
    cell = next(
        item for item in coverage["obligations"]
        if item["obligation_id"] == candidate.cell_id
    )

    assert cell["status"] == "covered"
    assert cell["admitted_scenario_ids"] == [candidate.candidate_id]
    assert cell["admission_evidence"][0]["qualification_id"] == result.qualification_id
    assert cell["admission_evidence"][0]["admission"]["sha256"] == sha256_file(
        result.bundle / "admission.json"
    )
    admission = coverage["admissions"][0]
    assert admission["candidate_ordinal"] == 0
    assert admission["production_command_id"]
    assert admission["production_evidence"]["sha256"] == sha256_file(
        candidate.bundle / "production.json"
    )
    assert any(
        item["kind"] == "pair"
        and item["status"] == "covered"
        and candidate.candidate_id in item["admitted_scenario_ids"]
        for item in coverage["obligations"]
    )


def test_partial_qualification_does_not_cover_any_claim(tmp_path: Path) -> None:
    candidate = produce_candidate(
        _targeted_blueprint(), output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert candidate is not None

    coverage = build_coverage(tmp_path)

    assert coverage["admissions"] == []
    assert coverage["aggregate_counts"]["covered"] == 0


def test_hash_mismatched_admission_evidence_downgrades_coverage(
    tmp_path: Path,
) -> None:
    candidate, result = _admit(tmp_path)
    admission = json.loads((result.bundle / "admission.json").read_text())
    episode = tmp_path / admission["evidence"][0]["path"]
    payload = json.loads(episode.read_text())
    transcript = tmp_path / payload["transcript"]["path"]
    transcript.write_text("{}\n")

    coverage = build_coverage(tmp_path)
    cell = next(
        item for item in coverage["obligations"]
        if item["obligation_id"] == candidate.cell_id
    )

    assert cell["status"] == "UNCOVERED"
    assert coverage["invalid_admissions"] == [
        {
            "candidate_id": candidate.candidate_id,
            "reason": "admission-evidence-hash-mismatch",
        }
    ]
    bundle = tmp_path / "reports/hash-mismatch"
    coverage["report_id"] = "hash-mismatch"
    bundle.mkdir(parents=True)
    atomic_json(bundle / "coverage.json", coverage)
    completion = evaluate_completion(coverage, output_root=tmp_path)
    assert completion["clauses"][2]["passed"] is False


def test_stale_contract_hashes_mark_report_stale_and_downgrade_claim(
    tmp_path: Path,
) -> None:
    candidate, result = _admit(tmp_path)
    admission_path = result.bundle / "admission.json"
    admission = json.loads(admission_path.read_text())
    admission["contract_hashes"]["fitness-targets"] = "0" * 64
    atomic_json(admission_path, admission)
    terminal_path = candidate.bundle / "terminal.json"
    terminal = json.loads(terminal_path.read_text())
    terminal["admission_sha256"] = sha256_file(admission_path)
    atomic_json(terminal_path, terminal)

    coverage = build_coverage(tmp_path)

    assert coverage["report_status"] == "stale-evidence"
    assert coverage["admissions"] == []
    assert coverage["invalid_admissions"][0]["reason"] == "contract-hash-mismatch"


def test_exhaustion_remains_uncovered_and_health_attributes_each_side(
    tmp_path: Path,
) -> None:
    blueprint = _targeted_blueprint()
    candidate = produce_candidate(
        blueprint, output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert candidate is not None
    for _ in range(3):
        result = qualify_candidate(
            candidate.candidate_id,
            output_root=tmp_path,
            runner=StubQualificationRunner(
                outcomes={("defects-off", 0): "unexpected-failure"}
            ),
            replacement_provider=StubRealizationProvider(),
        )
        if result.replacement is not None:
            candidate = result.replacement

    coverage = build_coverage(tmp_path)
    cell = next(
        item for item in coverage["obligations"]
        if item["obligation_id"] == blueprint.cell_id
    )

    assert cell["status"] == "UNCOVERED"
    assert cell["regeneration_exhausted"] is True
    assert coverage["regeneration_exhaustion"] == {
        "count": 1,
        "cell_ids": [blueprint.cell_id],
    }
    health = coverage["synthesis_health"]
    assert health["rejection_rates"]["candidate_qualification"]["rate"] == 1.0
    assert health["per_side_attribution"]["defects-off"]["count"] == 3
    assert health["regeneration_budget"]["exhausted_cell_count"] == 1


def test_check_completion_fails_honestly_with_clause_evidence_and_graph_gaps(
    tmp_path: Path, capsys
) -> None:
    assert cli.main(
        [
            "check-completion",
            "--output-root",
            str(tmp_path),
            "--report-id",
            "completion-check",
        ]
    ) == 1
    output = json.loads(capsys.readouterr().out)
    result_path = tmp_path / "reports/completion-check/completion.json"
    result = json.loads(result_path.read_text())

    assert output["status"] == "fail"
    assert [item["clause"] for item in result["clauses"]] == [1, 2, 3, 4, 5]
    assert result["clauses"][0]["passed"] is False
    assert result["clauses"][1]["passed"] is False
    assert result["clauses"][2]["passed"] is True
    assert result["clauses"][3]["passed"] is False
    assert result["clauses"][4]["passed"] is False
    assert any("pre-pilot J1 graph semantics remain pending" in gap for gap in result["gaps"])
    assert any("no admitted synthesized Scenario" in gap for gap in result["gaps"])
    assert (
        tmp_path / "reports/completion-check/completion.md"
    ).read_text() == render_completion_markdown(result)


def test_completion_can_pass_only_with_all_five_clause_evidence(
    tmp_path: Path,
) -> None:
    coverage = _contrived_passing_completion_state(tmp_path)

    result = evaluate_completion(coverage, output_root=tmp_path)

    assert result["passed"] is True
    assert [item["passed"] for item in result["clauses"]] == [True] * 5
    assert result["gaps"] == []
    assert {
        item["path"] for item in result["clauses"][3]["evidence"]
    } == {
        "reports/contrived-pass/coverage.json",
        "reports/contrived-pass/coverage.md",
    }


@pytest.mark.parametrize("pair_status", ["BLOCKED", "UNCOVERED"])
def test_completion_fails_when_any_eligible_pair_is_not_covered(
    tmp_path: Path, pair_status: str
) -> None:
    coverage = _contrived_passing_completion_state(tmp_path)
    pair = next(
        item
        for item in coverage["obligations"]
        if item["kind"] == "pair" and item["status"] == "covered"
    )
    pair["status"] = pair_status
    bundle = tmp_path / "reports/contrived-pass"
    atomic_json(bundle / "coverage.json", coverage)
    (bundle / "coverage.md").write_text(render_coverage_markdown(coverage))

    result = evaluate_completion(coverage, output_root=tmp_path)

    clause = result["clauses"][3]
    assert clause["passed"] is False
    assert any(
        f"1 {pair_status}" in gap and "eligible-pair gate incomplete" in gap
        for gap in clause["gaps"]
    )


def test_definition_test_rejects_a_later_candidate_ordinal(tmp_path: Path) -> None:
    coverage = _contrived_passing_completion_state(tmp_path)
    admission = next(
        item
        for item in coverage["admissions"]
        if item["axes"]["complication"] == "goal-shift"
    )
    admission["candidate_ordinal"] = 1
    bundle = tmp_path / "reports/contrived-pass"
    atomic_json(bundle / "coverage.json", coverage)
    (bundle / "coverage.md").write_text(render_coverage_markdown(coverage))

    result = evaluate_completion(coverage, output_root=tmp_path)

    assert result["clauses"][1]["passed"] is False
    assert any("ordinal-zero" in gap for gap in result["clauses"][1]["gaps"])


@pytest.mark.parametrize("mode", ["absent", "divergent"])
def test_completion_requires_markdown_projection(
    tmp_path: Path, mode: str
) -> None:
    coverage = _contrived_passing_completion_state(tmp_path)
    markdown = tmp_path / "reports/contrived-pass/coverage.md"
    if mode == "absent":
        markdown.unlink()
    else:
        markdown.write_text("independently authored\n")

    result = evaluate_completion(coverage, output_root=tmp_path)

    clause = result["clauses"][3]
    assert clause["passed"] is False
    expected = (
        "coverage.md has not been produced"
        if mode == "absent"
        else "coverage.md is not the projection of persisted coverage.json"
    )
    assert expected in clause["gaps"]


def test_stale_ledger_contract_hashes_do_not_confer_health_or_exhaustion(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "evidence/rejection.json"
    atomic_json(evidence_path, {"rejected": True})
    contract_hashes = load_reviewed_contracts().hashes
    contract_hashes["fitness-targets"] = "0" * 64
    RejectionLedger(tmp_path).append(
        subject_type="candidate",
        subject_id="candidate-stale",
        cell_id="cell-stale",
        candidate_ordinal=2,
        lifecycle_stage="qualification",
        reason_code="expected-failure-mismatch",
        detail="stale evidence",
        attribution=[
            {"side": "defect-on", "repetition": 0, "check": "expected-failure"}
        ],
        n_split={"defects_off": 3, "defect_on": 3},
        evidence=[evidence_reference(evidence_path, root=tmp_path)],
        config_snapshot_hash="0" * 64,
        contract_hashes=contract_hashes,
    )

    coverage = build_coverage(tmp_path)

    assert coverage["report_status"] == "stale-evidence"
    assert coverage["rejection_ledger"]["valid"] is True
    assert coverage["rejection_ledger"]["current_contracts"] is False
    assert coverage["rejection_ledger"]["event_count"] == 1
    assert coverage["regeneration_exhaustion"]["count"] == 0
    assert coverage["synthesis_health"]["trusted"] is False
    assert coverage["synthesis_health"]["rejection_rates"]["production"]["rate"] is None
    assert coverage["synthesis_health"]["per_side_attribution"] == {}


@pytest.mark.parametrize("path_kind", ["absolute", "parent"])
def test_evidence_references_reject_paths_outside_the_evidence_root(
    tmp_path: Path, path_kind: str
) -> None:
    outside = tmp_path.parent / "outside-evidence.txt"
    outside.write_text("outside\n")
    path = str(outside) if path_kind == "absolute" else "../outside-evidence.txt"

    with pytest.raises(EvidenceReferenceError, match="relative and contained"):
        validate_evidence_reference(
            {"path": path, "sha256": sha256_file(outside)}, root=tmp_path
        )


def test_reporting_rejects_absolute_admission_evidence_path(tmp_path: Path) -> None:
    candidate, result = _admit(tmp_path)
    admission_path = result.bundle / "admission.json"
    admission = json.loads(admission_path.read_text())
    referenced = tmp_path / admission["evidence"][0]["path"]
    admission["evidence"][0]["path"] = str(referenced)
    atomic_json(admission_path, admission)
    terminal_path = candidate.bundle / "terminal.json"
    terminal = json.loads(terminal_path.read_text())
    terminal["admission_sha256"] = sha256_file(admission_path)
    atomic_json(terminal_path, terminal)

    coverage = build_coverage(tmp_path)

    assert coverage["admissions"] == []
    assert "relative and contained" in coverage["invalid_admissions"][0]["reason"]


def test_completion_rejects_parent_definition_evidence_path(tmp_path: Path) -> None:
    coverage = _contrived_passing_completion_state(tmp_path)
    artifact_path = tmp_path / "completion/definition-tests.json"
    artifact = json.loads(artifact_path.read_text())
    artifact["tests"][0]["evidence"]["path"] = "../outside-evidence.txt"
    atomic_json(artifact_path, artifact)

    result = evaluate_completion(coverage, output_root=tmp_path)

    assert result["clauses"][1]["passed"] is False
    assert any("relative and contained" in gap for gap in result["clauses"][1]["gaps"])
