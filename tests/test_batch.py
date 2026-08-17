import asyncio
import json

from agentsim.batch import BatchRunSpec, BatchRunner
from agentsim.orchestrator import RunResult
from agentsim.scenario import load_scenario
from agentsim.trace import Trace
from agentsim.types import (
    BatchManifest,
    BatchRunRecord,
    CriterionVerdict,
    FailureRecord,
    TurnVerdict,
)


def spec(run_id: str, **metadata) -> BatchRunSpec:
    return BatchRunSpec(
        scenario=load_scenario("scenarios/j1_happy_path.yaml"),
        run_id=run_id,
        seed=7,
        model="stub-model",
        persona_variant="base",
        metadata=metadata,
    )


def result_for(run_spec: BatchRunSpec, outcome: str = "pass") -> RunResult:
    trace = Trace(conversation_id=run_spec.run_key, outcome=outcome)
    trace.add_user_turn("hello", "scripted", None)
    trace.add_agent_turn("hi", [], None)
    failures = []
    if outcome == "fail":
        failures = [FailureRecord("judge", "example", 1, "failed", {"kind": "x"})]
    return RunResult(
        trace=trace,
        outcome=outcome,
        final_reasoning=outcome,
        verdicts=[
            TurnVerdict(
                decision="fail" if outcome == "fail" else "pass",
                criteria=[CriterionVerdict("example", outcome != "fail", outcome)],
                reasoning=f"judge said {outcome}",
            )
        ],
        failures=failures,
        degraded_checks=[{"check": "example", "reason": "missing"}],
        llm_calls=2,
    )


def test_artifact_records_round_trip():
    record = BatchRunRecord(
        run_key="r1",
        scenario="s1",
        scenario_source="s.yaml",
        persona_variant="base",
        defect_flags={},
        model="m",
        seed=1,
        run_id="0",
        status="completed",
        outcome="fail",
        verdicts=[
            TurnVerdict(
                "fail",
                [CriterionVerdict("rule", False, "criterion failed")],
                "run failed",
            )
        ],
        failures=[FailureRecord("assertion", "rule", 3, "bad", {"x": 1})],
        llm_calls=4,
    )
    manifest = BatchManifest("b1", "now", runs={"r1": record}, label_llm_calls=1)
    revived = BatchManifest.from_dict(manifest.to_dict())
    assert revived.to_dict() == manifest.to_dict()
    assert revived.run_llm_calls_total == 4
    assert revived.llm_calls_total == 5


async def test_batch_caps_concurrency_and_writes_all_outcomes(tmp_path):
    active = 0
    peak = 0

    async def execute(run_spec):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        if run_spec.metadata["outcome"] == "raise":
            raise RuntimeError("boom")
        return result_for(run_spec, run_spec.metadata["outcome"])

    specs = [
        spec("pass", outcome="pass"),
        spec("fail", outcome="fail"),
        spec("incomplete", outcome="task_incomplete"),
        spec("error", outcome="raise"),
    ]
    runner = BatchRunner(tmp_path / "batch", concurrency=2)
    manifest = await runner.run(specs, execute)

    assert peak == 2
    assert {record.outcome for record in manifest.runs.values()} == {
        "pass", "fail", "task_incomplete", "error"
    }
    assert manifest.run_llm_calls_total == 6  # raised run returned no count
    for record in manifest.runs.values():
        assert record.status == "completed"
        assert (runner.output_dir / record.trace_path).is_file()
        assert (runner.output_dir / record.transcript_path).is_file()
        persisted = json.loads(
            (runner.output_dir / "runs" / record.run_key / "run.json").read_text()
        )
        assert persisted["outcome"] == record.outcome
        revived = BatchRunRecord.from_dict(persisted)
        assert revived.to_dict() == persisted
        if record.outcome != "error":
            assert persisted["verdicts"] == [verdict.to_dict() for verdict in record.verdicts]
    error = next(record for record in manifest.runs.values() if record.outcome == "error")
    assert error.failures == []
    assert "RuntimeError: boom" in error.error


async def test_resume_skips_completed_runs(tmp_path):
    calls = 0

    async def execute(run_spec):
        nonlocal calls
        calls += 1
        return result_for(run_spec)

    run_spec = spec("once", acceptance_side="precision")
    output = tmp_path / "batch"
    await BatchRunner(output).run([run_spec], execute)
    resumed = await BatchRunner(output).run([run_spec], execute)
    assert calls == 1
    assert resumed.runs[run_spec.run_key].outcome == "pass"


async def test_retry_errors_is_explicit(tmp_path):
    calls = 0

    async def execute(run_spec):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("first")
        return result_for(run_spec)

    run_spec = spec("retry")
    output = tmp_path / "batch"
    first = await BatchRunner(output).run([run_spec], execute)
    assert first.runs[run_spec.run_key].outcome == "error"
    await BatchRunner(output).run([run_spec], execute)
    assert calls == 1
    retried = await BatchRunner(output, retry_errors=True).run([run_spec], execute)
    assert calls == 2
    assert retried.runs[run_spec.run_key].outcome == "pass"
