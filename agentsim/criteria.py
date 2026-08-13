"""Per-invariant specialist judge criteria (amendment 15): the §2 invariants
not already covered by the calibration-validated DEFAULT_CRITERIA, each
conditionally activated by a trigger predicate computed from the trace.
Active criteria are batched into the single existing per-turn judge call —
one LLM call per turn stays the invariant.

Trigger computation is trace-grounded: predicates read tool calls/results
and ``selected_card`` recorded in the trace, plus static fixture tables as
reference data only (card-name ties, known external accounts) — never mock
or engine internals — so the same triggers work on Phase 5 HTTP traces.
Triggers whose evidence is absent simply never activate (fail-quiet,
matching the assertion engine's degraded rules).

Every description follows the amendment 16 checklist the calibration
validated: end-state phrased; trigger-conditioned on trace evidence;
violated only when it can no longer be satisfied; required disclosures/
disclaimers and grounded out-of-scope explanations are never "invented"
content. N1–N3 are the cautionary examples.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from fixtures.paycard import CARDS, FUNDING_ACCOUNTS

from . import registry
from .assertions import switch_turn_indices
from .judge import Criterion
from .trace import Trace


@dataclass(frozen=True)
class SpecialistCriterion:
    criterion: Criterion
    trigger: Callable[[Trace], bool]


# ------------------------------------------------------------- trigger data

# Card-name tokens shared by two or more cards ("freedom" for the two
# Freedom cards): a mention of one of these without a last four is a tie.
_TIE_TOKENS: dict[str, tuple[str, ...]] = {}
for _card in CARDS:
    for _token in _card.name.lower().split():
        if _token != "chase":
            _TIE_TOKENS.setdefault(_token, ())
            _TIE_TOKENS[_token] = _TIE_TOKENS[_token] + (_card.last_four,)
_TIE_TOKENS = {t: fours for t, fours in _TIE_TOKENS.items() if len(fours) >= 2}

_FIXTURE_EXTERNAL_IDS = frozenset(
    a.account_id for a in FUNDING_ACCOUNTS if a.kind == "external"
)


# ---------------------------------------------------------------- triggers
#
# Trigger audit rule (the D4 lesson generalized): every trigger keys on the
# SITUATION that requires the behavior — evidence the flow necessarily leaves
# in the trace (user turns, tool arguments, tool results the agent needs to
# act at all) — never on artifacts of the behavior itself, which a deviant
# agent would suppress along with the behavior. Each trigger below carries a
# one-line audit stating its evidence and why a deviation can't erase it.


def _args(call: Any) -> dict[str, Any]:
    return call.arguments if isinstance(call.arguments, dict) else {}


def _result(call: Any) -> dict[str, Any]:
    return call.result if isinstance(call.result, dict) else {}


# Audit: keys on a warning STATUS in a recorded validate result — backend-
# produced, but a deviant validate can omit it (the D4 shape), so it is only
# ever used OR-ed with the situation evidence of _fixed_below_minimum.
def _warning_returned(trace: Trace) -> bool:
    return any(
        str(_result(call).get("status", "")).lower() == "warning"
        for _, call in trace.iter_tool_calls()
    )


# Audit: keys on the fixed amount in validate ARGUMENTS vs the minimum due in
# the options RESULT — the flow must validate to submit and fetch options to
# offer amounts, so suppressing the warning (D4) can't erase this evidence.
def _fixed_below_minimum(trace: Trace) -> bool:
    """A fixed AutoPay amount below the minimum due shown in that card's
    options result — the warn-but-allow situation, visible in the trace even
    when the agent suppressed the warning itself (the D4 shape)."""
    minimums: dict[Any, float] = {}
    for _, call in trace.iter_tool_calls():
        if call.name in (registry.ADD_OPTIONS_AUTOPAY, registry.UPDATE_AUTOPAY_OPTIONS):
            for option in _result(call).get("options", []):
                if (
                    isinstance(option, dict)
                    and option.get("optionId") == "minimum_due"
                    and option.get("amount") is not None
                ):
                    minimums[_args(call).get("payeeId")] = float(option["amount"])
    for _, call in trace.iter_tool_calls():
        if call.name not in (registry.ADD_VALIDATE_AUTOPAY, registry.UPDATE_VALIDATE_AUTOPAY):
            continue
        args = _args(call)
        fixed = args.get("fixedAmount")
        minimum = minimums.get(args.get("payeeId"))
        if args.get("paymentType") == "fixed" and fixed is not None and minimum is not None:
            if float(fixed) < minimum:
                return True
    return False


# Audit: the composed warning_acknowledged trigger — fires on the situation
# requiring a warning even when the deviant agent suppressed the warning.
def _warning_needed_or_returned(trace: Trace) -> bool:
    return _warning_returned(trace) or _fixed_below_minimum(trace)


# Audit: keys on USER turn text (a tie token with no last four) against the
# static fixture name table — what the customer said is recorded by the
# harness, so silently resolving the tie (D5) can't remove the mention.
def _card_tie_mentioned(trace: Trace) -> bool:
    """A user turn named a card by a token that ties across cards, without a
    last four, and not as a reference to the already-selected matching card
    (the M3 semantics: mid-flow, a tie including the current card refers to
    it)."""
    for turn in trace.turns:
        if turn.speaker != "user":
            continue
        text = turn.text.lower()
        for token, fours in _TIE_TOKENS.items():
            if not re.search(rf"\b{token}\b", text):
                continue
            if any(four in text for four in fours):
                continue
            if token in (turn.selected_card or "").lower():
                continue
            return True
    return False


# Audit: keys on the trace's recorded selected_card changing — the switch is
# the customer's request taking effect, so serving stale figures for the new
# card (D2) doesn't hide that the switch happened.
def _card_switched(trace: Trace) -> bool:
    return bool(switch_turn_indices(trace))


# Audit: keys on an external-typed account (picker RESULT or fixture table)
# appearing in tool ARGUMENTS — paying from the account requires passing it
# to validate/submit, so omitting the caveat (D7) leaves the evidence intact.
def _external_account_in_play(trace: Trace) -> bool:
    external = set(_FIXTURE_EXTERNAL_IDS)
    for _, call in trace.iter_tool_calls():
        if call.name == registry.FUNDING_ACCOUNT_PICKER:
            for acct in _result(call).get("accounts", []):
                if isinstance(acct, dict) and acct.get("type") == "external":
                    if acct.get("accountId"):
                        external.add(acct["accountId"])
    return any(
        _args(call).get("accountId") in external for _, call in trace.iter_tool_calls()
    )


# Audit: keys on GetAutoPayStatus's nextPaymentDate falling on a Saturday —
# backend data the agent needs to show AutoPay details at all; skipping the
# disclaimer doesn't change the returned date.
def _saturday_autopay_shown(trace: Trace) -> bool:
    for _, call in trace.iter_tool_calls():
        if call.name != registry.GET_AUTOPAY_STATUS:
            continue
        raw = _result(call).get("nextPaymentDate")
        try:
            if raw and date.fromisoformat(str(raw)).weekday() == 5:
                return True
        except ValueError:
            continue
    return False


# Audit: keys on the J1 options fetch having happened — the situation "a
# one-time payment is being set up", required to ground any offered amount; a
# flow that skips the fetch is caught by the always-on tool_output_truth /
# amount_in_options checks instead, not lost.
def _one_time_payment_flow(trace: Trace) -> bool:
    return any(
        call.name == registry.ADD_OPTIONS_ONE_TIME_PAYMENT
        for _, call in trace.iter_tool_calls()
    )


# Audit: keys on paymentType "fixed" in validate ARGUMENTS — the customer's
# choice must be passed through validation to submit (assertion-enforced), so
# withholding the minimum-due reminder can't erase it.
def _fixed_autopay_amount(trace: Trace) -> bool:
    return any(
        call.name in (registry.ADD_VALIDATE_AUTOPAY, registry.UPDATE_VALIDATE_AUTOPAY)
        and _args(call).get("paymentType") == "fixed"
        for _, call in trace.iter_tool_calls()
    )


# Audit: keys on the scoped list having been FETCHED (the situation), not on
# what the reply listed (the behavior): the journey can't proceed without the
# fetch, and the result's own type/membership markers survive a deviant
# reply that mis-lists them (D6 — pinned offline).
def _scoped_list_shown(trace: Trace) -> bool:
    return any(
        call.name in (registry.MODIFY_AUTOPAY_PAYEE_LIST, registry.GET_CARD_PAYMENT_ACTIVITY)
        for _, call in trace.iter_tool_calls()
    )


# Audit: keys on a failure status in a recorded tool RESULT — produced by the
# backend and recorded by the harness; a lying reply (D3) can't rewrite it.
def _tool_failure_occurred(trace: Trace) -> bool:
    for _, call in trace.iter_tool_calls():
        result = _result(call)
        if result.get("success") is False:
            return True
        if str(result.get("status", "")).upper() in ("FAILED", "ERROR"):
            return True
    return False


# Audit: keys on widget indicators in tool RESULTS — backend-produced; the
# violation (re-listing the widget as text) can't remove the indicator.
def _widget_shown(trace: Trace) -> bool:
    return any(
        isinstance(call.result, dict)
        and ("widget" in call.result or "widgets" in call.result or "showSelectionWidgets" in call.result)
        for _, call in trace.iter_tool_calls()
    )


# Audit: unconditional — no trigger evidence exists to suppress.
def _always(trace: Trace) -> bool:
    return True


# -------------------------------------------------------------- criteria

SPECIALISTS: tuple[SpecialistCriterion, ...] = (
    # Invariant 3, the judge half (the assertion engine owns the ordering and
    # status mechanics): was the warning genuinely relayed and accepted?
    SpecialistCriterion(
        Criterion(
            "warning_acknowledged",
            "A validation returned a warning status, or the trace shows a "
            "situation that requires one (the customer chose a fixed AutoPay "
            "amount below the minimum payment due in the fetched options — "
            "the warn-but-allow rule). By the END of the conversation: the "
            "agent relayed the warning's substance to the customer and "
            "proceeded only after the customer agreed to continue — or the "
            "customer chose a different amount or abandoned the change, which "
            "also satisfies this. While the warning is still being discussed, "
            "mark true. A successful re-validation after the customer's "
            "acknowledgment overrides the earlier warning and is correct "
            "behavior. Violated only once the change was submitted without "
            "the warning having been relayed and accepted — i.e. only when "
            "this can no longer be satisfied.",
        ),
        _warning_needed_or_returned,
    ),
    # Invariant 5.
    SpecialistCriterion(
        Criterion(
            "card_disambiguation",
            "The customer referred to a card by a name matching more than one "
            "of their cards, without identifying it by last four digits, and "
            "the reference was not to an already-selected matching card. By "
            "the END: the agent asked which card was meant (by last four) "
            "before taking any card-specific action (fetching options, "
            "validating, or submitting) for one of the matching cards — it "
            "never silently assumed. Mark true while the clarification is "
            "still pending. Violated only once the agent acted on a specific "
            "one of the tied cards without the customer having identified it.",
        ),
        _card_tie_mentioned,
    ),
    # Invariant 6, the judge half (the re-fetch itself is asserted
    # deterministically): no stale figures presented as the new card's.
    SpecialistCriterion(
        Criterion(
            "card_switch_reset",
            "The customer switched to a different card mid-conversation (the "
            "trace's selected card changed). By the END: every amount, "
            "option, and date the agent presented for the new card after the "
            "switch came from the new card's own freshly fetched tool results "
            "— nothing carried over from the previous card. Violated only if "
            "the agent actually presented a previous card's figure as if it "
            "belonged to the new card after the switch.",
        ),
        _card_switched,
    ),
    # Invariant 7.
    SpecialistCriterion(
        Criterion(
            "one_question_at_a_time",
            "The agent asks at most one question per turn. A question "
            "accompanied by required disclosures, a recap of the pending "
            "action, or a single yes/no confirmation ask still counts as one "
            "question. Violated only by an agent turn that actually stacked "
            "two or more distinct open questions the customer must answer at "
            "once (e.g. asking for the amount AND the date in one turn). If "
            "no agent turn has done that, this holds.",
        ),
        _always,
    ),
    # Invariant 8.
    SpecialistCriterion(
        Criterion(
            "external_account_caveat",
            "The customer is paying from an account that is not a Chase "
            "account (marked external in the funding-account tool results). "
            "By the END: after that account came into play and before the "
            "action completed, the agent told the customer that Chase cannot "
            "see that account's balance. This caveat is required "
            "agent-authored wording — it never appears in tool results and "
            "must NOT be treated as invented content. Mark true while the "
            "flow is still in progress. Violated only once the action was "
            "submitted without the caveat ever having been given.",
        ),
        _external_account_in_play,
    ),
    # Invariant 9 — three narrow disclaimer criteria, individually triggered.
    SpecialistCriterion(
        Criterion(
            "saturday_disclaimer",
            "AutoPay details were shown for a card whose next payment date "
            "falls on a Saturday. By the END: when presenting those AutoPay "
            "details, the agent included the Saturday disclaimer (\"If your "
            "due date falls on a Saturday, we'll make the payment on the "
            "Friday before.\"). This is required agent-authored wording — it "
            "never appears in tool results and is NOT invented content, and "
            "it is correct even though the displayed date IS that Saturday. "
            "Violated only if the AutoPay details were presented and the "
            "conversation moved on without the disclaimer having accompanied "
            "them.",
        ),
        _saturday_autopay_shown,
    ),
    SpecialistCriterion(
        Criterion(
            "eastern_time_dates",
            "A one-time payment flow is in progress (its amount options were "
            "fetched). Whenever the agent asked the customer what date to "
            "pay, the ask mentioned that dates are Eastern Time and mentioned "
            "the card's payment due date; and each staged payment's date was "
            "identified as Eastern Time at least once when that payment was "
            "presented for confirmation — a shortened re-ask that repeats an "
            "already-presented payment need not repeat the designation. "
            "Required agent-authored wording, not invented content. If the "
            "agent never asked for a date (the customer supplied one "
            "unprompted), the ask requirement does not apply. Violated only "
            "by a date ask that omitted these, or by a staged payment whose "
            "presentation never identified its date as Eastern Time.",
        ),
        _one_time_payment_flow,
    ),
    SpecialistCriterion(
        Criterion(
            "minimum_due_reminder",
            "The customer chose a fixed AutoPay amount (visible in the "
            "validate arguments). By the END: the agent reminded the customer "
            "that the minimum payment due can change from month to month. "
            "Required agent-authored wording, not invented content. Mark true "
            "while the flow is in progress. Violated only once the AutoPay "
            "setup or update was submitted without the reminder ever having "
            "been given.",
        ),
        _fixed_autopay_amount,
    ),
    # Invariant 10 — no widget indicators exist in mock traces; written now
    # so Phase 5 real-agent traces get it for free.
    SpecialistCriterion(
        Criterion(
            "widget_rule",
            "A selection, confirmation, or success widget was shown to the "
            "customer (a tool result indicates one). The agent points the "
            "customer to the widget rather than re-listing its full contents "
            "as message text. Violated only by an agent turn that actually "
            "re-listed a shown widget's contents in full.",
        ),
        _widget_shown,
    ),
    # Invariant 11.
    SpecialistCriterion(
        Criterion(
            "journey_scoping",
            "This conversation touched an AutoPay-management or "
            "payment-cancellation list (see the ModifyAutoPayPayeeList / "
            "GetCardPaymentActivity results in the trace). (a) AutoPay "
            "management: the agent offered managing AutoPay only for cards "
            "present in the ModifyAutoPayPayeeList result; if the customer "
            "named a card not in it, the agent plainly said AutoPay isn't set "
            "up on that card. (b) Cancelling payments: the agent treated as "
            "cancellable only entries of type 'one_time' in the "
            "GetCardPaymentActivity result — an AutoPay payment (type "
            "'autopay', or absent from the result) was never offered for "
            "cancellation or advanced toward it. Explaining that such a "
            "payment cannot be cancelled here and pointing to turning off "
            "AutoPay instead is correct, grounded behavior — NOT invented "
            "content. An empty list is stated plainly. Violated only when the "
            "agent actually offered or acted on an out-of-scope item.",
        ),
        _scoped_list_shown,
    ),
    # Invariant 12.
    SpecialistCriterion(
        Criterion(
            "readable_api_errors",
            "A tool call failed (its result reports failure). By the END: the "
            "agent gave the customer a human-readable explanation of the "
            "problem and offered a way forward — retrying, an alternative "
            "(such as a different amount), or a live agent. Mark true while "
            "the agent is still handling the failure. Violated only if the "
            "conversation moved on or ended without the failure ever being "
            "explained and a next step offered. Whether the reply falsely "
            "claimed success is judged separately by honest_failure.",
        ),
        _tool_failure_occurred,
    ),
)


def active_criteria(trace: Trace) -> tuple[Criterion, ...]:
    """The specialist criteria whose trigger conditions hold on this trace —
    the GeneralJudge's dynamic_criteria hook (still one LLM call per turn)."""
    return tuple(s.criterion for s in SPECIALISTS if s.trigger(trace))
