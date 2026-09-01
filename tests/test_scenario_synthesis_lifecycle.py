from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentsim.orchestrator import RunResult
from agentsim.scenario import (
    ScenarioError,
    load_curated_scenario,
    load_library,
    load_synthesized_scenario,
)
from agentsim.trace import Trace
from agentsim.types import CriterionVerdict, TurnVerdict
from scenario_synthesis import config as synthesis_config
from scenario_synthesis import cli
from scenario_synthesis.candidate import CandidateError, load_candidate, produce_candidate
from scenario_synthesis.contracts import load_reviewed_contracts
from scenario_synthesis.generator import generate_blueprints
from scenario_synthesis.evidence import atomic_json, canonical_json, sha256_bytes, sha256_file
from scenario_synthesis.ledger import LedgerError, RejectionLedger
from scenario_synthesis.qualification import (
    EpisodeResult,
    LiveQualificationRunner,
    StubQualificationRunner,
    _validate_qualification_evidence,
    evaluate_admission,
    invalidate_admission,
    qualify_candidate,
)
from scenario_synthesis.simulator_compliance import (
    SIMULATOR_COMPLIANCE_CRITERION_IDS,
    simulator_compliance_criteria,
)
from scenario_synthesis.realization_provider import (
    LiveRealizationProvider,
    RealizationError,
    StubRealizationProvider,
    validate_surface,
)


@pytest.fixture(scope="module")
def targeted_blueprint():
    return next(item for item in generate_blueprints() if item.fitness_target_id is not None)


@pytest.fixture(scope="module")
def detection_unproven_blueprint():
    return next(item for item in generate_blueprints() if item.fitness_target_id is None)


@pytest.mark.parametrize(
    ("complication", "evidence_key", "expected_text"),
    [
        ("none", None, "passes vacuously"),
        ("underspecification", "disclosure_style", "withheld at least one required Goal fact"),
        ("mid-conversation-correction", "correction", "preserving the underlying Goal"),
        ("goal-shift", "goal_shift", "explicitly abandoned the in-progress Goal"),
        ("multi-intent-turn", "payment_instructions_in_one_turn", "missing parameters do not disqualify"),
        ("false-premise", "false_premise", "incorrect belief about real Fixture state"),
        ("out-of-scope-drift", "transient_out_of_scope_intent", "subsequently returned"),
        ("channel-noise", "recovery_requirement", "successfully recovered is irrelevant"),
        ("ambiguous-reference", "ambiguous_card_reference", "requiring disambiguation rather than elicitation"),
    ],
)
def test_simulator_complication_evidence_criterion_loading(
    complication: str,
    evidence_key: str | None,
    expected_text: str,
) -> None:
    evidence = {
        "knowledge_evidence": {
            "kind": "material_fluency_gap",
            "referent": "payment_amount_type",
        }
    }
    if evidence_key is not None:
        evidence[evidence_key] = "declared-evidence"

    criteria = simulator_compliance_criteria(
        "low",
        evidence["knowledge_evidence"],
        complication,
        evidence,
    )

    assert tuple(criterion.id for criterion in criteria) == (
        SIMULATOR_COMPLIANCE_CRITERION_IDS
    )
    descriptions = {criterion.id: criterion.description for criterion in criteria}
    assert expected_text in descriptions["simulator_complication_evidence"]


def test_simulator_goal_persistence_is_complication_aware() -> None:
    knowledge_evidence = {
        "kind": "material_fluency_gap",
        "referent": "payment_amount_type",
    }

    goal_shift = simulator_compliance_criteria(
        "low", knowledge_evidence, "goal-shift", {"goal_shift": {}}
    )
    drift = simulator_compliance_criteria(
        "low",
        knowledge_evidence,
        "out-of-scope-drift",
        {"transient_out_of_scope_intent": "change_autopay"},
    )
    unchanged = simulator_compliance_criteria(
        "low", knowledge_evidence, "none", {}
    )
    persistence = lambda criteria: next(
        item.description
        for item in criteria
        if item.id == "simulator_goal_persistence"
    )

    assert "Sharing parameters with the abandoned Goal" in persistence(goal_shift)
    assert "returned to the original Scenario Goal" in persistence(drift)
    assert "did not abandon or replace it prematurely" in persistence(unchanged)


def test_admitted_ordinal_one_bundle_validates_its_snapshot_criterion_set() -> None:
    output_root = Path("synthesized_scenarios")
    candidate_id = (
        "candidate-4a296207b9dd03895648ada38cfaaa043c2891b04e58b5a92792e3f327d25549"
    )
    qualification_id = (
        "qualification-ad342abf099b6a0267d70883e9f6117104cbdc0edf4b37b62ce4aa94cd4361cd"
    )
    candidate = load_candidate(output_root, candidate_id)
    bundle = output_root / "runs" / qualification_id
    qualification = json.loads(
        (bundle / "qualification.json").read_text(encoding="utf-8")
    )

    episodes = _validate_qualification_evidence(
        candidate,
        bundle,
        output_root,
        qualification["config_snapshot_hash"],
        load_reviewed_contracts().hashes,
        repetitions=3,
        expected_failure=None,
        defect_toggles=(),
    )

    assert len(episodes) == 3


def test_new_config_snapshot_records_current_compliance_criterion_set() -> None:
    snapshot = synthesis_config.create_config_snapshot()

    assert tuple(snapshot.content["simulator_compliance_criterion_ids"]) == (
        SIMULATOR_COMPLIANCE_CRITERION_IDS
    )


def test_realization_retry_is_separate_from_candidate_replacement_budget(
    tmp_path: Path, targeted_blueprint
) -> None:
    provider = StubRealizationProvider(
        failure_modes={(0, 0): "schema-invalid-output", (0, 1): "fact-drift"}
    )
    assert produce_candidate(targeted_blueprint, output_root=tmp_path, provider=provider) is None
    assert not list((tmp_path / "candidates").glob("candidate-*/production.json"))
    production_failures = RejectionLedger(tmp_path).records()
    assert [item["reason_code"] for item in production_failures] == [
        "schema-failure",
        "fact-equivalence-failure",
    ]

    candidate = produce_candidate(
        targeted_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(
            failure_modes={(0, 0): "sealed-world-violation"}
        ),
    )
    assert candidate is not None
    assert candidate.ordinal == 0
    assert len(RejectionLedger(tmp_path).records()) == 3


@pytest.mark.parametrize(
    ("side", "result", "reason"),
    [
        ("defects-off", "unexpected-failure", "defects-off-failure"),
        ("defects-off", "task_incomplete", "degraded-error-incomplete-evidence"),
        ("defects-off", "simulator-compliance-fail", "simulator-noncompliance"),
        ("defects-off", "error", "degraded-error-incomplete-evidence"),
        ("defect-on", "pass", "expected-failure-mismatch"),
        ("defect-on", "unexpected-failure", "expected-failure-mismatch"),
        ("defect-on", "task_incomplete", "degraded-error-incomplete-evidence"),
        ("defect-on", "simulator-compliance-fail", "simulator-noncompliance"),
        ("defect-on", "error", "degraded-error-incomplete-evidence"),
    ],
)
def test_every_injected_outcome_fails_closed(
    tmp_path: Path, targeted_blueprint, side: str, result: str, reason: str
) -> None:
    candidate = produce_candidate(
        targeted_blueprint, output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert candidate is not None
    qualified = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(outcomes={(side, 1): result}),
    )
    assert not qualified.decision.admitted
    assert qualified.decision.reason_code == reason


def test_degraded_and_extra_failures_have_distinct_admission_reasons(
    tmp_path: Path, targeted_blueprint
) -> None:
    candidate = produce_candidate(
        targeted_blueprint, output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert candidate is not None
    degraded = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(
            outcomes={("defects-off", 0): EpisodeResult("pass", degraded_checks=("trace",))}
        ),
    )
    assert degraded.decision.reason_code == "degraded-error-incomplete-evidence"

    other_root = tmp_path / "extra"
    candidate = produce_candidate(
        targeted_blueprint, output_root=other_root, provider=StubRealizationProvider()
    )
    assert candidate is not None
    expected = {"source": "assertion", "id": "validated_submit"}
    if targeted_blueprint.fitness_target_id != "d1":
        from scenario_synthesis.contracts import load_reviewed_contracts

        contract = load_reviewed_contracts().contracts["fitness-targets"].content["targets"]
        entry = next(
            item
            for item in contract
            if item["target_id"] == targeted_blueprint.fitness_target_id
            and item["shape_id"] == targeted_blueprint.fitness_shape_id
        )
        expected = dict(entry["expected_failure"])
    extra = qualify_candidate(
        candidate.candidate_id,
        output_root=other_root,
        runner=StubQualificationRunner(
            outcomes={
                ("defect-on", 0): EpisodeResult(
                    "expected-failure",
                    (expected, {"source": "judge", "id": "unrelated"}),
                )
            }
        ),
    )
    assert extra.decision.reason_code == "unrelated-failure"


def test_targeted_admission_requires_exact_three_by_three_and_hashes_evidence(
    tmp_path: Path, targeted_blueprint
) -> None:
    candidate = produce_candidate(
        targeted_blueprint, output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert candidate is not None
    result = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
    )
    assert result.decision.admitted
    admission = json.loads((result.bundle / "admission.json").read_text())
    assert admission["n_split"] == {"defects_off": 3, "defect_on": 3}
    assert not admission["detection_unproven"]
    assert len(admission["attribution"]) == 6
    first_episode = json.loads((result.bundle / admission["evidence"][0]["path"].split("/", 2)[-1]).read_text())
    assert {
        "simulator_id", "judge_id", "prompt_hashes", "fixture", "termination",
        "assertion_results", "judge_rulings", "trace", "transcript",
        "simulator_compliance_rulings",
    } <= set(first_episode)
    transcript = tmp_path / first_episode["transcript"]["path"]
    assert transcript.suffix == ".jsonl"
    records = [json.loads(line) for line in transcript.read_text().splitlines()]
    assert [record["record_type"] for record in records] == ["episode"]
    assert records[0]["schema_version"] == 1
    assert records[0]["turns"] == []
    assert records[0]["termination"]["reason"] == "stub-completed"
    assert set(records[0]["models"]) == {"simulator", "judge"}
    assert result.library_path is not None
    assert result.library_path.read_bytes() == candidate.scenario_path.read_bytes()


def test_detection_unproven_admission_runs_precision_only_and_marks_provenance(
    tmp_path: Path, detection_unproven_blueprint
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    result = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
    )
    admission = json.loads((result.bundle / "admission.json").read_text())
    terminal = json.loads((candidate.bundle / "terminal.json").read_text())
    assert admission["n_split"] == {"defects_off": 3, "defect_on": 0}
    assert admission["detection_unproven"] is True
    assert terminal["detection_unproven"] is True


def test_replacements_advance_ordinals_and_third_rejection_exhausts_cell(
    tmp_path: Path, targeted_blueprint
) -> None:
    candidate = produce_candidate(
        targeted_blueprint, output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert candidate is not None
    for ordinal in range(3):
        assert candidate.ordinal == ordinal
        result = qualify_candidate(
            candidate.candidate_id,
            output_root=tmp_path,
            runner=StubQualificationRunner(
                outcomes={("defects-off", 0): "unexpected-failure"}
            ),
            replacement_provider=StubRealizationProvider(),
        )
        repeated = qualify_candidate(
            candidate.candidate_id,
            output_root=tmp_path,
            runner=StubQualificationRunner(),
        )
        assert repeated.qualification_id == result.qualification_id
        if ordinal < 2:
            assert result.replacement is not None
            candidate = result.replacement
        else:
            assert result.replacement is None
            terminal = json.loads((candidate.bundle / "terminal.json").read_text())
            assert terminal["regeneration_exhausted"] is True
    records = [
        item for item in RejectionLedger(tmp_path).records() if item["subject_type"] == "candidate"
    ]
    assert [item["candidate_ordinal"] for item in records] == [0, 1, 2]
    assert all(item["attribution"] and item["n_split"]["defects_off"] == 3 for item in records)
    with pytest.raises(CandidateError, match="exhausted"):
        produce_candidate(
            targeted_blueprint, output_root=tmp_path, provider=StubRealizationProvider()
        )


def test_ledger_is_append_only_and_detects_evidence_tampering(
    tmp_path: Path, targeted_blueprint
) -> None:
    provider = StubRealizationProvider(failure_modes={(0, 0): "schema-invalid-output"})
    candidate = produce_candidate(targeted_blueprint, output_root=tmp_path, provider=provider)
    assert candidate is not None
    ledger = RejectionLedger(tmp_path)
    before = (tmp_path / "ledger/rejections.jsonl").read_bytes()
    assert len(ledger.records()) == 1
    evidence = tmp_path / ledger.records()[0]["evidence"][0]["path"]
    evidence.write_text("{}\n")
    with pytest.raises(LedgerError, match="evidence hash mismatch"):
        ledger.records()
    assert (tmp_path / "ledger/rejections.jsonl").read_bytes() == before


def test_invalid_existing_ledger_blocks_admission(tmp_path: Path, targeted_blueprint) -> None:
    candidate = produce_candidate(
        targeted_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(failure_modes={(0, 0): "schema-invalid-output"}),
    )
    assert candidate is not None
    ledger = RejectionLedger(tmp_path)
    evidence = tmp_path / ledger.records()[0]["evidence"][0]["path"]
    evidence.write_text("{}\n")
    with pytest.raises(LedgerError, match="evidence hash mismatch"):
        qualify_candidate(
            candidate.candidate_id,
            output_root=tmp_path,
            runner=StubQualificationRunner(),
        )


def test_admission_requires_exact_unique_repetition_indices() -> None:
    duplicate = tuple(
        {
            "side": "defects-off",
            "repetition": 0,
            "kind": "pass",
            "failures": [],
            "degraded_checks": [],
            "simulator_compliance": "pass",
        }
        for _ in range(3)
    )
    decision = evaluate_admission(duplicate, expected_failure=None)
    assert decision.reason_code == "degraded-error-incomplete-evidence"
    extra_side = (*duplicate[:2], {**duplicate[2], "repetition": 2, "side": "unknown"})
    decision = evaluate_admission(extra_side, expected_failure=None)
    assert decision.reason_code == "degraded-error-incomplete-evidence"
    complete = tuple(
        {**item, "repetition": repetition}
        for repetition, item in enumerate(duplicate)
    )
    decision = evaluate_admission(
        complete,
        expected_failure=None,
        required_assertions=("validated_submit",),
    )
    assert decision.reason_code == "degraded-error-incomplete-evidence"


def test_admission_rejects_pass_with_empty_judge_rulings() -> None:
    episodes = tuple(
        {
            "side": "defects-off",
            "repetition": repetition,
            "kind": "pass",
            "failures": [],
            "degraded_checks": [],
            "simulator_compliance": "pass",
            "assertion_results": [],
            "judge_rulings": [],
        }
        for repetition in range(3)
    )

    decision = evaluate_admission(episodes, expected_failure=None)

    assert not decision.admitted
    assert decision.reason_code == "degraded-error-incomplete-evidence"


def test_post_admission_rejection_is_a_ledger_contradiction(
    tmp_path: Path, detection_unproven_blueprint
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    qualified = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
        timestamp="2026-08-29T05:37:38Z",
    )
    admission = json.loads((qualified.bundle / "admission.json").read_text())
    terminal_path = candidate.bundle / "terminal.json"
    terminal = json.loads(terminal_path.read_text())
    terminal_path.unlink()
    RejectionLedger(tmp_path).append(
        subject_type="qualification",
        subject_id=qualified.qualification_id,
        cell_id=candidate.cell_id,
        candidate_ordinal=candidate.ordinal,
        lifecycle_stage="admission",
        reason_code="degraded-error-incomplete-evidence",
        detail="late contradictory rejection",
        attribution=[{
            "side": "qualification", "repetition": None, "check": "complete-evidence"
        }],
        n_split={"defects_off": 0, "defect_on": 0},
        evidence=[],
        config_snapshot_hash=admission["config_snapshot_hash"],
        contract_hashes=admission["contract_hashes"],
        timestamp="2026-08-29T05:39:09Z",
    )
    atomic_json(terminal_path, terminal)

    with pytest.raises(LedgerError, match="post-admission rejection"):
        RejectionLedger(tmp_path).records()


def test_harness_fault_can_supersede_a_spurious_post_admission_rejection(
    tmp_path: Path, detection_unproven_blueprint
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    qualified = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
        timestamp="2026-08-29T05:37:38Z",
    )
    admission = json.loads((qualified.bundle / "admission.json").read_text())
    terminal_path = candidate.bundle / "terminal.json"
    terminal = json.loads(terminal_path.read_text())
    terminal_path.unlink()
    ledger = RejectionLedger(tmp_path)
    ledger.append(
        subject_type="qualification",
        subject_id=qualified.qualification_id,
        cell_id=candidate.cell_id,
        candidate_ordinal=candidate.ordinal,
        lifecycle_stage="admission",
        reason_code="degraded-error-incomplete-evidence",
        detail="spurious finalization rejection",
        attribution=[{
            "side": "qualification", "repetition": None, "check": "complete-evidence"
        }],
        n_split={"defects_off": 0, "defect_on": 0},
        evidence=[],
        config_snapshot_hash=admission["config_snapshot_hash"],
        contract_hashes=admission["contract_hashes"],
        timestamp="2026-08-29T05:39:09Z",
    )
    ledger.append(
        subject_type="qualification",
        subject_id=qualified.qualification_id,
        cell_id=candidate.cell_id,
        candidate_ordinal=candidate.ordinal,
        lifecycle_stage="validation-error-invalidation",
        reason_code="harness-fault",
        detail="finalizer compared against repository state changed by its own evidence",
        attribution=[{
            "side": "qualification", "repetition": None, "check": "harness-validity"
        }],
        n_split=admission["n_split"],
        evidence=[],
        config_snapshot_hash=admission["config_snapshot_hash"],
        contract_hashes=admission["contract_hashes"],
        timestamp="2026-08-29T05:40:00Z",
    )
    atomic_json(terminal_path, terminal)

    assert RejectionLedger(tmp_path).records()[-1]["reason_code"] == "harness-fault"


def test_harness_fault_invalidation_retires_admission_without_consuming_budget(
    tmp_path: Path, detection_unproven_blueprint
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    qualified = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
        timestamp="2026-08-29T05:37:38Z",
    )
    assert qualified.library_path is not None

    record, archive_path = invalidate_admission(
        candidate.candidate_id,
        output_root=tmp_path,
        detail="HARNESS fault; candidate not at fault; K regeneration budget unchanged",
        timestamp="2026-08-29T05:40:00Z",
    )

    assert record["reason_code"] == "harness-fault"
    assert record["lifecycle_stage"] == "admission-invalidation"
    assert record["subject_type"] == "qualification"
    assert not qualified.library_path.exists()
    assert archive_path.is_file()
    assert RejectionLedger(tmp_path).records()[-1] == record

    ordinals: list[int] = []

    class DifferentSurfaceProvider:
        provider_id = "different-offline-surface"

        def realize(self, blueprint, *, candidate_ordinal, attempt):
            del attempt
            ordinals.append(candidate_ordinal)
            surface = dict(
                StubRealizationProvider().realize(
                    blueprint, candidate_ordinal=candidate_ordinal, attempt=0
                )
            )
            surface["description"] += " Fresh harness-valid realization."
            return surface

    replacement = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=DifferentSurfaceProvider(),
    )
    assert replacement is not None
    assert replacement.ordinal == 0
    assert ordinals == [0]


def test_completed_qualification_is_idempotently_reused(
    tmp_path: Path, detection_unproven_blueprint
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    first = qualify_candidate(
        candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
    )
    second = qualify_candidate(
        candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
    )
    assert second.qualification_id == first.qualification_id
    assert second.library_path == first.library_path


def test_completed_qualification_survives_repository_state_change(
    tmp_path: Path,
    detection_unproven_blueprint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    first = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
    )
    monkeypatch.setattr(
        synthesis_config,
        "_repository_state",
        lambda root: ("f" * 40, False),
    )

    class FailIfRun:
        runner_id = "offline-stub-run-scenario-v1"
        provider_mode = "offline-stub"
        calls = 0

        def run_scenario(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("committed Qualification evidence must not rerun")

    runner = FailIfRun()
    reused = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=runner,
    )

    assert runner.calls == 0
    assert reused.qualification_id == first.qualification_id
    assert reused.decision.admitted


def test_qualification_accepts_relative_output_root(
    tmp_path: Path,
    detection_unproven_blueprint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    output_root = Path("synthesized_scenarios")
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=output_root,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None

    result = qualify_candidate(
        candidate.candidate_id,
        output_root=output_root,
        runner=StubQualificationRunner(),
    )

    assert result.decision.admitted


def test_qualification_resumes_after_evidence_write_before_admission(
    tmp_path: Path,
    detection_unproven_blueprint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    first = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
    )
    assert first.library_path is not None
    (first.bundle / "admission.json").unlink()
    (candidate.bundle / "terminal.json").unlink()
    first.library_path.unlink()
    monkeypatch.setattr(
        synthesis_config,
        "_repository_state",
        lambda root: ("f" * 40, False),
    )

    class FailIfRun:
        runner_id = "offline-stub-run-scenario-v1"
        provider_mode = "offline-stub"
        calls = 0

        def run_scenario(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("complete Qualification evidence must not rerun")

    runner = FailIfRun()
    resumed = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=runner,
    )

    assert runner.calls == 0
    assert resumed.qualification_id == first.qualification_id
    assert resumed.decision.admitted


def test_qualification_finalization_ignores_its_own_repository_dirtying(
    tmp_path: Path,
    detection_unproven_blueprint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    calls = 0

    def repository_state(root):
        nonlocal calls
        del root
        calls += 1
        return "a" * 40, calls > 1

    monkeypatch.setattr(synthesis_config, "_repository_state", repository_state)

    result = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
    )

    assert result.decision.admitted


@pytest.mark.parametrize(
    "nested_key",
    [
        "transcript",
        "trace",
        "assertion_results",
        "judge_rulings",
        "simulator_compliance_rulings",
    ],
)
def test_completed_qualification_rejects_nested_evidence_hash_mismatch(
    tmp_path: Path, detection_unproven_blueprint, nested_key: str
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    result = qualify_candidate(
        candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
    )
    qualification = json.loads((result.bundle / "qualification.json").read_text())
    episode_path = tmp_path / qualification["episodes"][0]["path"]
    episode = json.loads(episode_path.read_text())
    (tmp_path / episode[nested_key]["path"]).write_text("{}\n")

    with pytest.raises(CandidateError, match="evidence"):
        qualify_candidate(
            candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
        )
    assert RejectionLedger(tmp_path).records(verify_evidence=False) == ()


def test_completed_qualification_rejects_absolute_nested_evidence_path(
    tmp_path: Path, detection_unproven_blueprint
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    result = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
    )
    qualification_path = result.bundle / "qualification.json"
    qualification = json.loads(qualification_path.read_text())
    episode_path = tmp_path / qualification["episodes"][0]["path"]
    episode = json.loads(episode_path.read_text())
    transcript_path = tmp_path / episode["transcript"]["path"]
    episode["transcript"]["path"] = str(transcript_path)
    atomic_json(episode_path, episode)
    qualification["episodes"][0]["sha256"] = sha256_file(episode_path)
    atomic_json(qualification_path, qualification)
    admission_path = result.bundle / "admission.json"
    admission = json.loads(admission_path.read_text())
    admission["evidence"][0]["sha256"] = sha256_file(episode_path)
    admission["evidence"][-1]["sha256"] = sha256_file(qualification_path)
    atomic_json(admission_path, admission)
    terminal_path = candidate.bundle / "terminal.json"
    terminal = json.loads(terminal_path.read_text())
    terminal["admission_sha256"] = sha256_file(admission_path)
    atomic_json(terminal_path, terminal)

    with pytest.raises(CandidateError, match="evidence path escapes the artifact root"):
        qualify_candidate(
            candidate.candidate_id,
            output_root=tmp_path,
            runner=StubQualificationRunner(),
        )


def test_completed_qualification_rejects_extra_episode_artifact(
    tmp_path: Path, detection_unproven_blueprint
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    result = qualify_candidate(
        candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
    )
    (result.bundle / "episodes" / "unreferenced.json").write_text("{}\n")
    with pytest.raises(CandidateError, match="extra evidence"):
        qualify_candidate(
            candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
        )
    assert RejectionLedger(tmp_path).records() == ()


def test_qualification_rejects_non_contract_transcript_with_ledger_entry(
    tmp_path: Path,
    detection_unproven_blueprint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scenario_synthesis.qualification as qualification

    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    monkeypatch.setattr(
        qualification,
        "_write_transcript",
        lambda path, record: path.write_text("# not repository JSONL\n"),
    )
    with pytest.raises(CandidateError, match="Transcript evidence"):
        qualify_candidate(
            candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
        )
    rejection = RejectionLedger(tmp_path).records()[-1]
    assert rejection["subject_type"] == "qualification"
    assert rejection["reason_code"] == "degraded-error-incomplete-evidence"


@pytest.mark.parametrize("durable_files", [(), ("blueprint.yaml",), ("blueprint.yaml", "scenario.yaml")])
def test_interrupted_candidate_bundle_is_quarantined_before_reproduction(
    tmp_path: Path, targeted_blueprint, durable_files: tuple[str, ...]
) -> None:
    source_root = tmp_path / "source"
    complete = produce_candidate(
        targeted_blueprint, output_root=source_root, provider=StubRealizationProvider()
    )
    assert complete is not None
    target_root = tmp_path / "target"
    partial = target_root / "candidates" / complete.candidate_id
    partial.mkdir(parents=True)
    for name in durable_files:
        shutil.copy2(complete.bundle / name, partial / name)

    reproduced = produce_candidate(
        targeted_blueprint, output_root=target_root, provider=StubRealizationProvider()
    )
    assert reproduced is not None
    assert reproduced.candidate_id == complete.candidate_id
    assert load_candidate(target_root, reproduced.candidate_id) == reproduced
    quarantined = list((target_root / "quarantine" / "production").glob(f"{complete.candidate_id}-*"))
    assert len(quarantined) == 1


def test_verified_complete_candidate_bundle_is_reused_idempotently(
    tmp_path: Path, targeted_blueprint
) -> None:
    candidate = produce_candidate(
        targeted_blueprint, output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert candidate is not None
    production_before = (candidate.bundle / "production.json").read_bytes()
    repeated = produce_candidate(
        targeted_blueprint, output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert repeated == candidate
    assert (candidate.bundle / "production.json").read_bytes() == production_before


def test_interrupted_staging_bundle_is_quarantined_before_atomic_commit(
    tmp_path: Path, targeted_blueprint
) -> None:
    source_root = tmp_path / "source"
    complete = produce_candidate(
        targeted_blueprint, output_root=source_root, provider=StubRealizationProvider()
    )
    assert complete is not None
    target_root = tmp_path / "target"
    partial = (
        target_root
        / "candidates"
        / (
            f".{complete.candidate_id}.{targeted_blueprint.cell_id}"
            ".partial-interrupted-command"
        )
    )
    partial.mkdir(parents=True)
    for name in ("blueprint.yaml", "scenario.yaml", "production.json"):
        shutil.copy2(complete.bundle / name, partial / name)

    reproduced = produce_candidate(
        targeted_blueprint, output_root=target_root, provider=StubRealizationProvider()
    )

    assert reproduced is not None
    assert reproduced.candidate_id == complete.candidate_id
    assert not partial.exists()
    quarantined = list(
        (target_root / "quarantine" / "production").glob(
            f"{complete.candidate_id}.*"
        )
    )
    assert len(quarantined) == 1


def test_interrupted_staging_is_quarantined_before_stochastic_rerealization(
    tmp_path: Path, targeted_blueprint
) -> None:
    class AlternateSurfaceProvider(StubRealizationProvider):
        provider_id = "alternate-surface-stub"

        def realize(self, *args, **kwargs):
            surface = dict(super().realize(*args, **kwargs))
            surface["description"] = str(surface["description"]) + " Alternate wording."
            return surface

    source_root = tmp_path / "source"
    interrupted = produce_candidate(
        targeted_blueprint, output_root=source_root, provider=StubRealizationProvider()
    )
    assert interrupted is not None
    target_root = tmp_path / "target"
    partial = (
        target_root
        / "candidates"
        / (
            f".{interrupted.candidate_id}.{targeted_blueprint.cell_id}"
            ".partial-interrupted-command"
        )
    )
    shutil.copytree(interrupted.bundle, partial)

    reproduced = produce_candidate(
        targeted_blueprint, output_root=target_root, provider=AlternateSurfaceProvider()
    )

    assert reproduced is not None
    assert reproduced.candidate_id != interrupted.candidate_id
    assert not partial.exists()
    assert len(list((target_root / "quarantine" / "production").iterdir())) == 1


def _rehash_admission_chain(result, root: Path, qualification: dict) -> None:
    qualification_path = result.bundle / "qualification.json"
    atomic_json(qualification_path, qualification)
    admission_path = result.bundle / "admission.json"
    admission = json.loads(admission_path.read_text())
    admission["n_split"] = qualification["n_split"]
    for reference in admission["evidence"]:
        reference["sha256"] = sha256_file(root / reference["path"])
    atomic_json(admission_path, admission)
    terminal_path = result.candidate.bundle / "terminal.json"
    terminal = json.loads(terminal_path.read_text())
    terminal["admission_sha256"] = sha256_file(admission_path)
    atomic_json(terminal_path, terminal)


def test_admission_rejects_internally_rehashed_shortened_repetition_split(
    tmp_path: Path, detection_unproven_blueprint
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    result = qualify_candidate(
        candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
    )
    qualification = json.loads((result.bundle / "qualification.json").read_text())
    qualification["n_split"]["defects_off"] = 1
    _rehash_admission_chain(result, tmp_path, qualification)

    with pytest.raises(CandidateError, match="repetition or defect configuration"):
        qualify_candidate(
            candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
        )
    assert RejectionLedger(tmp_path).records() == ()


def test_admission_rejects_internally_rehashed_episode_defect_configuration(
    tmp_path: Path, targeted_blueprint
) -> None:
    candidate = produce_candidate(
        targeted_blueprint, output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert candidate is not None
    result = qualify_candidate(
        candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
    )
    qualification_path = result.bundle / "qualification.json"
    qualification = json.loads(qualification_path.read_text())
    defect_on = next(
        reference
        for reference in qualification["episodes"]
        if Path(reference["path"]).name == "defect-on-0.json"
    )
    episode_path = tmp_path / defect_on["path"]
    episode = json.loads(episode_path.read_text())
    episode["defect_toggles"] = []
    atomic_json(episode_path, episode)
    defect_on["sha256"] = sha256_file(episode_path)
    _rehash_admission_chain(result, tmp_path, qualification)

    with pytest.raises(CandidateError, match="repetition or defect configuration"):
        qualify_candidate(
            candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
        )
    assert RejectionLedger(tmp_path).records() == ()


@pytest.mark.parametrize(
    ("nested_key", "collection", "mutation"),
    [
        ("assertion_results", "results", "false"),
        ("judge_rulings", "rulings", "missing"),
    ],
)
def test_admission_rejects_internally_rehashed_incomplete_check_results(
    tmp_path: Path,
    targeted_blueprint,
    nested_key: str,
    collection: str,
    mutation: str,
) -> None:
    candidate = produce_candidate(
        targeted_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    result = qualify_candidate(
        candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
    )
    qualification_path = result.bundle / "qualification.json"
    qualification = json.loads(qualification_path.read_text())
    episode_reference = qualification["episodes"][0]
    episode_path = tmp_path / episode_reference["path"]
    episode = json.loads(episode_path.read_text())
    artifact_path = tmp_path / episode[nested_key]["path"]
    artifact = json.loads(artifact_path.read_text())
    assert artifact[collection]
    if mutation == "false":
        artifact[collection][0]["passed"] = False
    else:
        artifact[collection][0].pop("passed")
    atomic_json(artifact_path, artifact)
    episode[nested_key]["sha256"] = sha256_file(artifact_path)
    atomic_json(episode_path, episode)
    episode_reference["sha256"] = sha256_file(episode_path)
    _rehash_admission_chain(result, tmp_path, qualification)

    with pytest.raises(CandidateError, match="admission decision"):
        qualify_candidate(
            candidate.candidate_id, output_root=tmp_path, runner=StubQualificationRunner()
        )
    assert RejectionLedger(tmp_path).records() == ()


def test_admission_recovers_if_library_commit_is_interrupted(
    tmp_path: Path,
    detection_unproven_blueprint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scenario_synthesis.qualification as qualification

    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    original = qualification._admit

    def interrupted(*args, commit: bool, **kwargs):
        if commit:
            raise RuntimeError("injected admission interruption")
        return original(*args, commit=commit, **kwargs)

    monkeypatch.setattr(qualification, "_admit", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        qualify_candidate(
            candidate.candidate_id,
            output_root=tmp_path,
            runner=StubQualificationRunner(),
        )
    monkeypatch.setattr(qualification, "_admit", original)
    recovered = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
    )
    assert recovered.library_path is not None and recovered.library_path.is_file()


def test_rejection_recovers_if_replacement_production_is_interrupted(
    tmp_path: Path, targeted_blueprint
) -> None:
    class InterruptedProvider:
        provider_id = "interrupted-stub"

        def realize(self, *args, **kwargs):
            raise RuntimeError("injected replacement interruption")

    candidate = produce_candidate(
        targeted_blueprint, output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert candidate is not None
    with pytest.raises(RuntimeError, match="replacement interruption"):
        qualify_candidate(
            candidate.candidate_id,
            output_root=tmp_path,
            runner=StubQualificationRunner(
                outcomes={("defects-off", 0): "unexpected-failure"}
            ),
            replacement_provider=InterruptedProvider(),
        )
    recovered = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
        replacement_provider=StubRealizationProvider(),
    )
    assert recovered.replacement is not None
    assert recovered.replacement.ordinal == 1


def test_rejection_recovers_if_terminal_write_is_interrupted_after_ledger(
    tmp_path: Path,
    targeted_blueprint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scenario_synthesis.qualification as qualification

    candidate = produce_candidate(
        targeted_blueprint, output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert candidate is not None
    original = qualification.write_terminal
    monkeypatch.setattr(
        qualification,
        "write_terminal",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("terminal interruption")),
    )
    with pytest.raises(RuntimeError, match="terminal interruption"):
        qualify_candidate(
            candidate.candidate_id,
            output_root=tmp_path,
            runner=StubQualificationRunner(
                outcomes={("defects-off", 0): "unexpected-failure"}
            ),
            replacement_provider=StubRealizationProvider(),
        )
    monkeypatch.setattr(qualification, "write_terminal", original)
    recovered = qualify_candidate(
        candidate.candidate_id,
        output_root=tmp_path,
        runner=StubQualificationRunner(),
        replacement_provider=StubRealizationProvider(),
    )
    assert recovered.replacement is not None
    records = [
        item
        for item in RejectionLedger(tmp_path).records()
        if item["subject_id"] == candidate.candidate_id
    ]
    assert len(records) == 1


def test_candidate_production_record_is_hash_verified(tmp_path: Path, targeted_blueprint) -> None:
    candidate = produce_candidate(
        targeted_blueprint, output_root=tmp_path, provider=StubRealizationProvider()
    )
    assert candidate is not None
    production_path = candidate.bundle / "production.json"
    production = json.loads(production_path.read_text())
    production["candidate_ordinal"] = 2
    production_without_hash = dict(production)
    production_without_hash.pop("record_hash")
    production["record_hash"] = sha256_bytes(
        canonical_json(production_without_hash).encode("utf-8")
    )
    production_path.write_text(json.dumps(production))
    with pytest.raises(CandidateError, match="candidate ID does not match"):
        load_candidate(tmp_path, candidate.candidate_id)


def test_curated_and_synthesized_content_cannot_cross_loaders(
    tmp_path: Path, detection_unproven_blueprint
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    with pytest.raises(ScenarioError, match="cannot load as curated"):
        load_curated_scenario(candidate.scenario_path)
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    (mixed / "synthesized.yaml").write_bytes(candidate.scenario_path.read_bytes())
    with pytest.raises(ScenarioError, match="cannot load as curated"):
        load_library(mixed)
    with pytest.raises(ScenarioError, match="cannot load as synthesized"):
        load_synthesized_scenario(Path("scenarios/j1_happy_path.yaml"))


def test_cli_offline_stub_produce_and_qualify_never_construct_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import agentsim.llm

    monkeypatch.setattr(
        agentsim.llm, "_get_client", lambda: pytest.fail("Slice 3 constructed an LLM client")
    )
    assert cli.main(["produce", "--stub", "--output-root", str(tmp_path)]) == 0
    produced = json.loads(capsys.readouterr().out)
    assert cli.main(
        [
            "qualify",
            "--stub",
            "--output-root",
            str(tmp_path),
            "--candidate-id",
            produced["candidate_id"],
        ]
    ) == 0
    admitted = json.loads(capsys.readouterr().out)
    assert admitted["status"] == "admitted"
    assert Path(admitted["library_path"]).is_file()


@pytest.mark.parametrize("command", ["produce", "qualify"])
def test_cli_requires_explicit_execution_mode_before_client_construction(
    command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import agentsim.llm

    monkeypatch.setattr(
        agentsim.llm, "_get_client", lambda: pytest.fail("constructed an LLM client")
    )
    argv = [command]
    if command == "qualify":
        argv.extend(["--candidate-id", "candidate-" + "0" * 64])
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert "choose --stub for offline development" in error
    assert "explicit --live execution" in error


def test_live_produce_requires_explicit_cell_before_client_construction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli.LiveRealizationProvider,
        "from_config",
        lambda: pytest.fail("constructed live realization provider"),
    )
    with pytest.raises(SystemExit) as exc:
        cli.main(["produce", "--live"])
    assert exc.value.code == 2
    assert "requires an explicit --cell-id" in capsys.readouterr().err


def test_live_commands_print_cost_ceiling_before_offline_injected_execution(
    tmp_path: Path,
    targeted_blueprint,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli.LiveRealizationProvider,
        "from_config",
        lambda: StubRealizationProvider(),
    )
    assert cli.main(
        [
            "produce",
            "--live",
            "--cell-id",
            targeted_blueprint.cell_id,
            "--output-root",
            str(tmp_path),
        ]
    ) == 0
    produced_lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert produced_lines[0]["status"] == "live-cost-ceiling"
    assert produced_lines[0]["maximum_planned_realization_calls"] == 2
    assert produced_lines[0]["maximum_planned_episodes"] == 0
    candidate_id = produced_lines[1]["candidate_id"]

    runner = StubQualificationRunner()
    runner.runner_id = "injected-live-run-scenario-v1"
    runner.provider_mode = "live"
    monkeypatch.setattr(
        cli.LiveQualificationRunner,
        "from_config",
        lambda: runner,
    )
    assert cli.main(
        [
            "qualify",
            "--live",
            "--candidate-id",
            candidate_id,
            "--output-root",
            str(tmp_path),
        ]
    ) == 0
    qualified_lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert qualified_lines[0]["status"] == "live-cost-ceiling"
    assert qualified_lines[0]["maximum_planned_realization_calls"] == 2
    assert qualified_lines[0]["maximum_planned_episodes"] == 6
    qualification = json.loads(
        (tmp_path / "runs" / qualified_lines[1]["qualification_id"] / "qualification.json").read_text()
    )
    assert qualification["provider_mode"] == "live"


def test_live_providers_pin_current_configured_models_without_calling_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    realization_models: list[str] = []
    qualification_models: list[str] = []

    class FakeLLM:
        def __init__(self, model: str) -> None:
            realization_models.append(model)

    monkeypatch.setattr(
        "scenario_synthesis.realization_provider.OpenAILLM", FakeLLM
    )
    provider = LiveRealizationProvider.from_config()
    assert provider.provider_id == "openai-structured-realization:gpt-5.6-luna"
    assert realization_models == ["gpt-5.6-luna"]

    class FakeQualificationLLM:
        def __init__(self, model: str) -> None:
            qualification_models.append(model)

    monkeypatch.setattr(
        "scenario_synthesis.qualification.OpenAILLM", FakeQualificationLLM
    )
    LiveQualificationRunner.from_config()
    assert qualification_models == ["gpt-5.6-luna", "gpt-5.5"]


def test_live_realization_provider_uses_structured_blueprint_surface(
    detection_unproven_blueprint,
) -> None:
    detection_unproven_blueprint = next(
        item
        for item in generate_blueprints()
        if item.fitness_target_id is None and item.knowledge_level == "low"
    )
    calls: list[dict[str, object]] = []

    class RecordingLLM:
        async def structured(self, **kwargs):
            calls.append(kwargs)
            return StubRealizationProvider().realize(
                detection_unproven_blueprint,
                candidate_ordinal=0,
                attempt=0,
            )

    provider = LiveRealizationProvider(
        llm=RecordingLLM(),
        system_prompt="configured realization prompt",
        token_budget=8192,
        provider_id="test-live-realization",
    )

    surface = provider.realize(
        detection_unproven_blueprint, candidate_ordinal=0, attempt=0
    )

    assert set(surface) == {"description", "persona", "goal", "success_criteria"}
    assert calls[0]["system"] == "configured realization prompt"
    assert calls[0]["effort"] == "none"
    assert calls[0]["max_tokens"] == 8192
    request = json.loads(calls[0]["messages"][0]["content"])
    assert request["blueprint"] == detection_unproven_blueprint.to_dict()
    assert "declared Knowledge level" in request["instruction"]
    assert "do not recite goal_facts" in request["instruction"]
    assert all(
        token in request["instruction"]
        for token in (
            *detection_unproven_blueprint.fixture_bindings.cards,
            *detection_unproven_blueprint.fixture_bindings.accounts,
        )
    )
    assert "must not contain the canonical label 'statement balance'" in request["instruction"]


def test_low_knowledge_surface_rejects_fluent_goal_fact_recital(
    detection_unproven_blueprint,
) -> None:
    detection_unproven_blueprint = next(
        item
        for item in generate_blueprints()
        if item.fitness_target_id is None and item.knowledge_level == "low"
    )
    surface = {
        "description": "A cooperative customer with a material fluency gap.",
        "persona": {"name": "Customer", "traits": "Needs help with amount types."},
        "goal": (
            "Set up the statement balance payment for card 9013 from account 5678 "
            "on the due date."
        ),
        "success_criteria": ["Complete the payment."],
    }

    with pytest.raises(RealizationError, match="Knowledge level"):
        validate_surface(detection_unproven_blueprint, surface)


def test_live_qualification_fails_missing_low_knowledge_evidence(
    detection_unproven_blueprint,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detection_unproven_blueprint = next(
        item
        for item in generate_blueprints()
        if item.fitness_target_id is None and item.knowledge_level == "low"
    )
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    scenario = load_synthesized_scenario(candidate.scenario_path)

    async def fake_run_scenario(*args, **kwargs):
        del args, kwargs
        trace = Trace("missing-level-evidence", outcome="pass")
        trace.add_user_turn(
            "Pay the statement balance on card 9013 from account 5678 on the due date.",
            "state goal",
            None,
        )
        return RunResult(
            trace=trace,
            verdicts=[TurnVerdict(
                "pass", [CriterionVerdict("goal_completion", True, "complete")], "complete"
            )],
            outcome="pass",
            final_reasoning="completed",
        )

    class FakeComplianceJudge:
        def __init__(self, llm, *, criteria):
            del llm
            self.criteria = criteria

        async def judge(self, trace):
            del trace
            return TurnVerdict(
                "continue",
                [
                    CriterionVerdict(
                        criterion.id,
                        criterion.id != "simulator_knowledge_level_evidence",
                        "missing material fluency gap"
                        if criterion.id == "simulator_knowledge_level_evidence"
                        else "compliant",
                    )
                    for criterion in self.criteria
                ],
                "checked",
            )

    monkeypatch.setattr("agentsim.scenario.run_scenario", fake_run_scenario)
    monkeypatch.setattr(
        "scenario_synthesis.qualification.GeneralJudge", FakeComplianceJudge
    )
    runner = LiveQualificationRunner(object(), object())

    result = runner.run_scenario(
        scenario,
        side="defects-off",
        repetition=0,
        defect_toggles=(),
        expected_failure=None,
        knowledge_level=detection_unproven_blueprint.knowledge_level,
        knowledge_evidence=detection_unproven_blueprint.goal_facts["knowledge_evidence"],
        complication=detection_unproven_blueprint.complication,
        complication_evidence=detection_unproven_blueprint.goal_facts,
    )

    assert result.kind == "simulator-compliance-fail"


def test_live_qualification_runner_uses_run_scenario_and_compliance_judge(
    detection_unproven_blueprint,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    scenario = load_synthesized_scenario(candidate.scenario_path)
    simulator_llm = object()
    judge_llm = object()
    observed: dict[str, object] = {}

    async def fake_run_scenario(scenario_arg, llm, agent, **kwargs):
        observed.update(
            scenario=scenario_arg,
            simulator_llm=llm,
            judge_llm=kwargs["judge_llm"],
            mock_config=agent.config,
        )
        trace = Trace("live-qualification-test", outcome="pass")
        return RunResult(
            trace=trace,
            verdicts=[TurnVerdict(
                "pass", [CriterionVerdict("goal_completion", True, "complete")], "complete"
            )],
            outcome="pass",
            final_reasoning="completed",
            llm_calls=4,
        )

    class FakeComplianceJudge:
        def __init__(self, llm, *, criteria):
            observed["compliance_llm"] = llm
            observed["compliance_criteria"] = criteria

        async def judge(self, trace):
            del trace
            return TurnVerdict(
                "continue",
                [
                    CriterionVerdict(criterion.id, True, "compliant")
                    for criterion in observed["compliance_criteria"]
                ],
                "compliant",
            )

    monkeypatch.setattr("agentsim.scenario.run_scenario", fake_run_scenario)
    monkeypatch.setattr(
        "scenario_synthesis.qualification.GeneralJudge", FakeComplianceJudge
    )
    runner = LiveQualificationRunner(simulator_llm, judge_llm)

    result = runner.run_scenario(
        scenario,
        side="defects-off",
        repetition=0,
        defect_toggles=(),
        expected_failure=None,
        knowledge_level=detection_unproven_blueprint.knowledge_level,
        knowledge_evidence=detection_unproven_blueprint.goal_facts[
            "knowledge_evidence"
        ],
        complication=detection_unproven_blueprint.complication,
        complication_evidence=detection_unproven_blueprint.goal_facts,
    )

    assert result.kind == "pass"
    assert result.run_result is not None
    assert result.to_dict(side="defects-off", repetition=0, toggles=())["llm_calls"] == 5
    assert observed["scenario"] is scenario
    assert observed["simulator_llm"] is simulator_llm
    assert observed["judge_llm"] is judge_llm
    assert observed["compliance_llm"] is judge_llm
    assert not any(vars(observed["mock_config"]).values())


def test_live_qualification_runner_rejects_pass_without_judge_rulings(
    detection_unproven_blueprint,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = produce_candidate(
        detection_unproven_blueprint,
        output_root=tmp_path,
        provider=StubRealizationProvider(),
    )
    assert candidate is not None
    scenario = load_synthesized_scenario(candidate.scenario_path)

    async def fake_run_scenario(*args, **kwargs):
        del args, kwargs
        return RunResult(
            trace=Trace("empty-judge-rulings", outcome="pass"),
            verdicts=[],
            outcome="pass",
            final_reasoning="completed without Judge evidence",
        )

    monkeypatch.setattr("agentsim.scenario.run_scenario", fake_run_scenario)
    result = LiveQualificationRunner(object(), object()).run_scenario(
        scenario,
        side="defects-off",
        repetition=0,
        defect_toggles=(),
        expected_failure=None,
        knowledge_level=detection_unproven_blueprint.knowledge_level,
        knowledge_evidence=detection_unproven_blueprint.goal_facts[
            "knowledge_evidence"
        ],
        complication=detection_unproven_blueprint.complication,
        complication_evidence=detection_unproven_blueprint.goal_facts,
    )

    assert result.kind == "error"
    assert result.degraded_checks == ("judge-rulings",)
