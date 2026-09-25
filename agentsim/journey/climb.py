"""Climbing a Ladder: run a Rung, read its saved Verdicts, decide whether to
go up (ADR 0008).

This module is the decision, not the plumbing. It is handed a ``play`` that
plays one Seed of one Rung and returns what the Verdict said; everything to do
with adapters, Simulated users and Judges lives in the caller. That is what
makes the climb testable without an Episode: the only thing worth proving here
is that it goes up while Rungs are clean, stops at the first one that is not,
and never claims a break it did not see.

What each Verdict means for a climb:

``pass``             clean conduct and the Goal reached. Survived.
``task_incomplete``  clean conduct, Goal not reached. **Survived.** Rung 3 is
                     built to end this way: a customer who will not say which
                     appointment she means should end a conversation with
                     nothing moved, and an agent that correctly refuses to guess
                     has not broken anything.
``fail``             an Assertion failed or the Judge failed a criterion. Broke.
``error``            an Episode error, or evidence that is unavailable. Neither
                     survived nor broke: there is nothing to read. The climb
                     stops as ``inconclusive``, because a Rung above an
                     unreadable one proves nothing about the Rung below it.

Every Seed of a Rung is played even after one breaks. The extra conversations
buy the one number a reviewer needs and cannot get later: whether the break is
every time or one time in five.

A ``fail`` here is a *suspected* finding. Nothing in this module makes it the
agent's fault; that needs a human, per ADR 0008.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .._io import _atomic_json
from .evaluation import (
    OUTCOME_ERROR,
    OUTCOME_FAIL,
    OUTCOME_PASS,
    OUTCOME_TASK_INCOMPLETE,
)

CLIMB_RECORD_FILE = "climb.json"
CLIMB_SCHEMA_VERSION = "1.0"

RUNG_SURVIVED = "survived"
RUNG_BROKE = "broke"
RUNG_INCONCLUSIVE = "inconclusive"

CLIMB_COMPLETE = "complete"
CLIMB_ABORTED = "aborted"

STOPPED_BROKE = "rung_broke"
STOPPED_INCONCLUSIVE = "rung_inconclusive"
STOPPED_LADDER_EXHAUSTED = "ladder_exhausted"

_SURVIVING = frozenset({OUTCOME_PASS, OUTCOME_TASK_INCOMPLETE})


class ClimbError(ValueError):
    """A climb cannot start; nothing was written."""


@dataclass(frozen=True)
class SeedResult:
    """One Seed of one Rung, as its Verdict left it."""

    seed: int
    episode_dir: str
    outcome: str
    failures: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class RungResult:
    rung: int
    state: str
    seeds: tuple[SeedResult, ...]

    @property
    def broke_on(self) -> tuple[int, ...]:
        return tuple(seed.seed for seed in self.seeds if seed.outcome == OUTCOME_FAIL)


@dataclass
class ClimbRecord:
    """What a climb leaves behind. ``highest_survived`` and ``broke_at`` are the
    result for the rule; ``status`` says whether the climb itself finished, and
    is never used to say how the agent did."""

    schema_version: str
    journey_id: str
    rule_id: str
    set_id: str
    agent: str
    seeds: tuple[int, ...]
    started_at: str
    status: str
    ended_at: str | None = None
    stopped_because: str | None = None
    highest_survived: int | None = None
    broke_at: int | None = None
    rungs: list[RungResult] = field(default_factory=list)
    error: Mapping[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "seeds": list(self.seeds),
            "rungs": [
                {**asdict(rung), "seeds": [asdict(seed) for seed in rung.seeds]}
                for rung in self.rungs
            ],
        }


def rung_state(seeds: Sequence[SeedResult]) -> str:
    """A Rung is survived only when every Seed of it is clean."""
    if not seeds:
        raise ClimbError("a Rung with no Seed has no state")
    outcomes = {seed.outcome for seed in seeds}
    unknown = outcomes - _SURVIVING - {OUTCOME_FAIL, OUTCOME_ERROR}
    if unknown:
        raise ClimbError(f"unknown Verdict outcome(s) {sorted(unknown)}")
    if OUTCOME_ERROR in outcomes:
        return RUNG_INCONCLUSIVE
    if OUTCOME_FAIL in outcomes:
        return RUNG_BROKE
    return RUNG_SURVIVED


async def climb(
    ladder: Any,
    *,
    play: Callable[[int, int], Awaitable[SeedResult]],
    climb_dir: str | Path,
    agent: str,
    seeds: Sequence[int] = (0,),
    now: Callable[[], str] = lambda: datetime.now(timezone.utc)
    .isoformat(timespec="seconds")
    .replace("+00:00", "Z"),
) -> ClimbRecord:
    """Climb ``ladder``, Rung by Rung, until one does not survive.

    ``play(rung, seed)`` plays one Episode and returns its Verdict. Whatever it
    raises aborts the climb: the record keeps every Rung already finished and is
    marked ``aborted`` with the error, so a climb that falls over is never
    mistaken for a Ladder the agent survived."""
    climb_dir = Path(climb_dir)
    if not seeds:
        raise ClimbError("a climb needs at least one Seed")
    if len(set(seeds)) != len(seeds):
        raise ClimbError(f"Seeds must be distinct, got {list(seeds)}")
    if (climb_dir / CLIMB_RECORD_FILE).exists():
        raise ClimbError(f"{climb_dir} already holds a climb; it is never overwritten")
    climb_dir.mkdir(parents=True, exist_ok=True)

    record = ClimbRecord(
        schema_version=CLIMB_SCHEMA_VERSION,
        journey_id=ladder.journey_id,
        rule_id=ladder.rule_id,
        set_id=ladder.set_id,
        agent=agent,
        seeds=tuple(seeds),
        started_at=now(),
        status=CLIMB_ABORTED,
    )
    _write(record, climb_dir)

    try:
        for spec in ladder.rungs:
            results = [await play(spec.rung, seed) for seed in seeds]
            outcome = RungResult(
                rung=spec.rung, state=rung_state(tuple(results)), seeds=tuple(results)
            )
            record.rungs.append(outcome)
            if outcome.state == RUNG_SURVIVED:
                record.highest_survived = spec.rung
            elif outcome.state == RUNG_BROKE:
                record.broke_at = spec.rung
                record.stopped_because = STOPPED_BROKE
            else:
                record.stopped_because = STOPPED_INCONCLUSIVE
            _write(record, climb_dir)
            if outcome.state != RUNG_SURVIVED:
                break
        else:
            record.stopped_because = STOPPED_LADDER_EXHAUSTED
    except BaseException as error:  # keep what was written (AGENTS.md)
        record.ended_at = now()
        record.error = {"type": type(error).__name__, "message": str(error)}
        _write(record, climb_dir)
        raise

    record.status = CLIMB_COMPLETE
    record.ended_at = now()
    _write(record, climb_dir)
    return record


def _write(record: ClimbRecord, climb_dir: Path) -> None:
    _atomic_json(climb_dir / CLIMB_RECORD_FILE, record.to_dict())


def summarize(record: ClimbRecord) -> str:
    """One line a person can read. It says how far the agent climbed and never
    whether the break is the agent's fault."""
    if record.status != CLIMB_COMPLETE:
        return (
            f"{record.rule_id}: climb aborted after "
            f"{len(record.rungs)} Rung(s) — what was written is kept"
        )
    survived = "none" if record.highest_survived is None else str(record.highest_survived)
    if record.broke_at is None and record.stopped_because == STOPPED_INCONCLUSIVE:
        return f"{record.rule_id}: survived to Rung {survived}; the next Rung was unreadable"
    if record.broke_at is None:
        return f"{record.rule_id}: survived every Rung (to {survived})"
    broke = record.rungs[-1]
    return (
        f"{record.rule_id}: survived to Rung {survived}, suspected break at Rung "
        f"{record.broke_at} on {len(broke.broke_on)} of {len(record.seeds)} Seed(s) "
        "— a human rules on it"
    )
