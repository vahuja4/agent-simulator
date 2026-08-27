"""MockPayCardAgent: journey routing plus the steps every journey shares —
card selection (with the D5 disambiguation deviation), funding-account
selection (with the D7 caveat deviation), and the picker tool calls.
Journey-specific flows live in the j1–j5 modules and receive this agent as
their toolbox.
"""

from __future__ import annotations

from typing import Callable

from fixtures.paycard import (
    AUTOPAY_ENROLLMENTS,
    CARDS,
    FROZEN_CLOCK,
    FUNDING_ACCOUNTS,
    SCHEDULED_PAYMENTS,
    Card,
    FundingAccount,
    card_by_id,
)

from ... import registry
from ...clock import Clock
from ...types import AgentInput, AgentResponse, ToolCall
from ..base import AgentAdapter
from . import j1_one_time, j2_autopay_setup, j3_autopay_update, j4_autopay_cancel, j5_cancel_payment
from .config import MockConfig
from .parsing import find_cards, match_autopay_type, route_journey
from .state import AutoPayState, ConvState, ScheduledPaymentState

# Always worded exactly like this (design J3/J4): shown with current AutoPay
# details regardless of which weekday the due date falls on.
SATURDAY_DISCLAIMER = (
    "If your due date falls on a Saturday, we'll make the payment on the Friday before."
)

_JOURNEY_STEPS: dict[str, Callable[["MockPayCardAgent", ConvState, str, list[ToolCall]], str]] = {
    "J1": j1_one_time.step,
    "J2": j2_autopay_setup.step,
    "J3": j3_autopay_update.step,
    "J4": j4_autopay_cancel.step,
    "J5": j5_cancel_payment.step,
}


class MockPayCardAgent(AgentAdapter):
    """Deterministic mock of the PayCard assistant, all five journeys."""

    def __init__(
        self,
        config: MockConfig | None = None,
        *,
        clock: Clock = FROZEN_CLOCK,
        cards: tuple[Card, ...] = CARDS,
        accounts: tuple[FundingAccount, ...] = FUNDING_ACCOUNTS,
    ) -> None:
        self.config = config or MockConfig()
        self.clock = clock
        self.cards = cards
        self.accounts = accounts
        self._states: dict[str, ConvState] = {}

    # ------------------------------------------------------------- interface

    async def call(self, input: AgentInput) -> AgentResponse:
        state = self._states.setdefault(input.conversation_id, self._new_state())
        text = input.last_user_message.lower()
        calls: list[ToolCall] = []
        reply = self._step(state, text, calls)
        return AgentResponse(
            content=reply,
            tool_calls=calls,
            selected_card=state.selected_card.label if state.selected_card else None,
        )

    def _new_state(self) -> ConvState:
        """Each conversation gets its own mutable copy of the AutoPay
        enrollments and scheduled payments, seeded from fixtures."""
        return ConvState(
            autopay={
                e.card_id: AutoPayState(
                    card_id=e.card_id,
                    payment_type=e.payment_type,
                    payment_type_label=e.payment_type_label,
                    fixed_amount=e.fixed_amount,
                    account_id=e.account_id,
                    repeating_model_id=e.repeating_model_id,
                )
                for e in AUTOPAY_ENROLLMENTS
            },
            scheduled_payments=[
                ScheduledPaymentState(
                    payment_id=p.payment_id,
                    card_id=p.card_id,
                    account_id=p.account_id,
                    amount=p.amount,
                    payment_date=p.payment_date,
                    kind=p.kind,
                )
                for p in SCHEDULED_PAYMENTS
            ],
        )

    def _step(self, state: ConvState, text: str, calls: list[ToolCall]) -> str:
        if state.journey is None:
            state.journey = route_journey(text)
            if state.journey is None and find_cards(text, self.cards):
                # A bare card mention defaults to a payment (Phase 1 behavior).
                state.journey = "J1"
            if state.journey is None:
                return (
                    "I can help you make a payment, set up or change AutoPay, "
                    "or cancel a scheduled payment on your Chase credit card. "
                    "What would you like to do?"
                )
        return _JOURNEY_STEPS[state.journey](self, state, text, calls)

    # -------------------------------------------------------- shared helpers

    def strip_fours(self) -> list[str]:
        """Last-four digits to strip before reading dollar figures."""
        return [c.last_four for c in self.cards] + [a.last_four for a in self.accounts]

    def handle_card_mention(
        self,
        state: ConvState,
        text: str,
        *,
        on_switch: Callable[[Card], None],
    ) -> str | None:
        """Card mentions are handled on every turn — selection, the last-four
        tie question (invariant 5), and mid-flow switches (invariant 6, via
        the journey's ``on_switch`` reset). Returns a full reply when the
        mention needs disambiguation, else None."""
        mentioned = find_cards(text, self.cards)
        if len(mentioned) > 1:
            if state.selected_card is not None and any(
                c.card_id == state.selected_card.card_id for c in mentioned
            ):
                # M3 calibration fix: mid-flow, a name tie that INCLUDES the
                # currently selected card refers to it ("this Freedom card"
                # while paying a Freedom card) — don't re-open disambiguation.
                # Only an unambiguous different card switches the flow.
                return None
            if self.config.d5_silent_card_disambiguation:
                # D5: silently resolve the tie to the first matching card —
                # no last-four clarification is ever asked.
                mentioned = [mentioned[0]]
            else:
                fours = " or ".join(f"...{c.last_four}" for c in mentioned)
                return (
                    "You have more than one card matching that. "
                    f"Which one did you mean — the one ending in {fours}?"
                )
        if len(mentioned) == 1:
            card = mentioned[0]
            if state.selected_card is None:
                state.selected_card = card
            elif card.card_id != state.selected_card.card_id:
                state.selected_card = card
                on_switch(card)
        return None

    def external_account_caveat(self, account: FundingAccount) -> str | None:
        """Invariant 8: paying from a non-Chase account gets the
        can't-see-that-balance caveat."""
        if account.kind != "external":
            return None
        if self.config.d7_no_external_account_warning:
            # D7: the external-account balance caveat is never given.
            return None
        return (
            f"Just so you know, since {account.name} isn't a Chase account, "
            "we can't see its balance."
        )

    def call_payee_list(self) -> ToolCall:
        return ToolCall(
            name=registry.PAYEE_LIST,
            arguments={},
            result={
                "payees": [
                    {
                        "payeeId": c.card_id,
                        "name": c.name,
                        "mask": c.last_four,
                        "dueDate": c.due_date.isoformat(),
                    }
                    for c in self.cards
                ]
            },
        )

    def call_funding_picker(self) -> ToolCall:
        return ToolCall(
            name=registry.FUNDING_ACCOUNT_PICKER,
            arguments={},
            result={
                "accounts": [
                    {
                        "accountId": a.account_id,
                        "name": a.name,
                        "mask": a.last_four,
                        "type": a.kind,
                    }
                    for a in self.accounts
                ]
            },
        )

    # --------------------------------------------------- AutoPay shared bits

    def active_autopay_cards(self, state: ConvState) -> list[Card]:
        """The cards J3/J4 may list: active AutoPay only (invariant 11)."""
        return [
            card_by_id(card_id)
            for card_id, ap in state.autopay.items()
            if ap.active
        ]

    def select_active_card(
        self,
        state: ConvState,
        text: str,
        calls: list[ToolCall],
        parts: list[str],
        *,
        verb: str,
    ) -> str | None:
        """Shared J3/J4 scoping: only AutoPay-active cards are ever offered
        (invariant 11); a non-active card mention gets a plain statement; a
        single active card is selected automatically. Returns a reply to send, or
        None when a card is selected and the flow may continue."""
        active = self.active_autopay_cards(state)
        if not state.modify_payee_list_fetched:
            calls.append(self.call_modify_payee_list(state))
            state.modify_payee_list_fetched = True
        if not active:
            return "You don't have automatic payments set up on any of your cards."

        mentioned = find_cards(text, self.cards)
        if len(mentioned) > 1 and not self.config.d5_silent_card_disambiguation:
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
                return (
                    f"Which card's automatic payments would you like to {verb}? "
                    f"You have: {labels}."
                )
        return None

    def call_modify_payee_list(self, state: ConvState) -> ToolCall:
        return ToolCall(
            name=registry.MODIFY_AUTOPAY_PAYEE_LIST,
            arguments={},
            result={
                "payees": [
                    {
                        "payeeId": c.card_id,
                        "name": c.name,
                        "mask": c.last_four,
                        "repeatingModelId": state.autopay[c.card_id].repeating_model_id,
                    }
                    for c in self.active_autopay_cards(state)
                ]
            },
        )

    def call_autopay_status(self, state: ConvState, card: Card) -> ToolCall:
        ap = state.autopay[card.card_id]
        return ToolCall(
            name=registry.GET_AUTOPAY_STATUS,
            arguments={"payeeId": card.card_id},
            result={
                "paymentType": ap.payment_type,
                "paymentTypeLabel": ap.payment_type_label,
                "fixedAmount": ap.fixed_amount,
                "accountLabel": self.account_label(ap.account_id),
                "nextPaymentDate": card.due_date.isoformat(),
                "repeatingModelId": ap.repeating_model_id,
            },
        )

    def capture_autopay_type(self, state: ConvState, text: str) -> str | None:
        matched = match_autopay_type(text, self.strip_fours())
        if matched is None:
            return None
        option_id, label, fixed = matched
        state.autopay_payment_type = option_id
        state.autopay_payment_type_label = label
        if fixed is not None:
            state.autopay_fixed_amount = fixed
        return option_id

    def account_label(self, account_id: str) -> str:
        for a in self.accounts:
            if a.account_id == account_id:
                return a.label
        return account_id

    def autopay_amount_phrase(self, ap: AutoPayState) -> str:
        """Human phrase for what an AutoPay setup pays, e.g. "the statement
        balance" or "a fixed amount of $25.00"."""
        from .parsing import fmt_money

        if ap.payment_type == "fixed" and ap.fixed_amount is not None:
            return f"a fixed amount of {fmt_money(ap.fixed_amount)}"
        return f"the {ap.payment_type_label.lower()}"
