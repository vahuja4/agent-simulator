"""J4 — Cancel AutoPay.

Only AutoPay-active cards → show current details (same Saturday disclaimer)
→ offer "Turn off automatic payments" → fetch a cancellation token →
"Are you sure? You'll need to make payments manually for [card …XXXX]" with
Yes/No → on Yes execute and note the confirmation email; on No confirm
AutoPay stays active.

Note the confirm/decline parsing here is journey-specific: in this flow
"cancel"/"turn it off" mean PROCEED, so the shared DECLINE_RE (which treats
"cancel" as a decline) must not be used at the final gate.
"""

from __future__ import annotations

import re

from ... import registry
from ...types import ToolCall
from .parsing import CONFIRM_RE, fmt_date
from .state import ConvState, PendingAutoPayCancel

# "No" wordings that keep AutoPay on. Deliberately excludes "cancel"/"stop".
_KEEP_RE = re.compile(
    r"\bno\b|\bdon'?t\b|\bkeep\b|\bleave\b|\bstay\b|\bnever ?mind\b|\bwait\b|\bhold on\b"
)
_PROCEED_RE = re.compile(r"\bturn (it |them )?off\b|\bcancel\b|\bswitch (it |them )?off\b")


def step(agent, state: ConvState, text: str, calls: list[ToolCall]) -> str:
    parts: list[str] = []

    from .j3_autopay_update import _call_status, _select_active_card

    reply = _select_active_card(agent, state, text, calls, parts, verb="turn off")
    if reply is not None:
        return reply
    card = state.selected_card
    ap = state.autopay[card.card_id]

    # Current details + Saturday disclaimer before the turn-off offer.
    if not state.autopay_status_shown:
        calls.append(_call_status(agent, state, card))
        state.autopay_status_shown = True
        from .agent import SATURDAY_DISCLAIMER

        parts.append(
            f"Here's your current AutoPay for your {card.label}: it pays "
            f"{agent.autopay_amount_phrase(ap)} from your "
            f"{agent.account_label(ap.account_id)} on your statement due date — "
            f"the next payment is {fmt_date(card.due_date)}. {SATURDAY_DISCLAIMER} "
            "Would you like to turn off automatic payments?"
        )
        state.turn_off_offered = True
        return " ".join(parts)

    if state.awaiting_confirmation:
        return _handle_are_you_sure(agent, state, text, calls)

    # The offer was made. "No" wordings win first — "no, don't turn it off"
    # must never read as assent just because it contains "turn it off".
    if _KEEP_RE.search(text):
        return f"No problem — AutoPay stays active on your {card.label}."
    # On assent, fetch the cancellation token and ask "Are you sure?".
    if CONFIRM_RE.search(text) or _PROCEED_RE.search(text):
        token = f"captoken-{state.next_form_id()}"
        calls.append(
            ToolCall(
                name=registry.CANCEL_AUTOPAY_OPTIONS,
                arguments={"payeeId": card.card_id, "repeatingModelId": ap.repeating_model_id},
                result={"token": token, "repeatingModelId": ap.repeating_model_id},
            )
        )
        state.pending_autopay_cancel = PendingAutoPayCancel(
            repeating_model_id=ap.repeating_model_id,
            token=token,
            card_label=card.label,
        )
        state.awaiting_confirmation = True
        return (
            f"Are you sure? You'll need to make payments manually for your card "
            f"...{card.last_four}. Yes or no?"
        )
    return (
        f"Would you like to turn off automatic payments for your {card.label}?"
    )


def _handle_are_you_sure(agent, state: ConvState, text: str, calls: list[ToolCall]) -> str:
    pending = state.pending_autopay_cancel
    assert pending is not None
    # "No" wins first — invariant 1 says only a clear yes executes.
    if _KEEP_RE.search(text):
        state.pending_autopay_cancel = None
        state.awaiting_confirmation = False
        return f"No problem — AutoPay stays active on your {pending.card_label}."
    if CONFIRM_RE.search(text) or _PROCEED_RE.search(text):
        result = {
            "status": "CANCELED",
            "success": True,
            "repeatingModelId": pending.repeating_model_id,
        }
        calls.append(
            ToolCall(
                name=registry.CANCEL_AUTOPAY,
                arguments={
                    "repeatingModelId": pending.repeating_model_id,
                    "token": pending.token,
                },
                result=result,
            )
        )
        state.autopay[state.selected_card.card_id].active = False
        state.completed_actions.append(result)
        state.pending_autopay_cancel = None
        state.awaiting_confirmation = False
        return (
            f"AutoPay is now off for your {pending.card_label}. You'll need to make "
            "payments manually going forward. You'll receive a confirmation email."
        )
    return (
        f"Just to check — should I turn off automatic payments for your "
        f"{pending.card_label}? Yes or no?"
    )
