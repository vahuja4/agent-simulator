from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentsim.llm import LLMTruncationError
from agentsim.scenario import load_scenario
from scripts import realize_scenarios
from scenario_synthesis.blueprint import load_blueprint
from scenario_synthesis import realize
from scenario_synthesis.realize import RealizationError, realize_blueprint
from scenario_synthesis.sample import behavioral_class_key


BLUEPRINT = Path("scenario_synthesis/blueprints/j1_happy_path.yaml")


def valid_output() -> dict[str, Any]:
    return {
        "description": "A customer schedules a statement-balance card payment.",
        "persona": {
            "name": "Jordan",
            "traits": {
                "patience": "patient",
                "attention_to_amounts": "attentive_to_amounts",
                "disclosure_style": "concise_upfront",
                "decisiveness": "decisive",
            },
        },
        "goal": (
            "Pay the statement balance for the card ending 0767 from the account "
            "ending 5678 on the due date, after explicit confirmation."
        ),
        "success_criteria": [
            "The statement-balance payment is submitted on the due date only after confirmation."
        ],
    }


def test_live_entrypoint_uses_manifest_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = load_blueprint(Path("scenario_synthesis/blueprints/j1_happy_path.yaml"))
    second = load_blueprint(Path("scenario_synthesis/blueprints/j1_card_switch.yaml"))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "seed": 1729,
                "counts": {"sample": 2},
                "sample_ids": [second.id, first.id],
            }
        )
    )
    monkeypatch.setattr(
        realize_scenarios,
        "enumerate_blueprints",
        lambda *, seed: (first, second),
    )

    selected = realize_scenarios.load_manifest_sample(manifest_path)

    assert [blueprint.id for blueprint in selected] == [second.id, first.id]


class StubLLM:
    def __init__(self, outputs: list[dict[str, Any] | Exception]) -> None:
        self.outputs = outputs
        self.calls = 0
        self.kwargs: list[dict[str, Any]] = []

    async def structured(self, **kwargs: Any) -> dict[str, Any]:
        output = self.outputs[self.calls]
        self.calls += 1
        self.kwargs.append(kwargs)
        if isinstance(output, Exception):
            raise output
        return output


@pytest.mark.asyncio
async def test_valid_realization_loads_through_existing_loader(tmp_path: Path) -> None:
    blueprint = load_blueprint(BLUEPRINT)
    llm = StubLLM([valid_output()])
    scenario = await realize_blueprint(blueprint, llm)
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml.safe_dump(scenario, sort_keys=False))

    loaded = load_scenario(path)
    assert loaded.name == blueprint.id
    assert [card.last_four for card in loaded.knowledge_cards] == ["0767"]
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_extra_identifier_is_rejected_after_one_retry() -> None:
    output = valid_output()
    output["goal"] += " Use account ending 9999."
    llm = StubLLM([deepcopy(output), deepcopy(output)])

    with pytest.raises(RealizationError, match="9999"):
        await realize_blueprint(load_blueprint(BLUEPRINT), llm)
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_altered_amount_is_rejected_after_one_retry() -> None:
    output = valid_output()
    output["success_criteria"][0] += " The amount is $311.45."
    llm = StubLLM([deepcopy(output), deepcopy(output)])

    with pytest.raises(RealizationError, match=r"311(?:\\.45)?"):
        await realize_blueprint(load_blueprint(BLUEPRINT), llm)
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_off_whitelist_trait_is_rejected_after_one_retry() -> None:
    output = valid_output()
    output["persona"]["traits"]["patience"] = "reckless"
    llm = StubLLM([deepcopy(output), deepcopy(output)])

    with pytest.raises(RealizationError, match="reviewed whitelist"):
        await realize_blueprint(load_blueprint(BLUEPRINT), llm)
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_rejected_first_output_can_succeed_on_retry(tmp_path: Path) -> None:
    invalid = valid_output()
    invalid["goal"] += " Use card ending 9999."
    llm = StubLLM([invalid, valid_output()])

    scenario = await realize_blueprint(load_blueprint(BLUEPRINT), llm)
    path = tmp_path / "retry.yaml"
    path.write_text(yaml.safe_dump(scenario, sort_keys=False))
    assert load_scenario(path).name == "j1-happy-path"
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_truncation_retries_once_with_larger_budget() -> None:
    llm = StubLLM(
        [LLMTruncationError("model output truncated"), valid_output()]
    )

    scenario = await realize_blueprint(load_blueprint(BLUEPRINT), llm)

    assert scenario["name"] == "j1-happy-path"
    assert llm.calls == 2
    assert [call["effort"] for call in llm.kwargs] == ["none", "none"]
    assert [call["max_tokens"] for call in llm.kwargs] == [8192, 16384]


@pytest.mark.asyncio
async def test_catalog_realizes_one_maximal_policy_member_and_records_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    maximal = load_blueprint(BLUEPRINT)
    subset = replace(maximal, id="policy-subset", policies=())
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"counts": {}}))
    monkeypatch.setattr(realize, "DEFAULT_YAML_DIR", tmp_path / "yaml")
    monkeypatch.setattr(realize, "DEFAULT_MANIFEST", manifest_path)
    (tmp_path / "yaml").mkdir()
    (tmp_path / "yaml" / "stale.yaml").write_text("stale: true\n")
    llm = StubLLM([valid_output()])

    paths = await realize.realize_catalog((subset, maximal), llm)
    manifest = json.loads(manifest_path.read_text())

    assert llm.calls == 1
    assert len(paths) == 1
    assert not (tmp_path / "yaml" / "stale.yaml").exists()
    assert load_scenario(paths[0]).name == maximal.id
    assert manifest["realized_scenarios"] == [
        {
            "scenario_id": maximal.id,
            "blueprint_id": maximal.id,
            "behavioral_class_key": behavioral_class_key(maximal),
        }
    ]
