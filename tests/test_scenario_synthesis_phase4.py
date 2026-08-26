from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agentsim.judge import DEFAULT_CRITERIA
from agentsim.orchestrator import RunResult
from agentsim.trace import Trace, TraceToolCall
from agentsim.types import CriterionVerdict, FailureRecord, TurnVerdict
from scenario_synthesis.blueprint import load_blueprint
from scenario_synthesis import dryrun
from scenario_synthesis.dryrun import DryRunCandidate


BLUEPRINTS = Path("scenario_synthesis/blueprints")


class ComplianceLLM:
    def __init__(self, *, valid: bool) -> None:
        self.valid = valid

    async def structured(self, **_: Any) -> dict[str, Any]:
        criteria = []
        for index, criterion in enumerate(dryrun.SIMULATOR_COMPLIANCE_CRITERIA):
            passed = self.valid or index != 0
            criteria.append(
                {
                    "criterion_id": criterion.id,
                    "passed": passed,
                    "reasoning": "stubbed compliance measurement",
                }
            )
        return {
            "criteria": criteria,
            "decision": "pass" if self.valid else "fail",
            "reasoning": "stubbed compliance measurement",
        }


def _trace(conversation_id: str) -> Trace:
    trace = Trace(conversation_id)
    trace.add_user_turn("Pay my card ending 9013.", "goal", None)
    trace.add_agent_turn(
        "I found the card and options.",
        [
            TraceToolCall("PayeeList", {}, {"cards": [{"lastFour": "9013"}]}),
            TraceToolCall(
                "FundingAccountPicker", {}, {"accounts": [{"lastFour": "5678"}]}
            ),
            TraceToolCall(
                "AddOptionsOneTimePayment", {}, {"options": [{"amount": 875.20}]}
            ),
            TraceToolCall(
                "AddValidateOneTimePayment", {}, {"status": "valid", "formId": "f1"}
            ),
        ],
        "9013",
    )
    trace.add_user_turn("Yes, schedule it.", "confirm", "9013")
    trace.add_agent_turn(
        "Scheduled.",
        [TraceToolCall("AddOneTimePayment", {"formId": "f1"}, {"success": True})],
        "9013",
    )
    return trace


@pytest.mark.asyncio
async def test_seeded_stubbed_batch_records_two_runs_and_separate_classes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    card_switch = load_blueprint(BLUEPRINTS / "j1_card_switch.yaml")
    happy = load_blueprint(BLUEPRINTS / "j1_happy_path.yaml")
    seen_configs: list[tuple[str, dict[str, bool]]] = []

    async def fake_run_scenario(scenario, llm, agent, *, conversation_id):
        config = {
            name: getattr(agent.config, name)
            for name in agent.config.__dataclass_fields__
        }
        seen_configs.append((conversation_id, config))
        trace = _trace(conversation_id)
        verdict = TurnVerdict(
            decision="pass",
            criteria=[CriterionVerdict("goal_completion", True, "ok")],
            reasoning="stubbed",
        )
        failures = []
        outcome = "pass"
        if scenario.name == "card-switch" and config["d2_stale_options_after_card_switch"]:
            outcome = "fail"
            failures = [
                FailureRecord("assertion", "refetch_after_card_switch", 3, "stale")
            ]
        elif scenario.name == "happy" and not any(config.values()):
            outcome = "fail"
        trace.outcome = outcome
        return RunResult(
            trace=trace,
            verdicts=[verdict],
            outcome=outcome,
            final_reasoning="stubbed",
            failures=failures,
        )

    monkeypatch.setattr(dryrun, "run_scenario", fake_run_scenario)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"seed": 19, "dry_runs": []}))
    candidates = (
        DryRunCandidate(card_switch, SimpleNamespace(name="card-switch")),
        DryRunCandidate(happy, SimpleNamespace(name="happy")),
    )

    def llm_factory(blueprint, configuration):
        return ComplianceLLM(
            valid=not (
                blueprint.id == happy.id and configuration == "targeted_defect"
            )
        )

    records = await dryrun.run_dryrun_batch(
        candidates,
        llm_factory,
        batch_label="batch-2",
        manifest_path=manifest_path,
    )
    manifest = json.loads(manifest_path.read_text())

    assert len(records) == 2
    assert {record["batch_label"] for record in records} == {"batch-2"}
    assert len(manifest["dry_runs"]) == 2  # neither failure class filtered a candidate
    by_id = {item["candidate_id"]: item for item in records}
    switch_runs = {run["configuration"]: run for run in by_id["card-switch"]["runs"]}
    happy_runs = {run["configuration"]: run for run in by_id["happy"]["runs"]}
    assert switch_runs["faithful"]["classification"] == "agent_pass"
    assert switch_runs["targeted_defect"]["classification"] == "agent_fail"
    assert by_id["card-switch"]["solvable"] is True
    assert by_id["card-switch"]["defect_sensitive"] is True
    assert happy_runs["faithful"]["classification"] == "agent_fail"
    assert happy_runs["targeted_defect"]["classification"] == "simulator_invalid"
    assert by_id["happy"]["solvable"] is False
    assert manifest["dry_run_summary"]["faithful_classifications"] == {
        "simulator_invalid": 0,
        "agent_fail": 1,
        "agent_pass": 1,
        "error": 0,
    }
    coverage = switch_runs["targeted_defect"]["coverage"]
    assert coverage["assertions_fired"] == ["refetch_after_card_switch"]
    assert coverage["judge_criteria_triggered"] == ["goal_completion"]
    assert "j1-select-card-fetch-options" in coverage["procedure_edges_hit"]
    assert "AddOptionsOneTimePayment:options" in coverage["tool_result_classes"]

    faithful_configs = [config for cid, config in seen_configs if cid.endswith("faithful")]
    assert faithful_configs and all(not any(config.values()) for config in faithful_configs)
    targeted_switch = next(
        config
        for cid, config in seen_configs
        if "j1-card-switch-targeted_defect" in cid
    )
    assert {name for name, enabled in targeted_switch.items() if enabled} == {
        "d1_same_turn_after_validation",
        "d1_submit_on_reask",
        "d2_stale_options_after_card_switch",
        "d3_false_success_on_failed_submit",
    }


def test_targeted_config_uses_only_policy_mapped_defects() -> None:
    blueprint = load_blueprint(BLUEPRINTS / "j1_last_four_disambiguation.yaml")
    config, toggles = dryrun.targeted_mock_config(blueprint)

    assert set(toggles) == {
        "d1_same_turn_after_validation",
        "d1_submit_on_reask",
        "d3_false_success_on_failed_submit",
        "d5_silent_card_disambiguation",
    }
    assert {
        name for name in config.__dataclass_fields__ if getattr(config, name)
    } == set(toggles)


def test_dryrun_selection_uses_latest_success_per_blueprint() -> None:
    original = {
        "blueprint_id": "j1-shared",
        "scenario_id": "original-scenario",
        "batch_label": "batch-2",
        "realization_outcome": "first_try_success",
    }
    reuse = {
        "blueprint_id": "j1-shared",
        "scenario_id": "reused-scenario",
        "batch_label": "batch-2",
        "realization_outcome": "reused",
    }

    selected = dryrun.select_successful_realizations(
        (original, reuse), "batch-2"
    )

    assert selected == (reuse,)


def test_simulator_compliance_criteria_are_separate_from_shared_judge() -> None:
    shared_ids = {criterion.id for criterion in DEFAULT_CRITERIA}
    compliance_ids = {
        criterion.id for criterion in dryrun.SIMULATOR_COMPLIANCE_CRITERIA
    }
    assert shared_ids.isdisjoint(compliance_ids)
