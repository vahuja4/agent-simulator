"""Generic async batch execution with resumable, self-contained artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

from ._io import _atomic_json
from .orchestrator import RunResult
from .scenario import Scenario
from .script import Step
from .trace import Trace
from .types import BatchManifest, BatchRunRecord

RunCallable = Callable[["BatchRunSpec"], Awaitable[RunResult]]
_OUTCOMES = {"pass", "fail", "task_incomplete", "error"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _slug(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    return "-".join(part for part in clean.split("-") if part)[:48] or "run"


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    )
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)


@dataclass(frozen=True)
class BatchRunSpec:
    scenario: Scenario
    run_id: str
    seed: int = 0
    model: str = ""
    persona_variant: str = "base"
    defect_flags: dict[str, bool] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    script: tuple[Step, ...] | None = None

    @property
    def run_key(self) -> str:
        identity = {
            "scenario": self.scenario.name,
            "run_id": self.run_id,
            "seed": self.seed,
            "model": self.model,
            "persona_variant": self.persona_variant,
            "defect_flags": self.defect_flags,
            "metadata": self.metadata,
        }
        digest = hashlib.sha256(_canonical(identity).encode()).hexdigest()[:12]
        return f"{_slug(self.scenario.name)}-{_slug(self.run_id)}-{digest}"


def render_transcript(trace: Trace) -> str:
    lines = [f"# Transcript: {trace.conversation_id}", ""]
    for turn in trace.turns:
        role = "Customer" if turn.speaker == "user" else "Assistant"
        lines.extend((f"## {turn.index} · {role}", "", turn.text, ""))
        for call in turn.tool_calls:
            lines.extend(
                (
                    f"- Tool: `{call.name}`",
                    f"  - Arguments: `{_canonical(call.arguments)}`",
                    f"  - Result: `{_canonical(call.result)}`",
                )
            )
        if turn.tool_calls:
            lines.append("")
    lines.extend((f"Outcome: `{trace.outcome}`", ""))
    return "\n".join(lines)


class BatchRunner:
    def __init__(
        self,
        output_dir: str | Path,
        *,
        concurrency: int = 4,
        retry_errors: bool = False,
        batch_id: str | None = None,
        configuration: dict[str, Any] | None = None,
    ) -> None:
        if concurrency <= 0:
            raise ValueError("concurrency must be positive")
        self.output_dir = Path(output_dir)
        self.concurrency = concurrency
        self.retry_errors = retry_errors
        self.batch_id = batch_id or self.output_dir.name
        self.configuration = dict(configuration or {})
        self.manifest_path = self.output_dir / "manifest.json"

    def _load_or_create_manifest(self) -> BatchManifest:
        if self.manifest_path.exists():
            manifest = BatchManifest.from_dict(json.loads(self.manifest_path.read_text()))
            if manifest.batch_id != self.batch_id:
                raise ValueError(
                    f"existing batch id {manifest.batch_id!r} does not match {self.batch_id!r}"
                )
            return manifest
        return BatchManifest(
            batch_id=self.batch_id,
            created_at=_utc_now(),
            configuration={"concurrency": self.concurrency, **self.configuration},
        )

    def _pending_record(self, spec: BatchRunSpec) -> BatchRunRecord:
        run_root = Path("runs") / spec.run_key
        return BatchRunRecord(
            run_key=spec.run_key,
            scenario=spec.scenario.name,
            scenario_source=spec.scenario.source,
            persona_variant=spec.persona_variant,
            defect_flags=dict(spec.defect_flags),
            model=spec.model,
            seed=spec.seed,
            run_id=spec.run_id,
            trace_path=str(run_root / "trace.json"),
            transcript_path=str(run_root / "transcript.md"),
            metadata=dict(spec.metadata),
        )

    def _completed_artifacts_valid(self, record: BatchRunRecord) -> bool:
        if record.status != "completed" or record.outcome not in _OUTCOMES:
            return False
        if not record.trace_path:
            return False
        trace_path = self.output_dir / record.trace_path
        run_path = trace_path.parent / "run.json"
        if not trace_path.is_file() or not run_path.is_file():
            return False
        try:
            persisted = BatchRunRecord.from_dict(json.loads(run_path.read_text()))
            trace = Trace.from_json(trace_path.read_text())
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return False
        return (
            persisted.run_key == record.run_key
            and persisted.outcome == record.outcome
            and trace.outcome == record.outcome
        )

    async def run(
        self, specs: Sequence[BatchRunSpec], execute: RunCallable
    ) -> BatchManifest:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "runs").mkdir(exist_ok=True)
        manifest = self._load_or_create_manifest()
        lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(self.concurrency)

        by_key = {spec.run_key: spec for spec in specs}
        if len(by_key) != len(specs):
            raise ValueError("batch run specs must have unique stable run keys")

        for spec in specs:
            manifest.runs.setdefault(spec.run_key, self._pending_record(spec))
        _atomic_json(self.manifest_path, manifest.to_dict())

        async def persist() -> None:
            async with lock:
                _atomic_json(self.manifest_path, manifest.to_dict())

        async def run_one(spec: BatchRunSpec) -> None:
            existing = manifest.runs[spec.run_key]
            if self._completed_artifacts_valid(existing) and not (
                self.retry_errors and existing.outcome == "error"
            ):
                return

            async with semaphore:
                record = self._pending_record(spec)
                record.status = "running"
                record.started_at = _utc_now()
                manifest.runs[spec.run_key] = record
                await persist()
                started = time.perf_counter()
                try:
                    result = await execute(spec)
                    if result.outcome not in _OUTCOMES:
                        raise ValueError(f"unknown run outcome {result.outcome!r}")
                    outcome = result.outcome
                    trace = result.trace
                    trace.outcome = outcome
                    record.final_reasoning = result.final_reasoning
                    record.verdicts = list(result.verdicts)
                    record.failures = list(result.failures)
                    record.degraded_checks = [dict(item) for item in result.degraded_checks]
                    record.llm_calls = result.llm_calls
                except Exception as exc:  # one bad run must not cancel the batch
                    outcome = "error"
                    trace = Trace(conversation_id=spec.run_key, outcome="error")
                    record.final_reasoning = f"batch execution error: {type(exc).__name__}: {exc}"
                    record.error = record.final_reasoning

                record.status = "completed"
                record.outcome = outcome
                record.finished_at = _utc_now()
                record.duration_seconds = round(time.perf_counter() - started, 6)
                run_root = self.output_dir / "runs" / spec.run_key
                _atomic_text(run_root / "trace.json", trace.to_json(indent=2) + "\n")
                _atomic_text(run_root / "transcript.md", render_transcript(trace))
                _atomic_json(run_root / "run.json", record.to_dict())
                manifest.runs[spec.run_key] = record
                await persist()

        await asyncio.gather(*(run_one(spec) for spec in specs))
        return manifest
