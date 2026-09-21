"""The whole pipeline offline, once (session 08):

    synthesize (stub narrative) → run over HTTP against a fake agent service,
    through the real ``JourneyServiceAdapter`` and its normalizer, with a
    Simulated-user and a Judge double → summarize

It shows the pieces fit and leave every file they promise. It says nothing
about Judge accuracy, the agent, or the quality of the Scenarios.
"""

from __future__ import annotations

import io
import json
import re
import threading
from http.server import ThreadingHTTPServer

import pytest

from scenario_synthesis import journey_synthesis as js
from scripts import journey_harness as jh
from tests.journey_run_doubles import JOURNEY_DIR, ScenarioJudge, saved_scenarios
from tests.test_journey_adapter import UPDATE_FAILED, FakeJourneyService, _Handler
from tests.test_journey_evaluation import ScriptedUser, say


@pytest.fixture
def service():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.fake = FakeJourneyService()
    server.fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    ).start()
    yield server.fake
    server.shutdown()
    server.server_close()


def agent_script(scenario, behaviour):
    """What the fake agent does on each message: ``(actions, reply)``."""
    appointment, slot = scenario.fixture.appointment_id, scenario.fixture.target_slot_ids[0]
    lookup = {"tool_name": "lookup_appointments", "arguments": {"customer_name": "x"},
              "result": {"appointments": [{"appointment_id": appointment}]}}
    slots = {"tool_name": "find_available_slots", "arguments": {"appointment_id": appointment},
             "result": {"slots": [{"slot_id": slot}]}}
    update = {"tool_name": "update_appointment",
              "arguments": {"appointment_id": appointment, "slot_id": slot},
              "result": {"appointment": {"appointment_id": appointment}}}
    done = "Done, it is moved."
    if scenario.fixture.tool_failures:
        update = {**update, "status": "failed", "result": None, "error": UPDATE_FAILED}
        done = "I'm sorry, the update failed; nothing was changed."
    if behaviour == "agent_error":
        return [([lookup], RuntimeError("graph recursion limit reached"))]
    if behaviour == "unconfirmed":
        return [([lookup], "I found it. When suits you?"), ([slots, update], done)]
    return [([lookup], "I found it. When suits you?"),
            ([slots], "There is one later slot. Shall I move it there?"),
            ([update], done)]


def test_synthesize_run_summarize_offline(tmp_path, service):
    out = io.StringIO()
    assert jh.main(
        ["synthesize", "--journey", str(JOURNEY_DIR), "--count", "3", "--set-id", "e2e",
         "--stub", "--output-root", str(tmp_path / "sets")],
        out=out,
    ) == 0
    set_dir = tmp_path / "sets" / "appointment-rescheduling" / "e2e"
    scenarios = saved_scenarios(set_dir)
    behaviours = ["pass", "unconfirmed", "agent_error"]
    users = {}
    for scenario, behaviour in zip(scenarios, behaviours, strict=True):
        script = agent_script(scenario, behaviour)
        service.script.extend(script)
        says = [say(f"message {n}") for n in range(1, len(script))]
        users[scenario.scenario_id] = ScriptedUser(*says, say("last", "goal_achieved"))

    status = jh.run_command(
        journey_dir=JOURNEY_DIR, scenarios_dir=set_dir, service_url=service.url,
        run_id="e2e-run", output_root=tmp_path / "journey_runs", request_timeout_s=5,
        out=out, simulated_user_factory=lambda s: users[s.scenario_id],
        judge=ScenarioJudge(),
    )
    run_dir = tmp_path / "journey_runs" / "e2e-run"
    assert status == 0, out.getvalue()
    assert jh.main(["summarize", str(run_dir)], out=out) == 0
    assert "agent: stub" in out.getvalue()

    # Saved Scenarios and provenance.
    assert len(scenarios) == 3 and (set_dir / "provenance.json").is_file()
    assert js.verify_provenance(set_dir, JOURNEY_DIR) == []

    # Conversations, raw Traces, normalized Traces and evaluation results.
    manifest = json.loads((run_dir / "manifest.json").read_text())
    outcomes = {}
    for run_key, record in manifest["runs"].items():
        episode_dir = run_dir / "runs" / run_key
        for name in ("scenario.yaml", "transcript.jsonl", "episode.json", "raw_trace.json",
                     "normalized_trace.json", "evaluation.json"):
            assert (episode_dir / name).is_file(), f"{run_key}: {name}"
        evaluation = json.loads((episode_dir / "evaluation.json").read_text())
        raw = json.loads((episode_dir / "raw_trace.json").read_text())
        assert raw["sealed"] is True and raw["agent"] == "stub"
        assert evaluation["outcome"] == record["outcome"]
        outcomes[record["scenario"]] = record["outcome"]
    assert [outcomes[s.scenario_id] for s in scenarios] == ["pass", "fail", "error"]
    assert service.conversations == {}  # every conversation was released, the probe too

    # The report, with links that resolve.
    report = (run_dir / "report.md").read_text()
    assert (run_dir / "clusters.json").is_file()
    assert "| 1 | 1 | 0 | 1 | 0 |" in report
    assert "assertion:user_turn_before_update" in report
    assert "### adapter service agent_error — 1 Episode(s)" in report
    links = re.findall(r"\]\(([^)]+)\)", report)
    assert links and all((run_dir / link).is_file() for link in links)
