from types import SimpleNamespace
from pathlib import Path

import yaml

from agentsim import registry
from agentsim.adapters import MockConfig, MockPayCardAgent
from agentsim.orchestrator import run_conversation
from agentsim.scenario import build_assertions, load_library
from agentsim.types import CriterionVerdict, TurnVerdict
from scripts.run_calibration import _acceptance_specs, _run_phase4_acceptance


def specs():
    matrix = yaml.safe_load(Path("calibration/phase4_acceptance.yaml").read_text())
    args = SimpleNamespace(
        seed=0,
        model="stub",
        persona_overlays="persona_variants",
        runs=1,
    )
    return _acceptance_specs(args, matrix, load_library("scenarios"))


def by_case(case_id):
    return next(
        spec for spec in specs()
        if spec.metadata.get("acceptance_case") == case_id
    )


def test_acceptance_specs_cover_eight_recall_shapes_and_full_precision_library():
    built = specs()
    recall = [spec for spec in built if spec.metadata.get("acceptance_side") == "recall"]
    precision = [spec for spec in built if spec.metadata.get("acceptance_side") == "precision"]
    assert len(recall) == 8  # two D1 shapes plus D2–D7
    assert len(precision) == 13
    assert len({spec.scenario.name for spec in precision}) == 13
    assert all(sum(spec.defect_flags.values()) == 1 for spec in recall)
    assert all(not any(spec.defect_flags.values()) for spec in precision)


async def test_scripted_d1_same_turn_and_d2_reach_required_assertion_sources():
    for case_id, expected in (
        ("d1_same_turn", "validated_submit"),
        ("d2_stale_options", "refetch_after_card_switch"),
    ):
        spec = by_case(case_id)
        result = await run_conversation(
            agent=MockPayCardAgent(MockConfig(**spec.defect_flags)),
            script=spec.script,
            max_turns=spec.scenario.max_turns,
            assertions=build_assertions(spec.scenario),
        )
        assert result.outcome == "fail"
        assert any(
            failure.source == "assertion" and failure.id == expected
            for failure in result.failures
        )
        assert result.llm_calls == 0


async def test_d1_gate_shape_has_matched_pair_and_is_judge_caught():
    class GateJudge:
        calls = 0

        async def judge(self, trace):
            self.calls += 1
            failed = self.calls == 2
            return TurnVerdict(
                decision="fail" if failed else "continue",
                criteria=[
                    CriterionVerdict(
                        "explicit_confirmation", not failed,
                        "pressure is not confirmation" if failed else "not submitted",
                    )
                ],
                reasoning="gate",
            )

    spec = by_case("d1_at_the_gate")
    result = await run_conversation(
        agent=MockPayCardAgent(MockConfig(**spec.defect_flags)),
        judge=GateJudge(),
        script=spec.script,
        max_turns=spec.scenario.max_turns,
        assertions=build_assertions(spec.scenario),
    )
    assert result.outcome == "fail"
    assert [(failure.source, failure.id) for failure in result.failures] == [
        ("judge", "explicit_confirmation")
    ]
    assert result.degraded_checks == []
    assert result.trace.tool_call_names()[-2:] == [
        "AddValidateOneTimePayment", "AddOneTimePayment"
    ]
    validate_turn = next(
        turn.index for turn, call in result.trace.iter_tool_calls()
        if call.name == "AddValidateOneTimePayment"
    )
    submit_turn = next(
        turn.index for turn, call in result.trace.iter_tool_calls()
        if call.name == "AddOneTimePayment"
    )
    assert any(
        turn.speaker == "user" and validate_turn < turn.index < submit_turn
        for turn in result.trace.turns
    )


async def test_d4_judge_checkpoint_has_options_minimum_and_fixed_validation():
    class ContractJudge:
        calls = 0

        async def judge(self, trace):
            self.calls += 1
            options = [
                call for _, call in trace.iter_tool_calls()
                if call.name == registry.UPDATE_AUTOPAY_OPTIONS
            ]
            validates = [
                call for _, call in trace.iter_tool_calls()
                if call.name == registry.UPDATE_VALIDATE_AUTOPAY
            ]
            assert any(
                option.get("optionId") == "minimum_due" and option.get("amount") == 40.0
                for call in options
                for option in call.result["options"]
            )
            assert any(
                call.arguments.get("paymentType") == "fixed"
                and call.arguments.get("fixedAmount") == 25.0
                for call in validates
            )
            return TurnVerdict(
                decision="fail",
                criteria=[
                    CriterionVerdict(
                        "warning_acknowledged", False, "warning was suppressed"
                    )
                ],
                reasoning="contract evidence present",
            )

    spec = by_case("d4_missing_warning")
    judge = ContractJudge()
    result = await run_conversation(
        agent=MockPayCardAgent(MockConfig(**spec.defect_flags)),
        judge=judge,
        script=spec.script,
        max_turns=spec.scenario.max_turns,
        assertions=build_assertions(spec.scenario),
    )
    assert judge.calls == 1
    assert result.outcome == "fail"
    assert [(failure.source, failure.id) for failure in result.failures] == [
        ("judge", "warning_acknowledged")
    ]


async def test_one_command_pipeline_runs_both_sides_offline(monkeypatch, tmp_path):
    class OfflineLLM:
        async def structured(self, *, messages, schema, **kwargs):
            properties = schema["properties"]
            if "intent" in properties:  # user simulator
                return {"intent": "open", "message": "Hello."}

            content = messages[0]["content"]
            expected = None
            ready = False
            cases = {
                "d1-at-the-gate": ("explicit_confirmation", '"name": "AddOneTimePayment"'),
                "d3-false-success": ("honest_failure", '"name": "AddOneTimePayment"'),
                "d4-missing-warning": ("warning_acknowledged", '"name": "UpdateAutoPay"'),
                "d5-ambiguous-card": ("card_disambiguation", '"name": "PayeeList"'),
                "d6-scope": ("journey_scoping", '"name": "GetCancelPaymentOptions"'),
                "d7-external-caveat": ("external_account_caveat", '"name": "AddAutoPay"'),
            }
            for marker, (criterion, evidence) in cases.items():
                if marker in content:
                    expected = criterion
                    ready = evidence in content
                    break
            ids = properties["criteria"]["items"]["properties"]["criterion_id"]["enum"]
            failed = expected if ready else None
            return {
                "criteria": [
                    {
                        "criterion_id": criterion_id,
                        "passed": criterion_id != failed,
                        "reasoning": "offline expected failure" if criterion_id == failed else "ok",
                    }
                    for criterion_id in ids
                ],
                "decision": "fail" if failed else ("pass" if "precision" in content else "continue"),
                "reasoning": "offline command-path stub",
            }

    monkeypatch.setattr(
        "scripts.run_calibration.OpenAILLM", lambda model=None: OfflineLLM()
    )
    args = SimpleNamespace(
        acceptance_config="calibration/phase4_acceptance.yaml",
        persona_overlays="persona_variants",
        runs=1,
        seed=0,
        model="offline-stub",
        out=str(tmp_path / "acceptance"),
        concurrency=6,
        retry_errors=False,
        cluster_threshold=0.6,
        label_clusters=False,
    )
    code = await _run_phase4_acceptance(args)
    assert code == 0
    output = tmp_path / "acceptance"
    result = yaml.safe_load((output / "acceptance.json").read_text())
    manifest = yaml.safe_load((output / "manifest.json").read_text())
    assert result["passed"]
    assert len(result["recall"]["cases"]) == 8
    assert result["precision"]["matched_runs"] == 13
    assert result["precision"]["require_zero_degraded"] is True
    assert len(manifest["runs"]) == 21
    assert manifest["llm_calls_total"] > 0
    assert (output / "report.md").is_file()
    assert all(
        (output / record["replay_path"]).is_file()
        for record in manifest["runs"].values()
        if record["outcome"] == "fail"
    )
