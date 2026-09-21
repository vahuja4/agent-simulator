"""Failure clustering and the Markdown report of a Journey Run (design note
section 9), on Runs played with doubles. ``cluster_failures`` is the payments
one, unchanged; what is tested here is what it is handed and what the report
does with every outcome it does not cluster.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from agentsim.journey import checks
from agentsim.journey.report import (
    FIDELITY_NOTICE,
    clustering_view,
    render_run_report,
    summarize_run,
)
from agentsim.types import FailureRecord
from scripts import journey_harness as jh
from tests.journey_run_doubles import play_run

REPORTED = "update_result_reported_accurately"
MIXED = ["pass", "unconfirmed", "padded", "gave_up", "agent_error", "transport",
         "simulator_error", "unconfirmed"]


def read(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.fixture
def mixed(tmp_path):
    """One of everything: 1 pass, 3 fail (two alike), 1 task_incomplete, 3 error."""
    played = play_run(tmp_path, MIXED, judge_failing={2: (REPORTED,)})
    assert played.status == 0
    return played, summarize_run(played.run_dir)


def rows(report: str, run_key: str) -> list[str]:
    """The table rows that list an Episode."""
    return [line for line in report.splitlines()
            if line.startswith("|") and f"`{run_key}`" in line]


def section_of(report: str, line: str) -> str:
    return re.findall(r"^## (.+)$", report[: report.index(line)], flags=re.M)[-1]


# --------------------------------------------------------------- clustering


def test_the_same_check_with_the_same_details_is_one_cluster(mixed):
    played, summary = mixed
    cluster = next(c for c in summary.clusters if c.id == checks.USER_TURN_BEFORE_UPDATE)
    assert (cluster.source, cluster.size) == ("assertion", 2)
    assert {m["run_key"] for m in cluster.members} == {
        played.episode_dir(1).name, played.episode_dir(7).name,
    }


def test_the_same_check_with_different_details_is_split(tmp_path):
    played = play_run(tmp_path, ["unconfirmed", "never_offered"])
    clusters = [
        c for c in summarize_run(played.run_dir).clusters
        if c.id == checks.USER_TURN_BEFORE_UPDATE
    ]
    assert sorted(m["data"]["reason"] for c in clusters for m in c.members) == [
        "no_user_turn_after_slot_surfaced", "slot_never_surfaced",
    ]
    assert [c.size for c in clusters] == [1, 1]


def test_an_error_never_lands_in_an_agent_failure_cluster(mixed):
    played, summary = mixed
    manifest = read(played.run_dir / "manifest.json")["runs"]
    clustered = {m["run_key"] for c in summary.clusters for m in c.members}
    assert clustered == {key for key, r in manifest.items() if r["outcome"] == "fail"}
    assert sum(c.size for c in summary.clusters) == 3
    assert summary.outcomes == {"pass": 1, "fail": 3, "task_incomplete": 1, "error": 3}


def test_the_same_failure_at_turn_2_and_at_turn_5_is_one_cluster(tmp_path):
    """Judge failure evidence names message and action ids, which differ as
    soon as two conversations differ in length. Clustering must not see them."""
    played = play_run(
        tmp_path, ["pass", "padded"], judge_failing={0: (REPORTED,), 1: (REPORTED,)}
    )
    saved = [
        read(played.episode_dir(i) / "evaluation.json")["failures"][0]["data"]["evidence"]
        for i in range(2)
    ]
    assert saved[0]["message_ids"] != saved[1]["message_ids"]  # the full record is kept
    assert saved[0]["message_ids"] and saved[0]["action_ids"]

    for record in read(played.run_dir / "manifest.json")["runs"].values():
        evidence = record["failures"][0]["data"]["evidence"]
        assert set(evidence) == {"files"}  # what clustering reads carries no ids

    cluster, = summarize_run(played.run_dir).clusters
    assert (cluster.source, cluster.id, cluster.size) == ("judge", REPORTED, 2)


def test_the_clustering_view_drops_only_the_per_episode_ids():
    failure = FailureRecord("judge", REPORTED, None, "said done, was not", {
        "stop_reason": "user_finished", "tools": ["update_appointment"],
        "evidence": {"message_ids": ["m5"], "action_ids": ["a3"], "files": ["raw_trace.json"]},
    })
    view = clustering_view(failure)
    assert view.data == {
        "stop_reason": "user_finished", "tools": ["update_appointment"],
        "evidence": {"files": ["raw_trace.json"]},
    }
    assert failure.data["evidence"]["message_ids"] == ["m5"]  # a copy, not a mutation
    assert (view.source, view.id, view.message) == ("judge", REPORTED, "said done, was not")


# ------------------------------------------------------------------- report


def test_the_outcome_counts_are_correct(mixed):
    played, summary = mixed
    report = summary.report_path.read_text()
    assert summary.report_path == played.run_dir / "report.md"
    assert "| pass | fail | task_incomplete | error | not finished |" in report
    assert "| 1 | 3 | 1 | 3 | 0 |" in report
    assert "ABORTED" not in report


def test_every_evidence_link_resolves_to_a_file_that_exists(mixed):
    played, summary = mixed
    report = summary.report_path.read_text()
    links = re.findall(r"\]\(([^)]+)\)", report)
    assert links and all(not link.startswith("/") for link in links)  # relative
    assert all((played.run_dir / link).is_file() for link in links)
    # conversation, raw Trace, normalized Trace and evaluation result, per member
    for index in (1, 2, 3, 4):
        row, = rows(report, played.episode_dir(index).name)
        for name in ("transcript.jsonl", "raw_trace.json", "normalized_trace.json",
                     "evaluation.json"):
            assert f"{played.episode_dir(index).name}/{name})" in row


def test_every_non_pass_episode_is_listed_exactly_once(mixed):
    """Counted in the outcome table means listed below it. ``task_incomplete``
    has no failure record, so no cluster can ever hold it."""
    played, summary = mixed
    report = summary.report_path.read_text()
    expected_section = {
        1: "Failure clusters (outcome `fail`)", 2: "Failure clusters (outcome `fail`)",
        7: "Failure clusters (outcome `fail`)", 3: "Task incomplete",
        4: "Agent errors", 5: "Infrastructure and harness errors",
        6: "Infrastructure and harness errors",
    }
    for index, section in expected_section.items():
        row, = rows(report, played.episode_dir(index).name)
        assert section_of(report, row) == section
    assert rows(report, played.episode_dir(0).name) == []  # the pass is only counted


def test_an_episode_with_two_failures_is_listed_once_per_failure_in_the_clusters(tmp_path):
    played = play_run(tmp_path, ["never_offered"])
    report = summarize_run(played.run_dir).report_path.read_text()
    failures = read(played.episode_dir(0) / "evaluation.json")["failures"]
    listed = rows(report, played.episode_dir(0).name)
    assert len(failures) >= 2 and len(listed) == len(failures)
    assert {section_of(report, row) for row in listed} == {"Failure clusters (outcome `fail`)"}


def test_task_incomplete_is_grouped_by_its_structured_reason(tmp_path):
    played = play_run(tmp_path, ["gave_up", "gave_up", "pass"])
    report = summarize_run(played.run_dir).report_path.read_text()
    outcomes = {s.expected_outcome for s in played.scenarios[:2]}
    headings = re.findall(r"^### Expected outcome .+$", report, flags=re.M)
    assert len(headings) == len(outcomes)
    for heading in headings:
        assert "not_evidenced, stopped on `user_gave_up`, Judge `pass`" in heading
    assert sum(int(h.split(" — ")[1].split()[0]) for h in headings) == 2


def test_agent_errors_are_listed_apart_from_infrastructure_errors(mixed):
    played, summary = mixed
    report = summary.report_path.read_text()
    agent = report.split("## Agent errors")[1].split("## Infrastructure")[0]
    infrastructure = report.split("## Infrastructure and harness errors")[1]
    assert "### adapter service agent_error — 1 Episode(s)" in agent
    assert "transport" not in agent
    assert "### adapter transport — 1 Episode(s)" in infrastructure
    assert "### simulated_user LLMError — 1 Episode(s)" in infrastructure
    assert "agent_error" not in infrastructure


def test_the_fidelity_notice_is_said_plainly_once_near_the_top(mixed):
    _, summary = mixed
    report = summary.report_path.read_text()
    assert report.count(FIDELITY_NOTICE) == 1
    assert report.index(FIDELITY_NOTICE) < report.index("## Outcomes")
    for said in ("No check confirms that the Simulated user played each Scenario as written",
                 "`update_matches_goal` fails when the customer accepted a slot outside",
                 "Read the linked conversation before treating a cluster as an agent defect",
                 "journey_spot_checks/", "agentsim/journey/spot_check.py"):
        assert said in FIDELITY_NOTICE


def test_clusters_are_presented_as_symptoms_and_nothing_is_labelled(mixed):
    played, summary = mixed
    report = summary.report_path.read_text()
    assert "similar failure symptoms, not a proven common root cause" in report
    assert "root cause" not in report.replace("not a proven common root cause", "")
    clusters = read(played.run_dir / "clusters.json")["clusters"]
    assert clusters and all(c["label"] is None for c in clusters)  # no LLM labels
    assert read(played.run_dir / "manifest.json")["label_llm_calls"] == 0


def test_the_judge_call_count_is_not_presented_as_a_total(mixed):
    _, summary = mixed
    report = summary.report_path.read_text()
    # Two Assertion failures and three errors never reached the Judge.
    assert "- Judge calls: 3. The Simulated user's model calls are not recorded, " \
           "so this is not a total." in report
    assert "Total" not in report


def test_the_report_says_which_agent_answered(mixed):
    _, summary = mixed
    assert "- Agent: `stub` at http://127.0.0.1:8765" in summary.report_path.read_text()


def test_the_report_is_rendered_from_the_run_directory_alone(mixed, tmp_path):
    played, _ = mixed
    moved = tmp_path / "moved"
    played.run_dir.rename(moved)  # the set and the Journey directory are not beside it
    assert render_run_report(moved) == (moved / "report.md").read_text()


# ---------------------------------------------------------------- summarize


def test_summarize_prints_the_counts_and_where_the_report_is(mixed):
    played, _ = mixed
    out = io.StringIO()
    assert jh.main(["summarize", str(played.run_dir)], out=out) == 0
    text = out.getvalue()
    assert "pass 1, fail 3, task_incomplete 1, error 3, not finished 0" in text
    assert "3 failure(s) in 2 cluster(s) of similar symptoms" in text
    assert str(played.run_dir / "report.md") in text
    assert "ABORTED" not in text


def test_summarize_refuses_a_directory_that_is_not_a_journey_run(tmp_path):
    out = io.StringIO()
    assert jh.main(["summarize", str(tmp_path)], out=out) == 2
    assert "journey_run.json" in out.getvalue()
    assert list(tmp_path.iterdir()) == []
