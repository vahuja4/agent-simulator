"""J2 (set up AutoPay) unit tests — no LLM."""

from __future__ import annotations

import pytest

from agentsim import registry
from agentsim.adapters import MockPayCardAgent
from conftest import MockDriver

FREEDOM_UNLIMITED = "card-freedom-unlimited-0767"


@pytest.fixture
def driver() -> MockDriver:
    return MockDriver(MockPayCardAgent())


async def test_happy_path_tool_sequence_and_disclosure(driver: MockDriver):
    r1 = await driver.say("I'd like to set up autopay on my Freedom Unlimited ending 0767.")
    # §2 order: PayeeList → AddOptionsAutoPay (funding picker comes later).
    assert [t.name for t in r1.tool_calls] == [
        registry.PAYEE_LIST,
        registry.ADD_OPTIONS_AUTOPAY,
    ]
    assert r1.tool_calls[1].arguments == {"payeeId": FREEDOM_UNLIMITED}
    # The due-date disclosure comes before any amount is collected.
    assert "statement due date" in r1.content
    assert "June 25, 2026" in r1.content

    r2 = await driver.say("The statement balance please.")
    assert [t.name for t in r2.tool_calls] == [registry.FUNDING_ACCOUNT_PICKER]

    r3 = await driver.say("From my Chase checking ending 5678.")
    assert [t.name for t in r3.tool_calls] == [registry.ADD_VALIDATE_AUTOPAY]
    validate = r3.tool_calls[0]
    assert validate.arguments["paymentType"] == "statement_balance"
    assert validate.result["status"] == "ready"
    form_id = validate.result["formId"]
    assert validate.result["pendingAutoPay"]["formId"] == form_id
    assert "Shall I turn on AutoPay?" in r3.content

    r4 = await driver.say("Yes, go ahead.")
    assert [t.name for t in r4.tool_calls] == [registry.ADD_AUTOPAY]
    submit = r4.tool_calls[0]
    assert submit.arguments == {"formId": form_id}
    assert submit.result["success"] is True
    assert "confirmation email" in r4.content

    # The enrollment landed in the conversation's world state.
    ap = driver.state.autopay[FREEDOM_UNLIMITED]
    assert ap.active and ap.payment_type == "statement_balance"


async def test_fixed_amount_asks_for_exact_figure(driver: MockDriver):
    await driver.say("Set up autopay for my Freedom Flex.")
    r = await driver.say("A fixed amount.")
    assert "What fixed amount" in r.content
    r = await driver.say("$50")
    # Figure captured; flow moves on to the funding account.
    assert "Which account" in r.content
    r = await driver.say("From my checking account.")
    # Invariant 9: fixed amounts carry the minimum-due-can-change reminder.
    assert "minimum payment due can change" in r.content
    r = await driver.say("Yes please.")
    ap = driver.state.autopay["card-freedom-flex-4421"]
    assert ap.payment_type == "fixed" and ap.fixed_amount == 50.0


async def test_validate_stages_pending_and_submit_consumes_it(driver: MockDriver):
    await driver.say("I want autopay on my Freedom Flex, paying the minimum due.")
    await driver.say("Pay it from my Chase checking.")
    state = driver.state
    assert state.pending_autopay is not None
    assert state.awaiting_confirmation

    await driver.say("Yes.")
    assert state.pending_autopay is None
    assert not state.awaiting_confirmation


async def test_no_submit_without_confirmation(driver: MockDriver):
    await driver.say("I want autopay on my Freedom Flex, paying the minimum due.")
    await driver.say("From my Chase checking.")
    r = await driver.say("Hmm, what happens on weekends?")
    assert registry.ADD_AUTOPAY not in [t.name for t in r.tool_calls]
    assert driver.state.awaiting_confirmation  # still parked at the gate


async def test_decline_at_confirmation_leaves_autopay_off(driver: MockDriver):
    await driver.say("I want autopay on my Freedom Flex, paying the minimum due.")
    await driver.say("From my Chase checking.")
    r = await driver.say("No, never mind.")
    assert r.tool_calls == []
    assert "haven't turned on AutoPay" in r.content
    assert "card-freedom-flex-4421" not in driver.state.autopay


async def test_already_enrolled_card_is_not_re_enrolled(driver: MockDriver):
    r = await driver.say("Set up autopay on my Sapphire card.")
    assert "already has AutoPay" in r.content
    assert registry.ADD_OPTIONS_AUTOPAY not in [t.name for t in r.tool_calls]
