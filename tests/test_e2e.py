"""End-to-end: the real MockPayCardAgent driven by the real UserSimulator and
GeneralJudge, with only the LLM calls stubbed. This is Phase 1's "done" gate.

Per the design amendments, the assertions here target the TRACE — the exact
tool-call sequence with result payloads, the PendingPayment staged by
validate and consumed by submit, and the user confirmation turn between the
two — not just the final verdict. The trace is the contract everything later
(assertion engine, clustering, reporting) builds on.
"""

from __future__ import annotations

from agentsim import registry
from agentsim.adapters import MockPayCardAgent
from agentsim.judge import DEFAULT_CRITERIA, GeneralJudge
from agentsim.orchestrator import run_conversation
from agentsim.simulator import STOP_SENTINEL, Persona, UserSimulator
from agentsim.trace import Trace
from conftest import StubLLMClient

PERSONA = Persona(name="Jordan", traits="polite, to the point")
GOAL = (
    "Pay the statement balance on your Chase Sapphire Preferred card (ending "
    "9013) from your Chase checking account, on the due date."
)


def scripted_simulator() -> UserSimulator:
    """The simulator's LLM is stubbed with a realistic J1 conversation."""
    llm = StubLLMClient(
        [
            {
                "intent": "state goal",
                "message": "Hi, I'd like to pay my Sapphire card, the one ending in 9013.",
            },
            {"intent": "pick account", "message": "Use my Chase checking ending 5678."},
            {"intent": "pick amount", "message": "The statement balance please."},
            {"intent": "pick date", "message": "Schedule it for June 20."},
            {"intent": "confirm", "message": "Yes, confirm it."},
            {"intent": "stop", "message": f"Great, thanks! {STOP_SENTINEL}"},
        ]
    )
    return UserSimulator(llm, persona=PERSONA, goal=GOAL)


def scripted_judge(decisions: list[str]) -> GeneralJudge:
    def verdict(decision: str) -> dict:
        return {
            "criteria": [
                {"criterion_id": c.id, "passed": True, "reasoning": "ok"}
                for c in DEFAULT_CRITERIA
            ],
            "decision": decision,
            "reasoning": f"scripted {decision}",
        }

    return GeneralJudge(StubLLMClient([verdict(d) for d in decisions]))


async def run_happy_path():
    return await run_conversation(
        simulator=scripted_simulator(),
        agent=MockPayCardAgent(),
        judge=scripted_judge(["continue", "continue", "continue", "continue", "pass"]),
        conversation_id="e2e-1",
        max_turns=10,
    )


async def test_one_time_payment_end_to_end_passes():
    result = await run_happy_path()
    assert result.outcome == "pass"
    assert result.trace.outcome == "pass"
    assert len(result.verdicts) == 5


async def test_trace_records_the_full_j1_tool_sequence_with_results():
    trace = (await run_happy_path()).trace

    assert trace.tool_call_names() == [
        registry.PAYEE_LIST,
        registry.FUNDING_ACCOUNT_PICKER,
        registry.ADD_OPTIONS_ONE_TIME_PAYMENT,
        registry.ADD_VALIDATE_ONE_TIME_PAYMENT,
        registry.ADD_ONE_TIME_PAYMENT,
    ]
    # Every tool call carries a result payload, not just the call.
    for _, call in trace.iter_tool_calls():
        assert call.result is not None

    calls = {call.name: call for _, call in trace.iter_tool_calls()}
    options = calls[registry.ADD_OPTIONS_ONE_TIME_PAYMENT]
    assert options.arguments == {"payeeId": "card-sapphire-9013"}
    assert any(
        o["optionId"] == "statement_balance" and o["amount"] == 875.20
        for o in options.result["options"]
    )


async def test_pending_payment_staged_by_validate_then_consumed_by_submit():
    trace = (await run_happy_path()).trace
    calls = {call.name: call for _, call in trace.iter_tool_calls()}

    validate = calls[registry.ADD_VALIDATE_ONE_TIME_PAYMENT]
    submit = calls[registry.ADD_ONE_TIME_PAYMENT]

    # Validate staged the pending object …
    assert validate.result["status"] == "ready"
    staged = validate.result["pendingPayment"]
    assert staged["amount"] == 875.20
    assert staged["paymentDate"] == "2026-06-20"
    assert staged["cardLabel"] == "Chase Sapphire Preferred (...9013)"

    # … and submit consumed exactly that staged object, by formId.
    assert submit.arguments == {"formId": staged["formId"]}
    assert submit.result["success"] is True
    assert submit.result["payment"] == staged


async def test_user_confirmation_turn_sits_between_validate_and_submit():
    trace = (await run_happy_path()).trace
    validate_turn = next(
        t for t, c in trace.iter_tool_calls() if c.name == registry.ADD_VALIDATE_ONE_TIME_PAYMENT
    )
    submit_turn = next(
        t for t, c in trace.iter_tool_calls() if c.name == registry.ADD_ONE_TIME_PAYMENT
    )
    between = [
        t
        for t in trace.turns
        if validate_turn.index < t.index < submit_turn.index and t.speaker == "user"
    ]
    # The ordering fact the future deterministic assertion will check …
    assert len(between) == 1
    # … and the text the judge reads to decide it was a real confirmation.
    assert between[0].text == "Yes, confirm it."
    assert between[0].intent == "confirm"


async def test_selected_card_state_is_recorded_per_turn():
    trace = (await run_happy_path()).trace
    assert trace.turns[0].selected_card is None  # before the agent ever spoke
    assert trace.turns[1].selected_card == "Chase Sapphire Preferred (...9013)"
    assert all(
        t.selected_card == "Chase Sapphire Preferred (...9013)" for t in trace.turns[2:]
    )


async def test_trace_round_trips_through_json():
    trace = (await run_happy_path()).trace
    assert Trace.from_json(trace.to_json()) == trace


async def test_judge_fail_produces_fail_outcome():
    result = await run_conversation(
        simulator=scripted_simulator(),
        agent=MockPayCardAgent(),
        judge=scripted_judge(["continue", "fail"]),
        conversation_id="e2e-2",
        max_turns=10,
    )
    assert result.outcome == "fail"
    assert result.trace.outcome == "fail"
    # The run stopped at the failing turn.
    assert len(result.verdicts) == 2
