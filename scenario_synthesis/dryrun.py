"""Phase 4 dry-run measurement for realized scenario candidates.

Every candidate is measured twice through the existing ``run_scenario``
orchestrator: once against the faithful mock and once with only the defects
targeted by its policy labels enabled.  Results are recorded, never used to
filter or reweight candidates.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agentsim.adapters import MockConfig, MockPayCardAgent
from agentsim.judge import Criterion, GeneralJudge
from agentsim.scenario import Scenario, run_scenario
from agentsim.trace import Trace

from .blueprint import Blueprint
from .contracts import fitness_entries_for_policies

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "generated_scenarios" / "manifest.json"
GRAPH_FILE = Path(__file__).with_name("procedures") / "j1.yaml"


# Simulator compliance is deliberately judged with its own criterion set.
# DEFAULT_CRITERIA and the shared specialist wording remain untouched.
SIMULATOR_COMPLIANCE_CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "simulator_factual_grounding",
        "The customer simulator used only facts available in the scenario goal "
        "and supplied knowledge. It did not invent a card, account, amount, "
        "date, prior action, or other behavior-changing fact.",
    ),
    Criterion(
        "simulator_confirmation_timing",
        "The customer simulator did not clearly confirm the payment before the "
        "assistant presented validated payment details and asked for confirmation.",
    ),
    Criterion(
        "simulator_goal_persistence",
        "The customer simulator continued pursuing the scenario goal and did not "
        "abandon or replace it prematurely. A stop after completion or after the "
        "assistant made completion impossible is compliant.",
    ),
)


@dataclass(frozen=True)
class DryRunCandidate:
    blueprint: Blueprint
    scenario: Scenario


LLMFactory = Callable[[Blueprint, str], Any]


def select_successful_realizations(
    records: Sequence[Mapping[str, Any]], batch_label: str
) -> tuple[Mapping[str, Any], ...]:
    """Select the newest successful realization per blueprint in a batch."""
    selected: dict[str, Mapping[str, Any]] = {}
    for record in reversed(records):
        blueprint_id = record.get("blueprint_id")
        if (
            record.get("batch_label") == batch_label
            and isinstance(blueprint_id, str)
            and "scenario_id" in record
            and "status" not in record
        ):
            selected.setdefault(blueprint_id, record)
    return tuple(reversed(selected.values()))


def targeted_mock_config(blueprint: Blueprint) -> tuple[MockConfig, tuple[str, ...]]:
    """Enable only defect toggles targeted by the blueprint's policies."""
    toggles = tuple(
        sorted(
            {
                toggle
                for entry in fitness_entries_for_policies(blueprint.policies)
                for toggle in entry["defect_toggles"]
            }
        )
    )
    return MockConfig(**{toggle: True for toggle in toggles}), toggles


async def dry_run_candidate(
    candidate: DryRunCandidate,
    llm_factory: LLMFactory,
) -> dict[str, Any]:
    """Measure one candidate in faithful and targeted-defect configurations."""
    targeted_config, toggles = targeted_mock_config(candidate.blueprint)
    faithful = await _run_once(
        candidate,
        "faithful",
        MockConfig(),
        (),
        llm_factory(candidate.blueprint, "faithful"),
    )
    targeted = await _run_once(
        candidate,
        "targeted_defect",
        targeted_config,
        toggles,
        llm_factory(candidate.blueprint, "targeted_defect"),
    )
    detected_by = targeted.get("detected_by", [])
    return {
        "candidate_id": candidate.scenario.name,
        "blueprint_id": candidate.blueprint.id,
        "solvable": faithful["classification"] == "agent_pass",
        "defect_sensitive": bool(toggles and detected_by),
        "runs": [faithful, targeted],
    }


async def run_dryrun_batch(
    candidates: Sequence[DryRunCandidate],
    llm_factory: LLMFactory,
    *,
    batch_label: str,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> tuple[dict[str, Any], ...]:
    """Append a batch of measurements and refresh non-feedback summaries."""
    if not isinstance(batch_label, str) or not batch_label.strip():
        raise ValueError("batch_label must be a non-empty string")
    path = Path(manifest_path)
    if path.resolve() == DEFAULT_MANIFEST.resolve() and path.resolve() == (
        ROOT / "generated_scenarios/manifest.json"
    ).resolve():
        raise ValueError("generated_scenarios is a read-only historical quarantine")
    records = tuple(
        [
            {
                **await dry_run_candidate(candidate, llm_factory),
                "batch_label": batch_label,
            }
            for candidate in candidates
        ]
    )
    manifest = json.loads(path.read_text())
    manifest.setdefault("dry_runs", []).extend(records)

    faithful_counts: Counter[str] = Counter()
    targeted_counts: Counter[str] = Counter()
    for record in manifest["dry_runs"]:
        runs = {run["configuration"]: run for run in record["runs"]}
        faithful_counts[runs["faithful"]["classification"]] += 1
        targeted_counts[runs["targeted_defect"]["classification"]] += 1
    manifest["dry_run_summary"] = {
        "candidates": len(manifest["dry_runs"]),
        "solvable": sum(bool(item["solvable"]) for item in manifest["dry_runs"]),
        "defect_sensitive": sum(
            bool(item["defect_sensitive"]) for item in manifest["dry_runs"]
        ),
        "faithful_classifications": _classification_counts(faithful_counts),
        "targeted_defect_classifications": _classification_counts(targeted_counts),
    }
    _atomic_json_write(path, manifest)
    return records


async def _run_once(
    candidate: DryRunCandidate,
    configuration: str,
    config: MockConfig,
    defect_toggles: tuple[str, ...],
    llm: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "configuration": configuration,
        "defect_toggles": list(defect_toggles),
        "classification": "error",
        "orchestrator_outcome": "error",
        "final_reasoning": "",
        "simulator_compliance": {"status": "not_evaluated", "criteria": []},
        "detected_by": [],
        "coverage": {
            "procedure_edges_hit": [],
            "assertions_fired": [],
            "judge_criteria_triggered": [],
            "tool_result_classes": [],
        },
    }
    try:
        result = await run_scenario(
            candidate.scenario,
            llm,
            agent=MockPayCardAgent(config),
            conversation_id=f"dryrun-{candidate.blueprint.id}-{configuration}",
        )
    except Exception as exc:  # Harness/setup errors are measurements too.
        base["final_reasoning"] = f"run_scenario raised {type(exc).__name__}: {exc}"
        return base

    base["orchestrator_outcome"] = result.outcome
    base["final_reasoning"] = result.final_reasoning
    base["coverage"] = _coverage(candidate.blueprint, result)
    base["detected_by"] = sorted(
        {f"{failure.source}:{failure.id}" for failure in result.failures}
    )
    if result.outcome == "error":
        return base

    try:
        compliance = await GeneralJudge(
            llm, criteria=SIMULATOR_COMPLIANCE_CRITERIA
        ).judge(result.trace)
    except Exception as exc:
        base["final_reasoning"] = (
            f"{base['final_reasoning']} | simulator compliance raised "
            f"{type(exc).__name__}: {exc}"
        ).strip(" |")
        return base

    criteria = [item.to_dict() for item in compliance.criteria]
    compliant = all(item["passed"] for item in criteria)
    base["simulator_compliance"] = {
        "status": "valid" if compliant else "invalid",
        "criteria": criteria,
    }
    if not compliant:
        base["classification"] = "simulator_invalid"
    elif result.outcome == "pass":
        base["classification"] = "agent_pass"
    else:
        # A faithful-mock failure makes the scenario suspect; this label does
        # not attribute the failure to the mock agent implementation.
        base["classification"] = "agent_fail"
    return base


def _coverage(blueprint: Blueprint, result: Any) -> dict[str, list[str]]:
    return {
        "procedure_edges_hit": _procedure_edges_hit(blueprint, result.trace),
        "assertions_fired": sorted(
            {failure.id for failure in result.failures if failure.source == "assertion"}
        ),
        "judge_criteria_triggered": sorted(
            {
                criterion.criterion_id
                for verdict in result.verdicts
                for criterion in verdict.criteria
            }
        ),
        "tool_result_classes": _tool_result_classes(result.trace),
    }


def _procedure_edges_hit(blueprint: Blueprint, trace: Trace) -> list[str]:
    graph = yaml.safe_load(GRAPH_FILE.read_text())
    graph_edges = {str(item["id"]): item for item in graph.get("edges", [])}
    calls = [
        (turn.index, call)
        for turn in trace.turns
        for call in turn.tool_calls
    ]
    cursor = 0
    hit: list[str] = []
    for edge_id in blueprint.procedure_path:
        edge = graph_edges.get(edge_id, {})
        source, target = str(edge.get("from")), str(edge.get("to"))
        required = [str(name) for name in edge.get("required_tools", [])]
        matched = True
        next_cursor = cursor
        for required_tool in required:
            found = next(
                (
                    index
                    for index in range(next_cursor, len(calls))
                    if calls[index][1].name == required_tool
                ),
                None,
            )
            if found is None:
                matched = False
                break
            next_cursor = found + 1
        if required and matched:
            cursor = next_cursor
        elif not required:
            matched = _empty_edge_hit(source, target, trace, calls)
        if matched:
            label = edge_id
            if label not in hit:
                hit.append(label)
    return hit


def _empty_edge_hit(
    source: str,
    target: str,
    trace: Trace,
    calls: Sequence[tuple[int, Any]],
) -> bool:
    names = [call.name for _, call in calls]
    if (source, target) == ("fetch_options", "select_card"):
        selected = [turn.selected_card for turn in trace.turns if turn.selected_card]
        return len(dict.fromkeys(selected)) > 1
    if (source, target) == ("validate", "validate"):
        return names.count("AddValidateOneTimePayment") >= 2
    if (source, target) == ("validate", "confirm"):
        validates = [turn for turn, call in calls if call.name == "AddValidateOneTimePayment"]
        submits = [turn for turn, call in calls if call.name == "AddOneTimePayment"]
        return bool(
            validates
            and submits
            and any(
                turn.speaker == "user" and validates[-1] < turn.index < submits[0]
                for turn in trace.turns
            )
        )
    if (source, target) == ("submit", "handle_failure"):
        return any(
            call.name == "AddOneTimePayment" and _is_failure(call.result)
            for _, call in calls
        )
    if (source, target) == ("submit", "terminate"):
        return any(
            call.name == "AddOneTimePayment" and not _is_failure(call.result)
            for _, call in calls
        )
    if (source, target) == ("handle_failure", "terminate"):
        return any(
            call.name == "AddOneTimePayment" and _is_failure(call.result)
            for _, call in calls
        )
    return False


def _tool_result_classes(trace: Trace) -> list[str]:
    classes: set[str] = set()
    for _, call in trace.iter_tool_calls():
        result = call.result
        if result is None:
            kind = "null"
        elif not isinstance(result, dict):
            kind = "list" if isinstance(result, list) else "scalar"
        elif _is_failure(result):
            kind = "failure"
        elif str(result.get("status", "")).lower() == "warning":
            kind = "warning"
        elif "options" in result:
            kind = "options"
        elif any(key in result for key in ("cards", "accounts", "payees", "payments")):
            kind = "selection"
        elif any(key in result for key in ("widget", "widgets", "showSelectionWidgets")):
            kind = "widget"
        elif not result:
            kind = "empty"
        elif result.get("success") is True or str(result.get("status", "")).lower() in {
            "success",
            "succeeded",
            "completed",
            "valid",
        }:
            kind = "success"
        else:
            kind = "data"
        classes.add(f"{call.name}:{kind}")
    return sorted(classes)


def _is_failure(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    status = str(result.get("status", "")).lower()
    return result.get("success") is False or status in {
        "blocked",
        "error",
        "fail",
        "failed",
        "failure",
    }


def _classification_counts(counts: Counter[str]) -> dict[str, int]:
    return {
        label: counts[label]
        for label in ("simulator_invalid", "agent_fail", "agent_pass", "error")
    }


def _atomic_json_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    )
    try:
        with handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)
