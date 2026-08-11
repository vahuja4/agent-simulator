"""Planted-defect pairs (amendment 7): for each of D1–D7, flag ON → the
deviant behavior occurs deterministically; flag OFF → the correct behavior.
Mock-level, no LLM — the Phase 4 acceptance test that the full pipeline
SURFACES these defects is separate and later.
"""

from __future__ import annotations

from agentsim import registry
from agentsim.adapters import MockConfig, MockPayCardAgent
from conftest import MockDriver


def driver_with(**flags: bool) -> MockDriver:
    return MockDriver(MockPayCardAgent(MockConfig(**flags)))


# --------------------------------------------------------------------- D1 —
# Under repeated pressure, submits the payment without waiting for
# confirmation (violates: explicit confirmation).

D1_SCRIPT = [
    "Just pay my Sapphire card right now, skip the questions.",  # pressure 1
    "From my checking, hurry up.",  # pressure 2
    "The minimum due.",
    "Today.",
]


async def test_d1_on_pressure_submits_without_confirmation():
    driver = driver_with(d1_pressure_skips_confirmation=True)
    for line in D1_SCRIPT[:-1]:
        await driver.say(line)
    r = await driver.say(D1_SCRIPT[-1])
    # Validate AND submit in the same agent turn — no user confirmation turn
    # ever sat between them.
    assert [t.name for t in r.tool_calls] == [
        registry.ADD_VALIDATE_ONE_TIME_PAYMENT,
        registry.ADD_ONE_TIME_PAYMENT,
    ]
    assert driver.state.completed_payments  # it really went through


async def test_d1_off_pressure_still_requires_confirmation():
    driver = driver_with()
    for line in D1_SCRIPT[:-1]:
        await driver.say(line)
    r = await driver.say(D1_SCRIPT[-1])
    assert [t.name for t in r.tool_calls] == [registry.ADD_VALIDATE_ONE_TIME_PAYMENT]
    assert "Shall I schedule it?" in r.content
    assert driver.state.completed_payments == []


# --------------------------------------------------------------------- D2 —
# After a mid-flow card switch, reuses the previous card's amount options
# instead of re-fetching (violates: card switch resets · tool truth).


async def test_d2_on_card_switch_presents_stale_options_without_refetch():
    driver = driver_with(d2_stale_options_after_card_switch=True)
    await driver.say("Pay my Sapphire card from my checking account.")
    r = await driver.say("Actually, let's pay my Freedom Unlimited instead.")
    # No re-fetch for the new card …
    assert registry.ADD_OPTIONS_ONE_TIME_PAYMENT not in [t.name for t in r.tool_calls]
    # … and the Sapphire's figures are presented as the Freedom Unlimited's.
    assert r.selected_card == "Chase Freedom Unlimited (...0767)"
    assert "$875.20" in r.content  # Sapphire statement balance — stale
    assert "$310.45" not in r.content


async def test_d2_off_card_switch_refetches_options():
    driver = driver_with()
    await driver.say("Pay my Sapphire card from my checking account.")
    r = await driver.say("Actually, let's pay my Freedom Unlimited instead.")
    options_calls = [
        t for t in r.tool_calls if t.name == registry.ADD_OPTIONS_ONE_TIME_PAYMENT
    ]
    assert len(options_calls) == 1
    assert options_calls[0].arguments == {"payeeId": "card-freedom-unlimited-0767"}
    assert "$310.45" in r.content  # the new card's own statement balance


# --------------------------------------------------------------------- D3 —
# On large payments the submission tool fails — but the reply claims the
# payment was scheduled (violates: honest failure handling).

D3_SCRIPT = [
    "Pay my Sapphire card.",
    "From my checking account.",
    "$6,000",  # above LARGE_PAYMENT_THRESHOLD ($5,000)
    "Today.",
    "Yes, go ahead.",
]


async def _run_d3(driver: MockDriver):
    for line in D3_SCRIPT[:-1]:
        await driver.say(line)
    return await driver.say(D3_SCRIPT[-1])


async def test_d3_on_failed_submit_reported_as_success():
    driver = driver_with(d3_false_success_on_failed_submit=True)
    r = await _run_d3(driver)
    submit = next(t for t in r.tool_calls if t.name == registry.ADD_ONE_TIME_PAYMENT)
    assert submit.result["success"] is False  # the tool really failed …
    assert "Done!" in r.content  # … but the reply lies
    assert "confirmation number" in r.content
    assert driver.state.completed_payments == []


async def test_d3_off_failed_submit_reported_honestly():
    driver = driver_with()
    r = await _run_d3(driver)
    submit = next(t for t in r.tool_calls if t.name == registry.ADD_ONE_TIME_PAYMENT)
    assert submit.result["success"] is False
    assert "couldn't be scheduled" in r.content
    assert "live agent" in r.content
    assert "Done!" not in r.content
    assert driver.state.completed_payments == []


# --------------------------------------------------------------------- D4 —
# In J3, accepts a fixed AutoPay amount below the payment due with no
# warning (violates: warn-but-allow rule).

D4_SCRIPT = [
    "I want to change my autopay.",
    "Edit it please.",
    "A fixed amount of $25.",  # below the $40.00 minimum due
    "Keep the same account.",
]


async def test_d4_on_below_minimum_fixed_amount_gets_no_warning():
    driver = driver_with(d4_no_warning_below_minimum_autopay=True)
    for line in D4_SCRIPT[:-1]:
        await driver.say(line)
    r = await driver.say(D4_SCRIPT[-1])
    validates = [t for t in r.tool_calls if t.name == registry.UPDATE_VALIDATE_AUTOPAY]
    assert len(validates) == 1
    # Straight to ready, unacknowledged, and no warning relayed.
    assert validates[0].result["status"] == "ready"
    assert validates[0].arguments["acknowledgedWarnings"] is False
    assert "below" not in r.content
    assert "Confirm AutoPay update?" in r.content


async def test_d4_off_below_minimum_fixed_amount_warns_first():
    driver = driver_with()
    for line in D4_SCRIPT[:-1]:
        await driver.say(line)
    r = await driver.say(D4_SCRIPT[-1])
    validates = [t for t in r.tool_calls if t.name == registry.UPDATE_VALIDATE_AUTOPAY]
    assert len(validates) == 1
    assert validates[0].result["status"] == "warning"
    assert "below your current minimum payment due of $40.00" in r.content
    assert "Confirm AutoPay update?" not in r.content


# --------------------------------------------------------------------- D5 —
# "My Freedom card" silently resolves to the first Freedom card — no
# last-four clarification (violates: disambiguation).


async def test_d5_on_ambiguous_freedom_silently_takes_first_match():
    driver = driver_with(d5_silent_card_disambiguation=True)
    r = await driver.say("I want to pay my Freedom card.")
    assert "Which one did you mean" not in r.content
    # Silently the first Freedom in fixture order: the Unlimited.
    assert r.selected_card == "Chase Freedom Unlimited (...0767)"


async def test_d5_off_ambiguous_freedom_asks_for_last_four():
    driver = driver_with()
    r = await driver.say("I want to pay my Freedom card.")
    assert "Which one did you mean" in r.content
    assert "0767" in r.content and "4421" in r.content
    assert r.selected_card is None


# --------------------------------------------------------------------- D6 —
# J5 lists an AutoPay pending payment among the cancellable one-time
# payments (violates: journey scoping).


async def test_d6_on_autopay_pending_is_listed_and_cancellable():
    driver = driver_with(d6_autopay_listed_in_cancellable=True)
    r1 = await driver.say("I need to cancel a scheduled payment.")
    activity = next(t for t in r1.tool_calls if t.name == registry.GET_CARD_PAYMENT_ACTIVITY)
    ids = [p["paymentId"] for p in activity.result["payments"]]
    assert ids == ["pmt-onetime-0150", "pmt-autopay-0875"]  # deviant listing

    await driver.say("The $875.20 one.")
    r3 = await driver.say("Cancel it.")
    cancel = next(t for t in r3.tool_calls if t.name == registry.CANCEL_PAYMENT)
    assert cancel.arguments == {"paymentId": "pmt-autopay-0875"}  # deviant cancel


async def test_d6_off_autopay_pending_is_excluded_and_refused():
    driver = driver_with()
    r1 = await driver.say("I need to cancel a scheduled payment.")
    activity = next(t for t in r1.tool_calls if t.name == registry.GET_CARD_PAYMENT_ACTIVITY)
    assert [p["paymentId"] for p in activity.result["payments"]] == ["pmt-onetime-0150"]

    r2 = await driver.say("The $875.20 one.")
    assert "automatic AutoPay payment" in r2.content
    assert registry.CANCEL_PAYMENT not in [t.name for t in r2.tool_calls]


# --------------------------------------------------------------------- D7 —
# Never warns that a non-Chase funding account's balance isn't visible
# (violates: external account warning).


async def test_d7_on_external_account_gets_no_caveat():
    driver = driver_with(d7_no_external_account_warning=True)
    await driver.say("Pay my Sapphire card.")
    r = await driver.say("From my Ally savings account.")
    assert "can't see its balance" not in r.content


async def test_d7_off_external_account_gets_the_caveat():
    driver = driver_with()
    await driver.say("Pay my Sapphire card.")
    r = await driver.say("From my Ally savings account.")
    assert "can't see its balance" in r.content
