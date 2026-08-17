import json

from agentsim.batch import BatchRunSpec, BatchRunner
from agentsim.clustering import cluster_failures, data_similarity, label_clusters
from agentsim.orchestrator import RunResult
from agentsim.replay import emit_batch_replays
from agentsim.scenario import load_scenario
from agentsim.trace import Trace
from agentsim.types import BatchManifest, FailureRecord


async def _make_batch(tmp_path):
    scenario = load_scenario("scenarios/j1_happy_path.yaml")
    cases = [
        ("a", {"tool": "x", "kind": "same"}),
        ("b", {"tool": "x", "kind": "same", "extra": "v"}),
        ("c", {"tool": "y", "kind": "different"}),
    ]
    specs = [
        BatchRunSpec(
            scenario=scenario,
            run_id=case,
            metadata={"case": case, "failure_data": data},
        )
        for case, data in cases
    ]

    async def execute(spec):
        trace = Trace(conversation_id=spec.run_key, outcome="fail")
        trace.add_user_turn("do it", "scripted", None)
        trace.add_agent_turn("no", [], None)
        return RunResult(
            trace=trace,
            outcome="fail",
            failures=[
                FailureRecord(
                    "judge", "shared_rule", 1, f"failure {spec.run_id}",
                    spec.metadata["failure_data"],
                )
            ],
            llm_calls=1,
        )

    output = tmp_path / "batch"
    await BatchRunner(output).run(specs, execute)
    emit_batch_replays(output)
    return output


def test_data_similarity_is_structured_and_deterministic():
    assert data_similarity({"a": 1, "b": 2}, {"b": 2, "a": 1}) == 1.0
    assert data_similarity({"a": 1}, {"a": 2}) == 0.0


async def test_clusters_are_deterministic_ranked_and_link_replays(tmp_path):
    output = await _make_batch(tmp_path)
    first = cluster_failures(output, similarity_threshold=0.6)
    second = cluster_failures(output, similarity_threshold=0.6)
    assert [cluster.to_dict() for cluster in first] == [cluster.to_dict() for cluster in second]
    assert [cluster.size for cluster in first] == [2, 1]
    assert all(member["replay_path"] for cluster in first for member in cluster.members)


async def test_optional_labels_are_one_call_per_cluster_and_cached(tmp_path):
    output = await _make_batch(tmp_path)
    clusters = cluster_failures(output)
    calls = 0

    async def labeler(cluster):
        nonlocal calls
        calls += 1
        return f"label {cluster.id} {cluster.size}"

    labeled = await label_clusters(output, labeler)
    assert calls == len(clusters)
    assert all(cluster.label for cluster in labeled)

    await label_clusters(output, labeler)
    assert calls == len(clusters)  # no call for cached membership hashes
    manifest = BatchManifest.from_dict(
        json.loads((output / "manifest.json").read_text())
    )
    assert manifest.label_llm_calls == len(clusters)
    assert manifest.llm_calls_total == 3 + len(clusters)

    regenerated = cluster_failures(output)
    assert [cluster.label for cluster in regenerated] == [
        cluster.label for cluster in labeled
    ]
