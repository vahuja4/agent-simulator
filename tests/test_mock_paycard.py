"""Direct unit tests of the mock's J1 flow — no LLM anywhere near these."""

from __future__ import annotations

import pytest

from agentsim import registry
from agentsim.adapters import MockPayCardAgent
from agentsim.types import AgentInput, AgentResponse, Message


class Driver:
    """Feeds scripted user lines to the mock, maintaining history."""

    def __init__(self, agent: MockPayCardAgent, conversation_id: str = "c1") -> None:
        self.agent = agent
        self.conversation_id = conversation_id
        self.history: list[Message] = []

    async def say(self, text: str) -> AgentResponse:
        self.history.append(Message("user", text))
        resp = await self.agent.call(AgentInput(self.conversation_id, list(self.history)))
        self.history.append(Message("assistant", resp.content))
        return resp


@pytest.fixture
def driver() -> Driver:
    return Driver(MockPayCardAgent())


async def test_happy_path_tool_sequence(driver: Driver):
    r1 = await driver.say("Hi, I'd like to pay my Sapphire card, the one ending in 9013.")
    assert [t.name for t in r1.tool_calls] == [registry.PAYEE_LIST, registry.FUNDING_ACCOUNT_PICKER]
    assert r1.selected_card == "Chase Sapphire Preferred (...9013)"

    r2 = await driver.say("Use my Chase checking ending 5678.")
    assert [t.name for t in r2.tool_calls] == [registry.ADD_OPTIONS_ONE_TIME_PAYMENT]
    assert r2.tool_calls[0].arguments == {"payeeId": "card-sapphire-9013"}
    # Options presented from the tool result, due date mentioned.
    assert "$875.20" in r2.content
    assert "June 20, 2026" in r2.content

    r3 = await driver.say("Pay the statement balance please.")
    assert r3.tool_calls == []
    assert "Eastern Time" in r3.content  # date question carries the ET rule

    r4 = await driver.say("Schedule it for June 20.")
    assert [t.name for t in r4.tool_calls] == [registry.ADD_VALIDATE_ONE_TIME_PAYMENT]
    validate = r4.tool_calls[0]
    assert validate.arguments["amount"] == 875.20
    assert validate.arguments["paymentDate"] == "2026-06-20"
    assert validate.result["status"] == "ready"
    form_id = validate.result["formId"]
    assert validate.result["pendingPayment"]["formId"] == form_id
    assert "Shall I schedule it?" in r4.content

    r5 = await driver.say("Yes, confirm it.")
    assert [t.name for t in r5.tool_calls] == [registry.ADD_ONE_TIME_PAYMENT]
    submit = r5.tool_calls[0]
    assert submit.arguments == {"formId": form_id}
    assert submit.result["success"] is True
    assert submit.result["confirmationNumber"] in r5.content


async def test_validate_stages_pending_and_submit_consumes_it(driver: Driver):
    await driver.say("I want to pay my Freedom Flex.")
    await driver.say("From my checking account.")
    await driver.say("The minimum payment.")
    await driver.say("On the due date.")
    state = driver.agent._states["c1"]
    assert state.pending is not None
    assert state.awaiting_confirmation

    await driver.say("Yes please.")
    assert state.pending is None
    assert not state.awaiting_confirmation
    assert len(state.completed_payments) == 1
    assert state.completed_payments[0]["payment"]["amount"] == 25.00


async def test_m002_post_validation_amount_correction_revalidates_and_submits(driver: Driver):
    await driver.say("Pay my Sapphire card.")
    await driver.say("From my checking account.")
    await driver.say("Pay the statement balance.")
    validated = await driver.say("On the due date.")
    original_form_id = validated.tool_calls[0].result["formId"]

    corrected = await driver.say("Actually, make that $40 instead.")
    assert [t.name for t in corrected.tool_calls] == [registry.ADD_VALIDATE_ONE_TIME_PAYMENT]
    revalidate = corrected.tool_calls[0]
    assert revalidate.arguments["amount"] == 40.00
    assert revalidate.result["pendingPayment"]["amount"] == 40.00
    assert revalidate.result["formId"] != original_form_id
    assert "$40.00" in corrected.content
    assert "$875.20" not in corrected.content

    confirmed = await driver.say("Yes.")
    assert [t.name for t in confirmed.tool_calls] == [registry.ADD_ONE_TIME_PAYMENT]
    submit = confirmed.tool_calls[0]
    assert submit.arguments == {"formId": revalidate.result["formId"]}
    assert submit.result["payment"]["amount"] == 40.00
    assert "$40.00" in confirmed.content


async def test_post_validation_date_correction_revalidates_and_submits(driver: Driver):
    await driver.say("Pay my Sapphire card.")
    await driver.say("From my checking account.")
    await driver.say("Pay the minimum due.")
    validated = await driver.say("On the due date.")
    original_form_id = validated.tool_calls[0].result["formId"]

    corrected = await driver.say("Actually, make that June 18 instead.")
    assert [t.name for t in corrected.tool_calls] == [registry.ADD_VALIDATE_ONE_TIME_PAYMENT]
    revalidate = corrected.tool_calls[0]
    assert revalidate.arguments["paymentDate"] == "2026-06-18"
    assert revalidate.result["formId"] != original_form_id
    assert "June 18, 2026" in corrected.content

    confirmed = await driver.say("Yes.")
    assert confirmed.tool_calls[0].arguments == {"formId": revalidate.result["formId"]}
    assert confirmed.tool_calls[0].result["payment"]["paymentDate"] == "2026-06-18"


async def test_no_submit_without_confirmation_step(driver: Driver):
    """Pressure before the flow is even complete never reaches the submit tool."""
    r = await driver.say("Just pay my Sapphire card right now, skip the questions.")
    assert registry.ADD_ONE_TIME_PAYMENT not in [t.name for t in r.tool_calls]
    r = await driver.say("Stop asking and submit it already!")
    assert registry.ADD_ONE_TIME_PAYMENT not in [t.name for t in r.tool_calls]
    assert driver.agent._states["c1"].completed_payments == []


async def test_decline_at_confirmation_cancels(driver: Driver):
    await driver.say("Pay my Sapphire card.")
    await driver.say("From checking.")
    await driver.say("Minimum due.")
    await driver.say("Today.")
    r = await driver.say("No, don't do that.")
    assert r.tool_calls == []
    state = driver.agent._states["c1"]
    assert state.pending is None
    assert state.completed_payments == []
    assert "won't schedule" in r.content


async def test_card_switch_refetches_options(driver: Driver):
    await driver.say("Pay my Sapphire card from my checking account.")
    r = await driver.say("Actually, let's pay my Freedom Unlimited instead.")
    options_calls = [t for t in r.tool_calls if t.name == registry.ADD_OPTIONS_ONE_TIME_PAYMENT]
    assert len(options_calls) == 1
    assert options_calls[0].arguments == {"payeeId": "card-freedom-unlimited-0767"}
    assert r.selected_card == "Chase Freedom Unlimited (...0767)"
    # New card's own figures, not the Sapphire's.
    assert "$310.45" in r.content


async def test_ambiguous_freedom_asks_for_last_four(driver: Driver):
    r = await driver.say("I want to pay my Freedom card.")
    assert "0767" in r.content and "4421" in r.content
    assert r.selected_card is None
    r2 = await driver.say("The one ending in 4421.")
    assert r2.selected_card == "Chase Freedom Flex (...4421)"


async def test_external_account_gets_balance_caveat(driver: Driver):
    await driver.say("Pay my Sapphire card.")
    r = await driver.say("From my Ally savings account.")
    assert "can't see its balance" in r.content


async def test_conversations_are_isolated():
    agent = MockPayCardAgent()
    d1 = Driver(agent, "c1")
    d2 = Driver(agent, "c2")
    await d1.say("Pay my Sapphire card.")
    r = await d2.say("Pay my Freedom Flex card.")
    assert r.selected_card == "Chase Freedom Flex (...4421)"
    assert agent._states["c1"].selected_card.last_four == "9013"
