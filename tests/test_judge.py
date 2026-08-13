"""GeneralJudge fail-closed behavior with a stubbed LLM."""

from __future__ import annotations

import pytest

from agentsim.judge import DEFAULT_CRITERIA, GeneralJudge
from agentsim.llm import LLMError
from agentsim.trace import Trace, TraceToolCall


def make_trace() -> Trace:
    trace = Trace(conversation_id="j1")
    trace.add_user_turn("pay my card", intent="goal", selected_card=None)
    trace.add_agent_turn(
        "Which card?",
        [TraceToolCall("PayeeList", {}, {"payees": []})],
        selected_card=None,
    )
    return trace


def all_true_criteria() -> list[dict]:
    return [
        {"criterion_id": c.id, "passed": True, "reasoning": "ok"} for c in DEFAULT_CRITERIA
    ]


async def test_explicit_pass_maps_to_pass(stub_llm):
    stub_llm.push({"criteria": all_true_criteria(), "decision": "pass", "reasoning": "done"})
    v = await GeneralJudge(stub_llm).judge(make_trace())
    assert v.decision == "pass"
    assert all(c.passed for c in v.criteria)


async def test_pass_with_a_false_criterion_downgrades_to_fail(stub_llm):
    criteria = all_true_criteria()
    criteria[1]["passed"] = False
    stub_llm.push({"criteria": criteria, "decision": "pass", "reasoning": "oops"})
    v = await GeneralJudge(stub_llm).judge(make_trace())
    assert v.decision == "fail"


async def test_continue_with_violation_becomes_fail(stub_llm):
    criteria = all_true_criteria()
    criteria[3]["passed"] = False
    stub_llm.push({"criteria": criteria, "decision": "continue", "reasoning": "hmm"})
    v = await GeneralJudge(stub_llm).judge(make_trace())
    assert v.decision == "fail"


async def test_missing_criterion_fails_closed(stub_llm):
    stub_llm.push(
        {"criteria": all_true_criteria()[:-1], "decision": "pass", "reasoning": "done"}
    )
    v = await GeneralJudge(stub_llm).judge(make_trace())
    assert v.decision == "fail"
    missing = [c for c in v.criteria if "missing" in c.reasoning]
    assert len(missing) == 1 and missing[0].passed is False


async def test_invalid_decision_fails_closed(stub_llm):
    stub_llm.push({"criteria": all_true_criteria(), "decision": "maybe", "reasoning": "?"})
    v = await GeneralJudge(stub_llm).judge(make_trace())
    assert v.decision == "fail"
    assert "fail-closed" in v.reasoning


async def test_clean_continue_stays_continue(stub_llm):
    stub_llm.push({"criteria": all_true_criteria(), "decision": "continue", "reasoning": "ongoing"})
    v = await GeneralJudge(stub_llm).judge(make_trace())
    assert v.decision == "continue"


async def test_llm_error_propagates(stub_llm):
    class Boom:
        async def structured(self, **kwargs):
            raise LLMError("judge call failed")

    with pytest.raises(LLMError):
        await GeneralJudge(Boom()).judge(make_trace())


async def test_prompt_carries_transcript_and_trace_with_results(stub_llm):
    stub_llm.push({"criteria": all_true_criteria(), "decision": "continue", "reasoning": "ok"})
    await GeneralJudge(stub_llm).judge(make_trace())
    content = stub_llm.calls[0]["messages"][0]["content"]
    assert "TRANSCRIPT:" in content and "Customer: pay my card" in content
    assert '"payees"' in content  # tool result payload included


# ------------------------------------------------- dynamic criteria (Phase 3)

from agentsim.judge import Criterion  # noqa: E402

EXTRA = Criterion("specialist_x", "An extra trigger-conditioned criterion.")


def judge_with_hook(stub_llm, active: bool) -> GeneralJudge:
    return GeneralJudge(
        stub_llm, dynamic_criteria=lambda trace: (EXTRA,) if active else ()
    )


async def test_active_dynamic_criterion_joins_prompt_schema_and_verdict(stub_llm):
    stub_llm.push({
        "criteria": all_true_criteria()
        + [{"criterion_id": EXTRA.id, "passed": True, "reasoning": "ok"}],
        "decision": "continue",
        "reasoning": "ok",
    })
    v = await judge_with_hook(stub_llm, active=True).judge(make_trace())
    assert v.decision == "continue"
    assert [c.criterion_id for c in v.criteria][-1] == EXTRA.id
    call = stub_llm.calls[0]
    assert EXTRA.id in call["system"]  # batched into the single call
    assert EXTRA.id in call["schema"]["properties"]["criteria"]["items"][
        "properties"]["criterion_id"]["enum"]


async def test_missing_active_dynamic_criterion_fails_closed(stub_llm):
    stub_llm.push({"criteria": all_true_criteria(), "decision": "pass", "reasoning": "done"})
    v = await judge_with_hook(stub_llm, active=True).judge(make_trace())
    assert v.decision == "fail"
    extra = [c for c in v.criteria if c.criterion_id == EXTRA.id]
    assert len(extra) == 1 and extra[0].passed is False


async def test_inactive_dynamic_criterion_is_not_demanded(stub_llm):
    stub_llm.push({"criteria": all_true_criteria(), "decision": "pass", "reasoning": "done"})
    v = await judge_with_hook(stub_llm, active=False).judge(make_trace())
    assert v.decision == "pass"
    assert EXTRA.id not in [c.criterion_id for c in v.criteria]
    assert EXTRA.id not in stub_llm.calls[0]["system"]


async def test_dynamic_criterion_never_shadows_a_base_id(stub_llm):
    clashing = Criterion("goal_completion", "SHOULD NOT REPLACE THE BASE WORDING")
    judge = GeneralJudge(stub_llm, dynamic_criteria=lambda trace: (clashing,))
    stub_llm.push({"criteria": all_true_criteria(), "decision": "pass", "reasoning": "done"})
    v = await judge.judge(make_trace())
    assert v.decision == "pass"  # base set unchanged, nothing extra demanded
    assert "SHOULD NOT REPLACE" not in stub_llm.calls[0]["system"]
