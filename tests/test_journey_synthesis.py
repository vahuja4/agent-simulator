"""Scenario synthesis for a Journey outside payments: code owns structure and
derives the expected outcome and checks; a model double writes three narrative
fields; nothing is saved as usable before it validates.

These tests show that invalid output is rejected and recorded. A Scenario that
passes validation is well-formed and grounded — that is not evidence of test
quality, coverage, Qualification or Admission, and no test here runs a
conversation or calls a model.
"""

import copy
import io
import json
from pathlib import Path

import pytest
import yaml

from agentsim.journey.definition import load_journey_inputs
from agentsim.journey.scenario import check_against_inputs, load_journey_scenario
from agentsim.llm import LLMError
from scenario_synthesis import journey_synthesis as js

JOURNEY_DIR = Path("journeys/appointment_rescheduling")
ROOT = Path(__file__).resolve().parents[1]


class ScriptedProvider:
    """A model double: the stub's narrative unless (spec number, attempt) is
    scripted. A callable script receives the stub's output to corrupt."""

    provider_id = "test-double"
    model = "double-model"

    def __init__(self, script=None):
        self.script = dict(script or {})
        self.requests = []
        self._stub = js.StubNarrativeProvider()

    def realize(self, request, *, attempt):
        self.requests.append((request, attempt))
        good = self._stub.realize(request, attempt=attempt)
        # The request withholds spec_id, so scripts key on call order.
        spec_number = sum(1 for _, first in self.requests if first == 1)
        scripted = self.script.get((spec_number, attempt))
        if scripted is None:
            return good
        if isinstance(scripted, BaseException):
            raise scripted
        return scripted(good) if callable(scripted) else scripted


def _synthesize(tmp_path, *, count=3, script=None, **kwargs):
    provider = ScriptedProvider(script)
    result = js.synthesize_set(
        JOURNEY_DIR, count=count, set_id="set-1", provider=provider,
        output_root=tmp_path, **kwargs,
    )
    return result, provider


def _rejection(result, index=0):
    return json.loads(result.rejected[index].read_text())


def _inputs():
    return load_journey_inputs(JOURNEY_DIR)


def _valid_document():
    journey, fixture_state = _inputs()
    spec = js.plan_specs(journey, fixture_state, js.VariationSettings(), count=1, seed=0)[0]
    narrative = js.parse_narrative(
        js.StubNarrativeProvider().realize(
            js._narrative_request(spec, journey, attempt=1, previous_reasons=()), attempt=1
        )
    )
    synthesis = {
        "set_id": "set-1", "journey_sha256": "a" * 64, "fixture_state_sha256": "b" * 64,
        "generation_config_sha256": "c" * 64, "generator_version": "test",
        "model": "stub", "generated_at": "2026-09-21T00:00:00Z",
    }
    return js.scenario_document(spec, narrative, journey, synthesis)


# ------------------------------------------------------------ a valid set


def test_a_valid_set_is_saved_loadable_and_carries_complete_provenance(tmp_path):
    result, _ = _synthesize(tmp_path, count=4)
    journey, fixture_state = _inputs()

    assert result.set_dir == tmp_path / "appointment-rescheduling" / "set-1"
    assert len(result.accepted) == 4 and result.shortfall == 0 and not result.rejected
    for path in result.accepted:
        scenario = load_journey_scenario(path)  # the session-03 seam, unchanged
        check_against_inputs(scenario, journey, fixture_state)
        assert path.name == f"{scenario.scenario_id}.yaml"
        assert scenario.synthesis.origin == "synthesized"
        assert scenario.synthesis.qualification == "none"
        assert scenario.synthesis.set_id == "set-1"
        assert scenario.synthesis.model == "double-model"
        assert scenario.synthesis.fixture_state_sha256 == fixture_state.sha256
        assert scenario.expected_outcome == journey.outcome_for(scenario.fixture.tool_failures)
        assert scenario.assertion_ids == journey.assertion_ids
        assert scenario.judge_criterion_ids == journey.judge_criterion_ids
        assert scenario.persona.name == fixture_state.customer(scenario.fixture.customer_id)["name"]

    provenance = json.loads((result.set_dir / "provenance.json").read_text())
    assert provenance["qualification"] == "none"
    assert "not Qualified or Admitted" in provenance["notice"]
    assert provenance["counts"] == {
        "requested": 4, "accepted": 4, "rejected_attempts": 0, "shortfall": 0,
    }
    assert provenance["generation_config"]["seed"] == 0
    assert provenance["model"] == "double-model"
    assert provenance["generated_at"].endswith("Z")
    assert [entry["status"] for entry in provenance["specs"]] == ["accepted"] * 4
    assert js.verify_provenance(result.set_dir, JOURNEY_DIR) == []


def test_provenance_is_rechecked_against_the_input_files(tmp_path):
    result, _ = _synthesize(tmp_path, count=2)
    changed_inputs = tmp_path / "journey"
    changed_inputs.mkdir()
    for name in ("journey.yaml", "fixture_state.yaml"):
        (changed_inputs / name).write_text((JOURNEY_DIR / name).read_text())
    assert js.verify_provenance(result.set_dir, changed_inputs) == []

    fixture = changed_inputs / "fixture_state.yaml"
    fixture.write_text(fixture.read_text().replace("Dr. Patel", "Dr. Pradhan"))
    problems = js.verify_provenance(result.set_dir, changed_inputs)
    assert "provenance.json: fixture_state_sha256 no longer matches" in problems
    assert not any("journey_sha256" in problem for problem in problems)

    result.accepted[0].write_text(result.accepted[0].read_text() + "\n# edited\n")
    assert any(
        "missing or changed" in problem
        for problem in js.verify_provenance(result.set_dir, JOURNEY_DIR)
    )


def test_planning_is_deterministic_and_stays_inside_the_inputs():
    journey, fixture_state = _inputs()
    plan = lambda seed: [  # noqa: E731
        spec.to_dict()
        for spec in js.plan_specs(journey, fixture_state, js.VariationSettings(), count=14, seed=seed)
    ]
    assert plan(0) == plan(0)
    assert plan(0) != plan(1)
    specs = plan(0)
    assert {s["complication"] for s in specs} == set(journey.supported_complications)
    assert {s["knowledge_level"] for s in specs} == {"low", "medium", "high"}
    assert {tuple(s["tool_failures"]) for s in specs} == {(), ("update_appointment",)}
    for spec in specs:
        assert fixture_state.appointment(spec["appointment_id"])["status"] == "scheduled"
        if spec["complication"] == "ambiguous-reference":
            assert spec["customer_id"] == "C-100"  # the only customer with two cleanings


def test_the_model_is_never_shown_tool_failures_outcomes_or_criteria(tmp_path):
    _, provider = _synthesize(tmp_path, count=4)
    for request, _ in provider.requests:
        shown = json.dumps(request)
        for withheld in ("tool_failures", "expected_outcome", "update_failed_reported",
                         "criteria", "reschedule_confirmed", "user_turn_before_update"):
            assert withheld not in shown


# -------------------------------------------------------------- rejections


def test_a_model_supplied_expected_outcome_is_rejected_never_overridden(tmp_path):
    """Design note section 6: rejected with ``model-supplied-derived-field`` —
    here one that disagrees with the derived outcome, and one that agrees."""
    result, _ = _synthesize(
        tmp_path, count=2,
        script={
            (1, 1): lambda good: {**good, "expected_outcome": "update_failed_reported"},
            (2, 1): lambda good: {**good, "expected_outcome": "rescheduled"},
        },
        settings=js.VariationSettings(tool_failure_conditions=((),)),
    )
    assert len(result.rejected) == 2
    for index in range(2):
        record = _rejection(result, index)
        assert record["reasons"][0]["code"] == "model-supplied-derived-field"
        assert "expected_outcome" in record["reasons"][0]["detail"]
        assert "expected_outcome" in record["raw_model_output"]
    # The second attempt succeeded with the derived outcome.
    assert len(result.accepted) == 2
    assert {load_journey_scenario(p).expected_outcome for p in result.accepted} == {"rescheduled"}


@pytest.mark.parametrize(
    "field_name, value",
    [
        ("fixture", {"appointment_id": "A-9999"}),
        ("criteria", {"judge": ["always_pass"]}),
        ("grounded_facts", [{"path": "slots.S-999.start", "value": "2026-10-30T09:00:00"}]),
    ],
)
def test_model_supplied_bindings_criteria_or_facts_are_rejected(tmp_path, field_name, value):
    result, _ = _synthesize(
        tmp_path, count=1, script={(1, 1): lambda good: {**good, field_name: value}}
    )
    assert _rejection(result)["reasons"][0]["code"] == "model-supplied-derived-field"
    rejected_persona, _ = _synthesize(
        tmp_path / "persona", count=1,
        script={(1, 1): lambda good: {**good, "persona": {**good["persona"], "name": "X"}}},
    )
    assert "persona.name" in _rejection(rejected_persona)["reasons"][0]["detail"]


@pytest.mark.parametrize(
    "invented",
    [
        "My confirmation code is HSD-9999.",
        "Move appointment A-1001 for me.",
        "I want the slot on 2026-10-30.",
        "I want the 12th instead.",
        "Move it to 3:15pm.",
        "Any time in December works.",
        "Thursday would be better.",
    ],
)
def test_narrative_that_invents_an_identifier_code_date_or_time_is_rejected(tmp_path, invented):
    result, _ = _synthesize(
        tmp_path, count=1,
        script={(1, 1): lambda good: {**good, "goal": f"{good['goal']} {invented}"}},
        settings=js.VariationSettings(complications=("none",)),
    )
    record = _rejection(result)
    assert record["reasons"][0]["code"] == "sealed-world-violation"
    assert record["spec"]["spec_id"] == "spec-001" and record["attempt"] == 1
    assert len(result.accepted) == 1  # the clean second attempt


def test_grounded_dates_and_times_may_be_written_naturally():
    facts = [
        {"path": "appointments.A-1001.start", "value": "2026-10-06T10:00:00"},
        {"path": "slots.S-102.start", "value": "2026-10-13T15:30:00"},
        {"path": "appointments.A-1001.confirmation_code", "value": "HSD-4821"},
    ]
    narrative = {
        "goal": (
            "Move my cleaning from Tuesday 6 October at 10am (code HSD-4821, ending 4821) "
            "to October 13th at 3:30pm, or 15:30 as they write it. You may ask me anything."
        )
    }
    assert js.narrative_sealed_world_violations(narrative, facts) == []
    assert js.narrative_sealed_world_violations({"goal": "at 10pm on 6 May"}, facts) == [
        "goal: '10pm' is not a grounded fact",
        "goal: 'may' is not in a grounded date",
    ]


@pytest.mark.parametrize(
    "mutate, code, fragment",
    [
        (lambda d: d["fixture"].update(appointment_id="A-9999"),
         "input-mismatch", "'A-9999' is not in Fixture state"),
        (lambda d: d["fixture"].update(target_slot_ids=["S-999"]),
         "input-mismatch", "'S-999' is not in Fixture state"),
        (lambda d: d["fixture"].update(customer_id="C-999"),
         "input-mismatch", "'C-999' is not in Fixture state"),
        (lambda d: d["grounded_facts"][2].update(value="Dr. Nobody"),
         "input-mismatch", "in the Scenario but"),
        (lambda d: d["criteria"]["judge"].append("always_pass"),
         "input-mismatch", "criteria.judge differ"),
        (lambda d: d["criteria"]["judge"].pop(), "input-mismatch", "criteria.judge differ"),
        (lambda d: d.update(complication="perturbation"),
         "schema-invalid", "complication must be one of"),
        (lambda d: d.update(complication="goal-shift"),
         "input-mismatch", "unsupported for this Journey"),
        (lambda d: d.update(knowledge_level="expert"),
         "schema-invalid", "knowledge_level must be one of"),
        (lambda d: d.update(expected_outcome="update_failed_reported"
                            if d["expected_outcome"] == "rescheduled" else "rescheduled"),
         "input-mismatch", "is not what the Journey definition derives"),
    ],
)
def test_a_document_that_does_not_fit_the_inputs_is_rejected(mutate, code, fragment):
    journey, fixture_state = _inputs()
    document = copy.deepcopy(_valid_document())
    js.validate_scenario_document(document, journey, fixture_state)  # valid before mutation
    mutate(document)
    with pytest.raises(js.Rejection) as excinfo:
        js.validate_scenario_document(document, journey, fixture_state)
    assert excinfo.value.code == code
    assert fragment in excinfo.value.detail


def test_a_planned_binding_that_is_not_in_fixture_state_is_rejected_and_recorded(
    tmp_path, monkeypatch
):
    """Defense in depth: even a spec from code is checked against the inputs."""
    real_plan = js.plan_specs

    def invented(*args, **kwargs):
        import dataclasses

        return [
            dataclasses.replace(spec, appointment_id="A-9999")
            for spec in real_plan(*args, **kwargs)
        ]

    monkeypatch.setattr(js, "plan_specs", invented)
    result, _ = _synthesize(tmp_path, count=1)
    assert result.accepted == () and result.shortfall == 1
    assert [_rejection(result, i)["reasons"][0]["code"] for i in range(2)] == ["input-mismatch"] * 2
    assert "'A-9999' is not in Fixture state" in _rejection(result)["reasons"][0]["detail"]


@pytest.mark.parametrize(
    "settings, fragment",
    [
        (js.VariationSettings(complications=("perturbation",)), "outside the closed set"),
        (js.VariationSettings(knowledge_levels=("expert",)), "outside the closed set"),
        (js.VariationSettings(archetypes=("angry",)), "outside the closed set"),
        (js.VariationSettings(complications=("goal-shift",)), "is unsupported for Journey"),
        (js.VariationSettings(tool_failure_conditions=(("lookup_appointments",),)),
         "no expected outcome can be derived"),
    ],
)
def test_variation_settings_outside_the_closed_sets_are_refused(tmp_path, settings, fragment):
    with pytest.raises(js.SynthesisConfigError, match=fragment):
        _synthesize(tmp_path, settings=settings)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        None,
        {"description": "x", "goal": "y"},
        {"description": "x", "persona": "brief", "goal": "y"},
        {"description": "x", "persona": {"traits": " "}, "goal": "y"},
        {"description": 7, "persona": {"traits": "brief"}, "goal": "y"},
    ],
)
def test_malformed_model_output_is_rejected_saved_and_reported(tmp_path, raw):
    out = io.StringIO()
    status = js.synthesize_command(
        journey_dir=JOURNEY_DIR, count=2, set_id="set-1", output_root=tmp_path,
        provider=ScriptedProvider({(1, 1): lambda good: raw, (1, 2): lambda good: raw}),
        out=out,
    )
    set_dir = tmp_path / "appointment-rescheduling" / "set-1"
    saved = sorted(p.name for p in (set_dir / "rejected").iterdir())
    assert saved == ["spec-001-1.json", "spec-001-2.json"]
    record = json.loads((set_dir / "rejected" / "spec-001-1.json").read_text())
    assert record["reasons"][0]["code"] == "malformed-output"
    assert record["raw_model_output"] == raw

    report = out.getvalue()
    assert status == 1
    assert "requested 2, accepted 1, rejected attempts 2, shortfall 1" in report
    assert "rejected spec-001 attempt 1: malformed-output" in report
    assert "SHORTFALL: 1 of 2 requested Scenarios were not produced (spec-001)" in report
    assert "not Qualified or Admitted" in report
    provenance = json.loads((set_dir / "provenance.json").read_text())
    assert provenance["counts"]["shortfall"] == 1
    assert provenance["specs"][0] == {
        "spec_id": "spec-001", "status": "exhausted", "scenario_id": None,
    }
    assert js.verify_provenance(set_dir, JOURNEY_DIR) == []


def test_a_provider_failure_is_a_recorded_rejection_and_the_retry_sees_the_reason(tmp_path):
    result, provider = _synthesize(
        tmp_path, count=1, script={(1, 1): LLMError("model refused the request")}
    )
    assert _rejection(result)["reasons"] == [
        {"code": "provider-error", "detail": "model refused the request"}
    ]
    assert _rejection(result)["raw_model_output"] is None
    retry_request, attempt = provider.requests[1]
    assert attempt == 2
    assert retry_request["previous_rejection"][0]["code"] == "provider-error"
    assert len(result.accepted) == 1


# ------------------------------------------------------ count and location


def test_the_requested_count_is_honored_and_the_command_exits_zero(tmp_path):
    out = io.StringIO()
    status = js.synthesize_command(
        journey_dir=JOURNEY_DIR, count=6, set_id="set-1", stub=True,
        output_root=tmp_path, out=out,
    )
    assert status == 0
    set_dir = tmp_path / "appointment-rescheduling" / "set-1"
    assert len(list((set_dir / "accepted").glob("*.yaml"))) == 6
    assert not (set_dir / "rejected").exists()
    assert "requested 6, accepted 6" in out.getvalue()
    assert "SHORTFALL" not in out.getvalue()
    assert "not Qualified or Admitted" in out.getvalue()


def test_stub_output_is_reproducible_apart_from_the_timestamp(tmp_path):
    names = []
    for root in (tmp_path / "a", tmp_path / "b"):
        result = js.synthesize_set(
            JOURNEY_DIR, count=3, set_id="set-1",
            provider=js.StubNarrativeProvider(), output_root=root,
        )
        names.append([path.name for path in result.accepted])
    assert names[0] == names[1]


def test_fixed_seed_stub_output_is_pinned_across_code_changes(tmp_path):
    """A Scenario id hashes the set id, the whole planned spec and the
    narrative, so the ordered ids pin the plan, the stub narrative and the id
    definition. A refactor must leave this digest alone. A deliberate change
    to the planner, the stub, the id or the reviewed Journey inputs updates it
    in the same commit."""
    result = js.synthesize_set(
        JOURNEY_DIR, count=12, set_id="pinned", seed=7,
        provider=js.StubNarrativeProvider(), output_root=tmp_path,
    )
    ids = "\n".join(path.stem for path in result.accepted)
    assert js.sha256_bytes(ids.encode("utf-8")) == (
        "7aa4d64ba7d5c0c64cd7f6dabd6da47794cafce8aa810f801b4b4f0550acea44"
    )


@pytest.mark.parametrize(
    "output_root",
    ["scenarios", "scenarios/synth", "synthesized_scenarios/library", "generated_scenarios"],
)
def test_nothing_is_ever_written_under_the_curated_or_phase_4_5_stores(output_root):
    def snapshot():
        return {
            name: sorted(str(p) for p in (ROOT / name).rglob("*"))
            for name in js.FORBIDDEN_OUTPUT_ROOTS
        }

    before = snapshot()
    out = io.StringIO()
    status = js.synthesize_command(
        journey_dir=JOURNEY_DIR, count=1, set_id="set-1", stub=True,
        output_root=output_root, out=out,
    )
    assert status == 2
    assert "never receives Journey synthesis output" in out.getvalue()
    assert snapshot() == before


def test_an_existing_set_is_never_overwritten(tmp_path):
    _synthesize(tmp_path, count=1)
    with pytest.raises(js.SynthesisConfigError, match="never overwritten"):
        _synthesize(tmp_path, count=1)


@pytest.mark.parametrize("set_id", ["../escape", "Set-1", "", "a/b"])
def test_a_set_id_cannot_leave_the_output_root(tmp_path, set_id):
    with pytest.raises(js.SynthesisConfigError, match="set_id"):
        js.synthesize_set(
            JOURNEY_DIR, count=1, set_id=set_id,
            provider=js.StubNarrativeProvider(), output_root=tmp_path,
        )


# ----------------------------------------------------- model-client wiring


def test_missing_model_configuration_fails_in_one_line_before_any_call(tmp_path, monkeypatch):
    monkeypatch.delenv(js.SYNTHESIS_MODEL_ENV, raising=False)
    out = io.StringIO()
    status = js.synthesize_command(
        journey_dir=JOURNEY_DIR, count=1, set_id="set-1", output_root=tmp_path, out=out
    )
    assert status == 2
    assert out.getvalue().count("\n") == 1
    assert js.SYNTHESIS_MODEL_ENV in out.getvalue()

    monkeypatch.setenv(js.SYNTHESIS_MODEL_ENV, "some-model")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = io.StringIO()
    assert js.synthesize_command(
        journey_dir=JOURNEY_DIR, count=1, set_id="set-1", output_root=tmp_path, out=out
    ) == 2
    assert "OPENAI_API_KEY" in out.getvalue()
    assert list(tmp_path.iterdir()) == []


def test_the_live_provider_sends_one_structured_request_through_the_llm_client(tmp_path):
    calls = []

    class LLMDouble:
        async def structured(self, **kwargs):
            calls.append(kwargs)
            request = json.loads(kwargs["messages"][0]["content"])
            return js.StubNarrativeProvider().realize(request, attempt=request["attempt"])

    provider = js.LiveNarrativeProvider(llm=LLMDouble(), model="some-model")
    result = js.synthesize_set(
        JOURNEY_DIR, count=2, set_id="set-1", provider=provider, output_root=tmp_path
    )
    assert len(result.accepted) == 2 and len(calls) == 2
    assert calls[0]["system"] == js.SYSTEM_PROMPT
    assert set(calls[0]["schema"]["properties"]) == {"description", "persona", "goal"}
    assert calls[0]["schema"]["additionalProperties"] is False
    scenario = yaml.safe_load(result.accepted[0].read_text())
    assert scenario["synthesis"]["model"] == "some-model"
    provenance = json.loads((result.set_dir / "provenance.json").read_text())
    assert provenance["provider_id"] == "openai-structured-journey-narrative:some-model"


# ------------------------------------------------------- an aborted run


def _abort_on_second_spec(error):
    return ScriptedProvider({(2, 1): error})


def test_an_unexpected_failure_mid_run_keeps_the_evidence_and_marks_the_set_aborted(tmp_path):
    """A provider raising something other than ``LLMError`` — here a
    ``ValueError``, which must not be mistaken for a configuration error."""
    out = io.StringIO()
    status = js.synthesize_command(
        journey_dir=JOURNEY_DIR, count=3, set_id="set-1", output_root=tmp_path,
        provider=_abort_on_second_spec(ValueError("boom")), out=out,
    )
    set_dir = tmp_path / "appointment-rescheduling" / "set-1"

    assert status == 1  # files were written and the count was not produced: never 2
    assert out.getvalue().count("\n") == 1
    assert out.getvalue().startswith("ABORTED: ValueError: boom")
    assert str(set_dir) in out.getvalue()

    provenance = json.loads((set_dir / "provenance.json").read_text())
    assert provenance["status"] == "aborted"
    assert provenance["error"] == {"type": "ValueError", "message": "boom", "spec_id": "spec-002"}
    assert provenance["counts"] == {
        "requested": 3, "accepted": 1, "rejected_attempts": 0, "shortfall": 2,
    }
    assert [entry["spec_id"] for entry in provenance["specs"]] == ["spec-001"]
    kept = list((set_dir / "accepted").glob("*.yaml"))
    assert [f"accepted/{path.name}" for path in kept] == [
        entry["file"] for entry in provenance["accepted"]
    ]
    load_journey_scenario(kept[0])

    problems = js.verify_provenance(set_dir, JOURNEY_DIR)
    assert problems == ["provenance.json: the run was aborted (ValueError: boom)"]


def test_the_aborted_line_stays_one_line_whatever_the_error_says(tmp_path):
    out = io.StringIO()
    js.synthesize_command(
        journey_dir=JOURNEY_DIR, count=2, set_id="set-1", output_root=tmp_path,
        provider=_abort_on_second_spec(RuntimeError("first line\nsecond line")), out=out,
    )
    assert out.getvalue().count("\n") == 1
    assert out.getvalue().startswith("ABORTED: RuntimeError: first line second line;")
    provenance = json.loads(
        (tmp_path / "appointment-rescheduling" / "set-1" / "provenance.json").read_text()
    )
    assert provenance["error"]["message"] == "first line\nsecond line"  # kept as raised


def test_a_completed_run_says_so(tmp_path):
    result, _ = _synthesize(tmp_path, count=1)
    provenance = json.loads((result.set_dir / "provenance.json").read_text())
    assert provenance["status"] == "complete" and "error" not in provenance


def test_synthesize_set_raises_synthesis_aborted_from_the_original_error(tmp_path):
    with pytest.raises(js.SynthesisAborted) as excinfo:
        js.synthesize_set(
            JOURNEY_DIR, count=3, set_id="set-1", output_root=tmp_path,
            provider=_abort_on_second_spec(KeyError("missing")),
        )
    assert not isinstance(excinfo.value, ValueError)
    assert isinstance(excinfo.value.__cause__, KeyError)
    assert excinfo.value.set_dir == tmp_path / "appointment-rescheduling" / "set-1"


def test_an_interrupted_run_is_marked_aborted_and_the_interrupt_propagates(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        js.synthesize_set(
            JOURNEY_DIR, count=3, set_id="set-1", output_root=tmp_path,
            provider=_abort_on_second_spec(KeyboardInterrupt()),
        )
    provenance = json.loads(
        (tmp_path / "appointment-rescheduling" / "set-1" / "provenance.json").read_text()
    )
    assert provenance["status"] == "aborted"
    assert provenance["error"]["type"] == "KeyboardInterrupt"


def test_a_set_directory_that_appears_during_planning_is_a_config_error(tmp_path, monkeypatch):
    """The race: another run creates the set directory after the existence
    check and before ``mkdir``."""
    real_plan = js.plan_specs
    set_dir = tmp_path / "appointment-rescheduling" / "set-1"

    def racing(*args, **kwargs):
        set_dir.mkdir(parents=True)
        return real_plan(*args, **kwargs)

    monkeypatch.setattr(js, "plan_specs", racing)
    out = io.StringIO()
    status = js.synthesize_command(
        journey_dir=JOURNEY_DIR, count=1, set_id="set-1", stub=True,
        output_root=tmp_path, out=out,
    )
    assert status == 2
    assert "never overwritten" in out.getvalue()
    assert list(set_dir.iterdir()) == []


# ------------------------------------------------ variation settings, again


def _journey_with(**changes):
    import dataclasses

    journey, _ = _inputs()
    return dataclasses.replace(journey, **changes)


def test_duplicate_tool_failure_conditions_are_refused_comparing_as_sets():
    from agentsim.journey.definition import ValidOutcome

    journey, _ = _inputs()
    with pytest.raises(js.SynthesisConfigError, match="tool_failure_conditions: duplicate"):
        js.VariationSettings(tool_failure_conditions=((), ())).resolved(journey)

    two_failures = _journey_with(
        valid_outcomes=(
            *journey.valid_outcomes,
            ValidOutcome("both_failed", "both tools failed", ("update_appointment", "lookup")),
        )
    )
    same_condition_twice = (("update_appointment", "lookup"), ("lookup", "update_appointment"))
    with pytest.raises(js.SynthesisConfigError, match="tool_failure_conditions: duplicate"):
        js.VariationSettings(tool_failure_conditions=same_condition_twice).resolved(two_failures)
    # One spelling of it is fine.
    resolved = js.VariationSettings(
        tool_failure_conditions=same_condition_twice[:1]
    ).resolved(two_failures)
    assert resolved.tool_failure_conditions == (("update_appointment", "lookup"),)


@pytest.mark.parametrize(
    "axis", ["archetypes", "knowledge_levels", "complications", "tool_failure_conditions"]
)
def test_an_explicitly_empty_axis_is_refused_rather_than_meaning_everything(tmp_path, axis):
    with pytest.raises(js.SynthesisConfigError, match=f"{axis}: must not be empty"):
        _synthesize(tmp_path, settings=js.VariationSettings(**{axis: ()}))
    assert list(tmp_path.iterdir()) == []


def test_an_omitted_axis_still_means_every_supported_value():
    journey, _ = _inputs()
    resolved = js.VariationSettings().resolved(journey)
    assert set(resolved.archetypes) == {"cooperative", "pressure", "vigilant", "persistent"}
    assert set(resolved.knowledge_levels) == {"low", "medium", "high"}
    assert resolved.complications == journey.supported_complications
    assert resolved.tool_failure_conditions == ((), ("update_appointment",))
    # The one-condition setting "no tool failure" is not an empty axis.
    assert js.VariationSettings(tool_failure_conditions=((),)).resolved(
        journey
    ).tool_failure_conditions == ((),)


def _journey_dir_with(tmp_path, *, journey=lambda raw: None, fixture_text=lambda text: text):
    """A copy of the reviewed Journey inputs with one deliberate change."""
    directory = tmp_path / "journey-inputs"
    directory.mkdir()
    raw = yaml.safe_load((JOURNEY_DIR / "journey.yaml").read_text())
    journey(raw)
    (directory / "journey.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    (directory / "fixture_state.yaml").write_text(
        fixture_text((JOURNEY_DIR / "fixture_state.yaml").read_text())
    )
    return directory


def test_a_supported_complication_with_no_writing_direction_is_refused_up_front(tmp_path):
    """Goal shift is unsupported for the reviewed Journey. A Journey that lists
    it as supported must be refused before anything is written, not crash on
    the first spec that uses it."""

    def support_goal_shift(raw):
        raw["complications"]["unsupported"].pop("goal-shift")
        raw["complications"]["supported"].append("goal-shift")

    journey_dir = _journey_dir_with(tmp_path, journey=support_goal_shift)
    output_root = tmp_path / "out"
    out = io.StringIO()
    status = js.synthesize_command(
        journey_dir=journey_dir, count=8, set_id="set-1", stub=True,
        output_root=output_root, out=out,
    )
    assert status == 2
    assert "'goal-shift'" in out.getvalue() and "no writing direction" in out.getvalue()
    assert not output_root.exists()
    # Asking only for Complications that have a direction still works.
    assert js.synthesize_command(
        journey_dir=journey_dir, count=2, set_id="set-1", output_root=output_root,
        provider=js.StubNarrativeProvider(), out=io.StringIO(),
    ) == 2  # the default settings still include goal-shift
    result = js.synthesize_set(
        journey_dir, count=2, set_id="set-1", output_root=output_root,
        provider=js.StubNarrativeProvider(),
        settings=js.VariationSettings(complications=("none", "false-premise")),
    )
    assert result.shortfall == 0


# ------------------------------------------- date-times with a UTC offset

_OFFSET_FACTS = [
    {"path": "appointments.A-1001.start", "value": "2026-10-06T10:00:00+00:00"},
    {"path": "slots.S-102.start", "value": "2026-10-13T15:30:00+00:00"},
]


def test_a_verbatim_grounded_date_time_and_its_clock_time_pass():
    for text in (
        "My appointment is at 2026-10-06T10:00:00+00:00.",
        "From 2026-10-06T10:00:00+00:00 to 2026-10-13T15:30:00+00:00, please.",
        "It starts at 10:00:00 and the new one at 15:30:00.",
    ):
        assert js.narrative_sealed_world_violations({"goal": text}, _OFFSET_FACTS) == []
    plain = [{"path": "appointments.A-1001.start", "value": "2026-10-06T10:00:00"}]
    assert js.narrative_sealed_world_violations({"goal": "At 10:00:00."}, plain) == []


@pytest.mark.parametrize(
    "text, ungrounded",
    [
        ("At 2026-10-06T11:00:00+00:00.", "2026-10-06T11:00:00"),  # another time
        ("At 2026-10-07T10:00:00+00:00.", "2026-10-07T10:00:00"),  # another date
        ("At 2026-10-06T10:00:00+05:00.", "05:00"),  # another offset
        ("At 2026-10-06T10:00:00+00:00 or 00:00.", "00:00"),  # the offset is not a time
        ("At 10:00:01.", "10:00:01"),
        ("At 10:30:00.", "10:30:00"),
        ("Code HSD-9999, appointment A-1001.", "HSD-9999"),
    ],
)
def test_the_offset_fix_loosens_nothing_else(text, ungrounded):
    violations = js.narrative_sealed_world_violations({"goal": text}, _OFFSET_FACTS)
    assert f"goal: {ungrounded!r} is not a grounded fact" in violations


def test_the_stub_produces_the_requested_count_on_a_fixture_with_utc_offsets(tmp_path):
    import re

    journey_dir = _journey_dir_with(
        tmp_path,
        fixture_text=lambda text: re.sub(r'(\d{2}:\d{2}:\d{2})"', r'\1+00:00"', text),
    )
    _, fixture_state = load_journey_inputs(journey_dir)
    assert fixture_state.now.endswith("+00:00")
    result = js.synthesize_set(
        journey_dir, count=6, set_id="set-1", output_root=tmp_path / "out",
        provider=js.StubNarrativeProvider(),
    )
    assert result.shortfall == 0 and result.rejected == ()
    assert js.verify_provenance(result.set_dir, journey_dir) == []


def test_model_output_with_keys_that_are_not_strings_is_malformed_not_a_crash():
    good = {"description": "d", "persona": {"traits": "t"}, "goal": "g"}
    with pytest.raises(js.Rejection) as excinfo:  # sorting mixed-type keys raised TypeError
        js.parse_narrative({1: "x", "expected_outcome": "rescheduled", **good})
    assert excinfo.value.code == "malformed-output"
    with pytest.raises(js.Rejection) as excinfo:
        js.parse_narrative({1: "x", "description": "d", "persona": {"traits": "t"}, "goal": "g"})
    assert excinfo.value.code == "malformed-output"
    with pytest.raises(js.Rejection) as excinfo:
        js.parse_narrative({"description": "d", "persona": {2: "x", "traits": "t"}, "goal": "g"})
    assert excinfo.value.code == "malformed-output"
