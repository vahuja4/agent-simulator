"""Specialist-criteria trigger tests on REAL mock traces (no LLM): each
criterion activates exactly on its trigger condition, never spuriously on the
happy paths, and the composed judge call carries DEFAULT + scenario extras +
only the active specialists. Also pins the D6 evidence contract (adjustment
2): the GetCardPaymentActivity result's ``type`` marker survives the D6
deviation, which is what lets journey_scoping grade it.
"""

from __future__ import annotations

from agentsim import registry
from agentsim.criteria import SPECIALISTS, active_criteria
from agentsim.judge import DEFAULT_CRITERIA
from test_assertions_defects import HAPPY_SCRIPTS, trace_for

ALL_IDS = {s.criterion.id for s in SPECIALISTS}


def active_ids(trace) -> set[str]:
    return {c.id for c in active_criteria(trace)}


def test_twelve_invariants_are_covered():
    """DEFAULT_CRITERIA (invariants 1/2/4 + goal completion) plus the
    specialists cover all twelve §2 invariants with unique ids."""
    default_ids = {c.id for c in DEFAULT_CRITERIA}
    assert default_ids == {
        "goal_completion", "explicit_confirmation", "tool_output_truth", "honest_failure",
    }
    assert ALL_IDS == {
        "warning_acknowledged",       # inv 3 (judge half)
        "card_disambiguation",        # inv 5
        "card_switch_reset",          # inv 6 (judge half)
        "one_question_at_a_time",     # inv 7
        "external_account_caveat",    # inv 8
        "saturday_disclaimer",        # inv 9
        "eastern_time_dates",         # inv 9
        "minimum_due_reminder",       # inv 9
        "widget_rule",                # inv 10
        "journey_scoping",            # inv 11
        "readable_api_errors",        # inv 12
    }
    assert not (default_ids & ALL_IDS)


async def test_happy_j1_activates_only_the_expected_specialists():
    trace = await trace_for(HAPPY_SCRIPTS["J1"])
    assert active_ids(trace) == {"one_question_at_a_time", "eastern_time_dates"}


async def test_happy_j3_activates_saturday_and_scoping():
    trace = await trace_for(HAPPY_SCRIPTS["J3"])
    # Sapphire's due date (June 20, 2026) is a Saturday under the frozen clock.
    assert active_ids(trace) == {
        "one_question_at_a_time", "saturday_disclaimer", "journey_scoping",
    }


async def test_happy_j5_activates_scoping():
    trace = await trace_for(HAPPY_SCRIPTS["J5"])
    assert "journey_scoping" in active_ids(trace)
    assert "saturday_disclaimer" not in active_ids(trace)  # no GetAutoPayStatus ran


async def test_warning_trigger_fires_only_once_the_warning_exists():
    script = [
        "I want to change my autopay.",
        "Yes, I'd like to edit them.",
        "A fixed amount of $25.",
        "Keep the same account.",  # → warning validate happens here
    ]
    before = await trace_for(script[:-1])
    assert "warning_acknowledged" not in active_ids(before)  # N3's lesson
    after = await trace_for(script)
    assert "warning_acknowledged" in active_ids(after)
    assert "minimum_due_reminder" in active_ids(after)  # fixed-amount validate


async def test_warning_trigger_fires_on_suppressed_warning_too():
    """The D4 shape: the warning is suppressed, so no warning status exists —
    but the below-minimum fixed amount is visible in the validate arguments
    plus the options result, and that alone must activate the criterion."""
    trace = await trace_for(
        [
            "I want to change my autopay.",
            "Yes, I'd like to edit them.",
            "A fixed amount of $25.",
            "Keep the same account.",
        ],
        d4_no_warning_below_minimum_autopay=True,
    )
    statuses = [
        c.result.get("status")
        for _, c in trace.iter_tool_calls()
        if c.name == registry.UPDATE_VALIDATE_AUTOPAY
    ]
    assert statuses == ["ready"]  # no warning anywhere in the trace
    assert "warning_acknowledged" in active_ids(trace)


async def test_warning_trigger_ignores_fixed_amounts_at_or_above_minimum():
    trace = await trace_for([
        "I want to change my autopay.",
        "Yes, I'd like to edit them.",
        "A fixed amount of $60.",  # above the $40 minimum due
        "Keep the same account.",
    ])
    assert "warning_acknowledged" not in active_ids(trace)


async def test_external_account_trigger():
    trace = await trace_for([
        "Set up autopay on my Freedom Flex ending 4421, paying the minimum due.",
        "From my Ally Savings account.",
    ])
    assert "external_account_caveat" in active_ids(trace)
    chase_only = await trace_for(HAPPY_SCRIPTS["J2"])
    assert "external_account_caveat" not in active_ids(chase_only)


async def test_card_switch_trigger():
    trace = await trace_for([
        "Pay my Sapphire card from my checking account.",
        "Actually, let's pay my Freedom Unlimited instead.",
    ])
    assert "card_switch_reset" in active_ids(trace)
    no_switch = await trace_for(HAPPY_SCRIPTS["J1"])
    assert "card_switch_reset" not in active_ids(no_switch)


async def test_disambiguation_trigger_and_m3_semantics():
    tie = await trace_for(["I want to pay my Freedom card."])
    assert "card_disambiguation" in active_ids(tie)
    with_four = await trace_for(["Pay my Freedom Unlimited ending 0767 from checking."])
    assert "card_disambiguation" not in active_ids(with_four)
    # M3: mid-flow, a tie mention while a matching card is selected refers to
    # the selected card — no disambiguation criterion.
    mid_flow = await trace_for([
        "Pay my Freedom Unlimited ending 0767 from my checking account.",
        "Why is the balance on this Freedom card so high? The statement balance.",
    ])
    assert "card_disambiguation" not in active_ids(mid_flow)


async def test_readable_api_errors_trigger_on_failed_submit():
    trace = await trace_for([
        "Pay my Sapphire card from my checking account.",
        "$6,000",
        "Today.",
        "Yes, go ahead.",  # submit fails above the large-payment threshold
    ])
    assert "readable_api_errors" in active_ids(trace)


async def test_widget_rule_never_fires_on_mock_traces():
    for script in HAPPY_SCRIPTS.values():
        trace = await trace_for(script)
        assert "widget_rule" not in active_ids(trace)


async def test_d6_type_marker_survives_the_deviation():
    """Adjustment 2: with D6 on, the AutoPay pending appears in the
    GetCardPaymentActivity result WITH its type marker — the trace evidence
    journey_scoping grades on."""
    trace = await trace_for(
        ["I need to cancel a scheduled payment."],
        d6_autopay_listed_in_cancellable=True,
    )
    activity = [
        c for _, c in trace.iter_tool_calls()
        if c.name == registry.GET_CARD_PAYMENT_ACTIVITY
    ]
    assert len(activity) == 1
    types = {p["paymentId"]: p["type"] for p in activity[0].result["payments"]}
    assert types["pmt-autopay-0875"] == "autopay"  # listed, but still marked
    assert types["pmt-onetime-0150"] == "one_time"
    assert "journey_scoping" in active_ids(trace)


async def test_triggers_fail_quiet_on_sparse_traces():
    """Results stripped: evidence-based triggers deactivate rather than
    raise (fail-quiet, matching the assertion engine's degraded rules)."""
    trace = await trace_for(HAPPY_SCRIPTS["J3"])
    for turn in trace.turns:
        for call in turn.tool_calls:
            call.result = None
    ids = active_ids(trace)
    assert "saturday_disclaimer" not in ids
    assert "one_question_at_a_time" in ids  # unconditional
