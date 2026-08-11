"""J4 (cancel AutoPay) unit tests — no LLM."""

from __future__ import annotations

import pytest

from agentsim import registry
from agentsim.adapters import MockPayCardAgent
from conftest import MockDriver

SAPPHIRE = "card-sapphire-9013"


@pytest.fixture
def driver() -> MockDriver:
    return MockDriver(MockPayCardAgent())


async def test_details_and_disclaimer_before_turn_off_offer(driver: MockDriver):
    r = await driver.say("Turn off autopay on my Sapphire card.")
    assert [t.name for t in r.tool_calls] == [
        registry.MODIFY_AUTOPAY_PAYEE_LIST,
        registry.GET_AUTOPAY_STATUS,
    ]
    assert "If your due date falls on a Saturday, we'll make the payment on the Friday before." in r.content
    assert "turn off automatic payments" in r.content
    # No token fetched yet — the customer hasn't accepted the offer.
    assert registry.CANCEL_AUTOPAY_OPTIONS not in [t.name for t in r.tool_calls]


async def test_happy_path_cancel_with_token_and_email_note(driver: MockDriver):
    await driver.say("Turn off autopay on my Sapphire card.")
    r2 = await driver.say("Yes, turn it off.")
    assert [t.name for t in r2.tool_calls] == [registry.CANCEL_AUTOPAY_OPTIONS]
    token = r2.tool_calls[0].result["token"]
    assert "Are you sure?" in r2.content
    assert "manually" in r2.content and "9013" in r2.content

    r3 = await driver.say("Yes, I'm sure.")
    assert [t.name for t in r3.tool_calls] == [registry.CANCEL_AUTOPAY]
    cancel = r3.tool_calls[0]
    assert cancel.arguments["token"] == token
    assert cancel.result["success"] is True
    assert "confirmation email" in r3.content
    assert driver.state.autopay[SAPPHIRE].active is False


async def test_no_at_are_you_sure_keeps_autopay_active(driver: MockDriver):
    await driver.say("Turn off autopay on my Sapphire card.")
    await driver.say("Yes, go ahead.")
    r = await driver.say("No, wait — keep it on.")
    assert r.tool_calls == []
    assert "stays active" in r.content
    assert driver.state.autopay[SAPPHIRE].active is True


async def test_declining_the_offer_keeps_autopay_active(driver: MockDriver):
    await driver.say("Cancel my autopay.")
    r = await driver.say("No, actually leave it on.")
    assert registry.CANCEL_AUTOPAY_OPTIONS not in [t.name for t in r.tool_calls]
    assert "stays active" in r.content
    assert driver.state.autopay[SAPPHIRE].active is True


async def test_scoping_non_autopay_card(driver: MockDriver):
    r = await driver.say("Turn off the autopay on my Freedom Unlimited.")
    assert "AutoPay isn't set up on your Chase Freedom Unlimited (...0767)" in r.content
    assert driver.state.autopay[SAPPHIRE].active is True
