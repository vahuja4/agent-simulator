"""Static Markdown reporting from a completed batch directory alone."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from .types import BatchManifest, FailureCluster


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _link(label: str, path: str | None) -> str:
    return f"[{label}]({path})" if path else "—"


def render_report(batch_dir: str | Path) -> str:
    batch_dir = Path(batch_dir)
    manifest = BatchManifest.from_dict(
        json.loads((batch_dir / "manifest.json").read_text())
    )
    cluster_data = (
        json.loads((batch_dir / "clusters.json").read_text())
        if (batch_dir / "clusters.json").exists()
        else {"clusters": []}
    )
    clusters = [FailureCluster.from_dict(item) for item in cluster_data.get("clusters", [])]
    clusters.sort(key=lambda c: (-c.size, c.source, c.id, c.cluster_id))
    completed = [r for r in manifest.runs.values() if r.status == "completed"]
    outcomes = Counter(record.outcome for record in completed)

    lines = [
        "# AgentSim Batch Report",
        "",
        f"- Batch: `{manifest.batch_id}`",
        f"- Runs: {len(completed)} completed / {len(manifest.runs)} planned",
        f"- Harness LLM calls in runs: {manifest.run_llm_calls_total}",
        f"- Cluster-label LLM calls: {manifest.label_llm_calls}",
        f"- Total recorded LLM calls: {manifest.llm_calls_total}",
        "",
        "## Outcomes",
        "",
        "| pass | fail | task_incomplete | error |",
        "|---:|---:|---:|---:|",
        f"| {outcomes['pass']} | {outcomes['fail']} | {outcomes['task_incomplete']} | {outcomes['error']} |",
        "",
    ]

    acceptance_path = batch_dir / "acceptance.json"
    if acceptance_path.exists():
        acceptance = json.loads(acceptance_path.read_text())
        lines.extend(
            (
                "## Acceptance",
                "",
                f"- Overall: `{'pass' if acceptance.get('passed') else 'fail'}`",
                f"- Recall: `{'pass' if acceptance.get('recall', {}).get('passed') else 'fail'}`",
                f"- Precision: `{'pass' if acceptance.get('precision', {}).get('passed') else 'fail'}`",
                "",
            )
        )
        for issue in acceptance.get("issues", []):
            lines.append(f"- {_cell(issue)}")
        if acceptance.get("issues"):
            lines.append("")

    degraded = [record for record in completed if record.degraded_checks]
    lines.extend(("## Degraded checks", "", f"Runs with degraded checks: {len(degraded)}", ""))
    if degraded:
        lines.extend(("| Run | Scenario | Checks |", "|---|---|---|"))
        for record in sorted(degraded, key=lambda item: item.run_key):
            checks = ", ".join(
                sorted({str(item.get("check", "unknown")) for item in record.degraded_checks})
            )
            lines.append(
                f"| `{record.run_key}` | {_cell(record.scenario)} | {_cell(checks)} |"
            )
        lines.append("")

    errors = [record for record in completed if record.outcome == "error"]
    lines.extend(("## Harness errors", "", f"Error runs: {len(errors)}", ""))
    for record in sorted(errors, key=lambda item: item.run_key):
        lines.append(f"- `{record.run_key}`: {_cell(record.error or record.final_reasoning)}")
    if errors:
        lines.append("")

    lines.extend(("## Failure clusters", ""))
    if not clusters:
        lines.extend(("No failure clusters.", ""))
    for rank, cluster in enumerate(clusters, start=1):
        title = cluster.label or f"{cluster.source}:{cluster.id}"
        lines.extend(
            (
                f"### {rank}. {_cell(title)}",
                "",
                f"- Source: `{cluster.source}`",
                f"- Failure id: `{cluster.id}`",
                f"- Size: {cluster.size}",
                f"- Cluster id: `{cluster.cluster_id}`",
                "",
                "| Scenario | Run | Turn | Artifacts |",
                "|---|---|---:|---|",
            )
        )
        for member in cluster.members:
            artifacts = " · ".join(
                (
                    _link("transcript", member.get("transcript_path")),
                    _link("trace", member.get("trace_path")),
                    _link("replay", member.get("replay_path")),
                )
            )
            lines.append(
                f"| {_cell(member.get('scenario', ''))} | `{member.get('run_key', '')}` "
                f"| {_cell(member.get('turn_index', ''))} | {artifacts} |"
            )
        lines.append("")
        for member in cluster.members:
            rationale = str(member.get("message", "")).replace("\n", " ")
            lines.extend((f"> `{member.get('run_key', '')}` — {rationale}", ""))
    return "\n".join(lines)


def write_report(batch_dir: str | Path) -> Path:
    batch_dir = Path(batch_dir)
    output = batch_dir / "report.md"
    text = render_report(batch_dir)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=batch_dir, delete=False
    )
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, output)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)
    return output
