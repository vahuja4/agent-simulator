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
