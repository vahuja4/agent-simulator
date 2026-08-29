"""Pure offline qualification evidence and two-sided admission evaluation."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

import yaml

from agentsim.adapters import MockConfig, MockPayCardAgent
from agentsim.judge import GeneralJudge
from agentsim.llm import LLMClient, OpenAILLM
from agentsim.orchestrator import RunResult
from agentsim.scenario import Scenario, load_synthesized_library, load_synthesized_scenario

from ._async import run
from .candidate import Candidate, CandidateError, load_candidate, produce_candidate, write_terminal
from .config import create_config_snapshot, load_config
from .contracts import ContractSet, load_reviewed_contracts
from .dryrun import SIMULATOR_COMPLIANCE_CRITERIA
from .evidence import (
    EvidenceReferenceError,
    atomic_json,
    canonical_json,
    evidence_reference,
    sha256_bytes,
    sha256_file,
    validate_evidence_reference,
)
from .ledger import RejectionLedger, exclusive_lock
from .realization_provider import RealizationProvider
from .validator import CoverageBlueprintValidator


KINDS = {
    "pass", "expected-failure", "unexpected-failure", "task_incomplete",
    "simulator-compliance-fail", "error",
}


@dataclass(frozen=True)
class EpisodeResult:
    kind: str
    failures: tuple[Mapping[str, str], ...] = ()
    degraded_checks: tuple[str, ...] = ()
    simulator_compliant: bool = True
    error: str | None = None
    run_result: RunResult | None = None
    simulator_compliance_rulings: tuple[Mapping[str, Any], ...] = ()
    additional_llm_calls: int = 0

    def to_dict(self, *, side: str, repetition: int, toggles: tuple[str, ...]) -> dict[str, Any]:
        return {
            "side": side,
            "repetition": repetition,
            "defect_toggles": list(toggles),
            "kind": self.kind,
            "outcome": _runtime_outcome(self.kind),
            "failures": [dict(item) for item in self.failures],
            "degraded_checks": list(self.degraded_checks),
            "simulator_compliance": "pass" if self.simulator_compliant else "fail",
            "error": self.error,
            "llm_calls": (
                0
                if self.run_result is None
                else self.run_result.llm_calls
                + self.additional_llm_calls
            ),
        }


class QualificationRunner(Protocol):
    runner_id: str
    provider_mode: str

    def run_scenario(
        self,
        scenario: Scenario,
        *,
        side: str,
        repetition: int,
        defect_toggles: tuple[str, ...],
        expected_failure: Mapping[str, str] | None,
    ) -> EpisodeResult: ...


@dataclass
class StubQualificationRunner:
    outcomes: Mapping[tuple[str, int], str | EpisodeResult] = field(default_factory=dict)
    runner_id: str = "offline-stub-run-scenario-v1"
    provider_mode: str = "offline-stub"

    def run_scenario(
        self,
        scenario: Scenario,
        *,
        side: str,
        repetition: int,
        defect_toggles: tuple[str, ...],
        expected_failure: Mapping[str, str] | None,
    ) -> EpisodeResult:
        del scenario, defect_toggles
        injected = self.outcomes.get(
            (side, repetition), "pass" if side == "defects-off" else "expected-failure"
        )
        if isinstance(injected, EpisodeResult):
            return injected
        kind = injected
        if kind not in KINDS:
            raise ValueError(f"unknown stub qualification outcome {kind!r}")
        if kind == "expected-failure":
            if expected_failure is None:
                return EpisodeResult("unexpected-failure", ({"source": "judge", "id": "unexpected"},))
            return EpisodeResult(kind, (dict(expected_failure),))
        if kind == "unexpected-failure":
            return EpisodeResult(kind, ({"source": "judge", "id": "unexpected"},))
        if kind == "simulator-compliance-fail":
            return EpisodeResult(kind, simulator_compliant=False)
        if kind == "error":
            return EpisodeResult(kind, error="injected stub error")
        return EpisodeResult(kind)


@dataclass
class LiveQualificationRunner:
    """Run Qualification Episodes through the existing simulator and Judge path."""

    simulator_llm: LLMClient
    judge_llm: LLMClient
    enforce_model_family_separation: bool = False
    runner_id: str = "live-run-scenario-v1"
    provider_mode: str = "live"

    @classmethod
    def from_config(cls) -> LiveQualificationRunner:
        config = load_config()
        return cls(
            simulator_llm=OpenAILLM(model=str(config.content["models"]["simulator"])),
            judge_llm=OpenAILLM(model=str(config.content["models"]["judge"])),
            enforce_model_family_separation=bool(
                config.content["enforce_model_family_separation"]
            ),
        )

    def run_scenario(
        self,
        scenario: Scenario,
        *,
        side: str,
        repetition: int,
        defect_toggles: tuple[str, ...],
        expected_failure: Mapping[str, str] | None,
    ) -> EpisodeResult:
        del side, repetition
        config = MockConfig(**{toggle: True for toggle in defect_toggles})
        effective = {
            name
            for name, enabled in vars(config).items()
            if enabled is True
        }
        if effective != set(defect_toggles):
            raise CandidateError("effective mock defect configuration does not match Qualification")
        return run(
            self._run_scenario(
                scenario,
                agent=MockPayCardAgent(config),
                expected_failure=expected_failure,
            )
        )

    async def _run_scenario(
        self,
        scenario: Scenario,
        *,
        agent: MockPayCardAgent,
        expected_failure: Mapping[str, str] | None,
    ) -> EpisodeResult:
        from agentsim.scenario import run_scenario

        result = await run_scenario(
            scenario,
            self.simulator_llm,
            agent=agent,
            judge_llm=self.judge_llm,
            enforce_model_family_separation=self.enforce_model_family_separation,
        )
        if result.outcome == "error":
            return EpisodeResult("error", error=result.final_reasoning, run_result=result)
        try:
            compliance = await GeneralJudge(
                self.judge_llm, criteria=SIMULATOR_COMPLIANCE_CRITERIA
            ).judge(result.trace)
        except Exception as exc:
            return EpisodeResult(
                "error",
                error=f"simulator compliance raised {type(exc).__name__}: {exc}",
                run_result=result,
                additional_llm_calls=1,
            )
        compliance_rulings = tuple(item.to_dict() for item in compliance.criteria)
        simulator_compliant = all(item.passed for item in compliance.criteria)
        failures = tuple(
            {"source": failure.source, "id": failure.id}
            for failure in result.failures
        )
        if not simulator_compliant:
            kind = "simulator-compliance-fail"
        elif result.outcome == "pass":
            kind = "pass"
        elif result.outcome == "task_incomplete":
            kind = "task_incomplete"
        elif expected_failure is not None and expected_failure in failures:
            kind = "expected-failure"
        else:
            kind = "unexpected-failure"
        return EpisodeResult(
            kind,
            failures=failures,
            degraded_checks=tuple(
                str(item.get("check", item.get("type", "unknown")))
                for item in result.degraded_checks
            ),
            simulator_compliant=simulator_compliant,
            run_result=result,
            simulator_compliance_rulings=compliance_rulings,
            additional_llm_calls=1,
        )


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    status: str
    reason_code: str | None
    detection_unproven: bool
    attribution: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class QualificationResult:
    qualification_id: str
    bundle: Path
    candidate: Candidate
    decision: AdmissionDecision
    library_path: Path | None
    replacement: Candidate | None


def evaluate_admission(
    episodes: tuple[Mapping[str, Any], ...],
    *,
    expected_failure: Mapping[str, str] | None,
    repetitions: int = 3,
    required_assertions: tuple[str, ...] = (),
    required_criteria: tuple[str, ...] = (),
) -> AdmissionDecision:
    expected_sides = {"defects-off"} if expected_failure is None else {"defects-off", "defect-on"}
    attribution: list[Mapping[str, Any]] = []
    if {item.get("side") for item in episodes} - expected_sides:
        return _reject("degraded-error-incomplete-evidence", episodes, "qualification-bundle")
    by_side = {side: [item for item in episodes if item["side"] == side] for side in expected_sides}
    if any(
        len(items) != repetitions
        or {item.get("repetition") for item in items} != set(range(repetitions))
        for items in by_side.values()
    ):
        return _reject("degraded-error-incomplete-evidence", episodes, "qualification-bundle")
    for item in episodes:
        if item["simulator_compliance"] != "pass":
            return _reject("simulator-noncompliance", (item,), "simulator-compliance")
        if item["kind"] in {"error", "task_incomplete"} or item["degraded_checks"]:
            return _reject("degraded-error-incomplete-evidence", (item,), "episode-evidence")
        if not _check_results_are_complete(
            item.get("assertion_results"),
            required_assertions,
            item.get("failures"),
            source="assertion",
        ) or not _check_results_are_complete(
            item.get("judge_rulings"),
            required_criteria,
            item.get("failures"),
            source="judge",
        ):
            return _reject("degraded-error-incomplete-evidence", (item,), "required-checks")
    for item in by_side["defects-off"]:
        if item["kind"] != "pass" or item["failures"]:
            return _reject("defects-off-failure", (item,), "defects-off-precision")
        attribution.append(_attribution(item, "defects-off-precision"))
    if expected_failure is None:
        return AdmissionDecision(True, "admitted", None, True, tuple(attribution))
    for item in by_side["defect-on"]:
        failures = item["failures"]
        if not any(failure == expected_failure for failure in failures):
            return _reject("expected-failure-mismatch", (item,), _check_name(expected_failure))
        if len(failures) != 1:
            return _reject("unrelated-failure", (item,), _check_name(expected_failure))
        if item["kind"] != "expected-failure":
            return _reject("expected-failure-mismatch", (item,), _check_name(expected_failure))
        attribution.append(_attribution(item, _check_name(expected_failure)))
    return AdmissionDecision(True, "admitted", None, False, tuple(attribution))


def _check_results_are_complete(
    results: Any,
    required_ids: tuple[str, ...],
    failures: Any,
    *,
    source: str,
) -> bool:
    if not isinstance(results, list) or not isinstance(failures, list):
        return False
    if any(
        not isinstance(result, Mapping)
        or set(result) != {"id", "passed"}
        or not isinstance(result["id"], str)
        or not isinstance(result["passed"], bool)
        for result in results
    ):
        return False
    if any(
        not isinstance(failure, Mapping)
        or set(failure) != {"source", "id"}
        or not isinstance(failure["source"], str)
        or not isinstance(failure["id"], str)
        for failure in failures
    ):
        return False
    result_ids = [result["id"] for result in results]
    if len(result_ids) != len(set(result_ids)) or set(result_ids) != set(required_ids):
        return False
    failed_ids = {
        failure["id"] for failure in failures if failure["source"] == source
    }
    return all(result["passed"] == (result["id"] not in failed_ids) for result in results)


def qualify_candidate(
    candidate_id: str,
    *,
    output_root: str | Path,
    runner: QualificationRunner,
    replacement_provider: RealizationProvider | None = None,
    timestamp: str | None = None,
) -> QualificationResult:
    root = Path(output_root)
    candidate = load_candidate(root, candidate_id)
    contracts = load_reviewed_contracts()
    config = load_config()
    snapshot = create_config_snapshot(config=config, contracts=contracts)
    _revalidate_candidate(candidate, config.sha256, contracts)
    expected_failure, toggles = _fitness_contract(candidate, contracts)
    repetitions = int(config.content["limits"]["admission_repetitions"])
    qualification_material = {
        "candidate_id": candidate_id,
        "snapshot_hash": snapshot.sha256,
        "runner_id": runner.runner_id,
        "repetitions": repetitions,
    }
    qualification_id = "qualification-" + sha256_bytes(
        canonical_json(qualification_material).encode("utf-8")
    )
    bundle = root / "runs" / qualification_id
    if (candidate.bundle / "terminal.json").exists():
        terminal = json.loads(
            (candidate.bundle / "terminal.json").read_text(encoding="utf-8")
        )
        bundle = root / "runs" / str(terminal.get("qualification_id", ""))
        return _load_existing_result(candidate, bundle, root, replacement_provider)
    if bundle.exists():
        if (bundle / "qualification.json").is_file():
            if (bundle / "admission.json").is_file():
                return _resume_incomplete(
                    candidate, bundle, root, replacement_provider, config, contracts
                )
            try:
                return _resume_qualification_evaluation(
                    candidate, bundle, root, replacement_provider, config, contracts
                )
            except CandidateError:
                pass
        quarantine = bundle.with_name(
            bundle.name + ".corrupt-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        )
        os.replace(bundle, quarantine)
    qualified_at = timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with exclusive_lock(root / "locks" / f"{candidate.cell_id}.lock", command="qualify"):
        RejectionLedger(root).records()
        bundle.mkdir(parents=True)
        snapshot_path = bundle / "config-snapshot.yaml"
        snapshot_path.write_text(yaml.safe_dump(snapshot.content, sort_keys=False), encoding="utf-8")
        episode_refs: list[Mapping[str, str]] = []
        sides = ("defects-off",) if expected_failure is None else ("defects-off", "defect-on")
        scenario = load_synthesized_scenario(candidate.scenario_path)
        for side in sides:
            side_toggles = () if side == "defects-off" else toggles
            for repetition in range(repetitions):
                try:
                    result = runner.run_scenario(
                        scenario,
                        side=side,
                        repetition=repetition,
                        defect_toggles=side_toggles,
                        expected_failure=expected_failure,
                    )
                except Exception as exc:
                    result = EpisodeResult(
                        "error", error=f"{type(exc).__name__}: {exc}"
                    )
                record = result.to_dict(side=side, repetition=repetition, toggles=side_toggles)
                assertion_results = [
                    {
                        "id": assertion.type,
                        "passed": not any(
                            failure["source"] == "assertion"
                            and failure["id"] == assertion.type
                            for failure in record["failures"]
                        ),
                    }
                    for assertion in candidate.blueprint.required_assertions
                ]
                if result.run_result is None:
                    judge_rulings = [
                        {
                            "id": criterion,
                            "passed": not any(
                                failure["source"] == "judge"
                                and failure["id"] == criterion
                                for failure in record["failures"]
                            ),
                        }
                        for criterion in candidate.blueprint.required_criteria
                    ]
                    turns: list[Mapping[str, Any]] = []
                    termination = "stub-completed"
                else:
                    observed = {
                        ruling.criterion_id: ruling
                        for verdict in result.run_result.verdicts
                        for ruling in verdict.criteria
                        if ruling.criterion_id in candidate.blueprint.required_criteria
                    }
                    judge_rulings = [
                        {"id": criterion, "passed": observed[criterion].passed}
                        for criterion in candidate.blueprint.required_criteria
                        if criterion in observed
                    ]
                    turns = [turn.to_dict() for turn in result.run_result.trace.turns]
                    termination = result.run_result.final_reasoning
                record.update(
                    {
                        "simulator_id": config.content["models"]["simulator"],
                        "judge_id": config.content["models"]["judge"],
                        "prompt_hashes": dict(snapshot.content["prompt_hashes"]),
                        "fixture": dict(snapshot.content["fixture"]),
                        "termination": termination,
                    }
                )
                stem = f"{side}-{repetition}"
                trace_path = bundle / "episodes" / f"{stem}-trace.json"
                transcript_path = bundle / "episodes" / f"{stem}-transcript.jsonl"
                assertion_results_path = bundle / "episodes" / f"{stem}-assertion-results.json"
                judge_rulings_path = bundle / "episodes" / f"{stem}-judge-rulings.json"
                compliance_path = (
                    bundle / "episodes" / f"{stem}-simulator-compliance-rulings.json"
                )
                atomic_json(
                    trace_path,
                    {
                        "schema_version": 1,
                        "provider": runner.runner_id,
                        "side": side,
                        "repetition": repetition,
                        "outcome": record["outcome"],
                        "turns": turns,
                    },
                )
                _write_transcript(
                    transcript_path,
                    {
                        "schema_version": 1,
                        "record_type": "episode",
                        "episode_id": f"{qualification_id}:{side}:{repetition}",
                        "side": side,
                        "repetition": repetition,
                        "turns": turns,
                        "termination": {"reason": termination, "outcome": record["outcome"]},
                        "timing": {"started_at": qualified_at, "completed_at": qualified_at},
                        "models": {
                            "simulator": config.content["models"]["simulator"],
                            "judge": config.content["models"]["judge"],
                        },
                    },
                )
                atomic_json(assertion_results_path, {"schema_version": 1, "results": assertion_results})
                atomic_json(judge_rulings_path, {"schema_version": 1, "rulings": judge_rulings})
                atomic_json(
                    compliance_path,
                    {
                        "schema_version": 1,
                        "rulings": [dict(item) for item in result.simulator_compliance_rulings],
                    },
                )
                record["trace"] = evidence_reference(trace_path, root=root)
                record["transcript"] = evidence_reference(transcript_path, root=root)
                record["assertion_results"] = evidence_reference(assertion_results_path, root=root)
                record["judge_rulings"] = evidence_reference(judge_rulings_path, root=root)
                record["simulator_compliance_rulings"] = evidence_reference(
                    compliance_path, root=root
                )
                episode_path = bundle / "episodes" / f"{side}-{repetition}.json"
                atomic_json(episode_path, record)
                episode_refs.append(evidence_reference(episode_path, root=root))
        qualification_record = {
            "schema_version": 1,
            "qualification_id": qualification_id,
            "candidate_id": candidate_id,
            "cell_id": candidate.cell_id,
            "candidate_ordinal": candidate.ordinal,
            "runner_id": runner.runner_id,
            "provider_mode": runner.provider_mode,
            "config_snapshot_hash": snapshot.sha256,
            "contract_hashes": contracts.hashes,
            "models": dict(config.content["models"]),
            "expected_failure": expected_failure,
            "defect_toggles": list(toggles),
            "n_split": {
                "defects_off": repetitions,
                "defect_on": 0 if expected_failure is None else repetitions,
            },
            "episodes": episode_refs,
            "qualified_at": qualified_at,
        }
        qualification_path = bundle / "qualification.json"
        atomic_json(qualification_path, qualification_record)
        _write_admission_from_qualification(candidate, bundle, root, config, contracts)
        return _resume_incomplete(
            candidate, bundle, root, replacement_provider, config, contracts,
            _cell_lock_held=True,
        )


def _resume_qualification_evaluation(
    candidate: Candidate,
    bundle: Path,
    root: Path,
    replacement_provider: RealizationProvider | None,
    config: Any,
    contracts: ContractSet,
) -> QualificationResult:
    """Evaluate complete Episode evidence after interruption before admission."""
    with exclusive_lock(
        root / "locks" / f"{candidate.cell_id}.lock", command="resume-qualify"
    ):
        RejectionLedger(root).records()
        expected_failure, toggles = _fitness_contract(candidate, contracts)
        repetitions = int(config.content["limits"]["admission_repetitions"])
        snapshot = create_config_snapshot(config=config, contracts=contracts)
        _validate_qualification_evidence(
            candidate,
            bundle,
            root,
            snapshot.sha256,
            contracts.hashes,
            repetitions=repetitions,
            expected_failure=expected_failure,
            defect_toggles=toggles,
        )
        _write_admission_from_qualification(candidate, bundle, root, config, contracts)
        return _resume_incomplete(
            candidate,
            bundle,
            root,
            replacement_provider,
            config,
            contracts,
            _cell_lock_held=True,
        )


def _write_admission_from_qualification(
    candidate: Candidate,
    bundle: Path,
    root: Path,
    config: Any,
    contracts: ContractSet,
) -> None:
    qualification_path = bundle / "qualification.json"
    qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    expected_failure, toggles = _fitness_contract(candidate, contracts)
    repetitions = int(config.content["limits"]["admission_repetitions"])
    snapshot = create_config_snapshot(config=config, contracts=contracts)
    episode_records = _validate_evidence_or_reject(
        candidate,
        bundle,
        root,
        lambda: _validate_qualification_evidence(
            candidate,
            bundle,
            root,
            snapshot.sha256,
            contracts.hashes,
            repetitions=repetitions,
            expected_failure=expected_failure,
            defect_toggles=toggles,
        ),
    )
    decision = evaluate_admission(
        episode_records,
        expected_failure=expected_failure,
        repetitions=repetitions,
        required_assertions=tuple(
            assertion.type for assertion in candidate.blueprint.required_assertions
        ),
        required_criteria=candidate.blueprint.required_criteria,
    )
    exhausted = not decision.admitted and candidate.ordinal >= int(
        config.content["limits"]["replacement_bound"]
    )
    admission_record = {
        "schema_version": 1,
        "qualification_id": bundle.name,
        "candidate_id": candidate.candidate_id,
        "cell_id": candidate.cell_id,
        "candidate_ordinal": candidate.ordinal,
        "status": decision.status,
        "reason_code": decision.reason_code,
        "detection_unproven": decision.detection_unproven,
        "attribution": [dict(item) for item in decision.attribution],
        "n_split": qualification["n_split"],
        "evidence": [
            *qualification["episodes"],
            evidence_reference(qualification_path, root=root),
        ],
        "config_snapshot_hash": snapshot.sha256,
        "contract_hashes": contracts.hashes,
        "regeneration_exhausted": exhausted,
        "decided_at": qualification["qualified_at"],
    }
    atomic_json(bundle / "admission.json", admission_record)


def _revalidate_candidate(candidate: Candidate, config_hash: str, contracts: ContractSet) -> None:
    CoverageBlueprintValidator(contracts=contracts).validate(candidate.blueprint)
    if candidate.blueprint.provenance.config_hash != config_hash:
        raise CandidateError("candidate configuration has drifted")
    production = json.loads((candidate.bundle / "production.json").read_text(encoding="utf-8"))
    if production["contract_hashes"] != contracts.hashes:
        raise CandidateError("candidate contract hashes have drifted")


def _load_existing_result(
    candidate: Candidate,
    bundle: Path,
    root: Path,
    replacement_provider: RealizationProvider | None,
) -> QualificationResult:
    config = load_config()
    contracts = load_reviewed_contracts()

    def validate() -> Mapping[str, Any]:
        terminal_path = candidate.bundle / "terminal.json"
        terminal_record = json.loads(terminal_path.read_text(encoding="utf-8"))
        admission_path = bundle / "admission.json"
        if (
            not admission_path.is_file()
            or terminal_record.get("qualification_id") != bundle.name
        ):
            raise CandidateError("terminal candidate has incomplete qualification evidence")
        if terminal_record.get("admission_sha256") != sha256_file(admission_path):
            raise CandidateError("terminal admission evidence hash mismatch")
        return _validate_admission_evidence(
            candidate,
            bundle,
            root,
            config,
            contracts,
            allow_repository_state_drift=True,
        )

    admission = _validate_evidence_or_reject(candidate, bundle, root, validate)
    terminal = json.loads((candidate.bundle / "terminal.json").read_text(encoding="utf-8"))
    decision = AdmissionDecision(
        admitted=admission["status"] == "admitted",
        status=str(admission["status"]),
        reason_code=admission.get("reason_code"),
        detection_unproven=bool(admission.get("detection_unproven")),
        attribution=tuple(admission.get("attribution", [])),
    )
    library_path = None
    replacement = None
    if decision.admitted:
        library_path = root / terminal["library_path"]
        if not library_path.is_file():
            library_path = _admit(candidate, root, config, contracts, commit=True)
        if library_path.read_bytes() != candidate.scenario_path.read_bytes():
            raise CandidateError("admitted library evidence has changed")
        RejectionLedger(root).records()
    else:
        records = RejectionLedger(root).records()
        rejection = next(
            (
                item for item in records
                if item["subject_type"] == "candidate"
                and item["subject_id"] == candidate.candidate_id
            ),
            None,
        )
        if rejection is None:
            raise CandidateError("rejected terminal candidate is missing its ledger event")
        replacement = _find_replacement(root, candidate.candidate_id)
        if (
            replacement is None
            and not terminal.get("regeneration_exhausted")
            and replacement_provider is not None
        ):
            replacement = produce_candidate(
                candidate.blueprint,
                output_root=root,
                provider=replacement_provider,
            )
    return QualificationResult(bundle.name, bundle, candidate, decision, library_path, replacement)


def _resume_incomplete(
    candidate: Candidate,
    bundle: Path,
    root: Path,
    replacement_provider: RealizationProvider | None,
    config: Any,
    contracts: ContractSet,
    *,
    _cell_lock_held: bool = False,
) -> QualificationResult:
    """Finish the commit steps without moving evidence already referenced by the ledger."""
    admission_path = bundle / "admission.json"
    admission = _validate_evidence_or_reject(
        candidate,
        bundle,
        root,
        lambda: _validate_admission_evidence(candidate, bundle, root, config, contracts),
    )
    qualified_at = str(admission["decided_at"])
    lock = nullcontext() if _cell_lock_held else exclusive_lock(
        root / "locks" / f"{candidate.cell_id}.lock", command="resume-qualify"
    )
    with lock:
        ledger = RejectionLedger(root)
        ledger.records()
        if admission["status"] == "admitted":
            library_path = _admit(candidate, root, config, contracts, commit=False)
            write_terminal(
                candidate,
                {
                    "schema_version": 1,
                    "candidate_id": candidate.candidate_id,
                    "status": "admitted",
                    "qualification_id": bundle.name,
                    "admission_sha256": sha256_file(admission_path),
                    "library_path": str(library_path.relative_to(root)),
                    "detection_unproven": bool(admission["detection_unproven"]),
                    "terminal_at": qualified_at,
                },
            )
            _admit(candidate, root, config, contracts, commit=True)
        else:
            production = json.loads(
                (candidate.bundle / "production.json").read_text(encoding="utf-8")
            )
            ledger.append(
                subject_type="candidate",
                subject_id=candidate.candidate_id,
                cell_id=candidate.cell_id,
                candidate_ordinal=candidate.ordinal,
                lifecycle_stage="qualification",
                reason_code=str(admission["reason_code"]),
                detail=f"candidate rejected: {admission['reason_code']}",
                attribution=admission["attribution"] or (
                    {
                        "side": "qualification",
                        "repetition": None,
                        "check": admission["reason_code"],
                    },
                ),
                n_split=admission["n_split"],
                evidence=[
                    evidence_reference(bundle / "qualification.json", root=root),
                    evidence_reference(admission_path, root=root),
                ],
                config_snapshot_hash=admission["config_snapshot_hash"],
                contract_hashes=contracts.hashes,
                predecessor_candidate_id=production.get("predecessor_candidate_id"),
                successor_candidate_id=None,
                timestamp=qualified_at,
            )
            write_terminal(
                candidate,
                {
                    "schema_version": 1,
                    "candidate_id": candidate.candidate_id,
                    "status": "rejected",
                    "qualification_id": bundle.name,
                    "admission_sha256": sha256_file(admission_path),
                    "regeneration_exhausted": bool(admission["regeneration_exhausted"]),
                    "terminal_at": qualified_at,
                },
            )
            if not admission["regeneration_exhausted"] and replacement_provider is not None:
                if _find_replacement(root, candidate.candidate_id) is None:
                    produce_candidate(
                        candidate.blueprint,
                        output_root=root,
                        provider=replacement_provider,
                        timestamp=qualified_at,
                        _cell_lock_held=True,
                    )
    return _load_existing_result(candidate, bundle, root, replacement_provider)


def _write_transcript(path: Path, record: Mapping[str, Any]) -> None:
    """Append one schema-stable JSON record without rewriting prior records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _validate_qualification_evidence(
    candidate: Candidate,
    bundle: Path,
    root: Path,
    snapshot_hash: str,
    contract_hashes: Mapping[str, str],
    *,
    repetitions: int,
    expected_failure: Mapping[str, str] | None,
    defect_toggles: tuple[str, ...],
) -> tuple[Mapping[str, Any], ...]:
    root = root.resolve()
    bundle = bundle.resolve()
    qualification_path = bundle / "qualification.json"
    try:
        qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateError("qualification evidence is missing or invalid") from exc
    required = {
        "schema_version", "qualification_id", "candidate_id", "cell_id",
        "candidate_ordinal", "runner_id", "provider_mode", "config_snapshot_hash",
        "contract_hashes", "models", "expected_failure", "defect_toggles", "n_split",
        "episodes", "qualified_at",
    }
    if set(qualification) != required or qualification.get("schema_version") != 1:
        raise CandidateError("qualification evidence has an incomplete schema")
    if (
        qualification["qualification_id"] != bundle.name
        or qualification["candidate_id"] != candidate.candidate_id
        or qualification["cell_id"] != candidate.cell_id
        or qualification["candidate_ordinal"] != candidate.ordinal
        or qualification["config_snapshot_hash"] != snapshot_hash
        or qualification["contract_hashes"] != contract_hashes
    ):
        raise CandidateError("qualification evidence identity or configuration mismatch")
    snapshot_path = bundle / "config-snapshot.yaml"
    try:
        snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CandidateError("qualification config snapshot is missing or invalid") from exc
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("snapshot_hash") != snapshot_hash
        or sha256_bytes(
            canonical_json(
                {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
            ).encode("utf-8")
        )
        != snapshot_hash
        or snapshot.get("contract_hashes") != contract_hashes
        or snapshot.get("models") != qualification["models"]
    ):
        raise CandidateError("qualification config snapshot does not match current configuration")
    expected_split = {
        "defects_off": repetitions,
        "defect_on": 0 if expected_failure is None else repetitions,
    }
    if (
        qualification["n_split"] != expected_split
        or qualification["expected_failure"] != expected_failure
        or qualification["defect_toggles"] != list(defect_toggles)
    ):
        raise CandidateError("qualification evidence repetition or defect configuration mismatch")
    expected_count = sum(expected_split.values())
    references = qualification["episodes"]
    if not isinstance(references, list) or len(references) != expected_count:
        raise CandidateError("qualification evidence has incomplete Episodes")
    hydrated: list[Mapping[str, Any]] = []
    inventory = {qualification_path, snapshot_path}
    seen_paths: set[Path] = set()
    expected_episode_ids = {
        (side, repetition)
        for side, count in (
            ("defects-off", expected_split["defects_off"]),
            ("defect-on", expected_split["defect_on"]),
        )
        for repetition in range(count)
    }
    seen_episode_ids: set[tuple[str, int]] = set()
    for reference in references:
        episode_path = _validate_reference(reference, root, suffix=".json")
        if episode_path in seen_paths or episode_path.parent != bundle / "episodes":
            raise CandidateError("qualification evidence has duplicate or foreign Episodes")
        seen_paths.add(episode_path)
        inventory.add(episode_path)
        episode = json.loads(episode_path.read_text(encoding="utf-8"))
        episode_required = {
            "side", "repetition", "defect_toggles", "kind", "outcome", "failures",
            "degraded_checks", "simulator_compliance", "error", "llm_calls",
            "simulator_id", "judge_id", "prompt_hashes", "fixture", "termination",
            "trace", "transcript", "assertion_results", "judge_rulings",
            "simulator_compliance_rulings",
        }
        if set(episode) != episode_required:
            raise CandidateError("Episode evidence has an incomplete schema")
        if (
            episode["simulator_id"] != snapshot["models"]["simulator"]
            or episode["judge_id"] != snapshot["models"]["judge"]
            or episode["prompt_hashes"] != snapshot["prompt_hashes"]
            or episode["fixture"] != snapshot["fixture"]
        ):
            raise CandidateError("Episode evidence configuration mismatch")
        side = episode["side"]
        repetition = episode["repetition"]
        episode_id = (side, repetition)
        expected_toggles = [] if side == "defects-off" else list(defect_toggles)
        if (
            episode_id not in expected_episode_ids
            or episode["defect_toggles"] != expected_toggles
        ):
            raise CandidateError("Episode evidence repetition or defect configuration mismatch")
        seen_episode_ids.add(episode_id)
        stem = f"{side}-{repetition}"
        if episode_path.name != f"{stem}.json":
            raise CandidateError("Episode evidence path does not match its identity")
        nested = {
            "trace": (".json", f"{stem}-trace.json"),
            "transcript": (".jsonl", f"{stem}-transcript.jsonl"),
            "assertion_results": (".json", f"{stem}-assertion-results.json"),
            "judge_rulings": (".json", f"{stem}-judge-rulings.json"),
            "simulator_compliance_rulings": (
                ".json",
                f"{stem}-simulator-compliance-rulings.json",
            ),
        }
        nested_paths = {}
        for key, (suffix, name) in nested.items():
            target = _validate_reference(episode[key], root, suffix=suffix)
            if target.parent != bundle / "episodes" or target.name != name:
                raise CandidateError(f"{key} evidence path does not match its Episode")
            nested_paths[key] = target
            inventory.add(target)
        _validate_transcript(
            nested_paths["transcript"], bundle.name, side, repetition,
            qualification["models"], episode["outcome"],
            episode["termination"],
        )
        trace = json.loads(nested_paths["trace"].read_text(encoding="utf-8"))
        if (
            set(trace) != {"schema_version", "provider", "side", "repetition", "outcome", "turns"}
            or trace["schema_version"] != 1
            or trace["side"] != side
            or trace["repetition"] != repetition
            or trace["outcome"] != episode["outcome"]
            or not isinstance(trace["turns"], list)
        ):
            raise CandidateError("Trace evidence violates its schema or Episode identity")
        assertion_artifact = json.loads(
            nested_paths["assertion_results"].read_text(encoding="utf-8")
        )
        ruling_artifact = json.loads(
            nested_paths["judge_rulings"].read_text(encoding="utf-8")
        )
        compliance_artifact = json.loads(
            nested_paths["simulator_compliance_rulings"].read_text(encoding="utf-8")
        )
        if set(assertion_artifact) != {"schema_version", "results"} or assertion_artifact["schema_version"] != 1:
            raise CandidateError("Assertion result evidence has an incomplete schema")
        if set(ruling_artifact) != {"schema_version", "rulings"} or ruling_artifact["schema_version"] != 1:
            raise CandidateError("Judge ruling evidence has an incomplete schema")
        if (
            set(compliance_artifact) != {"schema_version", "rulings"}
            or compliance_artifact["schema_version"] != 1
            or not isinstance(compliance_artifact["rulings"], list)
        ):
            raise CandidateError("simulator-compliance ruling evidence has an incomplete schema")
        hydrated.append(
            {
                **episode,
                "assertion_results": assertion_artifact["results"],
                "judge_rulings": ruling_artifact["rulings"],
            }
        )
    if seen_episode_ids != expected_episode_ids:
        raise CandidateError("qualification evidence has incomplete Episodes")
    actual = {path for path in bundle.rglob("*") if path.is_file()}
    allowed = inventory | ({bundle / "admission.json"} if (bundle / "admission.json").is_file() else set())
    if actual != allowed:
        raise CandidateError("qualification bundle contains missing or extra evidence artifacts")
    return tuple(hydrated)


def _validate_admission_evidence(
    candidate: Candidate,
    bundle: Path,
    root: Path,
    config: Any,
    contracts: ContractSet,
    *,
    allow_repository_state_drift: bool = False,
) -> Mapping[str, Any]:
    snapshot_path = bundle / "config-snapshot.yaml"
    try:
        persisted_snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CandidateError("qualification config snapshot is missing or invalid") from exc
    if not isinstance(persisted_snapshot, dict):
        raise CandidateError("qualification config snapshot is missing or invalid")
    snapshot_hash = str(persisted_snapshot.get("snapshot_hash", ""))
    current_snapshot = create_config_snapshot(config=config, contracts=contracts)
    if allow_repository_state_drift:
        semantic_keys = {
            "schema_version",
            "config_hash",
            "models",
            "prompt_hashes",
            "fixture",
            "contract_hashes",
        }
        if any(
            persisted_snapshot.get(key) != current_snapshot.content.get(key)
            for key in semantic_keys
        ):
            raise CandidateError("qualification evidence semantic configuration mismatch")
    elif snapshot_hash != current_snapshot.sha256:
        raise CandidateError("qualification evidence identity or configuration mismatch")
    expected_failure, defect_toggles = _fitness_contract(candidate, contracts)
    repetitions = int(config.content["limits"]["admission_repetitions"])
    episodes = _validate_qualification_evidence(
        candidate,
        bundle,
        root,
        snapshot_hash,
        contracts.hashes,
        repetitions=repetitions,
        expected_failure=expected_failure,
        defect_toggles=defect_toggles,
    )
    qualification_path = bundle / "qualification.json"
    qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    admission_path = bundle / "admission.json"
    try:
        admission = json.loads(admission_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateError("admission evidence is missing or invalid") from exc
    required = {
        "schema_version", "qualification_id", "candidate_id", "cell_id",
        "candidate_ordinal", "status", "reason_code", "detection_unproven",
        "attribution", "n_split", "evidence", "config_snapshot_hash",
        "contract_hashes", "regeneration_exhausted", "decided_at",
    }
    if set(admission) != required or admission["schema_version"] != 1:
        raise CandidateError("admission evidence has an incomplete schema")
    if (
        admission["qualification_id"] != bundle.name
        or admission["candidate_id"] != candidate.candidate_id
        or admission["cell_id"] != candidate.cell_id
        or admission["candidate_ordinal"] != candidate.ordinal
        or admission["config_snapshot_hash"] != snapshot_hash
        or admission["contract_hashes"] != contracts.hashes
        or admission["n_split"] != qualification["n_split"]
    ):
        raise CandidateError("admission evidence identity or configuration mismatch")
    expected_references = [
        *qualification["episodes"], evidence_reference(qualification_path, root=root)
    ]
    if admission["evidence"] != expected_references:
        raise CandidateError("admission evidence is incomplete or contains extras")
    for reference in admission["evidence"]:
        _validate_reference(reference, root)
    decision = evaluate_admission(
        episodes,
        expected_failure=expected_failure,
        repetitions=repetitions,
        required_assertions=tuple(
            assertion.type for assertion in candidate.blueprint.required_assertions
        ),
        required_criteria=candidate.blueprint.required_criteria,
    )
    if (
        admission["status"] != decision.status
        or admission["reason_code"] != decision.reason_code
        or admission["detection_unproven"] != decision.detection_unproven
        or admission["attribution"] != [dict(item) for item in decision.attribution]
    ):
        raise CandidateError("admission decision does not match complete evidence")
    return admission


def _validate_evidence_or_reject(
    candidate: Candidate,
    bundle: Path,
    root: Path,
    validate: Callable[[], Any],
) -> Any:
    try:
        return validate()
    except (CandidateError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _record_evidence_rejection(candidate, bundle, root, str(exc))
        if isinstance(exc, CandidateError):
            raise
        raise CandidateError(f"qualification evidence is invalid: {exc}") from exc


def _validate_reference(
    reference: Any, root: Path, *, suffix: str | None = None
) -> Path:
    try:
        target = validate_evidence_reference(reference, root=root)
    except EvidenceReferenceError as exc:
        detail = str(exc)
        if detail == "evidence reference schema is invalid":
            raise CandidateError("evidence reference has an incomplete schema") from exc
        if "relative and contained" in detail:
            raise CandidateError("evidence path escapes the artifact root") from exc
        if detail == "evidence hash mismatch":
            path = reference.get("path", "<unknown>") if isinstance(reference, dict) else "<unknown>"
            raise CandidateError(
                f"qualification evidence hash mismatch: {path}"
            ) from exc
        raise CandidateError(f"qualification evidence is invalid: {detail}") from exc
    if suffix is not None and target.suffix != suffix:
        raise CandidateError("evidence artifact has a non-contract file type")
    return target


def _validate_transcript(
    path: Path,
    qualification_id: str,
    side: str,
    repetition: int,
    models: Mapping[str, str],
    outcome: str,
    termination: str,
) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise CandidateError("Transcript evidence is incomplete")
    try:
        records = [json.loads(line) for line in lines]
    except json.JSONDecodeError as exc:
        raise CandidateError("Transcript evidence is not JSON Lines") from exc
    if any(line != canonical_json(record) for line, record in zip(lines, records)):
        raise CandidateError("Transcript evidence is not canonical JSON Lines")
    if len(records) != 1:
        raise CandidateError("Transcript evidence has an unsupported record sequence")
    record = records[0]
    required = {
        "schema_version", "record_type", "episode_id", "side", "repetition",
        "turns", "termination", "timing", "models",
    }
    if (
        set(record) != required
        or record["schema_version"] != 1
        or record["record_type"] != "episode"
        or record["episode_id"] != f"{qualification_id}:{side}:{repetition}"
        or record["side"] != side
        or record["repetition"] != repetition
        or not isinstance(record["turns"], list)
        or record["models"] != models
        or record["termination"] != {"reason": termination, "outcome": outcome}
        or set(record["timing"]) != {"started_at", "completed_at"}
    ):
        raise CandidateError("Transcript evidence violates the repository contract")


def _record_evidence_rejection(
    candidate: Candidate, bundle: Path, root: Path, detail: str
) -> None:
    config = load_config()
    contracts = load_reviewed_contracts()
    snapshot = create_config_snapshot(config=config, contracts=contracts)
    RejectionLedger(root).append(
        subject_type="qualification",
        subject_id=bundle.name,
        cell_id=candidate.cell_id,
        candidate_ordinal=candidate.ordinal,
        lifecycle_stage="admission",
        reason_code="degraded-error-incomplete-evidence",
        detail=detail,
        attribution=[{
            "side": "qualification", "repetition": None,
            "check": "complete-evidence",
        }],
        n_split={"defects_off": 0, "defect_on": 0},
        evidence=[],
        config_snapshot_hash=snapshot.sha256,
        contract_hashes=contracts.hashes,
    )


def _fitness_contract(
    candidate: Candidate, contracts: ContractSet
) -> tuple[Mapping[str, str] | None, tuple[str, ...]]:
    if candidate.blueprint.fitness_target_id is None:
        return None, ()
    for entry in contracts.contracts["fitness-targets"].content["targets"]:
        if (
            entry["target_id"] == candidate.blueprint.fitness_target_id
            and entry["shape_id"] == candidate.blueprint.fitness_shape_id
        ):
            return dict(entry["expected_failure"]), tuple(entry["defect_toggles"])
    raise CandidateError("candidate fitness target is not in the reviewed contract")


def _admit(
    candidate: Candidate,
    root: Path,
    config: Any,
    contracts: ContractSet,
    *,
    commit: bool,
) -> Path:
    _revalidate_candidate(candidate, config.sha256, contracts)
    scenario = load_synthesized_scenario(candidate.scenario_path)
    library = root / "library"
    library.mkdir(parents=True, exist_ok=True)
    existing = load_synthesized_library(library)
    same_cell_count = sum(
        item.synthesis is not None and item.synthesis.cell_id == candidate.cell_id
        for item in existing
    )
    if same_cell_count >= int(config.content["limits"]["same_cell_library_cap"]):
        raise CandidateError("Same-cell library cap reached")
    target = library / f"{scenario.name}.yaml"
    if target.exists() and target.read_bytes() != candidate.scenario_path.read_bytes():
        raise CandidateError("synthesized Scenario name collision")
    if not commit or target.exists():
        return target
    descriptor, temporary = tempfile.mkstemp(prefix=".admit-", dir=library)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(candidate.scenario_path.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        load_synthesized_scenario(temporary)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if target.read_bytes() != candidate.scenario_path.read_bytes():
        raise CandidateError("admitted Scenario differs from candidate evidence")
    return target


def _find_replacement(root: Path, predecessor_id: str) -> Candidate | None:
    for production_path in (root / "candidates").glob("candidate-*/production.json"):
        production = json.loads(production_path.read_text(encoding="utf-8"))
        if production.get("predecessor_candidate_id") == predecessor_id:
            return load_candidate(root, str(production["candidate_id"]))
    return None


def _runtime_outcome(kind: str) -> str:
    if kind == "pass" or kind == "simulator-compliance-fail":
        return "pass"
    if kind in {"expected-failure", "unexpected-failure"}:
        return "fail"
    return kind


def _check_name(failure: Mapping[str, str]) -> str:
    return f"{failure['source']}:{failure['id']}"


def _attribution(item: Mapping[str, Any], check: str) -> Mapping[str, Any]:
    return {"side": item["side"], "repetition": item["repetition"], "check": check}


def _reject(
    reason_code: str, episodes: Any, check: str
) -> AdmissionDecision:
    return AdmissionDecision(
        False,
        "rejected",
        reason_code,
        False,
        tuple(_attribution(item, check) for item in episodes),
    )
