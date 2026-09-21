"""Spot-check records: a human's ruling on whether the Simulated user played
the Scenario it was given, one record per reviewed Episode.

Nothing on the Journey-definition path checks Simulated-user fidelity
automatically (design note section 12 item 3): matching an LLM customer's free
text, or trusting its own report, was considered and rejected as too
unreliable to be worth its false alarms. These records are therefore the only
evidence of Simulated-user fidelity this path has, and they are the labelled
data a future fidelity Judge would be tuned against — which is why they are a
strict file format rather than a note in a report. AGENTS.md requires the
spot-check before any reported Run; this module gives it a home and adds no
check of its own.

Records live in YAML files under ``journey_spot_checks/`` (any file name; a
file per Run is the obvious split)::

    schema_version: 1
    records:
      - run_id: run-2026-09-22          # journey_runs/<run_id>/
        scenario_id: synth-appointment-rescheduling-0123456789ab
        reviewer: vahuja4
        date: 2026-09-22                # the day of the review
        persona:         {verdict: faithful, note: ""}
        knowledge_level: {verdict: drifted, note: "Never stated the rule."}
        complication:    {verdict: not_applicable, note: "Complication is none."}
        grounded_facts:  {verdict: faithful, note: ""}

Each of the four aspects is ``faithful | drifted | not_applicable``. ``note`` is
always present; a ``drifted`` verdict must say what drifted, because a label
without it cannot be learned from. The loader refuses unknown fields, unknown
verdicts, a record whose Episode does not exist under the runs root, and the
same reviewer recording the same Episode twice in one file.

Validate a file with::

    .venv/bin/python -m agentsim.journey.spot_check <file> [--runs-root journey_runs]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from ._strict import _list, _load_yaml, _mapping, _schema_version, _strict, _string

DEFAULT_RUNS_ROOT = "journey_runs"
# ``episode.EPISODE_FILE``, restated: importing ``episode`` pulls in the Agent
# adapter package and the payments simulator, which reading a record needs
# none of. Pinned equal by a test.
EPISODE_FILE = "episode.json"

VERDICT_FAITHFUL = "faithful"
VERDICT_DRIFTED = "drifted"
VERDICT_NOT_APPLICABLE = "not_applicable"
SPOT_CHECK_VERDICTS: tuple[str, ...] = (
    VERDICT_FAITHFUL, VERDICT_DRIFTED, VERDICT_NOT_APPLICABLE,
)
SPOT_CHECK_ASPECTS: tuple[str, ...] = (
    "persona", "knowledge_level", "complication", "grounded_facts",
)


class SpotCheckError(ValueError):
    """A spot-check file failed validation."""


@dataclass(frozen=True)
class AspectRuling:
    verdict: str
    note: str


@dataclass(frozen=True)
class SpotCheckRecord:
    run_id: str
    scenario_id: str
    reviewer: str
    date: str  # ISO ``YYYY-MM-DD``
    persona: AspectRuling
    knowledge_level: AspectRuling
    complication: AspectRuling
    grounded_facts: AspectRuling
    episode_dir: Path  # the reviewed Episode, resolved under the runs root


def load_spot_check_records(
    path: str | Path, *, runs_root: str | Path = DEFAULT_RUNS_ROOT
) -> tuple[SpotCheckRecord, ...]:
    """Every record in one spot-check file, or a ``SpotCheckError`` naming the
    first thing wrong with it. ``runs_root`` holds the Run directories the
    records refer to."""
    path = Path(path)
    where = path.name
    raw = _load_yaml(path, error=SpotCheckError)
    _strict(raw, {"schema_version", "records"}, where, error=SpotCheckError)
    _schema_version(raw["schema_version"], where, error=SpotCheckError)
    records = tuple(
        _parse_record(item, f"{where}: records[{i}]", Path(runs_root))
        for i, item in enumerate(_list(raw["records"], f"{where}: records", error=SpotCheckError))
    )
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        key = (record.run_id, record.scenario_id, record.reviewer)
        if key in seen:
            raise SpotCheckError(
                f"{where}: reviewer {record.reviewer!r} records Episode "
                f"{record.scenario_id!r} of Run {record.run_id!r} more than once"
            )
        seen.add(key)
    return records


def _parse_record(raw: Any, spot: str, runs_root: Path) -> SpotCheckRecord:
    record = _mapping(raw, spot, error=SpotCheckError)
    _strict(
        record,
        {"run_id", "scenario_id", "reviewer", "date", *SPOT_CHECK_ASPECTS},
        spot,
        error=SpotCheckError,
    )
    run_id = _string(record["run_id"], f"{spot}.run_id", error=SpotCheckError)
    scenario_id = _string(record["scenario_id"], f"{spot}.scenario_id", error=SpotCheckError)
    return SpotCheckRecord(
        run_id=run_id,
        scenario_id=scenario_id,
        reviewer=_string(record["reviewer"], f"{spot}.reviewer", error=SpotCheckError),
        date=_review_date(record["date"], f"{spot}.date"),
        episode_dir=_episode_dir(runs_root, run_id, scenario_id, spot),
        **{
            aspect: _parse_ruling(record[aspect], f"{spot}.{aspect}")
            for aspect in SPOT_CHECK_ASPECTS
        },
    )


def _parse_ruling(raw: Any, spot: str) -> AspectRuling:
    ruling = _mapping(raw, spot, error=SpotCheckError)
    _strict(ruling, {"verdict", "note"}, spot, error=SpotCheckError)
    verdict = ruling["verdict"]
    if verdict not in SPOT_CHECK_VERDICTS:
        raise SpotCheckError(
            f"{spot}.verdict must be one of {list(SPOT_CHECK_VERDICTS)}, got {verdict!r}"
        )
    note = ruling["note"]
    if not isinstance(note, str):
        raise SpotCheckError(f"{spot}.note must be a string")
    note = note.strip()
    if verdict == VERDICT_DRIFTED and not note:
        raise SpotCheckError(f"{spot}: a drifted verdict needs a note saying what drifted")
    return AspectRuling(verdict, note)


def _review_date(value: Any, spot: str) -> str:
    # YAML reads an unquoted 2026-09-22 as a date; a quoted one stays a string.
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            pass
    raise SpotCheckError(f"{spot} must be a calendar date, YYYY-MM-DD, got {value!r}")


def _episode_dir(runs_root: Path, run_id: str, scenario_id: str, spot: str) -> Path:
    """The Episode directory of this Scenario in this Run (design note section
    9: ``<runs_root>/<run_id>/runs/<run_key>/``; one Episode per Scenario). The
    ids are compared, never joined into a path."""
    run_dirs = runs_root.iterdir() if runs_root.is_dir() else ()
    run_dir = next((p for p in run_dirs if p.name == run_id and p.is_dir()), None)
    if run_dir is None:
        raise SpotCheckError(f"{spot}: no Run {run_id!r} under {runs_root}")
    matches = [
        episode_file.parent
        for episode_file in sorted(run_dir.glob(f"runs/*/{EPISODE_FILE}"))
        if _scenario_id_of(episode_file) == scenario_id
    ]
    if not matches:
        raise SpotCheckError(
            f"{spot}: Run {run_id!r} under {runs_root} has no Episode of "
            f"Scenario {scenario_id!r}"
        )
    if len(matches) > 1:
        raise SpotCheckError(
            f"{spot}: Run {run_id!r} has {len(matches)} Episodes of Scenario "
            f"{scenario_id!r}; a record must name exactly one"
        )
    return matches[0]


def _scenario_id_of(episode_file: Path) -> str | None:
    try:
        episode = json.loads(episode_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return episode.get("scenario_id") if isinstance(episode, Mapping) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a spot-check file.")
    parser.add_argument("file")
    parser.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT)
    args = parser.parse_args(argv)
    try:
        records = load_spot_check_records(args.file, runs_root=args.runs_root)
    except SpotCheckError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 2
    print(f"valid: {len(records)} spot-check record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
