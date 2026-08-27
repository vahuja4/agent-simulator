"""Pure offline qualification evidence and two-sided admission evaluation."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

import yaml

from agentsim.scenario import Scenario, load_synthesized_library, load_synthesized_scenario

from .candidate import Candidate, CandidateError, load_candidate, produce_candidate, write_terminal
from .config import create_config_snapshot, load_config
from .contracts import ContractSet, load_reviewed_contracts
from .evidence import (
    atomic_json,
    atomic_text,
    canonical_json,
    evidence_reference,
    sha256_bytes,
    sha256_file,
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
            "llm_calls": 0,
        }


class QualificationRunner(Protocol):
    runner_id: str

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
        assertion_ids = {result["id"] for result in item.get("assertion_results", [])}
        criterion_ids = {result["id"] for result in item.get("judge_rulings", [])}
        if assertion_ids != set(required_assertions) or criterion_ids != set(required_criteria):
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
        return _load_existing_result(candidate, bundle, root, replacement_provider)
    if bundle.exists():
        if (bundle / "qualification.json").is_file() and (bundle / "admission.json").is_file():
            return _resume_incomplete(
                candidate, bundle, root, replacement_provider, config, contracts
            )
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
        episode_records: list[Mapping[str, Any]] = []
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
                judge_rulings = [
                    {
                        "id": criterion,
                        "passed": not any(
                            failure["source"] == "judge" and failure["id"] == criterion
                            for failure in record["failures"]
                        ),
                    }
                    for criterion in candidate.blueprint.required_criteria
                ]
                record.update(
                    {
                        "simulator_id": config.content["models"]["simulator"],
                        "judge_id": config.content["models"]["judge"],
                        "prompt_hashes": dict(snapshot.content["prompt_hashes"]),
                        "fixture": dict(snapshot.content["fixture"]),
                        "termination": "stub-completed",
                        "assertion_results": assertion_results,
                        "judge_rulings": judge_rulings,
                    }
                )
                stem = f"{side}-{repetition}"
                trace_path = bundle / "episodes" / f"{stem}-trace.json"
                transcript_path = bundle / "episodes" / f"{stem}-transcript.md"
                atomic_json(
                    trace_path,
                    {
                        "schema_version": 1,
                        "provider": runner.runner_id,
                        "side": side,
                        "repetition": repetition,
                        "outcome": record["outcome"],
                        "turns": [],
                    },
                )
                atomic_text(
                    transcript_path,
                    f"# Offline stub episode\n\nSide: `{side}`\n\nOutcome: `{record['outcome']}`\n",
                )
                record["trace"] = evidence_reference(trace_path, root=root)
                record["transcript"] = evidence_reference(transcript_path, root=root)
                episode_path = bundle / "episodes" / f"{side}-{repetition}.json"
                atomic_json(episode_path, record)
                episode_records.append(record)
                episode_refs.append(evidence_reference(episode_path, root=root))
        decision = evaluate_admission(
            tuple(episode_records),
            expected_failure=expected_failure,
            repetitions=repetitions,
            required_assertions=tuple(
                assertion.type for assertion in candidate.blueprint.required_assertions
            ),
            required_criteria=candidate.blueprint.required_criteria,
        )
        qualification_record = {
            "schema_version": 1,
            "qualification_id": qualification_id,
            "candidate_id": candidate_id,
            "cell_id": candidate.cell_id,
            "candidate_ordinal": candidate.ordinal,
            "runner_id": runner.runner_id,
            "provider_mode": "offline-stub",
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
        library_path: Path | None = None
        replacement: Candidate | None = None
        exhausted = not decision.admitted and candidate.ordinal >= int(
            config.content["limits"]["replacement_bound"]
        )
        admission_record = {
            "schema_version": 1,
            "qualification_id": qualification_id,
            "candidate_id": candidate_id,
            "cell_id": candidate.cell_id,
            "candidate_ordinal": candidate.ordinal,
            "status": decision.status,
            "reason_code": decision.reason_code,
            "detection_unproven": decision.detection_unproven,
            "attribution": [dict(item) for item in decision.attribution],
            "n_split": qualification_record["n_split"],
            "evidence": [*episode_refs, evidence_reference(qualification_path, root=root)],
            "config_snapshot_hash": snapshot.sha256,
            "contract_hashes": contracts.hashes,
            "regeneration_exhausted": exhausted,
            "decided_at": qualified_at,
        }
        admission_path = bundle / "admission.json"
        atomic_json(admission_path, admission_record)
        if decision.admitted:
            RejectionLedger(root).records()
            library_path = _admit(candidate, root, config, contracts, commit=False)
            terminal = {
                "schema_version": 1,
                "candidate_id": candidate_id,
                "status": "admitted",
                "qualification_id": qualification_id,
                "admission_sha256": sha256_file(admission_path),
                "library_path": str(library_path.relative_to(root)),
                "detection_unproven": decision.detection_unproven,
                "terminal_at": qualified_at,
            }
            write_terminal(candidate, terminal)
            library_path = _admit(candidate, root, config, contracts, commit=True)
        else:
            terminal = {
                "schema_version": 1,
                "candidate_id": candidate_id,
                "status": "rejected",
                "qualification_id": qualification_id,
                "admission_sha256": sha256_file(admission_path),
                "regeneration_exhausted": exhausted,
                "terminal_at": qualified_at,
            }
            attribution = decision.attribution or (
                {"side": "qualification", "repetition": None, "check": decision.reason_code},
            )
            RejectionLedger(root).append(
                subject_type="candidate",
                subject_id=candidate_id,
                cell_id=candidate.cell_id,
                candidate_ordinal=candidate.ordinal,
                lifecycle_stage="qualification",
                reason_code=str(decision.reason_code),
                detail=f"candidate rejected: {decision.reason_code}",
                attribution=attribution,
                n_split=qualification_record["n_split"],
                evidence=[
                    evidence_reference(qualification_path, root=root),
                    evidence_reference(admission_path, root=root),
                ],
                config_snapshot_hash=snapshot.sha256,
                contract_hashes=contracts.hashes,
                predecessor_candidate_id=json.loads(
                    (candidate.bundle / "production.json").read_text(encoding="utf-8")
                ).get("predecessor_candidate_id"),
                successor_candidate_id=None,
                timestamp=qualified_at,
            )
            write_terminal(candidate, terminal)
            if not exhausted and replacement_provider is not None:
                replacement = produce_candidate(
                    candidate.blueprint,
                    output_root=root,
                    provider=replacement_provider,
                    timestamp=qualified_at,
                    _cell_lock_held=True,
                )
        return QualificationResult(
            qualification_id, bundle, candidate, decision, library_path, replacement
        )


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
    terminal = json.loads((candidate.bundle / "terminal.json").read_text(encoding="utf-8"))
    admission_path = bundle / "admission.json"
    if not admission_path.is_file() or terminal.get("qualification_id") != bundle.name:
        raise CandidateError("terminal candidate has incomplete qualification evidence")
    if terminal.get("admission_sha256") != sha256_file(admission_path):
        raise CandidateError("terminal admission evidence hash mismatch")
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    for reference in admission.get("evidence", []):
        target = root / reference["path"]
        if not target.is_file() or sha256_file(target) != reference["sha256"]:
            raise CandidateError(f"qualification evidence hash mismatch: {reference['path']}")
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
            config = load_config()
            contracts = load_reviewed_contracts()
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
) -> QualificationResult:
    """Finish the commit steps without moving evidence already referenced by the ledger."""
    admission_path = bundle / "admission.json"
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    if (
        admission.get("candidate_id") != candidate.candidate_id
        or admission.get("qualification_id") != bundle.name
        or admission.get("config_snapshot_hash")
        != create_config_snapshot(config=config, contracts=contracts).sha256
        or admission.get("contract_hashes") != contracts.hashes
    ):
        raise CandidateError("partial qualification evidence does not match current contracts")
    for reference in admission.get("evidence", []):
        target = root / reference["path"]
        if not target.is_file() or sha256_file(target) != reference["sha256"]:
            raise CandidateError(f"qualification evidence hash mismatch: {reference['path']}")
    qualified_at = str(admission["decided_at"])
    with exclusive_lock(root / "locks" / f"{candidate.cell_id}.lock", command="resume-qualify"):
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
