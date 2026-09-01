"""Strict operational configuration and immutable snapshot construction."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ._strict import (
    _mapping as _shared_mapping,
    _positive_int as _shared_positive_int,
    _strict as _shared_strict,
)
from .contracts import (
    CONTRACT_FILENAMES,
    ROOT,
    ContractSet,
    ContractValidationError,
    canonical_sha256,
    load_reviewed_contracts,
)
from .simulator_compliance import SIMULATOR_COMPLIANCE_CRITERION_IDS

DEFAULT_CONFIG = Path(__file__).with_name("config.yaml")


class ConfigurationError(ValueError):
    """The synthesis configuration is malformed or violates fixed bounds."""


@dataclass(frozen=True)
class SynthesisConfig:
    path: Path
    content: Mapping[str, Any]
    sha256: str


@dataclass(frozen=True)
class ValidationSnapshot:
    content: Mapping[str, Any]
    sha256: str


def load_config(
    path: str | Path = DEFAULT_CONFIG,
    *,
    root: str | Path = ROOT,
) -> SynthesisConfig:
    path = Path(path)
    root = Path(root)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"{path}: cannot load configuration: {exc}") from exc
    raw = _mapping(raw, path.name)
    _strict(
        raw,
        {
            "schema_version", "config_id", "paths", "versions", "models",
            "limits", "output_layout_version", "enforce_model_family_separation",
        },
        path.name,
    )
    schema_version = _positive_int(raw["schema_version"], f"{path.name}.schema_version")
    if schema_version != 1:
        raise ConfigurationError(f"{path.name}.schema_version {schema_version} is unsupported")
    _string(raw["config_id"], f"{path.name}.config_id")

    paths = _mapping(raw["paths"], f"{path.name}.paths")
    _strict(paths, {"contracts", "prompts"}, f"{path.name}.paths")
    contracts = _mapping(paths["contracts"], f"{path.name}.paths.contracts")
    if set(contracts) != set(CONTRACT_FILENAMES):
        raise ConfigurationError(
            f"{path.name}.paths.contracts must contain exactly {sorted(CONTRACT_FILENAMES)}"
        )
    for contract_id, configured_path in contracts.items():
        expected = f"scenario_synthesis/contracts/{CONTRACT_FILENAMES[contract_id]}"
        if configured_path != expected:
            raise ConfigurationError(
                f"{path.name}.paths.contracts.{contract_id} must be {expected!r}"
            )
        _require_file(root, configured_path, f"contract {contract_id}")
    prompts = _mapping(paths["prompts"], f"{path.name}.paths.prompts")
    if not prompts:
        raise ConfigurationError(f"{path.name}.paths.prompts must not be empty")
    for prompt_id, prompt_path in prompts.items():
        _string(prompt_id, f"{path.name}.paths.prompts key")
        _require_file(root, _string(prompt_path, f"{path.name}.paths.prompts.{prompt_id}"), f"prompt {prompt_id}")

    versions = _mapping(raw["versions"], f"{path.name}.versions")
    _strict(versions, {"generator", "realization"}, f"{path.name}.versions")
    _string(versions["generator"], f"{path.name}.versions.generator")
    _string(versions["realization"], f"{path.name}.versions.realization")

    models = _mapping(raw["models"], f"{path.name}.models")
    _strict(models, {"simulator", "judge"}, f"{path.name}.models")
    _string(models["simulator"], f"{path.name}.models.simulator")
    if models["judge"] != "gpt-5.5":
        raise ConfigurationError(f"{path.name}.models.judge must preserve calibrated gpt-5.5")

    limits = _mapping(raw["limits"], f"{path.name}.limits")
    fixed = {
        "admission_repetitions": 3,
        "replacement_bound": 2,
        "same_cell_library_cap": 2,
        "realization_retry_bound": 1,
    }
    expected_limit_fields = {
        "realization_token_budget", "realization_retry_bound",
        "admission_repetitions", "replacement_bound", "same_cell_library_cap",
        "concurrency", "max_cells_per_command",
    }
    _strict(limits, expected_limit_fields, f"{path.name}.limits")
    for key, value in limits.items():
        _positive_int(value, f"{path.name}.limits.{key}")
    for key, value in fixed.items():
        if limits[key] != value:
            raise ConfigurationError(
                f"{path.name}.limits.{key} is fixed at {value}, got {limits[key]!r}"
            )

    _positive_int(raw["output_layout_version"], f"{path.name}.output_layout_version")
    if raw["enforce_model_family_separation"] is not False:
        raise ConfigurationError(
            f"{path.name}.enforce_model_family_separation must remain false before Phase 5"
        )
    return SynthesisConfig(path, raw, canonical_sha256(raw))


def create_config_snapshot(
    *,
    config: SynthesisConfig | None = None,
    contracts: ContractSet | None = None,
    root: str | Path = ROOT,
    destination: str | Path | None = None,
) -> ValidationSnapshot:
    root = Path(root)
    config = config or load_config(root=root, path=root / "scenario_synthesis/config.yaml")
    contracts = contracts or load_reviewed_contracts(root=root)
    prompt_hashes = {
        prompt_id: hashlib.sha256((root / prompt_path).read_bytes()).hexdigest()
        for prompt_id, prompt_path in sorted(config.content["paths"]["prompts"].items())
    }
    fixture_path = root / "fixtures/paycard.py"
    revision, dirty = _repository_state(root)
    material: dict[str, Any] = {
        "schema_version": 1,
        "config_hash": config.sha256,
        "repository_revision": revision,
        "repository_dirty": dirty,
        "models": dict(config.content["models"]),
        "prompt_hashes": prompt_hashes,
        "fixture": {
            "version": "paycard-v1",
            "sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        },
        "contract_hashes": contracts.hashes,
        "simulator_compliance_criterion_ids": list(
            SIMULATOR_COMPLIANCE_CRITERION_IDS
        ),
    }
    snapshot_hash = canonical_sha256(material)
    content = {**material, "snapshot_hash": snapshot_hash}
    if destination is not None:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
    return ValidationSnapshot(content, snapshot_hash)


def validate_all(
    *,
    root: str | Path = ROOT,
    config_path: str | Path | None = None,
) -> tuple[SynthesisConfig, ContractSet, ValidationSnapshot]:
    root = Path(root)
    config = load_config(config_path or root / "scenario_synthesis/config.yaml", root=root)
    configured_contracts = config.content["paths"]["contracts"]
    directories = {(root / relative).parent for relative in configured_contracts.values()}
    if len(directories) != 1:
        raise ConfigurationError("reviewed contracts must share one configured directory")
    try:
        contracts = load_reviewed_contracts(root=root, contract_dir=directories.pop())
    except ContractValidationError:
        raise
    snapshot = create_config_snapshot(config=config, contracts=contracts, root=root)
    return config, contracts, snapshot


def _repository_state(root: Path) -> tuple[str | None, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None, True
    return revision or None, bool(status.strip())


def _require_file(root: Path, relative: str, label: str) -> Path:
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ConfigurationError(f"{label} path escapes repository: {relative}") from exc
    if not target.is_file():
        raise ConfigurationError(f"{label} path does not exist: {relative}")
    return target


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    return _shared_mapping(value, where, error=ConfigurationError)


def _strict(value: Mapping[str, Any], fields: set[str], where: str) -> None:
    return _shared_strict(value, fields, where, error=ConfigurationError)


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{where} must be a non-empty string")
    return value


def _positive_int(value: Any, where: str) -> int:
    return _shared_positive_int(value, where, error=ConfigurationError)
