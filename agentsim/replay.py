"""Mechanical replay artifacts derived only from serialized Trace turns."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .script import Step, agent, script_from_dicts, script_to_dicts, user, validate_script
from .trace import Trace
from .types import BatchManifest

REPLAY_SCHEMA_VERSION = "1.0"


def script_from_trace(trace: Trace) -> list[Step]:
    steps = [user(turn.text) if turn.speaker == "user" else agent() for turn in trace.turns]
    validate_script(steps)
    return steps


def replay_to_dict(trace: Trace) -> dict[str, Any]:
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "conversation_id": trace.conversation_id,
        "steps": script_to_dicts(script_from_trace(trace)),
    }


def replay_from_dict(data: dict[str, Any]) -> list[Step]:
    if data.get("schema_version") != REPLAY_SCHEMA_VERSION:
        raise ValueError(f"unsupported replay schema {data.get('schema_version')!r}")
    steps = script_from_dicts(data.get("steps", []))
    validate_script(steps)
    return steps


def load_replay(path: str | Path) -> list[Step]:
    return replay_from_dict(json.loads(Path(path).read_text()))


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    )
    try:
        with handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)


def emit_replay(trace: Trace, path: str | Path) -> Path:
    path = Path(path)
    _atomic_json(path, replay_to_dict(trace))
    return path


def emit_batch_replays(batch_dir: str | Path) -> BatchManifest:
    """Emit one replay per failed run and update its generic artifact links."""
    batch_dir = Path(batch_dir)
    manifest_path = batch_dir / "manifest.json"
    manifest = BatchManifest.from_dict(json.loads(manifest_path.read_text()))
    for run_key in sorted(manifest.runs):
        record = manifest.runs[run_key]
        if record.status != "completed" or record.outcome != "fail":
            continue
        if not record.trace_path:
            raise ValueError(f"failed run {run_key} has no trace path")
        trace = Trace.from_json((batch_dir / record.trace_path).read_text())
        replay_path = Path("runs") / run_key / "replay.json"
        emit_replay(trace, batch_dir / replay_path)
        record.replay_path = str(replay_path)
        run_path = batch_dir / "runs" / run_key / "run.json"
        _atomic_json(run_path, record.to_dict())
    _atomic_json(manifest_path, manifest.to_dict())
    return manifest
