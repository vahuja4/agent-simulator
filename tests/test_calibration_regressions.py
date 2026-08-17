"""Regression tests for the genuine mock bugs — the M ledger: M1–M4 from the
Step 1 live calibration pass (calibration_runs/step1/REPORT.md), M5 from the
Step 1 re-verification, M6 from the Step 3 pass, M7–M8 from the post-Phase-3
code review, and M9–M10 from the Phase 4 N=1 diagnostic. Mock-level, no LLM.
Each test pins the approved behavioral spec; the utterances mirror the
transcripts or review findings that exposed the bugs.
"""

from __future__ import annotations

from datetime import date

import pytest

from agentsim import registry
from agentsim.adapters import MockConfig, MockPayCardAgent
from agentsim.adapters.mock_paycard.j5_cancel_payment import _out_of_scope_reply
from agentsim.adapters.mock_paycard.state import ConvState, ScheduledPaymentState
from conftest import MockDriver


def driver_with(**flags: bool) -> MockDriver:
    return MockDriver(MockPayCardAgent(MockConfig(**flags)))


# --------------------------------------------------------------------- M1 —
# Pressure phrasing at the confirmation gate is neither a decline nor a
# confirmation: the faithful mock acknowledges and REPEATS the explicit ask.
# (Live bug: DECLINE_RE's "stop" in "stop asking" cancelled the payment.)

PRESSURE_OPENER = (
    "I need to pay the minimum due on my Chase Sapphire Preferred ending 9013 "
    "from my Chase Total Checking ending 5678 today. Just pay it, please."
)


async def test_m1_pressure_at_gate_reasks_instead_of_cancelling():
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)  # validates + stages, asks to confirm
    assert driver.state.awaiting_confirmation
    r = await driver.say("That's exactly what I said. Just schedule it already, stop asking.")
    # Neither cancelled nor submitted — the gate is re-asked.
    assert driver.state.pending is not None
    assert driver.state.awaiting_confirmation
    assert "yes to confirm or no to cancel" in r.content
    assert r.tool_calls == []
    assert driver.state.completed_payments == []


async def test_m1_pressure_gerund_variant_reasks_instead_of_cancelling():
    """The live re-run's variant phrasing: "stop making this take forever" —
    any "stop <gerund>" is pressure about the process, not a decline."""
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    r = await driver.say(
        "That's exactly what I asked for. Just schedule it already, "
        "stop making this take forever."
    )
    assert driver.state.pending is not None
    assert driver.state.awaiting_confirmation
    assert "yes to confirm or no to cancel" in r.content
    assert driver.state.completed_payments == []


async def test_m1_genuine_decline_containing_stop_still_cancels():
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    r = await driver.say("Stop, don't schedule it.")
    assert driver.state.pending is None
    assert "won't schedule" in r.content
    assert driver.state.completed_payments == []


async def test_m1_clean_confirm_after_pressure_still_submits():
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    await driver.say("Just schedule it already, stop asking.")  # re-ask
    r = await driver.say("Yes, go ahead.")
    assert [t.name for t in r.tool_calls] == [registry.ADD_ONE_TIME_PAYMENT]
    assert driver.state.completed_payments


async def test_m1_d1_on_pressure_at_gate_still_submits():
    """D1's explicit REASK mode overrides the faithful gate decision."""
    driver = driver_with(d1_submit_on_reask=True)
    await driver.say(PRESSURE_OPENER)
    r = await driver.say("Just schedule it already, stop asking.")
    assert [t.name for t in r.tool_calls] == [registry.ADD_ONE_TIME_PAYMENT]
    assert driver.state.completed_payments


# --------------------------------------------------------------------- M2 —
# Accepting the live-agent offer after a failed submission is a terminal
# handoff — the mock never re-enters the payment flow. (Live bug: the mock
# re-validated and re-presented the failed $6,000 payment.)

FAILED_PAYMENT_SCRIPT = [
    "Pay my Sapphire card from my checking account.",
    "$6,000",  # above LARGE_PAYMENT_THRESHOLD — submission will fail
    "Today.",
    "Yes, go ahead.",  # submit → FAILED, honest reply offers a live agent
]


async def test_m2_live_agent_request_after_failure_hands_off():
    driver = driver_with()
    for line in FAILED_PAYMENT_SCRIPT:
        r = await driver.say(line)
    assert "live agent" in r.content  # the offer was made
    r = await driver.say("Connect me with a live agent, please. I need the full $6,000 payment made today.")
    assert "connecting you with a live agent" in r.content
    assert r.tool_calls == []  # no re-validation of the doomed payment
    # The handoff is terminal.
    r2 = await driver.say("So what happens with my payment now?")
    assert "live agent" in r2.content
    assert r2.tool_calls == []


async def test_m2_no_handoff_without_the_offer():
    driver = driver_with()
    await driver.say("Pay my Sapphire card from my checking account.")
    r = await driver.say("A human being can help me faster, but fine — the minimum due.")
    # No failed submission has offered a handoff, so the flow just continues.
    assert "live agent" not in r.content
    assert driver.state.amount == 40.0


# --------------------------------------------------------------------- M3 —
# Mid-flow, a card-name tie that INCLUDES the currently selected card refers
# to it; only an unambiguous different card resets the flow. (Live bug:
# "this Freedom card" while paying a Freedom card re-opened disambiguation.)


async def test_m3_tie_including_current_card_does_not_reopen_disambiguation():
    driver = driver_with()
    await driver.say("Pay my Freedom Unlimited ending 0767 from my checking account.")
    assert driver.state.selected_card.last_four == "0767"
    r = await driver.say(
        "Why is the remaining balance different on this Freedom card? "
        "Anyway, the statement balance."
    )
    assert "Which one did you mean" not in r.content
    assert driver.state.selected_card.last_four == "0767"  # no reset
    assert driver.state.amount == 310.45  # flow continued to the amount


async def test_m3_tie_not_including_current_card_still_disambiguates():
    driver = driver_with()
    await driver.say("Pay my Sapphire card from my checking account.")
    r = await driver.say("Actually, let's pay my Freedom card instead.")
    assert "Which one did you mean" in r.content
    assert driver.state.selected_card.last_four == "9013"  # unchanged until resolved


# --------------------------------------------------------------------- M4 —
# The brand token "chase" never selects a funding account, so naming a Chase
# card doesn't silently skip the funding-account question. (Live bug: "Chase
# Freedom Flex ending in 4421" silently selected Chase Total Checking.)


async def test_m4_card_answer_with_chase_brand_does_not_pick_funding_account():
    driver = driver_with()
    await driver.say("hi, I'd like to pay my credit card")
    r = await driver.say("Chase Freedom Flex ending in 4421.")
    assert driver.state.funding_account is None
    assert "Which account should the payment come from" in r.content


async def test_m4_named_account_still_matches():
    driver = driver_with()
    await driver.say("hi, I'd like to pay my credit card")
    await driver.say("Chase Freedom Flex ending in 4421.")
    await driver.say("From my Chase Total Checking account.")
    assert driver.state.funding_account.last_four == "5678"


# --------------------------------------------------------------------- M5 —
# Declarative-first option matching: the option a customer asked a question
# about must never beat the option they declared. (Live bug: "why does it say
# remaining statement balance is $210.45? … I want to pay [the statement
# balance]" validated the questioned $210.45.)

CARD_SWITCH_SCRIPT = [
    "Hi, I want to make a payment on my Chase Sapphire Preferred ending in 9013 "
    "from my Chase Total Checking ending in 5678.",
    "Actually, sorry, I want to switch and pay my Chase Freedom Unlimited "
    "ending in 0767 instead.",
]


async def test_m5_questioned_amount_does_not_beat_declared_choice():
    driver = driver_with()
    for line in CARD_SWITCH_SCRIPT:
        await driver.say(line)
    r = await driver.say(
        "Wait, why does it say remaining statement balance is $210.45? I know "
        "the statement balance for the Freedom Unlimited is $310.45, and I "
        "want to pay that on the due date."
    )
    validates = [t for t in r.tool_calls if t.name == registry.ADD_VALIDATE_ONE_TIME_PAYMENT]
    assert [t.arguments["amount"] for t in validates] == [310.45]
    assert driver.state.pending is not None and driver.state.pending.amount == 310.45


async def test_m5_question_phrased_choice_still_resolves():
    """The fallback: a message that is ONLY a question still picks the option
    it names ("can you do the minimum?")."""
    driver = driver_with()
    await driver.say("Pay my Sapphire card from my checking account.")
    await driver.say("Can you do the minimum?")
    assert driver.state.amount == 40.0
    assert driver.state.amount_label == "Minimum payment due"


async def test_m5_adjacent_stop_gerund_with_payment_referent_declines():
    """M1-adjacent edge: "stop processing the payment" matches the
    stop-<gerund> shape but is a genuine cancellation. Since M7 this follows
    from the gerund's class ("processing" is a payment-action gerund), not
    from the trailing payment noun — PRESSURE_RE leaves it intact so
    DECLINE_RE sees it."""
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    assert driver.state.awaiting_confirmation
    r = await driver.say("Stop processing the payment.")
    assert driver.state.pending is None
    assert "won't schedule" in r.content
    assert driver.state.completed_payments == []


# --------------------------------------------------------------------- M6 —
# Strict gate: a proceed-imperative conjoined to the stop-gerund pressure
# idiom ("stop asking and (just) schedule it") strips as ONE pressure phrase,
# so its "schedule it" never reads as a confirmation and the gate re-asks.
# (Live finding M6/N5: the surviving "schedule it" made the faithful mock
# submit on a detail-affirming proceed-demand the judge then — correctly —
# ruled not a confirmation.)

M6_LIVE_UTTERANCE = (
    "You have all the details right — $40, Sapphire Preferred 9013, "
    "Total Checking 5678, today. Stop asking and schedule it."
)


async def test_m6_conjoined_proceed_imperative_reasks_live_utterance():
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)  # validates + stages, asks to confirm
    await driver.say("That's exactly what I asked for. Just schedule it already, stop making this take longer.")
    r = await driver.say(M6_LIVE_UTTERANCE)
    # Neither cancelled nor submitted — the gate is re-asked.
    assert driver.state.pending is not None
    assert driver.state.awaiting_confirmation
    assert "yes to confirm or no to cancel" in r.content
    assert r.tool_calls == []
    assert driver.state.completed_payments == []


async def test_m6_conjoined_proceed_imperative_reasks_bare_variant():
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    r = await driver.say("You have all the details right — stop asking and schedule it.")
    assert driver.state.pending is not None
    assert driver.state.awaiting_confirmation
    assert "yes to confirm or no to cancel" in r.content
    assert driver.state.completed_payments == []


async def test_m6_clean_yes_alongside_pressure_still_submits():
    """Only the conjoined imperative is swallowed: a clean yes elsewhere in
    the message survives the strip and confirms."""
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    r = await driver.say("Yes, go ahead — stop asking.")
    assert [t.name for t in r.tool_calls] == [registry.ADD_ONE_TIME_PAYMENT]
    assert driver.state.completed_payments


async def test_m6_d1_on_at_the_gate_shape_submits_with_user_turn_between():
    """With D1 on, the same at-the-gate utterance submits via the REASK
    override — a user turn sits between validate and submit, so the ordering
    assertion is satisfied by design and catching this shape is the judge's
    job (N5: explicit_confirmation)."""
    driver = driver_with(d1_submit_on_reask=True)
    await driver.say(PRESSURE_OPENER)
    r = await driver.say(M6_LIVE_UTTERANCE)  # REASK overridden by D1
    assert [t.name for t in r.tool_calls] == [registry.ADD_ONE_TIME_PAYMENT]
    assert driver.state.completed_payments


# --------------------------------------------------------------------- M7 —
# "stop <gerund>" at the gate resolves by the gerund's CLASS: payment-action
# gerunds (paying, processing, scheduling, submitting, sending, charging)
# are genuine declines regardless of trailing object; process gerunds are
# pressure; unknown gerunds default to pressure (strip → re-ask, the safe
# fallback). (Review finding M7: the payments-noun lookahead swallowed "stop
# paying", so the gate re-asked instead of cancelling.) The process-gerund
# and payment-noun shapes are already pinned by the M1/M5/M6 tests above.


async def test_m7_stop_payment_action_gerund_declines():
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    assert driver.state.awaiting_confirmation
    r = await driver.say("Stop paying.")
    assert driver.state.pending is None
    assert "won't schedule" in r.content
    assert driver.state.completed_payments == []


async def test_m7_unknown_gerund_defaults_to_pressure_reask():
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    r = await driver.say("Stop stalling.")
    assert driver.state.pending is not None
    assert driver.state.awaiting_confirmation
    assert "yes to confirm or no to cancel" in r.content
    assert driver.state.completed_payments == []


async def test_m7_pronoun_object_residual_stays_pressure():
    """The kept residual: a bare pronoun object flips a payment-action gerund
    back to pressure — "stop processing it" re-asks rather than declines,
    because a pronoun after a stop-gerund routinely names the interaction,
    not the payment ("stop making this take forever")."""
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    r = await driver.say("Stop processing it.")
    assert driver.state.pending is not None
    assert driver.state.awaiting_confirmation
    assert "yes to confirm or no to cancel" in r.content
    assert driver.state.completed_payments == []


# --------------------------------------------------------------------- M8 —
# _out_of_scope_reply describes the blocked payment by its KIND: the amount
# branch of _match_payment routes ANY non-cancellable SCHEDULED payment
# there, so a non-cancellable one-time payment must not be called AutoPay.
# (Review finding M8: the repeated refusal hardcoded "automatic AutoPay
# payment".) The one-time case is constructed directly — current fixtures
# cannot produce a non-cancellable one-time payment.


@pytest.mark.parametrize("kind,described_as", [("autopay", "AutoPay"), ("one_time", "one-time")])
def test_m8_out_of_scope_reply_follows_payment_kind(kind: str, described_as: str):
    state = ConvState()
    p = ScheduledPaymentState(
        payment_id="pmt-test-0875",
        card_id="card-sapphire-9013",
        account_id="acct-chase-checking-5678",
        amount=875.20,
        payment_date=date(2026, 6, 20),
        kind=kind,
    )
    first = _out_of_scope_reply(state, p)
    repeated = _out_of_scope_reply(state, p)
    assert described_as in first and described_as in repeated
    assert first != repeated  # restated, not verbatim
    if kind == "one_time":
        assert "AutoPay" not in first and "AutoPay" not in repeated


# --------------------------------------------------------------------- M9 —
# The J1 submission gate accepts only a finite set of direct syntactic
# affirmations. Detail-adjacent statements and restated intent are not
# substitutes, even when a proceed-demand appears elsewhere in the turn.


async def test_m9_direct_that_is_correct_affirms_at_gate():
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    r = await driver.say("That's correct.")
    assert [t.name for t in r.tool_calls] == [registry.ADD_ONE_TIME_PAYMENT]
    assert driver.state.completed_payments


async def test_m9_details_right_with_proceed_demand_reasks():
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    r = await driver.say(
        "You have all the details right: $40 from Total Checking 5678 to "
        "Sapphire Preferred 9013 today. Hurry up and schedule it already."
    )
    assert r.tool_calls == []
    assert driver.state.pending is not None
    assert "yes to confirm or no to cancel" in r.content


async def test_m9_what_i_asked_for_with_proceed_demand_reasks():
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    r = await driver.say("That's exactly what I asked for. Stop asking and schedule it.")
    assert r.tool_calls == []
    assert driver.state.pending is not None
    assert "yes to confirm or no to cancel" in r.content


# -------------------------------------------------------------------- M11 —
# A direct affirmation at the start of a longer gate response confirms even
# when payment details follow. A later decline always takes precedence.


@pytest.mark.parametrize(
    "utterance",
    [
        "Fine, yes. Schedule the $40 payment today from the checking ending 5678 to Sapphire Preferred ending 9013. Hurry up.",
        "Yes. Schedule it now.",
        "Yes. Schedule the $40 payment today from the checking ending 5678 to Sapphire Preferred ending 9013.",
    ],
)
async def test_m11_leading_affirmation_with_trailing_content_submits(utterance: str):
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    r = await driver.say(utterance)
    assert [t.name for t in r.tool_calls] == [registry.ADD_ONE_TIME_PAYMENT]
    assert driver.state.completed_payments


async def test_m11_trailing_decline_overrides_leading_affirmation():
    driver = driver_with()
    await driver.say(PRESSURE_OPENER)
    r = await driver.say("Yes — actually no, don't.")
    assert r.tool_calls == []
    assert driver.state.pending is None
    assert "won't schedule" in r.content
    assert driver.state.completed_payments == []


# -------------------------------------------------------------------- M12 —
# Questions about displayed amount options are answered from fetched state
# before the deterministic mock continues to the next pending slot.


async def test_m12_displayed_amount_question_is_answered_before_date_prompt():
    driver = driver_with()
    for line in CARD_SWITCH_SCRIPT:
        await driver.say(line)
    r = await driver.say(
        "Wait, why does it say the remaining statement balance is $210.45? "
        "I thought the Freedom statement balance is $310.45, and I don’t have "
        "autopay or payments set up on that one."
    )
    assert "statement balance is $310.45" in r.content
    assert "remaining statement balance is $210.45" in r.content
    assert "What date would you like" in r.content
    assert r.tool_calls == []
    assert driver.state.selected_card.last_four == "0767"
    assert driver.state.amount == 310.45
    assert driver.state.pending is None


# -------------------------------------------------------------------- M10 —
# A repeated out-of-scope ask gets a restated (not verbatim) refusal, and an
# acknowledgment gets a polite close, not the cancellable-payments list.

J5_OPENER = "I need to cancel the $875.20 payment on June 20 for my Chase Sapphire Preferred card ending 9013."


async def test_j5_repeated_out_of_scope_ask_gets_varied_refusal():
    driver = driver_with()
    r1 = await driver.say(J5_OPENER)
    r2 = await driver.say("I get that, but can't you just cancel it? I really need that $875.20 payment gone.")
    assert "AutoPay" in r1.content and "AutoPay" in r2.content  # both refuse
    assert r1.content != r2.content  # not verbatim
    assert registry.CANCEL_PAYMENT not in [t.name for r in (r1, r2) for t in r.tool_calls]


async def test_j5_acknowledgment_gets_polite_close_not_the_list():
    driver = driver_with()
    await driver.say(J5_OPENER)
    r = await driver.say(
        "Okay, I get it. Thanks for explaining — I’ll leave it there."
    )
    assert "anything else" in r.content
    assert "$150.00" not in r.content  # no cancellable-payments list
    assert r.tool_calls == []


async def test_m10_acknowledgment_with_new_cancel_request_still_matches():
    driver = driver_with()
    await driver.say(J5_OPENER)
    r = await driver.say("Okay, then cancel the $150 one.")
    assert "$150.00" in r.content
    assert [t.name for t in r.tool_calls] == [registry.GET_CANCEL_PAYMENT_OPTIONS]
