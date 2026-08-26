"""Strict loaders and validators for the reviewed Phase 4.5 contracts."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from agentsim.adapters import MockConfig
from agentsim.criteria import SPECIALISTS
from agentsim.judge import DEFAULT_CRITERIA
from agentsim.scenario import _ASSERTION_TYPES
from fixtures.paycard import CARDS, FUNDING_ACCOUNTS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT_DIR = Path(__file__).with_name("contracts")
CONTRACT_FILENAMES = {
    "persona-archetypes": "persona-archetypes.yaml",
    "complication-applicability": "complication-applicability.yaml",
    "pair-exclusions": "pair-exclusions.yaml",
    "fixture-state-classes": "fixture-state-classes.yaml",
    "fitness-targets": "fitness-targets.yaml",
}

ARCHETYPE_IDS = {"cooperative", "pressure", "vigilant", "persistent"}
COMPLICATION_IDS = {
    "none",
    "underspecification",
    "mid-conversation-correction",
    "goal-shift",
    "multi-intent-turn",
    "false-premise",
    "out-of-scope-drift",
    "channel-noise",
    "ambiguous-reference",
}
KNOWLEDGE_LEVELS = {"low", "medium", "high"}
AXIS_ORDER = (
    "journey-path",
    "persona-archetype",
    "knowledge-level",
    "complication",
    "fixture-state-class",
    "fitness-target",
)
EXCLUSION_REASON_CODES = {
    "approved-contract-contradiction",
    "journey-graph-impossibility",
    "fixture-domain-impossibility",
    "approved-axis-non-applicability",
}
DEPENDENCY_MODES = {"canonical-yaml", "bytes"}
SUPPORTED_SCHEMA_VERSION = 1
STABLE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FIXTURE_CLASS_PREDICATES = {
    "has_card", "has_account", "multiple_cards",
    "distinguishable_card_amounts", "ambiguous_card_names",
}
APPLICABILITY_FIXTURE_PREDICATES = FIXTURE_CLASS_PREDICATES | {
    "has_real_fixture_fact", "external_account",
}


class ContractValidationError(ValueError):
    """A reviewed contract is malformed, inconsistent, or stale."""


@dataclass(frozen=True)
class ReviewedContract:
    contract_id: str
    path: Path
    content: Mapping[str, Any]
    sha256: str


@dataclass(frozen=True)
class ContractSet:
    contracts: Mapping[str, ReviewedContract]
    graph: Mapping[str, Any]

    @property
    def hashes(self) -> dict[str, str]:
        return {
            contract_id: contract.sha256
            for contract_id, contract in sorted(self.contracts.items())
        }


def canonical_json_bytes(value: Any) -> bytes:
    """Return the single normalized representation used for semantic hashes."""
    _validate_canonical_value(value, "value")
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def dependency_sha256(path: Path, mode: str) -> str:
    if mode == "bytes":
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if mode == "canonical-yaml":
        return canonical_sha256(_load_yaml(path))
    raise ContractValidationError(f"unknown dependency hash mode {mode!r}")


def load_contract(
    path: str | Path,
    *,
    expected_id: str | None = None,
    root: str | Path = ROOT,
    verify_dependencies: bool = True,
) -> ReviewedContract:
    path = Path(path)
    raw = _mapping(_load_yaml(path), path.name)
    contract_id = _nonempty_string(raw.get("contract_id"), f"{path.name}.contract_id")
    payload_fields = {
        "persona-archetypes": {"archetypes", "mappings"},
        "complication-applicability": {"complications"},
        "pair-exclusions": {"exclusions"},
        "fixture-state-classes": {"classes"},
        "fitness-targets": {"targets"},
    }.get(contract_id)
    if payload_fields is None:
        raise ContractValidationError(f"{path.name}: unknown contract_id {contract_id!r}")
    _strict(raw, {"schema_version", "contract_id", "dependencies", *payload_fields}, path.name)
    schema_version = _positive_int(raw.get("schema_version"), f"{path.name}.schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ContractValidationError(
            f"{path.name}.schema_version {schema_version} is unsupported"
        )
    if expected_id is not None and contract_id != expected_id:
        raise ContractValidationError(
            f"{path.name}.contract_id must be {expected_id!r}, got {contract_id!r}"
        )
    dependencies = _mapping(raw.get("dependencies"), f"{path.name}.dependencies")
    _validate_dependencies(dependencies, root=Path(root), where=path.name, verify=verify_dependencies)
    validators = {
        "persona-archetypes": _validate_persona_archetypes,
        "complication-applicability": _validate_complication_applicability,
        "pair-exclusions": _validate_pair_exclusions,
        "fixture-state-classes": _validate_fixture_state_classes,
        "fitness-targets": _validate_fitness_targets,
    }
    validator = validators.get(contract_id)
    if validator is None:
        raise ContractValidationError(f"{path.name}: unknown contract_id {contract_id!r}")
    validator(raw, Path(root))
    return ReviewedContract(contract_id, path, raw, canonical_sha256(raw))


def load_reviewed_contracts(
    *,
    root: str | Path = ROOT,
    contract_dir: str | Path | None = None,
    verify_dependencies: bool = True,
) -> ContractSet:
    root = Path(root)
    directory = Path(contract_dir) if contract_dir is not None else root / "scenario_synthesis/contracts"
    loaded = {
        contract_id: load_contract(
            directory / filename,
            expected_id=contract_id,
            root=root,
            verify_dependencies=verify_dependencies,
        )
        for contract_id, filename in CONTRACT_FILENAMES.items()
    }
    graph = _mapping(
        _load_yaml(root / "scenario_synthesis/procedures/j1.yaml"), "J1 graph"
    )
    _validate_contract_set(loaded, graph, root)
    return ContractSet(loaded, graph)


def fitness_entries_for_policies(
    policy_ids: Sequence[str],
    *,
    contracts: ContractSet | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """Resolve legacy prototype policies through the authoritative contract."""
    contracts = contracts or load_reviewed_contracts()
    entries = contracts.contracts["fitness-targets"].content["targets"]
    chosen = set(policy_ids)
    return tuple(
        entry
        for entry in entries
        if chosen.intersection(entry["applicability"]["policy_ids"])
    )


def fitness_checks_for_policies(
    policy_ids: Sequence[str],
    *,
    contracts: ContractSet | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    assertions: set[str] = set()
    criteria: set[str] = set()
    for entry in fitness_entries_for_policies(policy_ids, contracts=contracts):
        failure = entry["expected_failure"]
        if failure["source"] == "assertion":
            assertions.add(failure["id"])
        else:
            criteria.add(failure["id"])
    return tuple(sorted(assertions)), tuple(sorted(criteria))


def _validate_dependencies(
    dependencies: Mapping[str, Any], *, root: Path, where: str, verify: bool
) -> None:
    for dependency_id, value in dependencies.items():
        _stable_id(dependency_id, f"{where}.dependencies key")
        item = _mapping(value, f"{where}.dependencies.{dependency_id}")
        _strict(item, {"path", "hash_mode", "sha256"}, f"{where}.dependencies.{dependency_id}")
        relative = _nonempty_string(item.get("path"), f"{where}.dependencies.{dependency_id}.path")
        mode = _enum(item.get("hash_mode"), DEPENDENCY_MODES, f"{where}.dependencies.{dependency_id}.hash_mode")
        expected = _sha256_string(item.get("sha256"), f"{where}.dependencies.{dependency_id}.sha256")
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise ContractValidationError(f"{where}: dependency path escapes repository: {relative}") from exc
        if not target.is_file():
            raise ContractValidationError(f"{where}: dependency does not exist: {relative}")
        if verify:
            actual = dependency_sha256(target, mode)
            if actual != expected:
                raise ContractValidationError(
                    f"{where}: stale dependency {dependency_id!r}: expected {expected}, got {actual}"
                )


def _validate_persona_archetypes(raw: Mapping[str, Any], root: Path) -> None:
    items = _mapping_list(raw["archetypes"], "persona-archetypes.archetypes")
    ids: list[str] = []
    for index, item in enumerate(items):
        where = f"persona-archetypes.archetypes[{index}]"
        _strict(item, {"id", "decision_ref", "behavior_contract_ref"}, where)
        ids.append(_stable_id(item.get("id"), f"{where}.id"))
        _reference(item.get("decision_ref"), f"{where}.decision_ref")
        behavior_ref = item.get("behavior_contract_ref")
        if behavior_ref is not None:
            _reference(behavior_ref, f"{where}.behavior_contract_ref")
    _exact_ids(ids, ARCHETYPE_IDS, "persona archetypes")

    mappings = _mapping_list(raw["mappings"], "persona-archetypes.mappings")
    mapped: dict[str, str] = {}
    for index, item in enumerate(mappings):
        where = f"persona-archetypes.mappings[{index}]"
        _strict(item, {"scenario_id", "archetype_id", "evidence_ref"}, where)
        scenario_id = _stable_id(item.get("scenario_id"), f"{where}.scenario_id")
        archetype_id = _enum(item.get("archetype_id"), ARCHETYPE_IDS, f"{where}.archetype_id")
        _reference(item.get("evidence_ref"), f"{where}.evidence_ref")
        if scenario_id in mapped:
            raise ContractValidationError(f"duplicate curated Scenario mapping {scenario_id!r}")
        mapped[scenario_id] = archetype_id
    curated = {
        _nonempty_string(_mapping(_load_yaml(path), path.name).get("name"), f"{path.name}.name")
        for path in (root / "scenarios").glob("*.yaml")
    }
    if set(mapped) != curated:
        raise ContractValidationError(
            f"curated Scenario mapping mismatch: missing={sorted(curated - set(mapped))}, "
            f"unknown={sorted(set(mapped) - curated)}"
        )


def _validate_complication_applicability(raw: Mapping[str, Any], root: Path) -> None:
    del root
    entries = _mapping_list(raw["complications"], "complication-applicability.complications")
    ids: list[str] = []
    for index, item in enumerate(entries):
        where = f"complication-applicability.complications[{index}]"
        _strict(
            item,
            {"id", "required_edge_ids", "required_event_ids", "fixture_predicates", "review"},
            where,
        )
        ids.append(_stable_id(item.get("id"), f"{where}.id"))
        _unique_strings(item.get("required_edge_ids"), f"{where}.required_edge_ids")
        _unique_strings(item.get("required_event_ids"), f"{where}.required_event_ids")
        predicates = set(_unique_strings(item.get("fixture_predicates"), f"{where}.fixture_predicates"))
        if predicates - APPLICABILITY_FIXTURE_PREDICATES:
            raise ContractValidationError(
                f"{where}.fixture_predicates contains unknown predicate(s) {sorted(predicates - APPLICABILITY_FIXTURE_PREDICATES)}"
            )
        review = _mapping(item.get("review"), f"{where}.review")
        _strict(review, {"state", "evidence_refs"}, f"{where}.review")
        _enum(review.get("state"), {"approved", "designed-not-empirically-validated"}, f"{where}.review.state")
        refs = _unique_strings(review.get("evidence_refs"), f"{where}.review.evidence_refs")
        if not refs:
            raise ContractValidationError(f"{where}.review.evidence_refs must not be empty")
    _exact_ids(ids, COMPLICATION_IDS, "complications")


def _validate_pair_exclusions(raw: Mapping[str, Any], root: Path) -> None:
    del root
    entries = _mapping_list(raw["exclusions"], "pair-exclusions.exclusions")
    rank = {axis: index for index, axis in enumerate(AXIS_ORDER)}
    seen: set[tuple[str, str, str, str]] = set()
    for index, item in enumerate(entries):
        where = f"pair-exclusions.exclusions[{index}]"
        _strict(
            item,
            {
                "axis_a", "value_a", "axis_b", "value_b", "reason_code",
                "rationale", "evidence_refs", "reviewer", "review_date",
            },
            where,
        )
        axis_a = _enum(item.get("axis_a"), set(AXIS_ORDER), f"{where}.axis_a")
        axis_b = _enum(item.get("axis_b"), set(AXIS_ORDER), f"{where}.axis_b")
        value_a = _stable_id(item.get("value_a"), f"{where}.value_a")
        value_b = _stable_id(item.get("value_b"), f"{where}.value_b")
        if rank[axis_a] > rank[axis_b] or (axis_a == axis_b and value_a > value_b):
            raise ContractValidationError(f"{where}: pair is not in canonical axis/value order")
        key = (axis_a, value_a, axis_b, value_b)
        if key in seen:
            raise ContractValidationError(f"{where}: duplicate canonical pair {key}")
        seen.add(key)
        _enum(item.get("reason_code"), EXCLUSION_REASON_CODES, f"{where}.reason_code")
        _nonempty_string(item.get("rationale"), f"{where}.rationale")
        if not _unique_strings(item.get("evidence_refs"), f"{where}.evidence_refs"):
            raise ContractValidationError(f"{where}.evidence_refs must not be empty")
        _nonempty_string(item.get("reviewer"), f"{where}.reviewer")
        _date_string(item.get("review_date"), f"{where}.review_date")


def _validate_fixture_state_classes(raw: Mapping[str, Any], root: Path) -> None:
    del root
    entries = _mapping_list(raw["classes"], "fixture-state-classes.classes")
    known_cards = {card.last_four for card in CARDS}
    known_accounts = {account.last_four for account in FUNDING_ACCOUNTS}
    ids: set[str] = set()
    bindings_seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for index, item in enumerate(entries):
        where = f"fixture-state-classes.classes[{index}]"
        _strict(item, {"id", "predicates", "bindings"}, where)
        class_id = _stable_id(item.get("id"), f"{where}.id")
        if class_id in ids:
            raise ContractValidationError(f"duplicate fixture-state class ID {class_id!r}")
        ids.add(class_id)
        predicates = _mapping(item.get("predicates"), f"{where}.predicates")
        if set(predicates) != FIXTURE_CLASS_PREDICATES or not all(
            isinstance(value, bool) for value in predicates.values()
        ):
            raise ContractValidationError(
                f"{where}.predicates must define exactly {sorted(FIXTURE_CLASS_PREDICATES)} as booleans"
            )
        bindings = _mapping_list(item.get("bindings"), f"{where}.bindings")
        if not bindings:
            raise ContractValidationError(f"{where}.bindings must not be empty")
        for binding_index, binding in enumerate(bindings):
            binding_where = f"{where}.bindings[{binding_index}]"
            _strict(binding, {"cards", "accounts"}, binding_where)
            cards = tuple(_unique_strings(binding.get("cards"), f"{binding_where}.cards"))
            accounts = tuple(_unique_strings(binding.get("accounts"), f"{binding_where}.accounts"))
            if not cards or not accounts:
                raise ContractValidationError(f"{binding_where}: cards and accounts must not be empty")
            if set(cards) - known_cards or set(accounts) - known_accounts:
                raise ContractValidationError(f"{binding_where}: unknown concrete Fixture binding")
            card_objects = [card for card in CARDS if card.last_four in cards]
            actual_predicates = _fixture_class_predicates(card_objects, len(accounts))
            if dict(predicates) != actual_predicates:
                raise ContractValidationError(
                    f"{binding_where}: binding does not satisfy class predicates"
                )
            key = (cards, accounts)
            if key in bindings_seen:
                raise ContractValidationError(f"{binding_where}: binding belongs to more than one class")
            bindings_seen.add(key)
    expected = {
        (tuple(card.last_four for card in cards), tuple(account.last_four for account in accounts))
        for card_count in range(1, len(CARDS) + 1)
        for cards in itertools.combinations(CARDS, card_count)
        for account_count in range(1, len(FUNDING_ACCOUNTS) + 1)
        for accounts in itertools.combinations(FUNDING_ACCOUNTS, account_count)
    }
    if bindings_seen != expected:
        raise ContractValidationError(
            f"fixture-state membership mismatch: missing={sorted(expected - bindings_seen)}, "
            f"unknown={sorted(bindings_seen - expected)}"
        )


def _validate_fitness_targets(raw: Mapping[str, Any], root: Path) -> None:
    del root
    entries = _mapping_list(raw["targets"], "fitness-targets.targets")
    toggle_ids = set(MockConfig.__dataclass_fields__)
    assertion_ids = set(_ASSERTION_TYPES)
    criterion_ids = {criterion.id for criterion in DEFAULT_CRITERIA} | {
        specialist.criterion.id for specialist in SPECIALISTS
    }
    expected_shapes = {
        ("d1", "same-turn"), ("d1", "at-the-gate"), ("d2", "default"),
        ("d3", "default"), ("d4", "default"), ("d5", "default"),
        ("d6", "default"), ("d7", "default"),
    }
    found: set[tuple[str, str]] = set()
    found_toggles: set[str] = set()
    found_policies: set[str] = set()
    from .policies import POLICIES

    for index, item in enumerate(entries):
        where = f"fitness-targets.targets[{index}]"
        _strict(
            item,
            {"target_id", "shape_id", "defect_toggles", "expected_failure", "applicability", "decision_ref"},
            where,
        )
        target_id = _stable_id(item.get("target_id"), f"{where}.target_id")
        shape_id = _stable_id(item.get("shape_id"), f"{where}.shape_id")
        key = (target_id, shape_id)
        if key in found:
            raise ContractValidationError(f"{where}: duplicate target/shape {key}")
        found.add(key)
        toggles = set(_unique_strings(item.get("defect_toggles"), f"{where}.defect_toggles"))
        if not toggles or toggles - toggle_ids:
            raise ContractValidationError(f"{where}: unknown or empty mock defect toggle set {sorted(toggles)}")
        if found_toggles.intersection(toggles):
            raise ContractValidationError(f"{where}: mock defect toggle is mapped more than once")
        found_toggles.update(toggles)
        failure = _mapping(item.get("expected_failure"), f"{where}.expected_failure")
        _strict(failure, {"source", "id"}, f"{where}.expected_failure")
        source = _enum(failure.get("source"), {"assertion", "judge"}, f"{where}.expected_failure.source")
        failure_id = _nonempty_string(failure.get("id"), f"{where}.expected_failure.id")
        registry = assertion_ids if source == "assertion" else criterion_ids
        if failure_id not in registry:
            raise ContractValidationError(f"{where}: unregistered {source} failure ID {failure_id!r}")
        applicability = _mapping(item.get("applicability"), f"{where}.applicability")
        _strict(applicability, {"journey_ids", "required_edge_ids", "fixture_predicates", "policy_ids"}, f"{where}.applicability")
        _unique_strings(applicability.get("journey_ids"), f"{where}.applicability.journey_ids")
        _unique_strings(applicability.get("required_edge_ids"), f"{where}.applicability.required_edge_ids")
        predicates = set(_unique_strings(applicability.get("fixture_predicates"), f"{where}.applicability.fixture_predicates"))
        if predicates - APPLICABILITY_FIXTURE_PREDICATES:
            raise ContractValidationError(
                f"{where}.applicability.fixture_predicates contains unknown predicate(s) {sorted(predicates - APPLICABILITY_FIXTURE_PREDICATES)}"
            )
        policy_ids = set(_unique_strings(applicability.get("policy_ids"), f"{where}.applicability.policy_ids"))
        if policy_ids - set(POLICIES):
            raise ContractValidationError(
                f"{where}.applicability.policy_ids contains unknown policy ID(s) {sorted(policy_ids - set(POLICIES))}"
            )
        found_policies.update(policy_ids)
        _reference(item.get("decision_ref"), f"{where}.decision_ref")
    if found != expected_shapes:
        raise ContractValidationError(
            f"fitness target shapes mismatch: missing={sorted(expected_shapes - found)}, "
            f"unknown={sorted(found - expected_shapes)}"
        )
    if found_toggles != toggle_ids:
        raise ContractValidationError(
            f"fitness target toggle coverage mismatch: missing={sorted(toggle_ids - found_toggles)}, "
            f"unknown={sorted(found_toggles - toggle_ids)}"
        )
    if found_policies != set(POLICIES):
        raise ContractValidationError(
            f"legacy policy coverage mismatch: missing={sorted(set(POLICIES) - found_policies)}"
        )


def _validate_contract_set(
    contracts: Mapping[str, ReviewedContract], graph: Mapping[str, Any], root: Path
) -> None:
    del root
    edges = _mapping_list(graph.get("edges"), "J1 graph.edges")
    edge_ids = [_stable_id(edge.get("id"), f"J1 graph.edges[{index}].id") for index, edge in enumerate(edges)]
    if len(edge_ids) != len(set(edge_ids)):
        raise ContractValidationError("J1 graph edge IDs must be unique")
    known_edges = set(edge_ids)
    for contract_id in ("complication-applicability", "fitness-targets"):
        payload = "complications" if contract_id.startswith("complication") else "targets"
        for item in contracts[contract_id].content[payload]:
            edge_list = item.get("required_edge_ids")
            if edge_list is None:
                edge_list = item["applicability"]["required_edge_ids"]
            unknown = set(edge_list) - known_edges
            if unknown:
                raise ContractValidationError(
                    f"{contract_id}: unknown required edge ID(s) {sorted(unknown)}"
                )


def _validate_canonical_value(value: Any, where: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ContractValidationError(f"{where}: non-finite floats are not canonical")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_canonical_value(item, f"{where}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractValidationError(f"{where}: mapping keys must be strings")
            _validate_canonical_value(item, f"{where}.{key}")
        return
    raise ContractValidationError(f"{where}: unsupported canonical value {type(value).__name__}")


def _fixture_class_predicates(cards: Sequence[Any], account_count: int) -> dict[str, bool]:
    signatures = {
        (card.minimum_due, card.statement_balance, card.current_balance)
        for card in cards
    }
    tokens = [
        {token.lower() for token in card.name.split() if token.lower() != "chase"}
        for card in cards
    ]
    return {
        "has_card": bool(cards),
        "has_account": account_count > 0,
        "multiple_cards": len(cards) >= 2,
        "distinguishable_card_amounts": len(cards) >= 2 and len(signatures) == len(cards),
        "ambiguous_card_names": any(
            left & right
            for index, left in enumerate(tokens)
            for right in tokens[index + 1 :]
        ),
    }


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractValidationError(f"{path}: cannot load YAML: {exc}") from exc


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{where} must be a mapping")
    return value


def _mapping_list(value: Any, where: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ContractValidationError(f"{where} must be a list of mappings")
    return value


def _strict(value: Mapping[str, Any], fields: set[str], where: str) -> None:
    missing = fields - set(value)
    unknown = set(value) - fields
    if missing:
        raise ContractValidationError(f"{where}: missing field(s) {sorted(missing)}")
    if unknown:
        raise ContractValidationError(f"{where}: unknown field(s) {sorted(unknown)}")


def _positive_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractValidationError(f"{where} must be a positive integer")
    return value


def _nonempty_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{where} must be a non-empty string")
    return value


def _stable_id(value: Any, where: str) -> str:
    value = _nonempty_string(value, where)
    if STABLE_ID_PATTERN.fullmatch(value) is None:
        raise ContractValidationError(f"{where} must be a lowercase kebab-case stable ID")
    return value


def _sha256_string(value: Any, where: str) -> str:
    value = _nonempty_string(value, where)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ContractValidationError(f"{where} must be a lowercase SHA-256 hex digest")
    return value


def _enum(value: Any, choices: set[str], where: str) -> str:
    value = _nonempty_string(value, where)
    if value not in choices:
        raise ContractValidationError(f"{where} must be one of {sorted(choices)}, got {value!r}")
    return value


def _unique_strings(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ContractValidationError(f"{where} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ContractValidationError(f"{where} must not contain duplicates")
    return value


def _exact_ids(ids: Sequence[str], expected: set[str], where: str) -> None:
    if len(ids) != len(set(ids)):
        raise ContractValidationError(f"{where} contain duplicate IDs")
    if set(ids) != expected:
        raise ContractValidationError(
            f"{where} mismatch: missing={sorted(expected - set(ids))}, unknown={sorted(set(ids) - expected)}"
        )


def _reference(value: Any, where: str) -> str:
    value = _nonempty_string(value, where)
    if not value.startswith(("docs/", "CONTEXT.md")):
        raise ContractValidationError(f"{where} must reference a repository decision/evidence document")
    return value


def _date_string(value: Any, where: str) -> str:
    value = _nonempty_string(value, where)
    pieces = value.split("-")
    if len(pieces) != 3 or tuple(map(len, pieces)) != (4, 2, 2) or not all(piece.isdigit() for piece in pieces):
        raise ContractValidationError(f"{where} must be an ISO YYYY-MM-DD string")
    return value
