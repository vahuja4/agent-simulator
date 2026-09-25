"""The Journey harness commands (design note section 9, ADR 0008), on doubles.

``run`` and ``probe`` are exercised through ``run_command`` and
``probe_command`` with an adapter, Simulated-user and Judge double: they have
no doubles mode of their own. These tests are plain functions — the commands
enter the process-local event loop themselves.

The ``probe`` tests are about the plumbing only: that the climb's decision
reaches real Episodes and real Verdicts, that a Rung is resolved by its number,
and that what a Probe leaves behind points at its evidence. Whether the agent
actually breaks is not a thing a double can say.
"""

from __future__ import annotations

import asyncio
import io
import json
import shutil
from pathlib import Path

import pytest

from agentsim.batch import BatchRunner
from agentsim.journey.definition import JourneyDefinitionError
from agentsim.journey.scenario import load_journey_scenario
from scenario_synthesis import journey_synthesis as js
from scripts import journey_harness as jh
from tests.journey_run_doubles import (
    JOURNEY_DIR,
    NO_ANSWER,
    SERVICE_URL,
    ScenarioJudge,
    SequenceAdapter,
    play_probe,
    play_run,
    realize,
    rung_scenarios,
    saved_scenarios,
    synthesize,
)
from tests.test_journey_synthesis import ScriptedProvider

EPISODE_FILES = {
    "scenario.yaml", "transcript.jsonl", "episode.json", "raw_trace.json",
    "normalized_trace.json", "evaluation.json", "trace.json", "transcript.md", "run.json",
}


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def run_record(run_dir: Path) -> dict:
    return read(run_dir / "journey_run.json")


def edited_journey_dir(root: Path) -> Path:
    """The Journey directory with one Judge criterion reworded."""
    copy = root / "edited_journey"
    shutil.copytree(JOURNEY_DIR, copy)
    journey = copy / "journey.yaml"
    text = journey.read_text()
    assert "clear yes" in text
    journey.write_text(text.replace("clear yes", "clear and unmistakable yes", 1))
    return copy


# --------------------------------------------------------------------- help


@pytest.mark.parametrize("command, mentions", [
    ((), ("synthesize", "run", "probe", "summarize")),
    (("synthesize",), ("--journey", "--count", "--set-id", "--stub", "not Qualification")),
    (("run",), ("--journey", "--scenarios", "--service-url", "--run-id",
                "--request-timeout", "--episode-timeout", "--re-evaluate", "120", "600")),
    (("probe",), ("--journey", "--scenarios", "--service-url", "--probe-id", "--seeds",
                  "journey_probes", "never a Pass rate", "suspected finding a human rules on",
                  "stopping at the first Rung not survived")),
    (("summarize",), ("RUN_DIR", "report.md", "not proven root causes")),
])
def test_every_command_prints_useful_help(capsys, command, mentions):
    with pytest.raises(SystemExit) as exit_:
        jh.main([*command, "--help"])
    assert exit_.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    for mention in mentions:
        assert mention in text


# --------------------------------------------------------------- synthesize


def test_synthesize_only_parses_arguments_and_returns_the_commands_status(tmp_path):
    out = io.StringIO()
    status = jh.main(
        ["synthesize", "--journey", str(JOURNEY_DIR), "--count", "2", "--set-id", "set-1",
         "--stub", "--output-root", str(tmp_path)],
        out=out,
    )
    set_dir = tmp_path / "appointment-rescheduling" / "set-1"
    assert status == 0
    assert len(list((set_dir / "accepted").glob("*.yaml"))) == 2
    assert js.verify_provenance(set_dir, JOURNEY_DIR) == []

    again = jh.main(
        ["synthesize", "--journey", str(JOURNEY_DIR), "--count", "2", "--set-id", "set-1",
         "--stub", "--output-root", str(tmp_path)],
        out=out,
    )
    assert again == 2  # the set id is taken


# ---------------------------------------------------------------------- run


def test_run_plays_every_scenario_in_order_and_leaves_a_complete_run(tmp_path):
    played = play_run(tmp_path, ["pass", "pass", "pass"])

    assert (played.status, played.raised) == (0, None)
    assert "agent: stub" in played.output  # never mistaken for the LangGraph agent
    assert played.adapter.adapters == []  # one conversation per Scenario, after the probe
    record = run_record(played.run_dir)
    assert record["status"] == "complete" and record["error"] is None
    assert record["agent"] == "stub"
    assert record["scenario_ids"] == [s.scenario_id for s in played.scenarios]
    assert (record["request_timeout_s"], record["episode_timeout_s"]) == (120.0, 600.0)

    manifest = read(played.run_dir / "manifest.json")
    assert [r["outcome"] for r in manifest["runs"].values()] == ["pass"] * 3
    for index in range(3):
        assert {p.name for p in played.episode_dir(index).iterdir()} == EPISODE_FILES
    started = [
        read(played.episode_dir(i) / "episode.json")["started_at"] for i in range(3)
    ]
    ended = [read(played.episode_dir(i) / "episode.json")["ended_at"] for i in range(3)]
    assert started == sorted(started) and all(e <= s for e, s in zip(ended, started[1:]))


def test_the_timeouts_are_parameters_that_reach_the_episode(tmp_path):
    played = play_run(tmp_path, ["pass"], episode_timeout_s=42.0, request_timeout_s=7.0)
    assert read(played.episode_dir(0) / "episode.json")["time_limit_s"] == 42.0
    assert run_record(played.run_dir)["request_timeout_s"] == 7.0


@pytest.mark.parametrize("behaviour", ["agent_error", "transport", "simulator_error"])
def test_a_scenario_that_errors_is_recorded_as_error_and_the_next_still_runs(
    tmp_path, behaviour
):
    played = play_run(tmp_path, ["pass", behaviour, "pass"])

    assert played.status == 0  # an error Episode is a result, not a command failure
    outcomes = [
        read(played.episode_dir(i) / "evaluation.json")["outcome"] for i in range(3)
    ]
    assert outcomes == ["pass", "error", "pass"]
    assert run_record(played.run_dir)["status"] == "complete"


def test_a_simulated_user_that_cannot_be_built_is_that_scenarios_error(tmp_path):
    """``check_against_inputs`` refuses such a Scenario first; if building
    raises anyway, it is that Scenario's error and the next one still runs."""
    gone = JourneyDefinitionError("knowledge rule 'gone' is not defined")
    played = play_run(tmp_path, ["pass", "pass", "pass"], unbuildable={1: gone})

    manifest = read(played.run_dir / "manifest.json")
    by_scenario = {r["scenario"]: r for r in manifest["runs"].values()}
    assert played.status == 0
    assert [by_scenario[s.scenario_id]["outcome"] for s in played.scenarios] == [
        "pass", "error", "pass",
    ]
    assert "JourneyDefinitionError" in by_scenario[played.scenarios[1].scenario_id]["error"]


def test_run_is_one_scenario_at_a_time_and_never_retries(tmp_path, monkeypatch):
    made = []

    class Spy(BatchRunner):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

        async def run(self, specs, execute):
            assert len(specs) == 1  # nothing can run alongside anything else
            return await super().run(specs, execute)

    monkeypatch.setattr(jh, "BatchRunner", Spy)
    played = play_run(tmp_path, ["pass", "agent_error", "pass"])

    assert played.status == 0 and made
    # run_episode refuses a directory that already holds an Episode: no retry.
    assert all(r.concurrency == 1 and r.retry_errors is False for r in made)
    assert played.adapter.adapters == []  # three conversations, none repeated


# ----------------------------------------------------------------- refusals


def assert_refused(played, *fragments):
    assert played.status == 2 and played.raised is None
    assert played.output.count("\n") == 1
    for fragment in fragments:
        assert fragment in played.output
    assert not played.run_dir.exists()  # exit 2 is always before the first write


def test_run_refuses_a_set_that_fails_its_provenance_check(tmp_path):
    set_dir = synthesize(tmp_path, 2)
    accepted = sorted((set_dir / "accepted").glob("*.yaml"))[0]
    accepted.write_text(accepted.read_text().replace("max_turns: 12", "max_turns: 99"))

    played = play_run(tmp_path, ["pass", "pass"], set_dir=set_dir)
    assert_refused(played, "fails its provenance check", "missing or changed")


def test_run_refuses_a_half_written_aborted_set(tmp_path):
    out = io.StringIO()
    status = js.synthesize_command(
        journey_dir=JOURNEY_DIR, count=3, set_id="set-1", output_root=tmp_path / "sets",
        provider=ScriptedProvider({(2, 1): RuntimeError("boom")}), out=out,
    )
    set_dir = tmp_path / "sets" / "appointment-rescheduling" / "set-1"
    assert status == 1 and len(list((set_dir / "accepted").glob("*.yaml"))) == 1

    played = play_run(tmp_path, ["pass"], set_dir=set_dir)
    assert_refused(played, "the run was aborted")


def test_run_refuses_a_journey_directory_the_scenarios_were_not_written_from(tmp_path):
    played = play_run(tmp_path, ["pass"], journey_dir=edited_journey_dir(tmp_path))
    assert_refused(played, "journey_sha256")


def test_a_scenario_whose_hashes_do_not_match_is_refused_on_its_own(tmp_path):
    set_dir = synthesize(tmp_path, 1)
    scenario, = saved_scenarios(set_dir)
    _, fixture_state = jh.load_journey_inputs(JOURNEY_DIR)

    assert jh._hash_problems(scenario, scenario.synthesis.journey_sha256, fixture_state) == []
    problems = jh._hash_problems(scenario, "0" * 64, fixture_state)
    assert len(problems) == 1 and "synthesis.journey_sha256" in problems[0]


def test_run_refuses_a_directory_that_is_not_a_set(tmp_path):
    (tmp_path / "loose").mkdir()
    played = play_run(tmp_path, [], set_dir=tmp_path / "loose")
    assert_refused(played, "no provenance.json")


def test_a_run_is_never_overwritten_and_its_id_is_checked(tmp_path):
    set_dir = synthesize(tmp_path, 1)
    first = play_run(tmp_path, ["pass"], set_dir=set_dir)
    before = (first.run_dir / "manifest.json").read_bytes()

    again = play_run(tmp_path, ["pass"], set_dir=set_dir)
    assert again.status == 2 and "never overwritten" in again.output
    assert (first.run_dir / "manifest.json").read_bytes() == before

    bad = play_run(tmp_path, ["pass"], set_dir=set_dir, run_id="../escape")
    assert bad.status == 2 and "run id" in bad.output


def test_an_unreachable_service_is_refused_before_anything_is_written(tmp_path):
    class Unreachable(SequenceAdapter):
        def start_conversation(self, *, fixture_state, tool_failures=()):
            raise NO_ANSWER

    played = play_run(tmp_path, ["pass"], adapter=Unreachable([]))
    assert played.status == 2 and "transport" in played.output
    assert not played.run_dir.exists()


def test_missing_model_configuration_is_one_line_before_any_write(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTSIM_SIMULATOR_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    no_model = play_run(tmp_path, ["pass"], simulated_user_factory=None)
    assert no_model.status == 2 and "--simulator-model" in no_model.output
    assert not no_model.run_dir.exists()

    no_key = play_run(tmp_path, ["pass"], set_dir=synthesize(tmp_path, 1, set_id="set-2"),
                      judge=None)
    assert no_key.status == 2 and "OPENAI_API_KEY" in no_key.output
    assert not no_key.run_dir.exists()


def test_run_needs_its_three_arguments_and_re_evaluate_takes_none_of_them(capsys):
    with pytest.raises(SystemExit) as missing:
        jh.main(["run", "--journey", str(JOURNEY_DIR), "--run-id", "run-1"])
    assert missing.value.code == 2
    assert "--scenarios, --service-url" in capsys.readouterr().err

    with pytest.raises(SystemExit) as mixed:
        jh.main(["run", "--journey", str(JOURNEY_DIR), "--re-evaluate", "journey_runs/x",
                 "--run-id", "run-1"])
    assert mixed.value.code == 2
    assert "cannot take --run-id" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        jh.main(["run", "--journey", str(JOURNEY_DIR), "--scenarios", "s",
                 "--service-url", SERVICE_URL, "--run-id", "r", "--request-timeout", "0"])


# ------------------------------------------------------------------- aborts


def test_an_interrupt_mid_run_keeps_completed_episodes_and_marks_the_run_aborted(tmp_path):
    played = play_run(tmp_path, ["pass", "interrupt", "pass"])

    assert isinstance(played.raised, asyncio.CancelledError)  # an interrupt stays one
    assert played.output.splitlines()[-1].startswith("ABORTED: CancelledError")
    record = run_record(played.run_dir)
    assert record["status"] == "aborted" and record["error"]["type"] == "CancelledError"

    # The completed Episode is intact.
    assert {p.name for p in played.episode_dir(0).iterdir()} == EPISODE_FILES
    assert read(played.episode_dir(0) / "evaluation.json")["outcome"] == "pass"
    # The interrupted one kept what it had and says so; the third never began.
    interrupted = read(played.episode_dir(1) / "episode.json")
    assert interrupted["status"] == "aborted" and interrupted["turns_completed"] == 1
    assert (played.episode_dir(1) / "transcript.jsonl").read_text().count("\n") == 2
    assert len(played.adapter.adapters) == 1
    assert played.scenarios[2].scenario_id not in played.run_keys

    out = io.StringIO()
    assert jh.summarize_command(played.run_dir, out=out) == 0
    assert "this Run was ABORTED" in out.getvalue()
    report = (played.run_dir / "report.md").read_text()
    assert "**This Run was ABORTED**" in report and "CancelledError" in report
    assert "| 1 | 0 | 0 | 0 | 2 |" in report
    assert played.scenarios[2].scenario_id in report.split("Never started:")[1]


def test_a_crash_after_the_first_write_exits_1_and_marks_the_run_aborted(
    tmp_path, monkeypatch
):
    class FailsOnTheSecondWrite(BatchRunner):
        calls = 0

        async def run(self, specs, execute):
            type(self).calls += 1
            if type(self).calls == 2:
                raise OSError("No space left\non device")
            return await super().run(specs, execute)

    monkeypatch.setattr(jh, "BatchRunner", FailsOnTheSecondWrite)
    played = play_run(tmp_path, ["pass", "pass"])

    assert (played.status, played.raised) == (1, None)  # never 2: files were written
    assert "ABORTED: OSError: No space left on device" in played.output
    record = run_record(played.run_dir)
    assert record["status"] == "aborted" and record["error"]["type"] == "OSError"
    assert read(played.episode_dir(0) / "evaluation.json")["outcome"] == "pass"


# -------------------------------------------------------------- re-evaluate


def conversation_files(episode_dir: Path) -> dict[str, bytes]:
    names = ("scenario.yaml", "transcript.jsonl", "episode.json", "raw_trace.json",
             "normalized_trace.json")
    return {name: (episode_dir / name).read_bytes() for name in names}


def test_re_evaluate_replaces_the_evaluation_and_replays_nothing(tmp_path):
    played = play_run(
        tmp_path, ["pass", "pass"], judge_failing={0: ("update_result_reported_accurately",)}
    )
    assert read(played.episode_dir(0) / "evaluation.json")["outcome"] == "fail"
    before = [conversation_files(played.episode_dir(i)) for i in range(2)]

    out = io.StringIO()
    status = jh.re_evaluate_command(
        journey_dir=JOURNEY_DIR, run_dir=played.run_dir, out=out, judge=ScenarioJudge(),
    )

    assert status == 0 and "Re-evaluating 2 saved Episode(s)" in out.getvalue()
    assert [conversation_files(played.episode_dir(i)) for i in range(2)] == before
    assert read(played.episode_dir(0) / "evaluation.json")["outcome"] == "pass"
    manifest = read(played.run_dir / "manifest.json")
    assert sorted(manifest["runs"]) == sorted(played.run_keys.values())
    assert {r["outcome"] for r in manifest["runs"].values()} == {"pass"}
    assert all(r["failures"] == [] for r in manifest["runs"].values())
    record = run_record(played.run_dir)
    assert record["status"] == "complete"
    assert record["re_evaluation"]["status"] == "complete"
    assert record["re_evaluation"]["started_at"] and record["re_evaluation"]["ended_at"]


def test_re_evaluate_refuses_a_journey_file_edited_since_the_run(tmp_path):
    played = play_run(tmp_path, ["pass"])
    evaluation = (played.episode_dir(0) / "evaluation.json").read_bytes()
    manifest = (played.run_dir / "manifest.json").read_bytes()
    judge = ScenarioJudge()

    out = io.StringIO()
    status = jh.re_evaluate_command(
        journey_dir=edited_journey_dir(tmp_path), run_dir=played.run_dir, out=out,
        judge=judge,
    )

    assert status == 2 and "synthesis.journey_sha256 does not match" in out.getvalue()
    assert judge.calls == []  # never judged with other wording
    assert (played.episode_dir(0) / "evaluation.json").read_bytes() == evaluation
    assert (played.run_dir / "manifest.json").read_bytes() == manifest


def test_re_evaluating_an_aborted_run_evaluates_what_was_saved_and_stays_aborted(tmp_path):
    played = play_run(tmp_path, ["pass", "interrupt", "pass"])
    status = jh.re_evaluate_command(
        journey_dir=JOURNEY_DIR, run_dir=played.run_dir, out=io.StringIO(),
        judge=ScenarioJudge(),
    )
    assert status == 0
    assert read(played.episode_dir(1) / "evaluation.json")["outcome"] == "error"
    record = run_record(played.run_dir)
    assert record["status"] == "aborted" and record["error"]["type"] == "CancelledError"


def test_the_judge_and_every_evaluation_hold_the_same_loaded_journey(tmp_path, monkeypatch):
    """Criterion wording lives in the Journey definition, so the object the
    Judge is built from and the one ``evaluate_episode`` resolves criteria
    from must be one and the same — in ``run`` and in ``run --re-evaluate``."""
    seen: dict[str, list] = {"judge": [], "evaluate": []}
    real_evaluate = jh.evaluate_episode

    def build_judge(journey, **kwargs):
        seen["judge"].append(journey)
        return ScenarioJudge()

    async def evaluate(episode_dir, judge, journey):
        seen["evaluate"].append(journey)
        return await real_evaluate(episode_dir, judge, journey)

    monkeypatch.setattr(jh, "live_journey_judge", build_judge)
    monkeypatch.setattr(jh, "evaluate_episode", evaluate)

    played = play_run(tmp_path, ["pass", "pass"], judge=None)
    assert played.status == 0
    status = jh.re_evaluate_command(
        journey_dir=JOURNEY_DIR, run_dir=played.run_dir, out=io.StringIO(),
    )
    assert status == 0

    assert len(seen["judge"]) == 2 and len(seen["evaluate"]) == 4  # run, then re-evaluate
    run_journey, re_evaluate_journey = seen["judge"]
    assert all(j is run_journey for j in seen["evaluate"][:2])
    assert all(j is re_evaluate_journey for j in seen["evaluate"][2:])


class InterruptedJudge(ScenarioJudge):
    """Cancelled on its second call, as Ctrl-C during a re-evaluation would be."""

    async def judge_episode(self, scenario, trace):
        if len(self.calls) == 1:
            raise asyncio.CancelledError()
        return await super().judge_episode(scenario, trace)


def test_an_interrupted_re_evaluation_does_not_make_a_finished_run_aborted(tmp_path):
    played = play_run(tmp_path, ["pass", "pass"])
    assert run_record(played.run_dir)["status"] == "complete"

    out = io.StringIO()
    with pytest.raises(asyncio.CancelledError):
        jh.re_evaluate_command(
            journey_dir=JOURNEY_DIR, run_dir=played.run_dir, out=out, judge=InterruptedJudge(),
        )

    # The conversations finished; only the re-evaluation did not. Two facts, apart.
    record = run_record(played.run_dir)
    assert record["status"] == "complete" and record["error"] is None
    assert record["re_evaluation"]["status"] == "aborted"
    assert record["re_evaluation"]["error"]["type"] == "CancelledError"
    assert out.getvalue().splitlines()[-1].startswith("ABORTED: CancelledError")
    summary = io.StringIO()
    assert jh.summarize_command(played.run_dir, out=summary) == 0
    assert "this Run was ABORTED" not in summary.getvalue()
    assert "last re-evaluation was ABORTED" in summary.getvalue()
    report = (played.run_dir / "report.md").read_text()
    assert "**This Run was ABORTED**" not in report
    assert "**The last re-evaluation was ABORTED**" in report and "CancelledError" in report

    # The next re-evaluation reaches every Episode and says so.
    status = jh.re_evaluate_command(
        journey_dir=JOURNEY_DIR, run_dir=played.run_dir, out=io.StringIO(),
        judge=ScenarioJudge(),
    )
    assert status == 0
    record = run_record(played.run_dir)
    assert record["status"] == "complete"
    assert record["re_evaluation"]["status"] == "complete"
    assert record["re_evaluation"]["error"] is None
    manifest = read(played.run_dir / "manifest.json")
    assert {r["outcome"] for r in manifest["runs"].values()} == {"pass"}
    summary = io.StringIO()
    assert jh.summarize_command(played.run_dir, out=summary) == 0
    assert "ABORTED" not in summary.getvalue()


def test_re_evaluate_refuses_a_directory_that_is_not_a_run(tmp_path):
    out = io.StringIO()
    status = jh.re_evaluate_command(journey_dir=JOURNEY_DIR, run_dir=tmp_path, out=out)
    assert status == 2 and "journey_run.json" in out.getvalue()


# -------------------------------------------------------------------- probe

PROBE_EPISODE_FILES = {
    "scenario.yaml", "transcript.jsonl", "episode.json", "raw_trace.json",
    "normalized_trace.json", "evaluation.json",
}
EVERY_RUNG = (1, 2, 3, 4)


def test_probe_climbs_rung_by_rung_and_stops_at_the_first_break(tmp_path):
    played = play_probe(tmp_path, {1: "pass", 2: "padded", 3: "gave_up", 4: "unconfirmed"})

    assert (played.status, played.raised) == (0, None)
    record = played.record
    assert record["status"] == "complete" and record["error"] is None
    assert record["rule_id"] == "identify_existing_appointment"
    assert record["agent"] == "stub"  # never mistaken for the LangGraph agent
    assert [rung["rung"] for rung in record["rungs"]] == list(EVERY_RUNG)
    assert [rung["state"] for rung in record["rungs"]] == [
        "survived", "survived", "survived", "broke"
    ]
    assert (record["highest_survived"], record["broke_at"]) == (3, 4)
    assert record["stopped_because"] == "rung_broke"
    assert played.played == [(rung, 0) for rung in EVERY_RUNG]
    for rung in EVERY_RUNG:
        assert {p.name for p in played.episode_dir(rung).iterdir()} == PROBE_EPISODE_FILES
    assert "suspected break at Rung 4" in played.output
    assert "a human rules on it" in played.output


def test_a_break_low_down_leaves_the_rungs_above_unplayed(tmp_path):
    """The Rungs above a break say nothing about it, and every one of them costs
    real Simulated-user and Judge calls."""
    played = play_probe(tmp_path, {1: "pass", 2: "unconfirmed", 3: "pass", 4: "pass"})

    assert played.played == [(1, 0), (2, 0)]
    assert not played.episode_dir(3).exists()
    assert len(played.adapter.adapters) == 2, "Rungs 3 and 4 must not be played"


def test_a_rung_the_agent_will_not_complete_is_survived(tmp_path):
    """Rung 3 is built to end ``task_incomplete``. Clean conduct is survival
    whether or not the Goal was reached: an agent that correctly refuses to
    guess which appointment she means has broken nothing."""
    played = play_probe(tmp_path, dict.fromkeys(EVERY_RUNG, "gave_up"))

    record = played.record
    assert [rung["seeds"][0]["outcome"] for rung in record["rungs"]] == (
        ["task_incomplete"] * 4
    )
    assert (record["highest_survived"], record["broke_at"]) == (4, None)
    assert record["stopped_because"] == "ladder_exhausted"
    assert "survived every Rung" in played.output


def test_an_episode_that_errors_stops_the_climb_without_claiming_a_break(tmp_path):
    played = play_probe(tmp_path, {1: "pass", 2: "agent_error", 3: "pass", 4: "pass"})

    record = played.record
    assert played.status == 0, "an Episode outcome is a result, not a command failure"
    assert record["rungs"][-1]["state"] == "inconclusive"
    assert record["broke_at"] is None, "evidence that is missing is not a break"
    assert record["highest_survived"] == 1
    assert played.played == [(1, 0), (2, 0)]
    assert "unreadable" in played.output


def test_every_seed_of_a_rung_is_played_even_after_one_breaks(tmp_path):
    """Whether a break is every time or one time in three is the number a
    reviewer needs and cannot get afterwards."""
    played = play_probe(
        tmp_path,
        {1: "pass", 2: {0: "pass", 1: "unconfirmed", 2: "pass"}, 3: "pass", 4: "pass"},
        seeds=(0, 1, 2),
    )

    record = played.record
    assert played.played == [(1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)]
    assert record["seeds"] == [0, 1, 2]
    assert [seed["outcome"] for seed in record["rungs"][1]["seeds"]] == [
        "pass", "fail", "pass"
    ]
    assert record["broke_at"] == 2
    assert "on 1 of 3 Seed(s)" in played.output


def test_the_record_names_each_seeds_evidence_and_the_check_that_failed(tmp_path):
    """A break is a suspected finding, so the record must lead a human straight
    to the Episode it happened in."""
    played = play_probe(tmp_path, {1: "pass", 2: "unconfirmed", 3: "pass", 4: "pass"})

    broke = played.record["rungs"][-1]["seeds"][0]
    assert broke["episode_dir"] == "rungs/rung-2/seed-0"
    evaluation = read(played.probe_dir / broke["episode_dir"] / "evaluation.json")
    assert evaluation["outcome"] == "fail"
    assert [failure["source"] for failure in broke["failures"]] == ["assertion"]
    assert [failure["id"] for failure in broke["failures"]] == [
        failure["id"] for failure in evaluation["failures"]
    ]


def test_a_rung_is_resolved_by_its_number_never_by_its_prose(tmp_path):
    """Rungs 3 and 4 of the committed Ladder share two difficulty directions, so
    a Rung selected by matching what its Scenario says would silently be the
    wrong one — and the climb would report a difficulty it did not play."""
    played = play_probe(tmp_path, dict.fromkeys(EVERY_RUNG, "pass"))

    for rung in EVERY_RUNG:
        saved = load_journey_scenario(played.episode_dir(rung) / "scenario.yaml")
        assert saved.synthesis.spec_id == f"rung-{rung}"
        assert saved.scenario_id == played.rungs[rung].scenario_id


def test_a_probe_is_never_overwritten_and_its_id_is_checked(tmp_path):
    set_dir = realize(tmp_path)
    behaviours = dict.fromkeys(EVERY_RUNG, "pass")
    assert play_probe(tmp_path, behaviours, set_dir=set_dir).status == 0

    again = play_probe(tmp_path, behaviours, set_dir=set_dir)
    assert again.status == 2 and "never overwritten" in again.output

    named = play_probe(tmp_path, behaviours, set_dir=set_dir, probe_id="Probe One")
    assert named.status == 2 and "must match" in named.output


def test_a_set_that_is_not_a_ladder_is_refused_before_anything_is_written(tmp_path):
    out = io.StringIO()
    status = jh.probe_command(
        journey_dir=JOURNEY_DIR, scenarios_dir=synthesize(tmp_path, 2),
        service_url=SERVICE_URL, probe_id="probe-1",
        output_root=tmp_path / "journey_probes", out=out,
        adapter=SequenceAdapter([]), simulated_user_factory=lambda scenario: None,
        judge=ScenarioJudge(),
    )
    assert status == 2 and "is not a Ladder set" in out.getvalue()
    assert not (tmp_path / "journey_probes").exists()


def test_a_ladder_set_missing_a_rung_is_refused(tmp_path):
    """A Ladder missing a Rung is not a shorter Ladder: a climb needs every Rung
    below the one that breaks. Realizing a Ladder already aborts rather than
    leaving a gap, and the provenance check refuses what it left behind, so this
    guard is reached only by a hand-edited set and is tested where it lives."""
    scenarios = rung_scenarios(realize(tmp_path))
    with pytest.raises(ValueError, match=r"missing Rung\(s\) \[4\]"):
        jh._ladder_set([scenarios[rung] for rung in (1, 2, 3)], tmp_path)


def test_a_probe_needs_distinct_seeds(tmp_path):
    played = play_probe(tmp_path, dict.fromkeys(EVERY_RUNG, "pass"), seeds=(0, 0))
    assert played.status == 2 and "must be distinct" in played.output
    assert not played.probe_dir.exists()


def test_an_interrupt_mid_climb_keeps_finished_rungs_and_marks_the_climb_aborted(tmp_path):
    played = play_probe(tmp_path, {1: "pass", 2: "interrupt", 3: "pass", 4: "pass"})

    assert isinstance(played.raised, asyncio.CancelledError)
    assert played.status is None
    record = played.record
    assert record["status"] == "aborted"
    assert record["error"]["type"] == "CancelledError"
    assert [rung["rung"] for rung in record["rungs"]] == [1]
    assert record["broke_at"] is None, "falling over is not the agent breaking"
    assert "ABORTED" in played.output


def test_a_climb_that_falls_over_exits_1_and_keeps_what_it_wrote(tmp_path):
    """A Simulated user that cannot be built is not an Episode error: nothing was
    played, so there is no Rung to call unreadable and the climb aborts. In a Run
    it is that Scenario's error and the next Scenario still runs."""
    played = play_probe(
        tmp_path, dict.fromkeys(EVERY_RUNG, "pass"),
        unbuildable={2: RuntimeError("no Simulated user")},
    )

    assert played.status == 1
    record = played.record
    assert record["status"] == "aborted" and record["error"]["type"] == "RuntimeError"
    assert [rung["rung"] for rung in record["rungs"]] == [1]
    assert (record["highest_survived"], record["broke_at"]) == (1, None)
    assert "ABORTED" in played.output


def test_probe_keeps_its_episodes_out_of_the_run_root(tmp_path):
    """A Run never contains Probe Episodes (ADR 0008), which starts with them
    not being written where a Run's are."""
    assert jh.DEFAULT_PROBE_ROOT != jh.DEFAULT_RUN_ROOT
    played = play_probe(tmp_path, dict.fromkeys(EVERY_RUNG, "pass"))
    assert not (tmp_path / "journey_runs").exists()
    assert played.record["set_id"] == "ladder-identify-existing-appointment"


# ------------------------------------------------------------------ hygiene


def test_development_runs_are_git_ignored_and_spot_check_records_are_not():
    lines = Path(".gitignore").read_text().splitlines()
    ignored = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    assert "journey_runs/" in ignored
    assert not any("journey_spot_checks" in line for line in ignored)
