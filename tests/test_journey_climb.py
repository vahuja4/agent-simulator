"""Climbing a Ladder: it goes up while Rungs are clean, stops at the first one
that is not, keeps what it wrote when it falls over, and never claims a break
it did not see. No Episode, no adapter, no model: ``play`` is injected."""

import json
from pathlib import Path

import pytest

from agentsim.journey.climb import (
    CLIMB_ABORTED,
    CLIMB_COMPLETE,
    CLIMB_RECORD_FILE,
    RUNG_BROKE,
    RUNG_INCONCLUSIVE,
    RUNG_SURVIVED,
    STOPPED_BROKE,
    STOPPED_INCONCLUSIVE,
    STOPPED_LADDER_EXHAUSTED,
    ClimbError,
    SeedResult,
    climb,
    rung_state,
    summarize,
)
from agentsim.journey.evaluation import (
    OUTCOME_ERROR,
    OUTCOME_FAIL,
    OUTCOME_PASS,
    OUTCOME_TASK_INCOMPLETE,
)
from scenario_synthesis.ladder import IDENTIFY_EXISTING_APPOINTMENT

LADDER = IDENTIFY_EXISTING_APPOINTMENT


def _play_from(outcomes):
    """``outcomes`` maps a Rung number to what each of its Seeds returned.
    Records what was asked for, so a test can assert what was not played."""
    played = []

    async def play(rung: int, seed: int) -> SeedResult:
        played.append((rung, seed))
        by_seed = outcomes[rung]
        outcome = by_seed[seed] if isinstance(by_seed, dict) else by_seed
        return SeedResult(seed=seed, episode_dir=f"rung-{rung}-seed-{seed}", outcome=outcome)

    return play, played


def _clock():
    stamps = iter(f"2026-09-25T00:00:{n:02d}Z" for n in range(60))
    return lambda: next(stamps)


async def _climb(tmp_path, outcomes, *, seeds=(0,)):
    play, played = _play_from(outcomes)
    record = await climb(
        LADDER,
        play=play,
        climb_dir=tmp_path / "climb",
        agent="stub",
        seeds=seeds,
        now=_clock(),
    )
    return record, played


# ------------------------------------------------------------ rung state


@pytest.mark.parametrize(
    "outcomes,expected",
    [
        ([OUTCOME_PASS], RUNG_SURVIVED),
        ([OUTCOME_TASK_INCOMPLETE], RUNG_SURVIVED),
        ([OUTCOME_PASS, OUTCOME_TASK_INCOMPLETE], RUNG_SURVIVED),
        ([OUTCOME_PASS, OUTCOME_FAIL], RUNG_BROKE),
        ([OUTCOME_FAIL, OUTCOME_FAIL], RUNG_BROKE),
        ([OUTCOME_PASS, OUTCOME_ERROR], RUNG_INCONCLUSIVE),
        ([OUTCOME_FAIL, OUTCOME_ERROR], RUNG_INCONCLUSIVE),
    ],
)
def test_a_rung_survives_only_when_every_seed_is_clean(outcomes, expected):
    seeds = tuple(
        SeedResult(seed=n, episode_dir=str(n), outcome=outcome)
        for n, outcome in enumerate(outcomes)
    )
    assert rung_state(seeds) == expected


def test_task_incomplete_is_survived_not_a_break():
    """Rung 3 is built to end this way. An agent that correctly refuses to guess
    which appointment she means has not broken anything."""
    assert rung_state((SeedResult(0, "d", OUTCOME_TASK_INCOMPLETE),)) == RUNG_SURVIVED


def test_an_unreadable_seed_outranks_a_failed_one():
    """With evidence missing there is nothing to rule on, so the climb must not
    report a break it cannot show."""
    seeds = (SeedResult(0, "d", OUTCOME_FAIL), SeedResult(1, "e", OUTCOME_ERROR))
    assert rung_state(seeds) == RUNG_INCONCLUSIVE


def test_an_unknown_outcome_is_refused():
    with pytest.raises(ClimbError, match="unknown Verdict outcome"):
        rung_state((SeedResult(0, "d", "probably_fine"),))


# ---------------------------------------------------------------- climbing


@pytest.mark.asyncio
async def test_it_climbs_while_rungs_are_clean_and_stops_at_the_first_break(tmp_path):
    record, played = await _climb(
        tmp_path,
        {1: OUTCOME_PASS, 2: OUTCOME_PASS, 3: OUTCOME_TASK_INCOMPLETE, 4: OUTCOME_FAIL},
    )
    assert record.highest_survived == 3
    assert record.broke_at == 4
    assert record.stopped_because == STOPPED_BROKE
    assert record.status == CLIMB_COMPLETE
    assert [rung.state for rung in record.rungs] == [
        RUNG_SURVIVED,
        RUNG_SURVIVED,
        RUNG_SURVIVED,
        RUNG_BROKE,
    ]
    assert played == [(1, 0), (2, 0), (3, 0), (4, 0)]


@pytest.mark.asyncio
async def test_a_break_low_down_stops_the_climb_before_the_rungs_above(tmp_path):
    record, played = await _climb(tmp_path, {1: OUTCOME_PASS, 2: OUTCOME_FAIL})
    assert record.highest_survived == 1
    assert record.broke_at == 2
    assert played == [(1, 0), (2, 0)], "Rungs 3 and 4 must not be played"


@pytest.mark.asyncio
async def test_surviving_every_rung_is_a_result_of_its_own(tmp_path):
    record, _ = await _climb(tmp_path, dict.fromkeys((1, 2, 3, 4), OUTCOME_PASS))
    assert record.highest_survived == 4
    assert record.broke_at is None
    assert record.stopped_because == STOPPED_LADDER_EXHAUSTED
    assert "survived every Rung" in summarize(record)


@pytest.mark.asyncio
async def test_an_unreadable_rung_stops_the_climb_without_claiming_a_break(tmp_path):
    record, played = await _climb(tmp_path, {1: OUTCOME_PASS, 2: OUTCOME_ERROR})
    assert record.highest_survived == 1
    assert record.broke_at is None
    assert record.stopped_because == STOPPED_INCONCLUSIVE
    assert played == [(1, 0), (2, 0)]
    assert "unreadable" in summarize(record)


@pytest.mark.asyncio
async def test_a_rung_that_breaks_on_one_seed_still_plays_the_rest(tmp_path):
    """Whether a break is every time or one time in three is the number a
    reviewer needs and cannot get afterwards."""
    record, played = await _climb(
        tmp_path,
        {1: OUTCOME_PASS, 2: {0: OUTCOME_PASS, 1: OUTCOME_FAIL, 2: OUTCOME_PASS}},
        seeds=(0, 1, 2),
    )
    assert record.broke_at == 2
    assert record.rungs[-1].broke_on == (1,)
    assert played == [(1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)]
    assert "on 1 of 3 Seed(s)" in summarize(record)


@pytest.mark.asyncio
async def test_a_rung_is_survived_only_when_all_its_seeds_are(tmp_path):
    record, _ = await _climb(
        tmp_path,
        {1: {0: OUTCOME_PASS, 1: OUTCOME_FAIL}},
        seeds=(0, 1),
    )
    assert record.highest_survived is None
    assert record.broke_at == 1


# ------------------------------------------------------- the written record


@pytest.mark.asyncio
async def test_the_record_is_written_as_the_climb_goes(tmp_path):
    """A climb interrupted between Rungs still has every finished Rung on
    disk."""
    seen = []

    async def play(rung: int, seed: int) -> SeedResult:
        path = tmp_path / "climb" / CLIMB_RECORD_FILE
        seen.append(len(json.loads(path.read_text())["rungs"]))
        return SeedResult(seed=seed, episode_dir=f"r{rung}", outcome=OUTCOME_PASS)

    await climb(
        LADDER, play=play, climb_dir=tmp_path / "climb", agent="stub", now=_clock()
    )
    assert seen == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_a_climb_that_falls_over_keeps_what_it_wrote_and_says_so(tmp_path):
    async def play(rung: int, seed: int) -> SeedResult:
        if rung == 3:
            raise RuntimeError("the service went away")
        return SeedResult(seed=seed, episode_dir=f"r{rung}", outcome=OUTCOME_PASS)

    with pytest.raises(RuntimeError, match="went away"):
        await climb(
            LADDER, play=play, climb_dir=tmp_path / "climb", agent="stub", now=_clock()
        )

    written = json.loads((tmp_path / "climb" / CLIMB_RECORD_FILE).read_text())
    assert written["status"] == CLIMB_ABORTED
    assert written["error"]["type"] == "RuntimeError"
    assert [rung["rung"] for rung in written["rungs"]] == [1, 2]
    assert written["broke_at"] is None, "falling over is not the agent breaking"


@pytest.mark.asyncio
async def test_the_record_names_the_rule_the_ladder_and_the_agent(tmp_path):
    record, _ = await _climb(tmp_path, {1: OUTCOME_FAIL})
    written = json.loads((tmp_path / "climb" / CLIMB_RECORD_FILE).read_text())
    assert written["rule_id"] == "identify_existing_appointment"
    assert written["set_id"] == "ladder-identify-existing-appointment"
    assert written["agent"] == "stub"
    assert written["journey_id"] == "appointment-rescheduling"
    assert written["schema_version"] == "1.0"


@pytest.mark.asyncio
async def test_an_existing_climb_is_never_overwritten(tmp_path):
    await _climb(tmp_path, {1: OUTCOME_FAIL})
    play, _ = _play_from({1: OUTCOME_PASS})
    with pytest.raises(ClimbError, match="never overwritten"):
        await climb(LADDER, play=play, climb_dir=tmp_path / "climb", agent="stub")


@pytest.mark.asyncio
async def test_repeated_seeds_are_refused(tmp_path):
    play, _ = _play_from({1: OUTCOME_PASS})
    with pytest.raises(ClimbError, match="must be distinct"):
        await climb(
            LADDER, play=play, climb_dir=tmp_path / "c", agent="stub", seeds=(0, 0)
        )


@pytest.mark.asyncio
async def test_a_climb_needs_a_seed(tmp_path):
    play, _ = _play_from({})
    with pytest.raises(ClimbError, match="at least one Seed"):
        await climb(LADDER, play=play, climb_dir=tmp_path / "c", agent="stub", seeds=())


@pytest.mark.asyncio
async def test_the_summary_reports_a_break_as_suspected_and_sends_it_to_a_person(tmp_path):
    """ADR 0008: nothing is confirmed by a machine, so the one line a person
    reads must not read as a ruling."""
    record, _ = await _climb(tmp_path, {1: OUTCOME_PASS, 2: OUTCOME_FAIL})
    line = summarize(record)
    assert "suspected break at Rung 2" in line
    assert "a human rules on it" in line
    assert "fault" not in line


@pytest.mark.asyncio
async def test_an_aborted_climb_is_never_summarized_as_a_ladder_survived(tmp_path):
    async def play(rung: int, seed: int) -> SeedResult:
        raise RuntimeError("the service went away")

    with pytest.raises(RuntimeError):
        await climb(
            LADDER, play=play, climb_dir=tmp_path / "climb", agent="stub", now=_clock()
        )
    written = json.loads((tmp_path / "climb" / CLIMB_RECORD_FILE).read_text())
    assert written["status"] == CLIMB_ABORTED
    assert written["highest_survived"] is None
