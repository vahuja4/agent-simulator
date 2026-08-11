"""J5 (cancel a scheduled one-time payment) unit tests — no LLM."""

from __future__ import annotations

import pytest

from agentsim import registry
from agentsim.adapters import MockPayCardAgent
from conftest import MockDriver


@pytest.fixture
def driver() -> MockDriver:
    return MockDriver(MockPayCardAgent())


async def test_activity_excludes_autopay_pending(driver: MockDriver):
    r = await driver.say("I need to cancel a scheduled payment.")
    activity = next(t for t in r.tool_calls if t.name == registry.GET_CARD_PAYMENT_ACTIVITY)
    payments = activity.result["payments"]
    # Journey scoping: only the $150 one-time payment — never the $875.20
    # AutoPay pending payment.
    assert [p["paymentId"] for p in payments] == ["pmt-onetime-0150"]
    assert all(p["type"] == "one_time" for p in payments)


async def test_happy_path_summary_gate_and_email_note(driver: MockDriver):
    r1 = await driver.say("I need to cancel a scheduled payment.")
    # With exactly one cancellable payment the mock proceeds to the options +
    # explicit gate in the same turn.
    assert [t.name for t in r1.tool_calls] == [
        registry.GET_CARD_PAYMENT_ACTIVITY,
        registry.GET_CANCEL_PAYMENT_OPTIONS,
    ]
    options = r1.tool_calls[1]
    # The design's summary string, verbatim shape.
    assert options.result["summary"] == "$150.00 to Chase Sapphire Preferred on June 20"
    assert '"Cancel it"' in r1.content and '"Don\'t cancel it"' in r1.content

    r2 = await driver.say("Cancel it.")
    assert [t.name for t in r2.tool_calls] == [registry.CANCEL_PAYMENT]
    cancel = r2.tool_calls[0]
    assert cancel.arguments == {"paymentId": "pmt-onetime-0150"}
    assert cancel.result["status"] == "Canceled"
    assert "confirmation email" in r2.content
    payment = next(p for p in driver.state.scheduled_payments if p.payment_id == "pmt-onetime-0150")
    assert payment.status == "CANCELED"


async def test_dont_cancel_keeps_it_scheduled(driver: MockDriver):
    await driver.say("I want to cancel my scheduled payment.")
    r = await driver.say("Don't cancel it.")
    assert r.tool_calls == []
    assert "stays scheduled" in r.content
    payment = next(p for p in driver.state.scheduled_payments if p.payment_id == "pmt-onetime-0150")
    assert payment.status == "SCHEDULED"


async def test_autopay_pending_reference_gets_scoping_statement(driver: MockDriver):
    # Opener avoids "autopay" wording (which would route to J4) — references
    # the AutoPay pending payment by amount instead.
    r = await driver.say("I want to cancel the $875.20 payment scheduled for June 20.")
    assert "automatic AutoPay payment" in r.content
    assert "can't cancel it here" in r.content
    assert registry.GET_CANCEL_PAYMENT_OPTIONS not in [t.name for t in r.tool_calls]
    assert registry.CANCEL_PAYMENT not in [t.name for t in r.tool_calls]


async def test_amount_reference_selects_the_right_payment(driver: MockDriver):
    r = await driver.say("Please cancel my $150 payment.")
    options = next(t for t in r.tool_calls if t.name == registry.GET_CANCEL_PAYMENT_OPTIONS)
    assert options.arguments == {"paymentId": "pmt-onetime-0150"}
