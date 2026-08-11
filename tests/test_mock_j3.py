"""J3 (modify existing AutoPay) unit tests — no LLM."""

from __future__ import annotations

import pytest

from agentsim import registry
from agentsim.adapters import MockPayCardAgent
from conftest import MockDriver

SAPPHIRE = "card-sapphire-9013"


@pytest.fixture
def driver() -> MockDriver:
    return MockDriver(MockPayCardAgent())


async def test_scoping_only_autopay_active_cards_listed(driver: MockDriver):
    r = await driver.say("I want to change my autopay.")
    payee_list = next(t for t in r.tool_calls if t.name == registry.MODIFY_AUTOPAY_PAYEE_LIST)
    # Only the Sapphire has AutoPay — the Freedom cards must not appear.
    assert [p["payeeId"] for p in payee_list.result["payees"]] == [SAPPHIRE]


async def test_non_autopay_card_gets_plain_statement(driver: MockDriver):
    r = await driver.say("I want to change the autopay on my Freedom Flex.")
    assert "AutoPay isn't set up on your Chase Freedom Flex (...4421)" in r.content
    assert registry.GET_AUTOPAY_STATUS not in [t.name for t in r.tool_calls]


async def test_current_details_and_saturday_disclaimer_before_edit(driver: MockDriver):
    r = await driver.say("I want to change my autopay.")
    # Single active card auto-selected; details + disclaimer shown BEFORE any
    # edit options.
    assert [t.name for t in r.tool_calls] == [
        registry.MODIFY_AUTOPAY_PAYEE_LIST,
        registry.GET_AUTOPAY_STATUS,
    ]
    assert "statement balance" in r.content
    assert "If your due date falls on a Saturday, we'll make the payment on the Friday before." in r.content
    assert "June 20, 2026" in r.content  # the (Saturday) next payment date
    assert registry.UPDATE_AUTOPAY_OPTIONS not in [t.name for t in r.tool_calls]


async def test_happy_path_update_to_minimum_due(driver: MockDriver):
    await driver.say("I want to change my autopay.")
    r2 = await driver.say("Yes, I'd like to edit them.")
    assert [t.name for t in r2.tool_calls] == [registry.UPDATE_AUTOPAY_OPTIONS]
    # The date-can't-change rule is stated with the edit options.
    assert "can't be changed" in r2.content

    r3 = await driver.say("Make it the minimum payment due.")
    assert r3.tool_calls == []
    assert "keep coming from" in r3.content

    r4 = await driver.say("Keep the same account.")
    assert [t.name for t in r4.tool_calls] == [registry.UPDATE_VALIDATE_AUTOPAY]
    validate = r4.tool_calls[0]
    assert validate.result["status"] == "ready"
    assert validate.arguments["paymentType"] == "minimum_due"
    assert "Confirm AutoPay update?" in r4.content

    r5 = await driver.say("Yes, confirm the update.")
    assert [t.name for t in r5.tool_calls] == [registry.UPDATE_AUTOPAY]
    submit = r5.tool_calls[0]
    assert submit.result["success"] is True
    assert submit.arguments["token"] == validate.arguments["token"]

    ap = driver.state.autopay[SAPPHIRE]
    assert ap.payment_type == "minimum_due"


async def test_below_minimum_fixed_amount_warns_then_allows(driver: MockDriver):
    """The warn-but-allow rule: warning relayed, acknowledged, re-validated
    with the acknowledged flag, then the normal confirm gate."""
    await driver.say("I want to change my autopay.")
    await driver.say("Edit them please.")
    await driver.say("A fixed amount of $25.")  # below the $40.00 minimum due
    r = await driver.say("Keep the same account.")
    assert [t.name for t in r.tool_calls] == [registry.UPDATE_VALIDATE_AUTOPAY]
    warned = r.tool_calls[0]
    assert warned.result["status"] == "warning"
    assert warned.arguments["acknowledgedWarnings"] is False
    assert "below your current minimum payment due of $40.00" in r.content
    # Warned, not blocked — and nothing staged yet.
    assert driver.state.pending_autopay_update is None

    r = await driver.say("Yes, continue anyway.")
    assert [t.name for t in r.tool_calls] == [registry.UPDATE_VALIDATE_AUTOPAY]
    revalidate = r.tool_calls[0]
    assert revalidate.result["status"] == "ready"
    assert revalidate.arguments["acknowledgedWarnings"] is True
    assert "Confirm AutoPay update?" in r.content

    r = await driver.say("Confirm.")
    assert [t.name for t in r.tool_calls] == [registry.UPDATE_AUTOPAY]
    ap = driver.state.autopay[SAPPHIRE]
    assert ap.payment_type == "fixed" and ap.fixed_amount == 25.0


async def test_no_update_without_explicit_confirmation(driver: MockDriver):
    await driver.say("I want to change my autopay.")
    await driver.say("Edit them please.")
    await driver.say("Make it the statement balance.")
    await driver.say("Keep the same account.")
    r = await driver.say("What was the amount again?")
    assert registry.UPDATE_AUTOPAY not in [t.name for t in r.tool_calls]
    ap = driver.state.autopay[SAPPHIRE]
    assert ap.payment_type == "statement_balance"  # unchanged


async def test_decline_at_confirmation_keeps_current_setup(driver: MockDriver):
    await driver.say("I want to change my autopay.")
    await driver.say("Edit them please.")
    await driver.say("Make it the minimum payment due.")
    await driver.say("Keep the same account.")
    r = await driver.say("Actually no, leave it as is.")
    assert r.tool_calls == []
    assert "haven't changed" in r.content
    assert driver.state.autopay[SAPPHIRE].payment_type == "statement_balance"
