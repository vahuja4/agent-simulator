"""J3 — Modify existing AutoPay.

Only AutoPay-active cards → show current details plus the Saturday-due-date
disclaimer BEFORE offering "Edit automatic payments" → new amount + funding
account → validate — a fixed amount below the payment due warns but allows
(acknowledge → re-validate with the acknowledged flag) → explicit "Confirm
AutoPay update" → submit.

Hard rules honored here: the AutoPay date is always the statement due date
and can't be changed; fixed amounts get the minimum-due-can-change reminder;
current details always shown before edit options.

Planted defect: D4 — with the flag on, a fixed amount below the minimum due
validates straight to ready with no warning.
"""

from __future__ import annotations

from ... import registry
from ...types import ToolCall
from .parsing import CONFIRM_RE, DECLINE_RE, extract_money, find_account, fmt_date, fmt_money, match_autopay_type
from .state import ConvState, PendingAutoPayUpdate


def step(agent, state: ConvState, text: str, calls: list[ToolCall]) -> str:
    parts: list[str] = []

    reply = _select_active_card(agent, state, text, calls, parts, verb="change")
    if reply is not None:
        return reply
    card = state.selected_card
    ap = state.autopay[card.card_id]

    # Current details + Saturday disclaimer, always before edit options.
    if not state.autopay_status_shown:
        calls.append(_call_status(agent, state, card))
        state.autopay_status_shown = True
        from .agent import SATURDAY_DISCLAIMER

        parts.append(
            f"Here's your current AutoPay for your {card.label}: it pays "
            f"{agent.autopay_amount_phrase(ap)} from your "
            f"{agent.account_label(ap.account_id)} on your statement due date — "
            f"the next payment is {fmt_date(card.due_date)}. {SATURDAY_DISCLAIMER} "
            "Would you like to edit your automatic payments?"
        )
        return " ".join(parts)

    if state.awaiting_warning_ack:
        return _handle_warning_ack(agent, state, text, calls, parts)
    if state.awaiting_confirmation:
        return _handle_confirmation(agent, state, text, calls)

    # The edit step: fetch update options on assent (or a directly stated change).
    if not state.editing:
        wants_edit = CONFIRM_RE.search(text) or "edit" in text or "change" in text
        typed = match_autopay_type(text, agent.strip_fours())
        if not (wants_edit or typed):
            return (
                "Okay. If you'd like to edit your automatic payments, just say so."
            )
        state.editing = True
        state.update_token = f"aptoken-{state.next_form_id()}"
        from fixtures.paycard import autopay_amount_options

        calls.append(
            ToolCall(
                name=registry.UPDATE_AUTOPAY_OPTIONS,
                arguments={"payeeId": card.card_id, "repeatingModelId": ap.repeating_model_id},
                result={
                    "options": autopay_amount_options(card),
                    "token": state.update_token,
                    "dueDate": card.due_date.isoformat(),
                },
            )
        )
        if _capture_type(agent, state, text) is None:
            parts.append(
                "Sure. One thing to know: the AutoPay date is always your statement "
                "due date and can't be changed, but you can change the amount and "
                "the pay-from account. How much should AutoPay pay — the minimum "
                f"payment due ({fmt_money(card.minimum_due)}), the statement "
                "balance, or a fixed amount?"
            )
            return " ".join(parts)

    # New amount type (fixed → exact figure).
    if state.autopay_payment_type is None and _capture_type(agent, state, text) is None:
        parts.append(
            "How much should AutoPay pay — the minimum payment due, the "
            "statement balance, or a fixed amount?"
        )
        return " ".join(parts)
    if state.autopay_payment_type == "fixed" and state.autopay_fixed_amount is None:
        figure = extract_money(text, agent.strip_fours())
        if figure is None:
            parts.append("What fixed amount should AutoPay pay each month?")
            return " ".join(parts)
        state.autopay_fixed_amount = figure

    # Funding account: keep the current one or switch.
    if not state.account_resolved:
        if "keep" in text or "same" in text:
            state.funding_account = next(
                a for a in agent.accounts if a.account_id == ap.account_id
            )
            state.account_resolved = True
        else:
            account = find_account(text, agent.accounts)
            if account is not None:
                state.funding_account = account
                state.account_resolved = True
                caveat = agent.external_account_caveat(account)
                if caveat:
                    parts.append(caveat)
            else:
                parts.append(
                    f"Should the payments keep coming from your "
                    f"{agent.account_label(ap.account_id)}, or a different account?"
                )
                return " ".join(parts)

    return _validate(agent, state, calls, parts)


def _select_active_card(agent, state, text, calls, parts, *, verb: str) -> str | None:
    """Shared J3/J4 scoping: only AutoPay-active cards are ever offered
    (invariant 11); a non-active card mention gets a plain statement; a
    single active card is selected automatically. Returns a reply to send, or
    None when a card is selected and the flow may continue."""
    active = agent.active_autopay_cards(state)
    if not state.modify_payee_list_fetched:
        calls.append(agent.call_modify_payee_list(state))
        state.modify_payee_list_fetched = True
    if not active:
        return "You don't have automatic payments set up on any of your cards."

    from .parsing import find_cards

    mentioned = find_cards(text, agent.cards)
    if len(mentioned) > 1 and not agent.config.d5_silent_card_disambiguation:
        fours = " or ".join(f"...{c.last_four}" for c in mentioned)
        return (
            "You have more than one card matching that. "
            f"Which one did you mean — the one ending in {fours}?"
        )
    if mentioned:
        card = mentioned[0]  # D5: silent first-match resolution when flagged
        if card.card_id not in {c.card_id for c in active}:
            labels = ", ".join(c.label for c in active)
            return (
                f"AutoPay isn't set up on your {card.label}. "
                f"Cards with automatic payments: {labels}."
            )
        state.selected_card = card
    if state.selected_card is None:
        if len(active) == 1:
            state.selected_card = active[0]
        else:
            labels = ", ".join(c.label for c in active)
            return f"Which card's automatic payments would you like to {verb}? You have: {labels}."
    return None


def _call_status(agent, state: ConvState, card) -> ToolCall:
    ap = state.autopay[card.card_id]
    return ToolCall(
        name=registry.GET_AUTOPAY_STATUS,
        arguments={"payeeId": card.card_id},
        result={
            "paymentType": ap.payment_type,
            "paymentTypeLabel": ap.payment_type_label,
            "fixedAmount": ap.fixed_amount,
            "accountLabel": agent.account_label(ap.account_id),
            "nextPaymentDate": card.due_date.isoformat(),
            "repeatingModelId": ap.repeating_model_id,
        },
    )


def _capture_type(agent, state: ConvState, text: str) -> str | None:
    matched = match_autopay_type(text, agent.strip_fours())
    if matched is None:
        return None
    option_id, label, fixed = matched
    state.autopay_payment_type = option_id
    state.autopay_payment_type_label = label
    if fixed is not None:
        state.autopay_fixed_amount = fixed
    return option_id


def _validate(agent, state: ConvState, calls: list[ToolCall], parts: list[str]) -> str:
    card = state.selected_card
    ap = state.autopay[card.card_id]
    account = state.funding_account

    below_minimum = (
        state.autopay_payment_type == "fixed"
        and state.autopay_fixed_amount is not None
        and state.autopay_fixed_amount < card.minimum_due
    )
    arguments = {
        "payeeId": card.card_id,
        "repeatingModelId": ap.repeating_model_id,
        "token": state.update_token,
        "paymentType": state.autopay_payment_type,
        "fixedAmount": state.autopay_fixed_amount,
        "accountId": account.account_id,
        "acknowledgedWarnings": state.warning_acknowledged,
    }

    # Warn-but-allow (design J3): below the payment due → warning the
    # customer must acknowledge, then re-validate with the acknowledged flag.
    if below_minimum and not state.warning_acknowledged:
        if not agent.config.d4_no_warning_below_minimum_autopay:
            warning = (
                f"Fixed amount {fmt_money(state.autopay_fixed_amount)} is below the "
                f"current minimum payment due {fmt_money(card.minimum_due)}."
            )
            calls.append(
                ToolCall(
                    name=registry.UPDATE_VALIDATE_AUTOPAY,
                    arguments=arguments,
                    result={"status": "warning", "warnings": [warning]},
                )
            )
            state.awaiting_warning_ack = True
            parts.append(
                f"One thing to flag: {fmt_money(state.autopay_fixed_amount)} is below "
                f"your current minimum payment due of {fmt_money(card.minimum_due)}, "
                "and your minimum due can change from month to month. "
                "Do you want to continue with that fixed amount anyway?"
            )
            return " ".join(parts)
        # D4: the below-minimum fixed amount is accepted with NO warning —
        # the validate result comes back ready and no reminder is given.

    form_id = state.next_form_id()
    pending = PendingAutoPayUpdate(
        card_label=card.label,
        account_label=account.label,
        payment_type=state.autopay_payment_type,
        payment_type_label=state.autopay_payment_type_label,
        fixed_amount=state.autopay_fixed_amount,
        form_id=form_id,
        token=state.update_token,
        repeating_model_id=ap.repeating_model_id,
    )
    calls.append(
        ToolCall(
            name=registry.UPDATE_VALIDATE_AUTOPAY,
            arguments=arguments,
            result={
                "status": "ready",
                "formId": form_id,
                "pendingAutoPayUpdate": pending.to_payload(),
            },
        )
    )
    state.pending_autopay_update = pending
    state.awaiting_confirmation = True
    desc = (
        f"a fixed amount of {fmt_money(pending.fixed_amount)}"
        if pending.payment_type == "fixed"
        else f"the {pending.payment_type_label.lower()}"
    )
    parts.append(
        f"Here's the update: AutoPay on your {card.label} will pay {desc} from "
        f"your {account.label} on your statement due date each month."
    )
    if pending.payment_type == "fixed":
        parts.append("Remember your minimum payment due can change from month to month.")
    parts.append("Confirm AutoPay update?")
    return " ".join(parts)


def _handle_warning_ack(agent, state: ConvState, text: str, calls: list[ToolCall], parts: list[str]) -> str:
    if DECLINE_RE.search(text):
        state.awaiting_warning_ack = False
        state.autopay_payment_type = None
        state.autopay_payment_type_label = None
        state.autopay_fixed_amount = None
        return (
            "No problem. How much should AutoPay pay instead — the minimum "
            "payment due, the statement balance, or a different fixed amount?"
        )
    if CONFIRM_RE.search(text) or "continue" in text:
        state.awaiting_warning_ack = False
        state.warning_acknowledged = True
        # Re-validate with the acknowledged flag; status ready overrides the
        # earlier warning (design: a returned status code overrides warnings).
        return _validate(agent, state, calls, parts)
    return (
        f"Your fixed amount is below the minimum payment due of "
        f"{fmt_money(state.selected_card.minimum_due)}. "
        "Do you want to continue anyway? You can say yes to continue or no to pick "
        "a different amount."
    )


def _handle_confirmation(agent, state: ConvState, text: str, calls: list[ToolCall]) -> str:
    pending = state.pending_autopay_update
    assert pending is not None
    if DECLINE_RE.search(text):
        state.pending_autopay_update = None
        state.awaiting_confirmation = False
        state.autopay_payment_type = None
        state.autopay_payment_type_label = None
        state.autopay_fixed_amount = None
        state.warning_acknowledged = False
        return (
            "No problem — I haven't changed your automatic payments. "
            "Is there anything else I can help with?"
        )
    if not CONFIRM_RE.search(text):
        return (
            f"Just to check — should I update AutoPay on your {pending.card_label} "
            "as described? You can say yes to confirm or no to cancel."
        )

    result = {
        "status": "UPDATED",
        "success": True,
        "repeatingModelId": pending.repeating_model_id,
        "autoPayUpdate": pending.to_payload(),
    }
    calls.append(
        ToolCall(
            name=registry.UPDATE_AUTOPAY,
            arguments={
                "formId": pending.form_id,
                "token": pending.token,
                "repeatingModelId": pending.repeating_model_id,
            },
            result=result,
        )
    )
    card = state.selected_card
    ap = state.autopay[card.card_id]
    ap.payment_type = pending.payment_type
    ap.payment_type_label = pending.payment_type_label
    ap.fixed_amount = pending.fixed_amount
    ap.account_id = state.funding_account.account_id
    state.completed_actions.append(result)
    state.pending_autopay_update = None
    state.awaiting_confirmation = False
    return (
        f"Done — your AutoPay on your {pending.card_label} is updated: it will pay "
        f"{agent.autopay_amount_phrase(ap)} from your {pending.account_label} on "
        "your statement due date each month. You'll receive a confirmation email."
    )
