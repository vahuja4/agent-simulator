"""Summary of one Journey Run directory (design note section 9): failure
clusters and a static Markdown report, from the Run directory alone.

Clustering is ``agentsim.clustering.cluster_failures``, unchanged. It reads
``manifest.json`` and clusters outcome ``fail`` only, so an ``error`` can never
enter an agent-failure cluster, and a ``task_incomplete`` Episode — which has
no failure record, only a structured reason — can never enter one either. The
report therefore gives every outcome its own section, and an Episode counted in
the outcome table is always listed below it.

A cluster is a group of similar failure symptoms. It is not a diagnosis.
"""

from __future__ import annotations

import copy
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from ..batch import _atomic_text
from ..clustering import cluster_failures
from ..report import _cell, _link
from ..types import BatchManifest, BatchRunRecord, FailureCluster, FailureRecord
from .episode import (
    EPISODE_FILE,
    NORMALIZED_TRACE_FILE,
    RAW_TRACE_FILE,
    TRANSCRIPT_FILE,
)
from .evaluation import EVALUATION_FILE

RUN_RECORD_SCHEMA_VERSION = "1.0"
RUN_RECORD_FILE = "journey_run.json"
REPORT_FILE = "report.md"

RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETE = "complete"
RUN_STATUS_ABORTED = "aborted"

# Per-Episode identities inside a failure's ``data``. They differ whenever two
# conversations differ in length, so they are kept out of what is clustered.
_EPISODE_ID_KEYS = ("message_ids", "action_ids")

_EVIDENCE_LINKS = (
    ("conversation", TRANSCRIPT_FILE),
    ("raw Trace", RAW_TRACE_FILE),
    ("normalized Trace", NORMALIZED_TRACE_FILE),
    ("evaluation", EVALUATION_FILE),
    ("Episode record", EPISODE_FILE),
)

FIDELITY_NOTICE = (
    "**Simulated-user fidelity is not checked.** No check confirms that the "
    "Simulated user played each Scenario as written — its Persona, its Knowledge "
    "level (a specification here, not verified behavior), its Complication or its "
    "grounded facts. A failure below may therefore be the Simulated user's doing "
    "and not the agent's: for example, `update_matches_goal` fails when the "
    "customer accepted a slot outside its targets and the agent booked it "
    "correctly. Read the linked conversation before treating a cluster as an agent "
    "defect. A reported Run needs the human spot-check, recorded as Spot-check "
    "records under `journey_spot_checks/` in the format "
    "`agentsim/journey/spot_check.py` defines."
)
CLUSTER_NOTICE = (
    "Each cluster groups failures of the same check whose structured details are "
    "similar. A cluster is a set of similar failure symptoms, not a proven common "
    "root cause."
)


class RunSummaryError(ValueError):
    """The directory cannot be summarized as a Journey Run; nothing was written."""


def clustering_view(failure: FailureRecord) -> FailureRecord:
    """The failure as clustering may see it: the same record without the
    per-Episode message and action ids. The full record stays in
    ``evaluation.json``."""
    data = copy.deepcopy(failure.data)
    evidence = data.get("evidence")
    if isinstance(evidence, dict):
        for key in _EPISODE_ID_KEYS:
            evidence.pop(key, None)
    return replace(failure, data=data)


def load_run_record(run_dir: str | Path) -> dict[str, Any]:
    path = Path(run_dir) / RUN_RECORD_FILE
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RunSummaryError(f"{path} cannot be read: {error}") from error
    if not isinstance(record, dict):
        raise RunSummaryError(f"{path} is not an object")
    return record


@dataclass(frozen=True)
class RunSummary:
    run_dir: Path
    status: str
    outcomes: dict[str, int]
    not_finished: int
    clusters: list[FailureCluster]
    report_path: Path

    @property
    def aborted(self) -> bool:
        return self.status != RUN_STATUS_COMPLETE


def summarize_run(run_dir: str | Path) -> RunSummary:
    """Cluster the Run's failures and write ``clusters.json`` and ``report.md``."""
    run_dir = Path(run_dir)
    run = _Run.load(run_dir)
    clusters = cluster_failures(run_dir)
    report_path = run_dir / REPORT_FILE
    _atomic_text(report_path, _render(run, clusters))
    return RunSummary(
        run_dir=run_dir,
        status=str(run.record.get("status")),
        outcomes=run.outcomes,
        not_finished=len(run.not_finished),
        clusters=clusters,
        report_path=report_path,
    )


# ------------------------------------------------------------------ reading


@dataclass(frozen=True)
class _Episode:
    """One manifest record with what its Episode directory holds."""

    record: BatchRunRecord
    links: str
    evaluation: Mapping[str, Any] | None
    episode: Mapping[str, Any] | None

    @property
    def run_key(self) -> str:
        return self.record.run_key

    @property
    def explanation(self) -> str:
        if self.evaluation and self.evaluation.get("explanation"):
            return str(self.evaluation["explanation"])
        if self.record.error or self.record.final_reasoning:
            return self.record.error or self.record.final_reasoning
        error = (self.episode or {}).get("error")
        if isinstance(error, Mapping):
            return f"{error.get('type')}: {error.get('message')}"
        return "no outcome was recorded"

    @property
    def stop_reason(self) -> Any:
        return (self.evaluation or self.episode or {}).get("stop_reason")


@dataclass(frozen=True)
class _Run:
    run_dir: Path
    record: dict[str, Any]
    manifest: BatchManifest
    episodes: tuple[_Episode, ...]

    @classmethod
    def load(cls, run_dir: Path) -> "_Run":
        record = load_run_record(run_dir)
        try:
            manifest = BatchManifest.from_dict(
                json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise RunSummaryError(f"{run_dir}/manifest.json cannot be read: {error}") from error
        episodes = tuple(
            _episode(run_dir, manifest.runs[key]) for key in sorted(manifest.runs)
        )
        return cls(run_dir, record, manifest, episodes)

    def with_outcome(self, outcome: str) -> list[_Episode]:
        return [
            e for e in self.episodes
            if e.record.status == "completed" and e.record.outcome == outcome
        ]

    @property
    def outcomes(self) -> dict[str, int]:
        return {
            outcome: len(self.with_outcome(outcome))
            for outcome in ("pass", "fail", "task_incomplete", "error")
        }

    @property
    def not_finished(self) -> list[_Episode]:
        return [e for e in self.episodes if e.record.status != "completed"]

    @property
    def never_started(self) -> list[str]:
        """Planned Scenarios the Run never reached."""
        reached = {e.record.scenario for e in self.episodes}
        planned = self.record.get("scenario_ids") or []
        return [str(s) for s in planned if s not in reached]


def _episode(run_dir: Path, record: BatchRunRecord) -> _Episode:
    episode_dir = Path("runs") / record.run_key
    links = " · ".join(
        _link(label, str(episode_dir / name))
        for label, name in _EVIDENCE_LINKS
        if (run_dir / episode_dir / name).is_file()
    )
    return _Episode(
        record=record,
        links=links or "—",
        evaluation=_json_object(run_dir / episode_dir / EVALUATION_FILE),
        episode=_json_object(run_dir / episode_dir / EPISODE_FILE),
    )


def _json_object(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _error_group(episode: _Episode) -> tuple[bool, str]:
    """``(the agent's fault, group label)`` for an ``error`` Episode: the error
    kind and service code the Episode record holds, or the evaluation rule
    that made it an error."""
    evaluation = episode.evaluation or {}
    rule = (evaluation.get("rule") or {}).get("name")
    error = evaluation.get("episode_error") or (episode.episode or {}).get("error")
    if rule in (None, "episode_error") and isinstance(error, Mapping):
        adapter_error = error.get("adapter_error")
        if isinstance(adapter_error, Mapping):
            code = adapter_error.get("code")
            label = f"adapter {adapter_error.get('kind')}" + (f" {code}" if code else "")
            return bool(adapter_error.get("agent_fault")), label
        return False, f"{error.get('source')} {error.get('type')}"
    if rule is not None:
        return False, f"evaluation {rule}"
    return False, "no Episode record"


# ---------------------------------------------------------------- rendering


def render_run_report(run_dir: str | Path) -> str:
    """The report of a Run already clustered (``clusters.json`` as saved)."""
    run_dir = Path(run_dir)
    cluster_path = run_dir / "clusters.json"
    cluster_data = (
        json.loads(cluster_path.read_text(encoding="utf-8"))
        if cluster_path.exists() else {"clusters": []}
    )
    clusters = [FailureCluster.from_dict(item) for item in cluster_data.get("clusters", [])]
    clusters.sort(key=lambda c: (-c.size, c.source, c.id, c.cluster_id))
    return _render(_Run.load(run_dir), clusters)


def _render(run: _Run, clusters: list[FailureCluster]) -> str:
    lines = [f"# Journey Run report: {_cell(run.record.get('run_id', run.run_dir.name))}", ""]
    lines.extend(_header(run))
    lines.extend((FIDELITY_NOTICE, ""))
    lines.extend(_outcomes(run))
    lines.extend(_clusters(run, clusters))
    lines.extend(_task_incomplete(run))
    lines.extend(_errors(run))
    lines.extend(_not_finished(run))
    return "\n".join(lines)


def _header(run: _Run) -> list[str]:
    record = run.record
    status = record.get("status")
    lines = []
    if status != RUN_STATUS_COMPLETE:
        error = record.get("error") or {}
        why = (
            f": {error.get('type')}: {error.get('message')}" if error
            else " (no end was recorded)"
        )
        lines.extend((
            f"**This Run was ABORTED** (status `{_cell(status)}`){_cell(why)}. "
            "It did not play every Scenario; the counts below cover only what ran.",
            "",
        ))
    agents = sorted({
        str(e.episode["agent"]) for e in run.episodes if e.episode and e.episode.get("agent")
    })
    lines.extend((
        f"- Journey: `{_cell(record.get('journey_id'))}`",
        f"- Agent: `{_cell(record.get('agent'))}` at {_cell(record.get('service_url'))}"
        + (f" (Episodes answered by: {', '.join(agents)})" if agents else ""),
        f"- Scenario set: `{_cell(record.get('scenario_set'))}` "
        f"({len(record.get('scenario_ids') or [])} Scenarios, one Episode each, run "
        "sequentially)",
        f"- Simulated-user model: `{_cell(record.get('simulator_model'))}` · "
        f"Judge model: `{_cell(record.get('judge_model'))}`",
        f"- Started {_cell(record.get('started_at'))}, ended {_cell(record.get('ended_at'))}",
    ))
    if record.get("re_evaluated_at"):
        lines.append(f"- Re-evaluated {_cell(record['re_evaluated_at'])}")
    lines.extend((
        f"- Judge calls: {run.manifest.run_llm_calls_total}. The Simulated user's "
        "model calls are not recorded, so this is not a total.",
        "- This report does not establish Judge accuracy, test quality or coverage: "
        "the Scenarios are validated, not Qualified, and the Judge prompt is "
        "uncalibrated.",
        "",
    ))
    return lines


def _outcomes(run: _Run) -> list[str]:
    counts = run.outcomes
    unfinished = len(run.not_finished) + len(run.never_started)
    return [
        "## Outcomes",
        "",
        "| pass | fail | task_incomplete | error | not finished |",
        "|---:|---:|---:|---:|---:|",
        f"| {counts['pass']} | {counts['fail']} | {counts['task_incomplete']} "
        f"| {counts['error']} | {unfinished} |",
        "",
        "`fail` and `task_incomplete` are about the agent; `error` means nothing could "
        "be concluded.",
        "",
    ]


def _episode_table(episodes: list[_Episode]) -> list[str]:
    lines = ["| Scenario | Episode | Stop reason | Evidence |", "|---|---|---|---|"]
    for episode in episodes:
        lines.append(
            f"| {_cell(episode.record.scenario)} | `{episode.run_key}` "
            f"| {_cell(episode.stop_reason or '—')} | {episode.links} |"
        )
    lines.append("")
    for episode in episodes:
        lines.extend((f"> `{episode.run_key}` — {_cell(episode.explanation)}", ""))
    return lines


def _clusters(run: _Run, clusters: list[FailureCluster]) -> list[str]:
    by_key = {e.run_key: e for e in run.episodes}
    lines = ["## Failure clusters (outcome `fail`)", "", CLUSTER_NOTICE, ""]
    if not clusters:
        lines.extend(("No failure clusters.", ""))
    for rank, cluster in enumerate(clusters, start=1):
        lines.extend((
            f"### {rank}. {_cell(cluster.source)}:{_cell(cluster.id)} — "
            f"{cluster.size} failure(s)",
            "",
            f"- Cluster id: `{cluster.cluster_id}`",
            "",
            "| Scenario | Episode | Details | Evidence |",
            "|---|---|---|---|",
        ))
        for member in cluster.members:
            details = ", ".join(
                f"{key}={value}" for key, value in sorted(member.get("data", {}).items())
                if key != "evidence"
            )
            episode = by_key.get(member.get("run_key", ""))
            lines.append(
                f"| {_cell(member.get('scenario', ''))} | `{member.get('run_key', '')}` "
                f"| {_cell(details)} | {episode.links if episode else '—'} |"
            )
        lines.append("")
        for member in cluster.members:
            lines.extend((
                f"> `{member.get('run_key', '')}` — {_cell(member.get('message', ''))}", "",
            ))

    clustered = {member.get("run_key") for cluster in clusters for member in cluster.members}
    loose = [e for e in run.with_outcome("fail") if e.run_key not in clustered]
    if loose:
        lines.extend(("### Failed Episodes with no failure record", ""))
        lines.extend(_episode_table(loose))
    return lines


def _task_incomplete(run: _Run) -> list[str]:
    episodes = run.with_outcome("task_incomplete")
    lines = [
        "## Task incomplete",
        "",
        "Conduct was clean but the Expected outcome was not reached. These Episodes "
        "carry no failure record, so they are never in a cluster above; they are "
        "grouped by the structured reason evaluation recorded.",
        "",
    ]
    if not episodes:
        return lines + ["No `task_incomplete` Episodes.", ""]
    groups: dict[tuple[str, ...], list[_Episode]] = defaultdict(list)
    for episode in episodes:
        reason = (episode.evaluation or {}).get("incomplete") or {}
        groups[tuple(
            str(reason.get(key)) for key in
            ("expected_outcome", "outcome_status", "stop_reason", "judge_decision")
        )].append(episode)
    for key in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        expected, status, stop_reason, decision = key
        lines.extend((
            f"### Expected outcome `{_cell(expected)}` {_cell(status)}, stopped on "
            f"`{_cell(stop_reason)}`, Judge `{_cell(decision)}` — {len(groups[key])} Episode(s)",
            "",
        ))
        lines.extend(_episode_table(groups[key]))
    return lines


def _errors(run: _Run) -> list[str]:
    agent: dict[str, list[_Episode]] = defaultdict(list)
    other: dict[str, list[_Episode]] = defaultdict(list)
    for episode in run.with_outcome("error"):
        agent_fault, label = _error_group(episode)
        (agent if agent_fault else other)[label].append(episode)

    lines = [
        "## Agent errors",
        "",
        "The agent raised while handling a message (a crash, or a model looping past "
        "its step limit). The outcome is `error`, but this is the agent's doing, not "
        "infrastructure.",
        "",
    ]
    lines.extend(_error_groups(agent, "No agent errors."))
    lines.extend((
        "## Infrastructure and harness errors",
        "",
        "Transport, timeout, Simulated-user, Judge and evidence problems. They say "
        "nothing about the agent.",
        "",
    ))
    lines.extend(_error_groups(other, "No infrastructure or harness errors."))
    return lines


def _error_groups(groups: Mapping[str, list[_Episode]], empty: str) -> list[str]:
    if not groups:
        return [empty, ""]
    lines = []
    for label in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        lines.extend((f"### {_cell(label)} — {len(groups[label])} Episode(s)", ""))
        lines.extend(_episode_table(groups[label]))
    return lines


def _not_finished(run: _Run) -> list[str]:
    episodes, never_started = run.not_finished, run.never_started
    if not episodes and not never_started:
        return []
    lines = [
        "## Not finished",
        "",
        "The Run ended before these had an outcome.",
        "",
    ]
    if episodes:
        counts = Counter(e.record.status for e in episodes)
        lines.extend((
            "Interrupted: " + ", ".join(f"{n} {status}" for status, n in sorted(counts.items())),
            "",
        ))
        lines.extend(_episode_table(episodes))
    if never_started:
        lines.extend(("Never started:", ""))
        lines.extend(f"- {_cell(scenario_id)}" for scenario_id in never_started)
        lines.append("")
    return lines
