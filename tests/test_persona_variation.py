from dataclasses import asdict

import pytest

from agentsim.persona_variation import (
    PersonaOverlayError,
    apply_persona_overlay,
    load_persona_overlay,
    load_persona_overlays,
    overlay_for_run,
)
from agentsim.scenario import load_scenario


def test_overlay_returns_copy_and_changes_only_persona(tmp_path):
    scenario = load_scenario("scenarios/j1_happy_path.yaml")
    before = asdict(scenario)
    path = tmp_path / "variant.yaml"
    path.write_text("id: clipped\nname: Jo\ntraits_append: answers very briefly\n")
    overlay = load_persona_overlay(path)
    varied = apply_persona_overlay(scenario, overlay)

    assert varied is not scenario
    assert varied.persona.name == "Jo"
    assert varied.persona.traits.endswith("answers very briefly")
    assert asdict(scenario) == before
    varied_dict = asdict(varied)
    original_dict = asdict(scenario)
    varied_dict.pop("persona")
    original_dict.pop("persona")
    assert varied_dict == original_dict


def test_overlay_rejects_semantic_fields(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("id: bad\ntraits_append: terse\ngoal: do something else\n")
    with pytest.raises(PersonaOverlayError, match="cannot change.*goal"):
        load_persona_overlay(path)


def test_overlay_schedule_is_deterministic_and_includes_base():
    overlays = load_persona_overlays("persona_variants")
    first = [overlay_for_run(overlays, seed=0, run_index=i) for i in range(8)]
    second = [overlay_for_run(overlays, seed=0, run_index=i) for i in range(8)]
    assert first == second
    assert first[0] is None
    assert {item.id for item in first if item is not None} == {
        "cautious", "concise", "impatient"
    }
