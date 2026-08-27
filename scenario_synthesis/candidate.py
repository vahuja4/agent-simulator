"""Offline candidate production and immutable candidate-bundle handling."""

from __future__ import annotations

import json
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from agentsim.scenario import load_synthesized_scenario

from .blueprint import CoverageBlueprint, dump_coverage_blueprint, load_coverage_blueprint
from .config import create_config_snapshot, load_config
from .contracts import load_reviewed_contracts
from .evidence import (
    atomic_json,
    canonical_json,
    evidence_reference,
    sha256_bytes,
    sha256_file,
)
from .ledger import RejectionLedger, exclusive_lock
from .realization_provider import RealizationError, RealizationProvider, validate_surface
from .validator import CoverageBlueprintValidator


class CandidateError(RuntimeError):
    """Candidate lifecycle preconditions are not satisfied."""


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    cell_id: str
    ordinal: int
    bundle: Path
    blueprint: CoverageBlueprint

    @property
    def scenario_path(self) -> Path:
        return self.bundle / "scenario.yaml"


def produce_candidate(
    blueprint: CoverageBlueprint,
    *,
    output_root: str | Path,
    provider: RealizationProvider,
    timestamp: str | None = None,
    _cell_lock_held: bool = False,
) -> Candidate | None:
    """Try twice to realize the next candidate ordinal; failed calls consume no K slot."""
    root = Path(output_root)
    contracts = load_reviewed_contracts()
    config = load_config()
    snapshot = create_config_snapshot(config=config, contracts=contracts)
    CoverageBlueprintValidator(contracts=contracts).validate(blueprint)
    if blueprint.provenance.config_hash != config.sha256:
        raise CandidateError("blueprint configuration has drifted")
    replacement_bound = int(config.content["limits"]["replacement_bound"])
    cell_lock = root / "locks" / f"{blueprint.cell_id}.lock"
    produced_at = timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    command_id = "production-command-" + uuid.uuid4().hex
    failures: list[dict[str, Any]] = []
    lock_context = nullcontext() if _cell_lock_held else exclusive_lock(cell_lock, command="produce")
    with lock_context:
        ordinal, predecessor = _next_ordinal(root, blueprint.cell_id)
        if ordinal > replacement_bound:
            raise CandidateError("candidate regeneration budget is exhausted")
        for attempt_index in range(int(config.content["limits"]["realization_retry_bound"]) + 1):
            attempt_id = "realization-attempt-" + uuid.uuid4().hex
            try:
                raw_surface = provider.realize(
                    blueprint, candidate_ordinal=ordinal, attempt=attempt_index
                )
                surface = validate_surface(blueprint, raw_surface)
            except RealizationError as exc:
                attempt = {
                    "schema_version": 1,
                    "realization_attempt_id": attempt_id,
                    "production_command_id": command_id,
                    "cell_id": blueprint.cell_id,
                    "candidate_ordinal": ordinal,
                    "attempt_index": attempt_index,
                    "provider_id": provider.provider_id,
                    "status": "failed",
                    "reason_code": exc.reason_code,
                    "detail": str(exc),
                    "timestamp": produced_at,
                }
                attempt_path = root / "candidates/production-attempts" / f"{attempt_id}.json"
                atomic_json(attempt_path, attempt)
                RejectionLedger(root).append(
                    subject_type="realization-attempt",
                    subject_id=attempt_id,
                    cell_id=blueprint.cell_id,
                    candidate_ordinal=None,
                    lifecycle_stage="production",
                    reason_code=exc.reason_code,
                    detail=str(exc),
                    attribution=[{"side": "production", "repetition": None, "check": exc.reason_code}],
                    n_split={"defects_off": 0, "defect_on": 0},
                    evidence=[evidence_reference(attempt_path, root=root)],
                    config_snapshot_hash=snapshot.sha256,
                    contract_hashes=contracts.hashes,
                    predecessor_candidate_id=predecessor,
                    timestamp=produced_at,
                )
                failures.append(attempt)
                continue
            scenario_without_identity = _scenario_material(blueprint, surface)
            candidate_id = _candidate_id(blueprint, ordinal, scenario_without_identity)
            scenario = {
                **scenario_without_identity,
                "synthesis": {
                    "schema_version": 1,
                    "origin": "synthesized",
                    "candidate_id": candidate_id,
                    "blueprint_id": blueprint.blueprint_id,
                    "cell_id": blueprint.cell_id,
                    "blueprint_content_hash": blueprint.blueprint_id.removeprefix("blueprint-"),
                },
            }
            bundle = root / "candidates" / candidate_id
            if bundle.exists():
                existing = load_candidate(root, candidate_id)
                if existing.cell_id != blueprint.cell_id or existing.ordinal != ordinal:
                    raise CandidateError("candidate ID collision")
                return existing
            bundle.mkdir(parents=True)
            dump_coverage_blueprint(blueprint, bundle / "blueprint.yaml")
            (bundle / "scenario.yaml").write_text(
                yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8"
            )
            load_synthesized_scenario(bundle / "scenario.yaml")
            bundle_hashes = {
                "blueprint.yaml": sha256_file(bundle / "blueprint.yaml"),
                "scenario.yaml": sha256_file(bundle / "scenario.yaml"),
            }
            production_record = {
                    "schema_version": 1,
                    "production_command_id": command_id,
                    "candidate_id": candidate_id,
                    "cell_id": blueprint.cell_id,
                    "candidate_ordinal": ordinal,
                    "provider_id": provider.provider_id,
                    "realization_attempt_id": attempt_id,
                    "failed_attempts": failures,
                    "predecessor_candidate_id": predecessor,
                    "config_snapshot_hash": snapshot.sha256,
                    "contract_hashes": contracts.hashes,
                    "bundle_hashes": bundle_hashes,
                    "produced_at": produced_at,
                }
            production_record["record_hash"] = sha256_bytes(
                canonical_json(production_record).encode("utf-8")
            )
            atomic_json(bundle / "production.json", production_record)
            return Candidate(candidate_id, blueprint.cell_id, ordinal, bundle, blueprint)
    return None


def load_candidate(output_root: str | Path, candidate_id: str) -> Candidate:
    bundle = Path(output_root) / "candidates" / candidate_id
    production = json.loads((bundle / "production.json").read_text(encoding="utf-8"))
    production_material = dict(production)
    record_hash = production_material.pop("record_hash", None)
    if record_hash != sha256_bytes(canonical_json(production_material).encode("utf-8")):
        raise CandidateError("candidate production record hash mismatch")
    blueprint = load_coverage_blueprint(bundle / "blueprint.yaml")
    scenario = load_synthesized_scenario(bundle / "scenario.yaml")
    raw_scenario = yaml.safe_load((bundle / "scenario.yaml").read_text(encoding="utf-8"))
    raw_scenario.pop("synthesis")
    ordinal = int(production["candidate_ordinal"])
    if _candidate_id(blueprint, ordinal, raw_scenario) != candidate_id:
        raise CandidateError("candidate ID does not match ordinal and normalized content")
    if scenario.synthesis is None or scenario.synthesis.candidate_id != candidate_id:
        raise CandidateError("candidate scenario identity mismatch")
    if production["candidate_id"] != candidate_id or production["cell_id"] != blueprint.cell_id:
        raise CandidateError("candidate production identity mismatch")
    expected_hashes = production.get("bundle_hashes", {})
    actual_hashes = {
        "blueprint.yaml": sha256_file(bundle / "blueprint.yaml"),
        "scenario.yaml": sha256_file(bundle / "scenario.yaml"),
    }
    if expected_hashes != actual_hashes:
        raise CandidateError("candidate bundle hash mismatch")
    return Candidate(
        candidate_id, blueprint.cell_id, ordinal, bundle, blueprint
    )


def write_terminal(candidate: Candidate, record: Mapping[str, Any]) -> None:
    target = candidate.bundle / "terminal.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != record:
            raise CandidateError("candidate already has a different terminal state")
        return
    atomic_json(target, dict(record))


def _next_ordinal(root: Path, cell_id: str) -> tuple[int, str | None]:
    found: list[tuple[int, str, Path]] = []
    candidates = root / "candidates"
    if candidates.exists():
        for production_path in candidates.glob("candidate-*/production.json"):
            production = json.loads(production_path.read_text(encoding="utf-8"))
            if production.get("cell_id") == cell_id:
                found.append(
                    (int(production["candidate_ordinal"]), str(production["candidate_id"]), production_path.parent)
                )
    if not found:
        return 0, None
    ordinal, candidate_id, bundle = max(found)
    terminal_path = bundle / "terminal.json"
    if not terminal_path.exists():
        raise CandidateError(f"candidate {candidate_id} is not terminal")
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    if terminal.get("status") == "admitted":
        raise CandidateError("cell already has an admitted candidate")
    if terminal.get("status") != "rejected":
        raise CandidateError("candidate terminal status is invalid")
    return ordinal + 1, candidate_id


def _scenario_material(
    blueprint: CoverageBlueprint, surface: Mapping[str, Any]
) -> dict[str, Any]:
    surface_hash = sha256_bytes(canonical_json(surface).encode("utf-8"))
    journey = blueprint.journey_path_id.split("-path-", 1)[0].upper()
    return {
        "name": f"synth-{blueprint.cell_id[5:17]}-{surface_hash[:12]}",
        "journey": journey,
        "description": surface["description"],
        "persona": dict(surface["persona"]),
        "goal": surface["goal"],
        "knowledge": {
            "cards": list(blueprint.fixture_bindings.cards),
            "accounts": list(blueprint.fixture_bindings.accounts),
        },
        "success_criteria": list(surface["success_criteria"]),
        "max_turns": blueprint.max_turns,
        "tool_assertions": [
            {"type": item.type, **item.fields} for item in blueprint.required_assertions
        ],
    }


def _candidate_id(
    blueprint: CoverageBlueprint, ordinal: int, scenario_without_identity: Mapping[str, Any]
) -> str:
    identity_material = {
        "blueprint": blueprint.to_dict(),
        "candidate_ordinal": ordinal,
        "scenario": dict(scenario_without_identity),
    }
    return "candidate-" + sha256_bytes(
        canonical_json(identity_material).encode("utf-8")
    )
