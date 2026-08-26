"""J5 — Cancel a scheduled one-time payment.

Retrieve upcoming cancellable payments (amount, card, pay-from account,
date) — AutoPay pending payments are explicitly OUT of scope here → identify
which to cancel → fetch cancellation options and build the summary string
("$150.00 to Chase Sapphire Preferred on June 20") → "Cancel it" / "Don't
cancel it" → execute with Canceled status + email note, or confirm it stays
scheduled.

Planted defect: D6 — with the flag on, the pending AutoPay payment appears
in the cancellable list (and can then be "cancelled" like any other).

Confirm/decline parsing is journey-specific: "cancel it" means PROCEED here,
so the shared DECLINE_RE must not be used at the final gate, and "don't
cancel it" must be checked before "cancel it".
"""

from __future__ import annotations

import re

from fixtures.paycard import account_by_id, card_by_id

from ... import registry
from ...types import ToolCall
from .parsing import CONFIRM_RE, extract_money, fmt_money
from .state import ConvState, ScheduledPaymentState

# "Don't cancel" wordings — checked BEFORE the proceed wordings because
# "don't cancel it" contains "cancel it".
_KEEP_RE = re.compile(
    r"\bdon'?t\b|\bdo not\b|\bno\b|\bkeep\b|\bleave\b|\bstay\b|\bnever ?mind\b|"
    r"\bwait\b|\bhold on\b"
)
_CANCEL_RE = re.compile(r"\bcancel\b")

# Acknowledgment/closing wordings — a customer accepting an explanation
# should get a polite close, not the cancellable-payments list.
_ACK_RE = re.compile(
    r"\bthanks\b|\bthank you\b|\bokay\b|\bok\b|\balright\b|\bunderstood\b|"
    r"\bi understand\b|\bgot it\b|\bmakes sense\b"
)
_REFERENCE_RE = re.compile(r"\b(?:it|that|this one|that one)\b")


def step(agent, state: ConvState, text: str, calls: list[ToolCall]) -> str:
    # Upcoming cancellable payments, fetched once per conversation.
    if not state.activity_fetched:
        state.activity_fetched = True
        # Journey scoping (invariant 11): AutoPay pending payments are never
        # cancellable here.
        cancellable = [
            p
            for p in state.scheduled_payments
            if p.status == "SCHEDULED"
            and (
                p.kind == "one_time"
                # D6: the pending AutoPay payment is wrongly listed among the
                # cancellable payments.
                or agent.config.d6_autopay_listed_in_cancellable
            )
        ]
        state.cancellable = cancellable
        calls.append(
            ToolCall(
                name=registry.GET_CARD_PAYMENT_ACTIVITY,
                arguments={},
                result={"payments": [_payload(p) for p in cancellable]},
            )
        )
        if not cancellable:
            return "You don't have any upcoming payments that can be cancelled."

    if state.awaiting_confirmation:
        return _handle_cancel_gate(agent, state, text, calls)

    # Identify which payment to cancel.
    if state.selected_payment is None:
        # M10: once an out-of-scope explanation has been given, recognize a
        # pure acknowledgment/close before trying to resolve pronouns to the
        # lone cancellable payment. A genuine new cancellation request still
        # falls through because it contains "cancel".
        if (
            state.out_of_scope_explained
            and _ACK_RE.search(text)
            and not _CANCEL_RE.search(text)
        ):
            return "You're welcome — is there anything else I can help you with?"
        matched, blocked_reply = _match_payment(agent, state, text)
        if blocked_reply is not None:
            return blocked_reply
        if matched is None:
            if _ACK_RE.search(text) and not _CANCEL_RE.search(text):
                return "You're welcome — is there anything else I can help you with?"
            lines = "; ".join(_describe(p) for p in state.cancellable)
            return (
                f"Here are your upcoming payments that can be cancelled: {lines}. "
                "Which one would you like to cancel?"
            )
        state.selected_payment = matched

    # Cancellation options + the summary string, then the explicit gate.
    if not state.cancel_options_fetched:
        p = state.selected_payment
        state.cancel_options_fetched = True
        summary = _summary(p)
        calls.append(
            ToolCall(
                name=registry.GET_CANCEL_PAYMENT_OPTIONS,
                arguments={"paymentId": p.payment_id},
                result={"paymentId": p.payment_id, "summary": summary},
            )
        )
        state.awaiting_confirmation = True
        account = account_by_id(p.account_id)
        return (
            f"You'd like to cancel this payment: {summary}, paid from your "
            f"{account.label}. Should I cancel it? You can say \"Cancel it\" or "
            '"Don\'t cancel it".'
        )
    return "Which payment would you like to cancel?"


def _handle_cancel_gate(agent, state: ConvState, text: str, calls: list[ToolCall]) -> str:
    p = state.selected_payment
    assert p is not None
    # An amount reference to a DIFFERENT payment than the one at the gate
    # means the customer wants that other one — re-enter identification
    # (which also produces the out-of-scope statement for AutoPay pendings).
    figure = extract_money(text, agent.strip_fours())
    if figure is not None and figure != p.amount:
        state.selected_payment = None
        state.cancel_options_fetched = False
        state.awaiting_confirmation = False
        return step(agent, state, text, calls)
    if _KEEP_RE.search(text):
        state.selected_payment = None
        state.cancel_options_fetched = False
        state.awaiting_confirmation = False
        return f"No problem — the payment of {fmt_money(p.amount)} stays scheduled."
    if _CANCEL_RE.search(text) or CONFIRM_RE.search(text):
        result = {"status": "Canceled", "success": True, "paymentId": p.payment_id}
        calls.append(
            ToolCall(
                name=registry.CANCEL_PAYMENT,
                arguments={"paymentId": p.payment_id},
                result=result,
            )
        )
        p.status = "CANCELED"
        state.completed_actions.append(result)
        state.selected_payment = None
        state.cancel_options_fetched = False
        state.awaiting_confirmation = False
        return (
            f"Done — the payment of {fmt_money(p.amount)} is cancelled. "
            "You'll receive a confirmation email."
        )
    return (
        f"Should I cancel the payment of {fmt_money(p.amount)}? "
        'You can say "Cancel it" or "Don\'t cancel it".'
    )


def _match_payment(
    agent, state: ConvState, text: str
) -> tuple[ScheduledPaymentState | None, str | None]:
    """Which scheduled payment the message refers to → (payment, None), or
    (None, reply) when the reference is to a payment that is out of scope
    (an AutoPay pending, with D6 off), or (None, None) when unresolvable."""
    figure = extract_money(text, agent.strip_fours())
    cancellable_ids = {p.payment_id for p in state.cancellable}

    # An amount reference is checked against ALL scheduled payments first, so
    # a reference to the AutoPay pending payment gets the scoping statement
    # rather than silently matching nothing.
    if figure is not None:
        for p in state.scheduled_payments:
            if p.status == "SCHEDULED" and p.amount == figure:
                if p.payment_id in cancellable_ids:
                    return p, None
                return None, _out_of_scope_reply(state, p)
        return None, None

    # An explicit AutoPay reference inside J5 (rare — "autopay" openers route
    # to J2–J4) is the same out-of-scope case.
    if re.search(r"\bauto[- ]?pay\b|\bautomatic\b", text):
        for p in state.scheduled_payments:
            if p.status == "SCHEDULED" and p.kind == "autopay":
                if p.payment_id not in cancellable_ids:
                    return None, _out_of_scope_reply(state, p)
                return p, None

    # A pronoun retry after an out-of-scope refusal still refers to that
    # payment; never substitute the unrelated lone cancellable payment.
    if state.out_of_scope_payment_id and (
        _CANCEL_RE.search(text) or _REFERENCE_RE.search(text)
    ):
        blocked = next(
            (
                p
                for p in state.scheduled_payments
                if p.payment_id == state.out_of_scope_payment_id
                and p.status == "SCHEDULED"
            ),
            None,
        )
        if blocked is not None:
            return None, _out_of_scope_reply(state, blocked)

    # A lone cancellable payment can be picked by simple assent/reference.
    if len(state.cancellable) == 1:
        if CONFIRM_RE.search(text) or _CANCEL_RE.search(text) or _REFERENCE_RE.search(text):
            return state.cancellable[0], None
    return None, None


def _out_of_scope_reply(state: ConvState, p: ScheduledPaymentState) -> str:
    card = card_by_id(p.card_id)
    state.out_of_scope_payment_id = p.payment_id
    # M8 calibration fix: _match_payment's amount branch routes ANY
    # non-cancellable SCHEDULED payment here, so the wording is derived from
    # the payment's kind — a non-cancellable one-time payment must not be
    # described as AutoPay.
    if p.kind == "autopay":
        kind_desc = "automatic AutoPay payment"
        scope_clause = " — I can only cancel scheduled one-time payments"
        alternative = " If you'd like, you can turn off AutoPay instead."
        restated_scope = (
            "; only scheduled one-time payments can be cancelled in this "
            "flow. If you'd like to stop future automatic payments, you can "
            "turn off AutoPay."
        )
    else:
        kind_desc = "scheduled one-time payment"
        scope_clause = ""
        alternative = ""
        restated_scope = (
            "; it isn't one of the payments that can be cancelled in this flow."
        )
    if state.out_of_scope_explained:
        # A repeated ask gets a restated, not verbatim, refusal.
        return (
            f"I'm sorry — I really can't cancel the {fmt_money(p.amount)} "
            f"{kind_desc} from here{restated_scope}"
        )
    state.out_of_scope_explained = True
    return (
        f"The {fmt_money(p.amount)} payment on {_short_date(p)} is an upcoming "
        f"{kind_desc} for your {card.label}, so I can't cancel it "
        f"here{scope_clause}.{alternative}"
    )


def _payload(p: ScheduledPaymentState) -> dict[str, object]:
    card = card_by_id(p.card_id)
    account = account_by_id(p.account_id)
    return {
        "paymentId": p.payment_id,
        "amount": p.amount,
        "cardLabel": card.label,
        "accountLabel": account.label,
        "paymentDate": p.payment_date.isoformat(),
        "type": p.kind,
    }


def _short_date(p: ScheduledPaymentState) -> str:
    return f"{p.payment_date.strftime('%B')} {p.payment_date.day}"


def _summary(p: ScheduledPaymentState) -> str:
    """The design's summary string: "$150.00 to Chase Sapphire Preferred on
    June 20"."""
    card = card_by_id(p.card_id)
    return f"{fmt_money(p.amount)} to {card.name} on {_short_date(p)}"


def _describe(p: ScheduledPaymentState) -> str:
    card = card_by_id(p.card_id)
    account = account_by_id(p.account_id)
    return (
        f"{fmt_money(p.amount)} to your {card.label} from your {account.label} "
        f"on {_short_date(p)}"
    )
