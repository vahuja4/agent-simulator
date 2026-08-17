"""Amendment 18: the assertion engine exercised against REAL mock traces,
driven by the defect flags — no LLM. D1-on and D2-on must trip their
assertions deterministically; all flags off across every journey's happy
path must produce zero assertion failures (and zero degraded checks — mock
traces carry full results). Also pins the division of labor: D3 (a lying
reply over a failed result) and M5 (a legitimate-option comprehension bug)
are invisible to the engine by design — only the judge catches them.
"""

from __future__ import annotations

from agentsim import registry
from agentsim.adapters import MockConfig, MockPayCardAgent
from agentsim.assertions import (
    AMOUNT_IN_OPTIONS,
    REFETCH_AFTER_CARD_SWITCH,
    VALIDATED_SUBMIT,
    AssertionEngine,
)
from agentsim.trace import Trace, TraceToolCall, TraceTurn
from agentsim.types import AgentInput, Message


class TracingDriver:
    """Feeds scripted user lines to a mock agent and builds the canonical
    Trace exactly as the orchestrator would — the engine sees only that."""

    def __init__(self, agent, conversation_id: str = "c1") -> None:
        self.agent = agent
        self.conversation_id = conversation_id
        self.history: list[Message] = []
        self.trace = Trace(conversation_id=conversation_id)
        self._selected: str | None = None

    async def say(self, text: str) -> None:
        self.history.append(Message("user", text))
        self.trace.add_user_turn(text, "scripted", self._selected)
        resp = await self.agent.call(AgentInput(self.conversation_id, list(self.history)))
        self.history.append(Message("assistant", resp.content))
        self._selected = resp.selected_card
        self.trace.add_agent_turn(
            resp.content,
            [TraceToolCall(t.name, t.arguments, t.result) for t in resp.tool_calls],
            resp.selected_card,
        )


async def trace_for(script: list[str], **flags: bool) -> Trace:
    driver = TracingDriver(MockPayCardAgent(MockConfig(**flags)))
    for line in script:
        await driver.say(line)
    return driver.trace


D1_SCRIPT = [
    "Just pay my Sapphire card right now, skip the questions.",
    "From my checking, hurry up.",
    "The minimum due.",
    "Today.",
]

D2_SCRIPT = [
    "Pay my Sapphire card from my checking account.",
    "Actually, let's pay my Freedom Unlimited instead.",
    "The statement balance.",
    "Today.",
]

HAPPY_SCRIPTS = {
    "J1": [
        "Pay the statement balance on my Chase Sapphire Preferred ending 9013 "
        "from my Chase Total Checking ending 5678 on the due date.",
        "Yes, go ahead.",
    ],
    "J2": [
        "I'd like to set up autopay on my Freedom Unlimited ending 0767.",
        "The statement balance please.",
        "From my Chase checking ending 5678.",
        "Yes, go ahead.",
    ],
    "J3": [
        "I want to change my autopay.",
        "Yes, I'd like to edit them.",
        "Make it the minimum payment due.",
        "Keep the same account.",
        "Yes, confirm the update.",
    ],
    "J4": [
        "Turn off autopay on my Sapphire card.",
        "Yes, turn it off.",
        "Yes, I'm sure.",
    ],
    "J5": [
        "I need to cancel a scheduled payment.",
        "Cancel it.",
        "Cancel it.",
    ],
}


# --------------------------------------------------------- defect flags ON


async def test_d1_on_trips_validated_submit():
    trace = await trace_for(D1_SCRIPT, d1_same_turn_after_validation=True)
    fails = AssertionEngine().check(trace).failures
    assert [f.id for f in fails] == [VALIDATED_SUBMIT]
    assert "same agent turn" in fails[0].message
    # The submit really happened — this is the D1 deviation, not a re-ask.
    assert registry.ADD_ONE_TIME_PAYMENT in trace.tool_call_names()


async def test_d2_on_trips_refetch_after_card_switch():
    trace = await trace_for(D2_SCRIPT, d2_stale_options_after_card_switch=True)
    ids = {f.id for f in AssertionEngine().check(trace).failures}
    assert REFETCH_AFTER_CARD_SWITCH in ids
    # The stale options also mean no fetch exists for the new card at all.
    assert AMOUNT_IN_OPTIONS in ids


async def test_d1_off_same_script_is_clean():
    trace = await trace_for(D1_SCRIPT)
    assert AssertionEngine().check(trace).failures == []


async def test_d2_off_same_script_is_clean():
    trace = await trace_for(D2_SCRIPT + ["Yes, go ahead."])
    report = AssertionEngine().check(trace)
    assert report.failures == []


# ------------------------------------------------------- all flags OFF


async def test_all_happy_paths_produce_zero_assertion_failures():
    for journey, script in HAPPY_SCRIPTS.items():
        trace = await trace_for(script)
        report = AssertionEngine().check(trace)
        assert report.failures == [], f"{journey}: {[f.to_dict() for f in report.failures]}"
        assert report.degraded == [], f"{journey}: {report.degraded}"


async def test_warn_acknowledge_revalidate_cycle_is_clean():
    """The J3 warn-but-allow path: warning validate → acknowledgment →
    re-validate(ready) → confirm → submit must satisfy the pairing (the
    warning poisons only until the re-validate)."""
    trace = await trace_for([
        "I want to change my autopay.",
        "Yes, I'd like to edit them.",
        "A fixed amount of $25.",
        "Keep the same account.",
        "Yes, continue with that amount.",
        "Yes, confirm the update.",
    ])
    assert registry.UPDATE_AUTOPAY in trace.tool_call_names()
    statuses = [
        c.result.get("status")
        for _, c in trace.iter_tool_calls()
        if c.name == registry.UPDATE_VALIDATE_AUTOPAY
    ]
    assert statuses == ["warning", "ready"]  # the cycle really ran
    assert AssertionEngine().check(trace).failures == []


# ------------------------------------- judge-only defects stay invisible


async def test_d3_false_success_is_invisible_to_the_engine():
    """D3: the submit result says FAILED but the reply claims success. The
    trace is mechanically consistent — only the judge (honest_failure) can
    catch the lie."""
    trace = await trace_for(
        [
            "Pay my Sapphire card from my checking account.",
            "$6,000",
            "Today.",
            "Yes, go ahead.",
        ],
        d3_false_success_on_failed_submit=True,
    )
    submit_results = [
        c.result for _, c in trace.iter_tool_calls() if c.name == registry.ADD_ONE_TIME_PAYMENT
    ]
    assert submit_results and submit_results[0]["success"] is False  # it DID fail
    assert AssertionEngine().check(trace).failures == []


async def test_m5_reference_case_passes_amount_in_options():
    """M5 (the calibration's judge-only reference): validating the QUESTIONED
    $210.45 instead of the declared $310.45 passes amount_in_options because
    both are legitimate fetched options — a comprehension bug only the judge
    layer can catch."""
    options = TraceToolCall(
        name=registry.ADD_OPTIONS_ONE_TIME_PAYMENT,
        arguments={"payeeId": "card-freedom-unlimited-0767"},
        result={"options": [
            {"optionId": "minimum_due", "amount": 35.0},
            {"optionId": "statement_balance", "amount": 310.45},
            {"optionId": "remaining_statement_balance", "amount": 210.45},
        ]},
    )
    validate = TraceToolCall(
        name=registry.ADD_VALIDATE_ONE_TIME_PAYMENT,
        arguments={"payeeId": "card-freedom-unlimited-0767", "amount": 210.45},
        result={"status": "ready", "formId": "form-0001"},
    )
    trace = Trace(conversation_id="m5")
    trace.turns = [
        TraceTurn(0, "user", "why does it say $210.45? I want to pay the statement balance"),
        TraceTurn(1, "agent", "shall I schedule $210.45?", tool_calls=[options, validate],
                  selected_card="Chase Freedom Unlimited (...0767)"),
    ]
    assert AssertionEngine().check(trace).failures == []
