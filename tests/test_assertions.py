"""Unit tests for the deterministic assertion engine over hand-built Trace
objects (including deserialized-from-JSON ones): pairing edges, poisoning,
amount/options membership, card-switch re-fetch, must_not_call, and the
degraded behavior on traces that lack results or selected_card. Pure Python,
no LLM, no mock.
"""

from __future__ import annotations

from agentsim import registry
from agentsim.assertions import (
    AMOUNT_IN_OPTIONS,
    MUST_NOT_CALL,
    REFETCH_AFTER_CARD_SWITCH,
    VALIDATED_SUBMIT,
    AssertionEngine,
)
from agentsim.trace import Trace, TraceToolCall, TraceTurn


def make_trace(*turns: TraceTurn) -> Trace:
    trace = Trace(conversation_id="t1")
    for i, t in enumerate(turns):
        t.index = i
        trace.turns.append(t)
    return trace


def user(text: str, card: str | None = None) -> TraceTurn:
    return TraceTurn(index=0, speaker="user", text=text, selected_card=card)


def agent(
    text: str = "...", calls: list[TraceToolCall] | None = None, card: str | None = None
) -> TraceTurn:
    return TraceTurn(
        index=0, speaker="agent", text=text, tool_calls=calls or [], selected_card=card
    )


SAPPHIRE = "Chase Sapphire Preferred (...9013)"
FREEDOM = "Chase Freedom Unlimited (...0767)"

OPTIONS_RESULT = {
    "options": [
        {"optionId": "minimum_due", "label": "Minimum payment due", "amount": 40.0},
        {"optionId": "statement_balance", "label": "Statement balance", "amount": 875.2},
        {"optionId": "other", "label": "Other amount", "amount": None},
    ],
    "dueDate": "2026-06-20",
}


def options_call(payee: str = "card-sapphire-9013") -> TraceToolCall:
    return TraceToolCall(
        name=registry.ADD_OPTIONS_ONE_TIME_PAYMENT,
        arguments={"payeeId": payee},
        result=OPTIONS_RESULT,
    )


def validate_call(
    amount: float = 875.2,
    form_id: str = "form-0001",
    payee: str = "card-sapphire-9013",
    status: str = "ready",
) -> TraceToolCall:
    return TraceToolCall(
        name=registry.ADD_VALIDATE_ONE_TIME_PAYMENT,
        arguments={"payeeId": payee, "amount": amount, "paymentDate": "2026-06-20"},
        result={"status": status, "formId": form_id},
    )


def submit_call(form_id: str = "form-0001") -> TraceToolCall:
    return TraceToolCall(
        name=registry.ADD_ONE_TIME_PAYMENT,
        arguments={"formId": form_id},
        result={"status": "SCHEDULED", "success": True},
    )


def happy_j1_trace() -> Trace:
    return make_trace(
        user("pay my sapphire, statement balance, on the due date"),
        agent("here's what I have — shall I schedule it?",
              [options_call(), validate_call()], SAPPHIRE),
        user("yes", SAPPHIRE),
        agent("done!", [submit_call()], SAPPHIRE),
    )


def failure_ids(trace: Trace, **kwargs) -> list[str]:
    return [f.id for f in AssertionEngine(**kwargs).check(trace).failures]


# ------------------------------------------------------- validated_submit


def test_happy_pairing_passes():
    report = AssertionEngine().check(happy_j1_trace())
    assert report.failures == []
    assert report.degraded == []


def test_submit_without_any_validate_fails():
    trace = make_trace(user("pay"), agent("done", [submit_call()], SAPPHIRE))
    fails = AssertionEngine().check(trace).failures
    assert [f.id for f in fails] == [VALIDATED_SUBMIT]
    assert "no prior" in fails[0].message


def test_same_turn_validate_and_submit_fails():
    # The D1-on shape: validate + submit in one agent turn, no user turn between.
    trace = make_trace(
        user("just do it"),
        agent("done", [options_call(), validate_call(), submit_call()], SAPPHIRE),
    )
    fails = AssertionEngine().check(trace).failures
    assert [f.id for f in fails] == [VALIDATED_SUBMIT]
    assert "same agent turn" in fails[0].message
    assert fails[0].data["validate_turn"] == fails[0].data["submit_turn"]


def test_no_user_turn_between_agent_turns_fails():
    trace = make_trace(
        user("pay it"),
        agent("validating", [options_call(), validate_call()], SAPPHIRE),
        agent("done", [submit_call()], SAPPHIRE),
    )
    assert failure_ids(trace) == [VALIDATED_SUBMIT]


def test_form_id_mismatch_fails():
    trace = make_trace(
        user("pay it"),
        agent("ok", [options_call(), validate_call(form_id="form-0001")], SAPPHIRE),
        user("yes"),
        agent("done", [submit_call(form_id="form-9999")], SAPPHIRE),
    )
    fails = AssertionEngine().check(trace).failures
    assert [f.id for f in fails] == [VALIDATED_SUBMIT]
    assert fails[0].data["submit_id"] == "form-9999"


def test_warning_status_poisons_pair():
    trace = make_trace(
        user("pay it"),
        agent("warning...", [options_call(), validate_call(status="warning")], SAPPHIRE),
        user("yes do it"),
        agent("done", [submit_call()], SAPPHIRE),
    )
    fails = AssertionEngine().check(trace).failures
    assert [f.id for f in fails] == [VALIDATED_SUBMIT]
    assert "poisoned" in fails[0].message


def test_revalidation_after_warning_clears_the_pair():
    trace = make_trace(
        user("pay it"),
        agent("warning...", [options_call(), validate_call(status="warning", form_id="form-0001")], SAPPHIRE),
        user("continue anyway"),
        agent("ok — confirm?", [validate_call(status="ready", form_id="form-0002")], SAPPHIRE),
        user("yes"),
        agent("done", [submit_call(form_id="form-0002")], SAPPHIRE),
    )
    assert AssertionEngine().check(trace).failures == []


def test_all_five_pairings_are_checked():
    """Each submit tool with no counterpart trips validated_submit."""
    for submit_tool in registry.SUBMIT_TOOLS:
        trace = make_trace(
            user("go"),
            agent("done", [TraceToolCall(name=submit_tool, arguments={})]),
        )
        assert VALIDATED_SUBMIT in failure_ids(trace), submit_tool


def test_cancel_autopay_token_pairing_passes():
    token_fetch = TraceToolCall(
        name=registry.CANCEL_AUTOPAY_OPTIONS,
        arguments={"payeeId": "card-sapphire-9013", "repeatingModelId": "rpm-1"},
        result={"token": "captoken-1", "repeatingModelId": "rpm-1"},
    )
    cancel = TraceToolCall(
        name=registry.CANCEL_AUTOPAY,
        arguments={"repeatingModelId": "rpm-1", "token": "captoken-1"},
        result={"status": "CANCELED", "success": True},
    )
    trace = make_trace(
        user("turn off autopay"),
        agent("are you sure?", [token_fetch], SAPPHIRE),
        user("yes"),
        agent("done", [cancel], SAPPHIRE),
    )
    assert AssertionEngine().check(trace).failures == []


# ------------------------------------------------------- amount_in_options


def test_amount_from_options_passes():
    assert AssertionEngine().check(happy_j1_trace()).failures == []


def test_amount_not_in_options_and_never_stated_fails():
    trace = make_trace(
        user("pay my sapphire"),
        agent("ok?", [options_call(), validate_call(amount=123.45)], SAPPHIRE),
    )
    fails = AssertionEngine().check(trace).failures
    assert [f.id for f in fails] == [AMOUNT_IN_OPTIONS]
    assert fails[0].data["amount"] == 123.45


def test_customer_stated_other_amount_passes():
    trace = make_trace(
        user("pay $6,000 on my sapphire from checking today"),
        agent("ok?", [options_call(), validate_call(amount=6000.0)], SAPPHIRE),
    )
    assert AssertionEngine().check(trace).failures == []


def test_bare_number_message_counts_as_stated_amount():
    trace = make_trace(
        user("pay my sapphire"),
        agent("how much?", [options_call()], SAPPHIRE),
        user("6000"),
        agent("ok?", [validate_call(amount=6000.0)], SAPPHIRE),
    )
    assert AssertionEngine().check(trace).failures == []


def test_last_four_never_reads_as_stated_amount():
    trace = make_trace(
        user("pay my card ending in 0767"),
        agent("ok?", [options_call(), validate_call(amount=767.0)], SAPPHIRE),
    )
    assert failure_ids(trace) == [AMOUNT_IN_OPTIONS]


def test_validate_with_no_options_fetch_for_that_card_fails():
    trace = make_trace(
        user("pay my freedom card"),
        agent(
            "ok?",
            [options_call(payee="card-sapphire-9013"),
             validate_call(payee="card-freedom-unlimited-0767", amount=875.2)],
            FREEDOM,
        ),
    )
    fails = [f for f in AssertionEngine().check(trace).failures if f.id == AMOUNT_IN_OPTIONS]
    assert len(fails) == 1
    assert "no prior" in fails[0].message


def test_autopay_payment_type_must_come_from_options():
    autopay_options = TraceToolCall(
        name=registry.ADD_OPTIONS_AUTOPAY,
        arguments={"payeeId": "card-freedom-unlimited-0767"},
        result={"options": [
            {"optionId": "minimum_due", "amount": 35.0},
            {"optionId": "statement_balance", "amount": 310.45},
            {"optionId": "fixed", "amount": None},
        ]},
    )
    def validate(payment_type: str) -> TraceToolCall:
        return TraceToolCall(
            name=registry.ADD_VALIDATE_AUTOPAY,
            arguments={"payeeId": "card-freedom-unlimited-0767", "paymentType": payment_type},
            result={"status": "ready", "formId": "form-0001"},
        )

    good = make_trace(user("autopay"), agent("ok?", [autopay_options, validate("fixed")], FREEDOM))
    assert AssertionEngine().check(good).failures == []
    bad = make_trace(user("autopay"), agent("ok?", [autopay_options, validate("weekly")], FREEDOM))
    assert failure_ids(bad) == [AMOUNT_IN_OPTIONS]


# ---------------------------------------------- refetch_after_card_switch


def test_validate_after_switch_without_refetch_fails():
    # The D2-on shape: options fetched for the first card only.
    trace = make_trace(
        user("pay my sapphire"),
        agent("how much?", [options_call(payee="card-sapphire-9013")], SAPPHIRE),
        user("actually my freedom card. statement balance."),
        agent("ok?", [validate_call(payee="card-freedom-unlimited-0767", amount=875.2)], FREEDOM),
    )
    ids = failure_ids(trace)
    assert REFETCH_AFTER_CARD_SWITCH in ids


def test_refetch_after_switch_passes():
    trace = make_trace(
        user("pay my sapphire"),
        agent("how much?", [options_call(payee="card-sapphire-9013")], SAPPHIRE),
        user("actually my freedom card"),
        agent("how much?", [options_call(payee="card-freedom-unlimited-0767")], FREEDOM),
        user("statement balance on the due date"),
        agent(
            "ok?",
            [TraceToolCall(
                name=registry.ADD_VALIDATE_ONE_TIME_PAYMENT,
                arguments={"payeeId": "card-freedom-unlimited-0767", "amount": 875.2},
                result={"status": "ready", "formId": "form-0001"},
            )],
            FREEDOM,
        ),
    )
    assert AssertionEngine().check(trace).failures == []


def test_first_card_selection_is_not_a_switch():
    assert AssertionEngine().check(happy_j1_trace()).failures == []


# ------------------------------------------------------------ must_not_call


def test_must_not_call_flags_the_forbidden_tool():
    trace = make_trace(
        user("cancel my payment"),
        agent("done", [TraceToolCall(name=registry.CANCEL_PAYMENT, arguments={})]),
    )
    fails = [
        f
        for f in AssertionEngine(must_not_call=[registry.CANCEL_PAYMENT]).check(trace).failures
        if f.id == MUST_NOT_CALL
    ]
    assert len(fails) == 1
    assert fails[0].data["tool"] == registry.CANCEL_PAYMENT


def test_must_not_call_ignores_other_tools():
    report = AssertionEngine(must_not_call=[registry.CANCEL_PAYMENT]).check(happy_j1_trace())
    assert report.failures == []


# ----------------------------------------------------------- degraded mode


def strip_results(trace: Trace) -> Trace:
    for t in trace.turns:
        for c in t.tool_calls:
            c.result = None
    return trace


def test_missing_results_degrade_but_ordering_still_checked():
    # A results-free version of the happy path: no failures, but the status
    # and options-content checks are reported as degraded, not silently gone.
    report = AssertionEngine().check(strip_results(happy_j1_trace()))
    assert report.failures == []
    checks = {d["check"] for d in report.degraded}
    assert VALIDATED_SUBMIT in checks
    assert AMOUNT_IN_OPTIONS in checks


def test_missing_results_still_catch_same_turn_submit():
    trace = strip_results(
        make_trace(
            user("just do it"),
            agent("done", [options_call(), validate_call(), submit_call()], SAPPHIRE),
        )
    )
    fails = [f for f in AssertionEngine().check(trace).failures if f.id == VALIDATED_SUBMIT]
    assert len(fails) == 1
    assert "same agent turn" in fails[0].message


def test_no_selected_card_data_degrades_switch_check():
    trace = happy_j1_trace()
    for t in trace.turns:
        t.selected_card = None
    report = AssertionEngine().check(trace)
    assert report.failures == []
    assert any(d["check"] == REFETCH_AFTER_CARD_SWITCH for d in report.degraded)


def test_engine_never_raises_on_sparse_calls():
    trace = make_trace(
        user("hello"),
        agent("done", [
            TraceToolCall(name=registry.ADD_ONE_TIME_PAYMENT, arguments={}, result=None),
            TraceToolCall(name=registry.ADD_VALIDATE_ONE_TIME_PAYMENT, arguments={}, result=None),
        ]),
    )
    AssertionEngine().check(trace)  # must not raise


# ---------------------------------------------------------- serialization


def test_report_identical_on_json_round_tripped_trace():
    trace = make_trace(
        user("just do it"),
        agent("done", [options_call(), validate_call(amount=123.45), submit_call()], SAPPHIRE),
    )
    direct = AssertionEngine().check(trace)
    revived = AssertionEngine().check(Trace.from_json(trace.to_json()))
    assert [f.to_dict() for f in direct.failures] == [f.to_dict() for f in revived.failures]
    assert direct.degraded == revived.degraded
    assert {f.id for f in direct.failures} == {VALIDATED_SUBMIT, AMOUNT_IN_OPTIONS}
