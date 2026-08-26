from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scenario_synthesis import cli
from scenario_synthesis.config import ConfigurationError, create_config_snapshot, load_config
from scenario_synthesis.contracts import (
    AXIS_ORDER,
    CONTRACT_FILENAMES,
    ROOT,
    ContractValidationError,
    canonical_sha256,
    load_contract,
    load_reviewed_contracts,
)

CONTRACT_DIR = ROOT / "scenario_synthesis/contracts"


def _raw(name: str) -> dict:
    return yaml.safe_load((CONTRACT_DIR / CONTRACT_FILENAMES[name]).read_text())


def _write(tmp_path: Path, name: str, raw: dict) -> Path:
    target = tmp_path / CONTRACT_FILENAMES[name]
    target.write_text(yaml.safe_dump(raw, sort_keys=False))
    return target


def test_complete_reviewed_contract_set_loads_with_authoritative_hashes() -> None:
    contracts = load_reviewed_contracts()
    assert set(contracts.contracts) == set(CONTRACT_FILENAMES)
    assert all(len(value) == 64 for value in contracts.hashes.values())
    assert all(
        contract.content["schema_version"] == 1
        for contract in contracts.contracts.values()
    )
    assert all(contract.content["dependencies"] for contract in contracts.contracts.values())


def test_reviewed_contracts_reject_unknown_fields(tmp_path: Path) -> None:
    raw = _raw("persona-archetypes")
    raw["archetypes"][0]["behavioral_prose"] = "parallel authority"
    with pytest.raises(ContractValidationError, match="unknown field"):
        load_contract(
            _write(tmp_path, "persona-archetypes", raw),
            expected_id="persona-archetypes",
            root=ROOT,
        )


@pytest.mark.parametrize("schema_version", [0, -1, True, "1"])
def test_reviewed_contracts_require_positive_integer_schema_versions(
    tmp_path: Path, schema_version: object
) -> None:
    raw = _raw("pair-exclusions")
    raw["schema_version"] = schema_version
    with pytest.raises(ContractValidationError, match="positive integer"):
        load_contract(
            _write(tmp_path, "pair-exclusions", raw),
            expected_id="pair-exclusions",
            root=ROOT,
        )


def test_reviewed_contracts_reject_unsupported_schema_versions(tmp_path: Path) -> None:
    raw = _raw("pair-exclusions")
    raw["schema_version"] = 2
    with pytest.raises(ContractValidationError, match="unsupported"):
        load_contract(
            _write(tmp_path, "pair-exclusions", raw),
            expected_id="pair-exclusions",
            root=ROOT,
        )


def test_canonical_hash_vector_is_format_and_key_order_independent() -> None:
    first = {"z": True, "a": [1, {"b": "é"}]}
    second = yaml.safe_load("a: [1, {b: é}]\nz: true\n")
    assert canonical_sha256(first) == canonical_sha256(second)
    assert canonical_sha256(first) == "9f45287d73534f6f618df55e237e8d4014cb4c570b487fd322688cfc4f59503c"


def test_stale_dependency_fails_closed(tmp_path: Path) -> None:
    raw = _raw("persona-archetypes")
    raw["dependencies"]["curated-persona-mapping"]["sha256"] = "0" * 64
    with pytest.raises(ContractValidationError, match="stale dependency"):
        load_contract(
            _write(tmp_path, "persona-archetypes", raw),
            expected_id="persona-archetypes",
            root=ROOT,
        )


def _exclusion() -> dict:
    return {
        "axis_a": "persona-archetype",
        "value_a": "cooperative",
        "axis_b": "complication",
        "value_b": "goal-shift",
        "reason_code": "approved-axis-non-applicability",
        "rationale": "Reviewed test fixture entry.",
        "evidence_refs": ["docs/adrs/0004-default-pairs-to-eligible-with-reviewed-exclusions.md"],
        "reviewer": "contract-test",
        "review_date": "2026-08-26",
    }


def test_pair_exclusions_require_canonical_order_and_uniqueness(tmp_path: Path) -> None:
    raw = _raw("pair-exclusions")
    entry = _exclusion()
    raw["exclusions"] = [entry, dict(entry)]
    with pytest.raises(ContractValidationError, match="duplicate canonical pair"):
        load_contract(
            _write(tmp_path, "pair-exclusions", raw),
            expected_id="pair-exclusions",
            root=ROOT,
        )

    entry["axis_a"], entry["axis_b"] = entry["axis_b"], entry["axis_a"]
    entry["value_a"], entry["value_b"] = entry["value_b"], entry["value_a"]
    raw["exclusions"] = [entry]
    with pytest.raises(ContractValidationError, match="canonical axis/value order"):
        load_contract(
            _write(tmp_path, "pair-exclusions", raw),
            expected_id="pair-exclusions",
            root=ROOT,
        )
    assert AXIS_ORDER.index("persona-archetype") < AXIS_ORDER.index("complication")


def test_fixture_bindings_belong_to_exactly_one_class() -> None:
    classes = load_reviewed_contracts().contracts["fixture-state-classes"].content["classes"]
    memberships = [
        (tuple(binding["cards"]), tuple(binding["accounts"]))
        for fixture_class in classes
        for binding in fixture_class["bindings"]
    ]
    assert len(memberships) == 21
    assert len(memberships) == len(set(memberships))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("defect_toggles", ["not_a_mock_toggle"], "mock defect toggle"),
        ("expected_failure", {"source": "assertion", "id": "not_registered"}, "unregistered assertion"),
    ],
)
def test_fitness_targets_validate_directly_against_runtime_registries(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    raw = _raw("fitness-targets")
    raw["targets"][0][field] = value
    with pytest.raises(ContractValidationError, match=message):
        load_contract(
            _write(tmp_path, "fitness-targets", raw),
            expected_id="fitness-targets",
            root=ROOT,
        )


def test_config_is_strict_and_snapshot_is_self_identifying(tmp_path: Path) -> None:
    config = load_config()
    contracts = load_reviewed_contracts()
    destination = tmp_path / "config-snapshot.yaml"
    snapshot = create_config_snapshot(
        config=config, contracts=contracts, destination=destination
    )
    written = yaml.safe_load(destination.read_text())
    assert written["snapshot_hash"] == snapshot.sha256
    assert canonical_sha256({k: v for k, v in written.items() if k != "snapshot_hash"}) == snapshot.sha256
    assert written["contract_hashes"] == contracts.hashes

    raw = dict(config.content)
    raw["unexpected"] = True
    bad = tmp_path / "config.yaml"
    bad.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(ConfigurationError, match="unknown field"):
        load_config(bad)


def test_validate_contracts_cli_is_offline_and_end_to_end(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import agentsim.llm

    monkeypatch.setattr(
        agentsim.llm,
        "_get_client",
        lambda: pytest.fail("validate-contracts constructed an LLM client"),
    )
    assert cli.main(["validate-contracts"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "valid"
    assert set(result["contract_hashes"]) == set(CONTRACT_FILENAMES)


@pytest.mark.parametrize(
    "command", ["plan", "produce", "qualify", "report", "check-completion"]
)
def test_later_slice_commands_are_explicitly_not_implemented(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([command])
    assert exc.value.code == 2
    assert "not implemented" in capsys.readouterr().err
