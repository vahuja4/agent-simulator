from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentsim.scenario import (
    ScenarioError,
    load_curated_scenario,
    load_library,
    load_synthesized_scenario,
)
from scenario_synthesis import cli
from scenario_synthesis.candidate import CandidateError, load_candidate, produce_candidate
from scenario_synthesis.generator import generate_blueprints
from scenario_synthesis.evidence import canonical_json, sha256_bytes
from scenario_synthesis.ledger import LedgerError, RejectionLedger
from scenario_synthesis.qualification import (
    EpisodeResult,
    StubQualificationRunner,
    evaluate_admission,
    qualify_candidate,
)
from scenario_synthesis.realization_provider import StubRealizationProvider


@pytest.fixture(scope="module")
def targeted_blueprint():
    return next(item for item in generate_blueprints() if item.fitness_target_id is not None)


@pytest.fixture(scope="module")
def detection_unproven_blueprint():
    return next(item for item in generate_blueprints() if item.fitness_target_id is None)


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
    } <= set(first_episode)
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
    assert cli.main(["produce", "--output-root", str(tmp_path)]) == 0
    produced = json.loads(capsys.readouterr().out)
    assert cli.main(
        [
            "qualify",
            "--output-root",
            str(tmp_path),
            "--candidate-id",
            produced["candidate_id"],
        ]
    ) == 0
    admitted = json.loads(capsys.readouterr().out)
    assert admitted["status"] == "admitted"
    assert Path(admitted["library_path"]).is_file()


def test_live_modes_remain_unimplemented(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["produce", "--live"])
    assert exc.value.code == 2
    assert "not implemented" in capsys.readouterr().err
