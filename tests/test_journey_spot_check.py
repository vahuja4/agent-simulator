"""The spot-check record: the file format a human's Simulated-user fidelity
rulings are kept in, and its strict loader. Offline; nothing here checks the
Simulated user."""

from __future__ import annotations

import copy
import json

import pytest
import yaml

from agentsim.journey import episode, spot_check as sc

RUN_ID = "run-2026-09-22"
SCENARIO_ID = "synth-appointment-rescheduling-0123456789ab"


def _record(**changes):
    record = {
        "run_id": RUN_ID,
        "scenario_id": SCENARIO_ID,
        "reviewer": "vahuja4",
        "date": "2026-09-22",
        "persona": {"verdict": "faithful", "note": ""},
        "knowledge_level": {"verdict": "drifted", "note": "Never stated the rule."},
        "complication": {"verdict": "not_applicable", "note": "Complication is none."},
        "grounded_facts": {"verdict": "faithful", "note": ""},
    }
    record.update(changes)
    return record


@pytest.fixture
def runs_root(tmp_path):
    """A Run directory holding one Episode of ``SCENARIO_ID``."""
    episode_dir = tmp_path / "journey_runs" / RUN_ID / "runs" / "some-run-key"
    episode_dir.mkdir(parents=True)
    (episode_dir / episode.EPISODE_FILE).write_text(
        json.dumps({"scenario_id": SCENARIO_ID}), encoding="utf-8"
    )
    return tmp_path / "journey_runs"


def _write(tmp_path, document):
    path = tmp_path / "spot_checks.yaml"
    path.write_text(
        document if isinstance(document, str) else yaml.safe_dump(document), encoding="utf-8"
    )
    return path


def _load(tmp_path, runs_root, *records, **top_level):
    document = {"schema_version": 1, "records": list(records), **top_level}
    return sc.load_spot_check_records(_write(tmp_path, document), runs_root=runs_root)


def _refused(tmp_path, runs_root, *records, **top_level) -> str:
    with pytest.raises(sc.SpotCheckError) as refused:
        _load(tmp_path, runs_root, *records, **top_level)
    return str(refused.value)


def test_a_valid_file_loads(tmp_path, runs_root):
    (record,) = _load(tmp_path, runs_root, _record())
    assert (record.run_id, record.scenario_id, record.reviewer, record.date) == (
        RUN_ID, SCENARIO_ID, "vahuja4", "2026-09-22"
    )
    assert record.persona == sc.AspectRuling("faithful", "")
    assert record.knowledge_level == sc.AspectRuling("drifted", "Never stated the rule.")
    assert record.complication.verdict == "not_applicable"
    assert record.grounded_facts.verdict == "faithful"
    assert record.episode_dir == runs_root / RUN_ID / "runs" / "some-run-key"


def test_the_documented_example_is_a_valid_file(tmp_path, runs_root):
    example = sc.__doc__.split("::\n\n", 1)[1].split("\n\nEach of the four", 1)[0]
    (record,) = sc.load_spot_check_records(_write(tmp_path, example), runs_root=runs_root)
    # An unquoted YAML date is read as a date, not a string.
    assert record.date == "2026-09-22"
    assert [getattr(record, aspect).verdict for aspect in sc.SPOT_CHECK_ASPECTS] == [
        "faithful", "drifted", "not_applicable", "faithful"
    ]


def test_two_reviewers_may_record_the_same_episode(tmp_path, runs_root):
    records = _load(tmp_path, runs_root, _record(), _record(reviewer="second-reviewer"))
    assert [r.reviewer for r in records] == ["vahuja4", "second-reviewer"]


def test_unknown_fields_are_refused_at_every_level(tmp_path, runs_root):
    assert "unknown field(s) ['deviation_flags']" in _refused(
        tmp_path, runs_root, _record(deviation_flags=[])
    )
    ruling = {"verdict": "faithful", "note": "", "confidence": 0.9}
    assert "persona: unknown field(s) ['confidence']" in _refused(
        tmp_path, runs_root, _record(persona=ruling)
    )
    assert "unknown field(s) ['reviewed_by']" in _refused(
        tmp_path, runs_root, _record(), reviewed_by="x"
    )


@pytest.mark.parametrize("aspect", sc.SPOT_CHECK_ASPECTS)
def test_a_missing_aspect_is_refused(tmp_path, runs_root, aspect):
    record = _record()
    del record[aspect]
    assert f"missing field(s) ['{aspect}']" in _refused(tmp_path, runs_root, record)


@pytest.mark.parametrize("verdict", ["pass", "Faithful", "", None, True])
def test_an_unknown_verdict_is_refused(tmp_path, runs_root, verdict):
    message = _refused(
        tmp_path, runs_root, _record(complication={"verdict": verdict, "note": "x"})
    )
    assert "complication.verdict must be one of" in message
    assert "['faithful', 'drifted', 'not_applicable']" in message


def test_a_drifted_verdict_must_say_what_drifted(tmp_path, runs_root):
    message = _refused(
        tmp_path, runs_root, _record(persona={"verdict": "drifted", "note": "  "})
    )
    assert "persona: a drifted verdict needs a note" in message


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"run_id": "no-such-run"}, "no Run 'no-such-run'"),
        ({"scenario_id": "synth-other"}, "has no Episode of Scenario 'synth-other'"),
        # An id is compared with what is on disk, never joined into a path.
        ({"run_id": f"../journey_runs/{RUN_ID}"}, "no Run"),
    ],
)
def test_a_reference_to_an_episode_that_does_not_exist_is_refused(
    tmp_path, runs_root, changes, expected
):
    assert expected in _refused(tmp_path, runs_root, _record(**changes))


def test_a_missing_runs_root_is_refused_not_a_crash(tmp_path):
    assert "no Run" in _refused(tmp_path, tmp_path / "nowhere", _record())


def test_a_scenario_with_two_episodes_in_one_run_is_refused(tmp_path, runs_root):
    second = runs_root / RUN_ID / "runs" / "another-run-key"
    second.mkdir()
    (second / episode.EPISODE_FILE).write_text(json.dumps({"scenario_id": SCENARIO_ID}))
    assert "must name exactly one" in _refused(tmp_path, runs_root, _record())


def test_the_same_reviewer_recording_an_episode_twice_is_refused(tmp_path, runs_root):
    assert "more than once" in _refused(tmp_path, runs_root, _record(), copy.deepcopy(_record()))


@pytest.mark.parametrize("bad_date", ["22/09/2026", "2026-09-22T10:00:00", 20260922, ""])
def test_a_date_that_is_not_a_calendar_date_is_refused(tmp_path, runs_root, bad_date):
    assert "date must be a calendar date" in _refused(tmp_path, runs_root, _record(date=bad_date))


def test_the_schema_version_is_checked(tmp_path, runs_root):
    with pytest.raises(sc.SpotCheckError, match="schema_version must be 1"):
        sc.load_spot_check_records(
            _write(tmp_path, {"schema_version": 2, "records": []}), runs_root=runs_root
        )


def test_the_restated_episode_file_name_equals_the_episode_loop():
    assert sc.EPISODE_FILE == episode.EPISODE_FILE


def test_the_validation_command_says_valid_or_gives_one_line(tmp_path, runs_root, capsys):
    good = _write(tmp_path, {"schema_version": 1, "records": [_record()]})
    assert sc.main([str(good), "--runs-root", str(runs_root)]) == 0
    assert capsys.readouterr().out == "valid: 1 spot-check record(s)\n"

    bad = _write(tmp_path, {"schema_version": 1, "records": [_record(run_id="gone")]})
    assert sc.main([str(bad), "--runs-root", str(runs_root)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("invalid: ") and captured.err.count("\n") == 1
