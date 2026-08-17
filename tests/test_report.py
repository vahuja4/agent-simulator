import json

from agentsim.report import render_report, write_report
from agentsim.types import BatchManifest, BatchRunRecord, FailureCluster, FailureRecord


def test_report_is_static_artifact_with_separate_outcomes_and_links(tmp_path):
    runs = {}
    outcomes = ("pass", "fail", "task_incomplete", "error")
    for index, outcome in enumerate(outcomes):
        key = f"run-{outcome}"
        root = tmp_path / "runs" / key
        root.mkdir(parents=True)
        for name in ("trace.json", "transcript.md", "replay.json"):
            (root / name).write_text("artifact")
        runs[key] = BatchRunRecord(
            run_key=key,
            scenario=f"scenario-{index}",
            scenario_source="scenario.yaml",
            persona_variant="base",
            defect_flags={},
            model="stub",
            seed=index,
            run_id=str(index),
            status="completed",
            outcome=outcome,
            failures=[FailureRecord("judge", "rule", 1, "stored rationale")]
            if outcome == "fail" else [],
            degraded_checks=[{"check": "partial"}] if outcome == "task_incomplete" else [],
            llm_calls=2,
            trace_path=f"runs/{key}/trace.json",
            transcript_path=f"runs/{key}/transcript.md",
            replay_path=f"runs/{key}/replay.json" if outcome == "fail" else None,
            error="harness broke" if outcome == "error" else None,
        )
    manifest = BatchManifest("batch", "now", runs=runs, label_llm_calls=1)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest.to_dict()))
    fail = runs["run-fail"]
    cluster = FailureCluster(
        cluster_id="judge-rule-1",
        source="judge",
        id="rule",
        membership_hash="hash",
        label="Cached label",
        members=[{
            "run_key": fail.run_key,
            "scenario": fail.scenario,
            "turn_index": 1,
            "message": "stored rationale",
            "trace_path": fail.trace_path,
            "transcript_path": fail.transcript_path,
            "replay_path": fail.replay_path,
        }],
    )
    (tmp_path / "clusters.json").write_text(json.dumps({"clusters": [cluster.to_dict()]}))
    (tmp_path / "acceptance.json").write_text(json.dumps({
        "passed": False,
        "recall": {"passed": True},
        "precision": {"passed": False},
        "issues": ["precision failed"],
    }))

    text = render_report(tmp_path)
    assert "| 1 | 1 | 1 | 1 |" in text
    assert "Total recorded LLM calls: 9" in text
    assert "Runs with degraded checks: 1" in text
    assert "harness broke" in text
    assert "Cached label" in text
    assert "[transcript](runs/run-fail/transcript.md)" in text
    assert "[trace](runs/run-fail/trace.json)" in text
    assert "[replay](runs/run-fail/replay.json)" in text
    assert "stored rationale" in text
    path = write_report(tmp_path)
    assert path.read_text() == text
