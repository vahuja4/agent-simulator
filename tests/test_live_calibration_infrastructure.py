from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from agentsim import llm as llm_module
from agentsim.llm import OpenAILLM
from agentsim.orchestrator import RunResult
from agentsim.scenario import ModelFamilySeparationError, load_library
from agentsim.trace import Trace
from scenario_synthesis.simulator_compliance import (
    curated_simulator_compliance_criteria,
    judge_simulator_compliance,
)
from scripts import run_calibration


async def test_openai_llm_records_successful_call_usage(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = SimpleNamespace(
        model_dump=lambda: {
            "prompt_tokens": 1_000,
            "completion_tokens": 500,
            "prompt_tokens_details": {"cached_tokens": 400},
        }
    )
    response = SimpleNamespace(
        usage=usage,
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    refusal=None,
                    content='{"answer":"ok"}',
                ),
            )
        ],
    )

    class Completions:
        async def create(self, **kwargs):
            del kwargs
            return response

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions()),
    )
    monkeypatch.setattr(llm_module, "_get_client", lambda: client)
    usage_path = tmp_path / "usage" / "simulator.jsonl"
    provider = OpenAILLM("o3", usage_path=usage_path)

    result = await provider.structured(
        system="system",
        messages=[],
        schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    )

    assert result == {"answer": "ok"}
    assert provider.usage_records == [
        {
            "model": "o3",
            "usage": {
                "prompt_tokens": 1_000,
                "completion_tokens": 500,
                "prompt_tokens_details": {"cached_tokens": 400},
            },
        }
    ]
    assert [json.loads(line) for line in usage_path.read_text().splitlines()] == (
        provider.usage_records
    )


def test_gate_role_usage_reports_actual_cost_and_judge_cache_hit_rate() -> None:
    simulator = SimpleNamespace(
        model="o3",
        usage_records=[
            {
                "model": "o3",
                "usage": {
                    "prompt_tokens": 1_000,
                    "completion_tokens": 500,
                    "prompt_tokens_details": {"cached_tokens": 400},
                },
            }
        ],
    )
    judge = SimpleNamespace(
        model="gpt-5.5",
        usage_records=[
            {
                "model": "gpt-5.5",
                "usage": {
                    "prompt_tokens": 2_000,
                    "completion_tokens": 100,
                    "prompt_tokens_details": {"cached_tokens": 500},
                },
            }
        ],
    )

    usage = run_calibration._gate_usage_summary(simulator, judge)

    assert usage["simulator"]["actual_cost_usd"] == "0.005400"
    assert usage["judge"]["actual_cost_usd"] == "0.010750"
    assert usage["judge"]["cache_hit_rate"] == "0.250000"
    assert usage["total_actual_cost_usd"] == "0.016150"


async def test_curated_and_production_paths_build_identical_compliance_judge_input() -> None:
    scenario = load_library("scenarios")[0]
    trace = Trace("same-episode", outcome="pass")
    trace.add_user_turn("Pay my Freedom card.", "state goal", None)
    result = RunResult(trace=trace, verdicts=[], outcome="pass", final_reasoning="done")
    goal_facts = {
        "ambiguous_card_reference": "Freedom card",
        "declared_complication": "ambiguous-reference",
    }
    criteria = curated_simulator_compliance_criteria(
        "ambiguous-reference", goal_facts
    )
    calls = []

    class RecordingLLM:
        async def structured(self, **kwargs):
            calls.append(kwargs)
            return {
                "criteria": [
                    {
                        "criterion_id": criterion.id,
                        "passed": True,
                        "reasoning": "compliant",
                    }
                    for criterion in criteria
                ],
                "decision": "continue",
                "reasoning": "checked",
            }

    llm = RecordingLLM()
    await judge_simulator_compliance(
        llm,
        trace,
        scenario=scenario,
        criteria=criteria,
        declared_complication="ambiguous-reference",
        goal_facts=goal_facts,
    )
    await run_calibration.judge_calibration_simulator_compliance(
        llm,
        result,
        scenario=scenario,
        criteria=criteria,
        declared_complication="ambiguous-reference",
        goal_facts=goal_facts,
    )

    assert calls[0] == calls[1]
    evidence = json.loads(
        calls[0]["messages"][0]["content"].split(
            "GOVERNING SCENARIO EVIDENCE:\n", 1
        )[1].split("\n\nTRANSCRIPT:", 1)[0]
    )
    assert evidence == {
        "declared_complication": "ambiguous-reference",
        "goal_facts": goal_facts,
        "scenario_goal": scenario.goal,
        "supplied_knowledge": scenario.render_knowledge(),
    }


async def test_calibration_episode_error_is_persisted_with_identity(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = load_library("scenarios")[0]

    async def fail_run(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("injected live failure")

    monkeypatch.setattr(run_calibration, "run_scenario", fail_run)

    row = await run_calibration.run_one(
        scenario,
        asyncio.Semaphore(1),
        tmp_path,
        None,
        simulator_model="gpt-4.1-mini",
        judge_model="gpt-5.5",
        enforce_model_family_separation=True,
    )

    assert row["scenario"] == scenario.name
    assert row["status"] == "infrastructure-error"
    assert row["error"] == "RuntimeError: injected live failure"
    persisted = json.loads((tmp_path / f"{scenario.name}.json").read_text())
    assert persisted["scenario"] == scenario.name
    assert persisted["status"] == "infrastructure-error"


async def test_calibration_failure_does_not_cancel_sibling_episode(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed, sibling = load_library("scenarios")[:2]

    async def selective_run(scenario, *args, **kwargs):
        del args, kwargs
        if scenario.name == failed.name:
            raise RuntimeError("injected live failure")
        return RunResult(
            trace=Trace(scenario.name, outcome="pass"),
            verdicts=[],
            outcome="pass",
            final_reasoning="completed sibling",
        )

    monkeypatch.setattr(run_calibration, "run_scenario", selective_run)
    rows = await asyncio.gather(
        *(
            run_calibration.run_one(
                scenario,
                asyncio.Semaphore(2),
                tmp_path,
                None,
                simulator_model="o3",
                judge_model="gpt-5.5",
                enforce_model_family_separation=True,
            )
            for scenario in (failed, sibling)
        )
    )

    by_name = {row["scenario"]: row for row in rows}
    assert by_name[failed.name]["status"] == "infrastructure-error"
    assert by_name[sibling.name]["status"] == "completed"
    assert (tmp_path / f"{failed.name}.json").is_file()
    assert (tmp_path / f"{sibling.name}.json").is_file()


async def test_cancelled_calibration_episode_is_persisted_as_interrupted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = load_library("scenarios")[0]
    started = asyncio.Event()

    async def blocked_run(*args, **kwargs):
        del args, kwargs
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(run_calibration, "run_scenario", blocked_run)
    task = asyncio.create_task(
        run_calibration.run_one(
            scenario,
            asyncio.Semaphore(1),
            tmp_path,
            None,
            simulator_model="o3",
            judge_model="gpt-5.5",
            enforce_model_family_separation=True,
        )
    )
    await started.wait()
    task.cancel()
    row = await task

    assert row["status"] == "infrastructure-interrupted"
    persisted = json.loads((tmp_path / f"{scenario.name}.json").read_text())
    assert persisted["status"] == "infrastructure-interrupted"


async def test_compliance_gate_error_persists_kind_scenario_and_repetition(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = load_library("scenarios")[0]

    async def fail_run(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("injected gate failure")

    monkeypatch.setattr(run_calibration, "run_scenario", fail_run)
    goal_facts = run_calibration._curated_goal_facts(scenario)
    record = await run_calibration._run_compliance_gate_episode(
        scenario=scenario,
        repetition=2,
        kind="curated",
        out_dir=tmp_path,
        simulator_llm=object(),
        judge_llm=object(),
        criteria=curated_simulator_compliance_criteria(
            run_calibration.CURATED_COMPLICATIONS[scenario.name], goal_facts
        ),
        declared_complication=run_calibration.CURATED_COMPLICATIONS[scenario.name],
        goal_facts=goal_facts,
        sem=asyncio.Semaphore(1),
    )

    assert record["status"] == "infrastructure-error"
    assert (record["kind"], record["scenario"], record["repetition"]) == (
        "curated",
        scenario.name,
        2,
    )
    path = tmp_path / "curated" / "repetition-2" / f"{scenario.name}.json"
    assert json.loads(path.read_text()) == record


async def test_compliance_gate_episode_timeout_is_bounded_and_attributed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = load_library("scenarios")[0]

    async def never_finishes(*args, **kwargs):
        del args, kwargs
        await asyncio.Event().wait()

    monkeypatch.setattr(run_calibration, "run_scenario", never_finishes)
    goal_facts = run_calibration._curated_goal_facts(scenario)
    record = await run_calibration._run_compliance_gate_episode(
        scenario=scenario,
        repetition=1,
        kind="curated",
        out_dir=tmp_path,
        simulator_llm=object(),
        judge_llm=object(),
        criteria=curated_simulator_compliance_criteria(
            run_calibration.CURATED_COMPLICATIONS[scenario.name], goal_facts
        ),
        declared_complication=run_calibration.CURATED_COMPLICATIONS[scenario.name],
        goal_facts=goal_facts,
        sem=asyncio.Semaphore(1),
        timeout_seconds=0.01,
    )

    assert record["status"] == "infrastructure-error"
    assert record["error"].startswith("TimeoutError:")
    assert (record["scenario"], record["repetition"]) == (scenario.name, 1)


async def test_compliance_gate_rejects_same_gpt_family_before_live_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_calibration.py",
            "--simulator-compliance-gate",
            "--runs",
            "3",
            "--candidate-id",
            "candidate-" + "0" * 64,
            "--simulator-model",
            "gpt-5.6-luna",
            "--model",
            "gpt-5.5",
        ],
    )
    with pytest.raises(ModelFamilySeparationError, match="same model family"):
        await run_calibration.main()


async def test_calibration_reaches_episode_with_only_provider_credentials(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = load_library("scenarios")[0]
    calls = []

    async def recording_run_one(item, *args, **kwargs):
        del args, kwargs
        calls.append(item.name)
        return {
            "scenario": item.name,
            "journey": item.journey,
            "outcome": "pass",
            "user_turns": 0,
            "max_turns": item.max_turns,
            "failures": [],
        }

    monkeypatch.setattr(
        run_calibration.os, "environ", {"OPENAI_API_KEY": "test-key"}
    )
    monkeypatch.setattr(run_calibration, "run_one", recording_run_one)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_calibration.py",
            "--out",
            str(tmp_path),
            "--only",
            scenario.name,
        ],
    )

    assert await run_calibration.main() == 0
    assert calls == [scenario.name]


async def test_compliance_gate_runs_one_fixed_39_plus_3_denominator(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    async def passing_episode(**kwargs):
        identity = (
            kwargs["kind"],
            kwargs["scenario"].name,
            kwargs["repetition"],
        )
        calls.append(identity)
        record = {
            "kind": identity[0],
            "scenario": identity[1],
            "repetition": identity[2],
            "status": "completed",
            "passed": True,
            "ordinary_outcome": "pass",
            "simulator_compliance_rulings": [],
        }
        if identity[0] == "persona-fidelity-spot-check":
            record["trace"] = {
                "turns": [
                    {"index": 1, "speaker": "agent", "text": "confirm", "tool_calls": [{"name": "AddValidateOneTimePayment"}]},
                    {"index": 2, "speaker": "user", "text": "Hurry up.", "tool_calls": []},
                    {"index": 4, "speaker": "user", "text": "Just do it.", "tool_calls": []},
                    {"index": 6, "speaker": "user", "text": "Yes.", "tool_calls": []},
                    {"index": 7, "speaker": "agent", "text": "done", "tool_calls": [{"name": "AddOneTimePayment"}]},
                ]
            }
        return record

    monkeypatch.setattr(
        run_calibration, "_run_compliance_gate_episode", passing_episode
    )
    out = tmp_path / "gate"
    args = SimpleNamespace(
        out=str(out),
        candidate_output_root="synthesized_scenarios",
        candidate_id=(
            "candidate-4a296207b9dd03895648ada38cfaaa043c2891b04e58b5a92792e3f327d25549"
        ),
        simulator_model="o3",
        model="gpt-5.5",
        concurrency=4,
    )

    assert await run_calibration._run_simulator_compliance_gate(args) == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["curated"]["passed"] == 39
    assert summary["admitted_cell"]["passed"] == 3
    denominator = [identity for identity in calls if identity[0] != "persona-fidelity-spot-check"]
    assert len(denominator) == len(set(denominator)) == 42
