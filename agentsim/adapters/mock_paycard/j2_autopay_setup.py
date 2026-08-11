"""J2 — Set up AutoPay.

Card → disclose that AutoPay runs on the statement due date → amount options
(fixed amount → ask for the exact figure) → AutoPay-enabled funding accounts
→ validate (stages the PendingAutoPay) → confirm → submit (consumes it).

Tool order per design §2: PayeeList → AddOptionsAutoPay →
FundingAccountPicker → AddValidateAutoPay → AddAutoPay. Note the funding
picker comes AFTER the amount options here, unlike J1.

D7 (missing external-account caveat) lives in the shared funding helper.
"""

from __future__ import annotations

from fixtures.paycard import Card, autopay_amount_options

from ... import registry
from ...types import ToolCall
from .parsing import (
    CONFIRM_RE,
    DECLINE_RE,
    find_account,
    fmt_date,
    fmt_money,
    match_autopay_type,
)
from .state import AutoPayState, ConvState, PendingAutoPay


def step(agent, state: ConvState, text: str, calls: list[ToolCall]) -> str:
    parts: list[str] = []

    def on_switch(card: Card) -> None:
        _reset_for_switch(state)
        parts.append(f"Sure — let's set up AutoPay for your {card.label} instead.")

    reply = agent.handle_card_mention(state, text, on_switch=on_switch)
    if reply:
        return reply

    if state.awaiting_confirmation:
        return _handle_confirmation(agent, state, text, calls)

    # Card selection.
    if not state.payee_list_fetched:
        calls.append(agent.call_payee_list())
        state.payee_list_fetched = True
    if state.selected_card is None:
        labels = ", ".join(c.label for c in agent.cards)
        parts.append(f"Which card would you like to set up AutoPay for? You have: {labels}.")
        return " ".join(parts)

    card = state.selected_card
    existing = state.autopay.get(card.card_id)
    if existing is not None and existing.active:
        parts.append(
            f"Your {card.label} already has AutoPay set up — it pays "
            f"{agent.autopay_amount_phrase(existing)} each month. If you'd like to "
            "change or turn off those automatic payments, just say so."
        )
        return " ".join(parts)

    # Amount options, with the due-date disclosure up front.
    if state.autopay_options_card_id != card.card_id:
        options = autopay_amount_options(card)
        state.autopay_options_card_id = card.card_id
        calls.append(
            ToolCall(
                name=registry.ADD_OPTIONS_AUTOPAY,
                arguments={"payeeId": card.card_id},
                result={"options": options, "dueDate": card.due_date.isoformat()},
            )
        )
        if _capture_autopay_type(agent, state, text) is None:
            parts.append(
                "Quick note first: AutoPay payments are made on your statement due "
                f"date each month (your next one is {fmt_date(card.due_date)}). "
                f"How much should AutoPay pay — the minimum payment due "
                f"({fmt_money(card.minimum_due)}), the statement balance, or a "
                "fixed amount?"
            )
            return " ".join(parts)

    # Amount type (fixed → need the exact figure).
    if state.autopay_payment_type is None and _capture_autopay_type(agent, state, text) is None:
        parts.append(
            "How much should AutoPay pay — the minimum payment due, the "
            "statement balance, or a fixed amount?"
        )
        return " ".join(parts)
    if state.autopay_payment_type == "fixed" and state.autopay_fixed_amount is None:
        from .parsing import extract_money

        figure = extract_money(text, agent.strip_fours())
        if figure is None:
            parts.append("What fixed amount should AutoPay pay each month?")
            return " ".join(parts)
        state.autopay_fixed_amount = figure

    # Funding account (AutoPay-enabled).
    if state.funding_account is None:
        if not state.funding_picker_fetched:
            calls.append(agent.call_funding_picker())
            state.funding_picker_fetched = True
        account = find_account(text, agent.accounts)
        if account is None:
            labels = ", ".join(a.label for a in agent.accounts)
            parts.append(f"Which account should AutoPay pay from? You have: {labels}.")
            return " ".join(parts)
        state.funding_account = account
        caveat = agent.external_account_caveat(account)
        if caveat:
            parts.append(caveat)

    # Everything collected → validate, which stages the PendingAutoPay.
    return _validate_and_stage(agent, state, calls, parts)


def _reset_for_switch(state: ConvState) -> None:
    """Switching cards restarts J2 with the new card's own options."""
    state.autopay_options_card_id = None
    state.autopay_payment_type = None
    state.autopay_payment_type_label = None
    state.autopay_fixed_amount = None
    state.pending_autopay = None
    state.awaiting_confirmation = False


def _capture_autopay_type(agent, state: ConvState, text: str) -> str | None:
    matched = match_autopay_type(text, agent.strip_fours())
    if matched is None:
        return None
    option_id, label, fixed = matched
    state.autopay_payment_type = option_id
    state.autopay_payment_type_label = label
    if fixed is not None:
        state.autopay_fixed_amount = fixed
    return option_id


def _autopay_desc(state: ConvState) -> str:
    if state.autopay_payment_type == "fixed":
        return f"a fixed amount of {fmt_money(state.autopay_fixed_amount)}"
    return f"the {state.autopay_payment_type_label.lower()}"


def _validate_and_stage(agent, state: ConvState, calls: list[ToolCall], parts: list[str]) -> str:
    card = state.selected_card
    account = state.funding_account
    form_id = state.next_form_id()
    pending = PendingAutoPay(
        card_label=card.label,
        account_label=account.label,
        payment_type=state.autopay_payment_type,
        payment_type_label=state.autopay_payment_type_label,
        fixed_amount=state.autopay_fixed_amount,
        form_id=form_id,
    )
    calls.append(
        ToolCall(
            name=registry.ADD_VALIDATE_AUTOPAY,
            arguments={
                "payeeId": card.card_id,
                "accountId": account.account_id,
                "paymentType": state.autopay_payment_type,
                "fixedAmount": state.autopay_fixed_amount,
            },
            result={"status": "ready", "formId": form_id, "pendingAutoPay": pending.to_payload()},
        )
    )
    state.pending_autopay = pending
    state.awaiting_confirmation = True
    parts.append(
        f"Here's your AutoPay setup: {_autopay_desc(state)} for your {card.label}, "
        f"paid from your {account.label} on your statement due date each month."
    )
    if state.autopay_payment_type == "fixed":
        # Invariant 9: fixed amounts get the minimum-due-can-change reminder.
        parts.append("Keep in mind your minimum payment due can change from month to month.")
    parts.append("Shall I turn on AutoPay?")
    return " ".join(parts)


def _handle_confirmation(agent, state: ConvState, text: str, calls: list[ToolCall]) -> str:
    pending = state.pending_autopay
    assert pending is not None
    if DECLINE_RE.search(text):
        state.pending_autopay = None
        state.awaiting_confirmation = False
        state.autopay_payment_type = None
        state.autopay_payment_type_label = None
        state.autopay_fixed_amount = None
        return "No problem — I haven't turned on AutoPay. Is there anything else I can help with?"
    if not CONFIRM_RE.search(text):
        return (
            f"Just to check — should I turn on AutoPay for your {pending.card_label}, "
            f"paying from your {pending.account_label}? You can say yes to confirm "
            "or no to cancel."
        )

    # Submission consumes the staged pending object.
    card = state.selected_card
    account = state.funding_account
    repeating_model_id = f"rpm-{card.card_id.removeprefix('card-')}"
    result = {
        "status": "ENROLLED",
        "success": True,
        "repeatingModelId": repeating_model_id,
        "autoPay": pending.to_payload(),
    }
    calls.append(
        ToolCall(name=registry.ADD_AUTOPAY, arguments={"formId": pending.form_id}, result=result)
    )
    state.autopay[card.card_id] = AutoPayState(
        card_id=card.card_id,
        payment_type=pending.payment_type,
        payment_type_label=pending.payment_type_label,
        fixed_amount=pending.fixed_amount,
        account_id=account.account_id,
        repeating_model_id=repeating_model_id,
    )
    state.completed_actions.append(result)
    state.pending_autopay = None
    state.awaiting_confirmation = False
    return (
        f"AutoPay is on for your {pending.card_label}: {_desc_from_pending(pending)} "
        f"from your {pending.account_label} on your statement due date each month. "
        "You'll receive a confirmation email."
    )


def _desc_from_pending(pending: PendingAutoPay) -> str:
    if pending.payment_type == "fixed" and pending.fixed_amount is not None:
        return f"a fixed amount of {fmt_money(pending.fixed_amount)}"
    return f"the {pending.payment_type_label.lower()}"
