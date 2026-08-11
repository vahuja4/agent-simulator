"""Fixture universe for the PayCard mock and the user simulator's grounded
knowledge: one customer, three cards, two funding accounts, one AutoPay
enrollment, two upcoming scheduled payments, and a frozen "now". Every
element exists to exercise a specific journey or planted defect — see the
purpose comments on each.

All dates are relative to FROZEN_NOW so the Saturday-due-date and Eastern
Time rules stay testable. Business logic receives these through an injected
Clock — never datetime.now().
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from agentsim.clock import EASTERN, FrozenClock

# Wednesday, June 10 2026, 09:30 Eastern.
FROZEN_NOW = datetime(2026, 6, 10, 9, 30, tzinfo=EASTERN)
FROZEN_CLOCK = FrozenClock(FROZEN_NOW)


@dataclass(frozen=True)
class Card:
    card_id: str
    name: str
    last_four: str
    current_balance: float
    statement_balance: float
    remaining_statement_balance: float
    minimum_due: float
    due_date: date

    @property
    def label(self) -> str:
        return f"{self.name} (...{self.last_four})"


@dataclass(frozen=True)
class FundingAccount:
    account_id: str
    name: str
    last_four: str
    kind: str  # "chase" | "external"
    balance: float | None  # None for external — Chase can't see it

    @property
    def label(self) -> str:
        return f"{self.name} (...{self.last_four})"


CARDS: tuple[Card, ...] = (
    # The AutoPay-active card (see AUTOPAY_ENROLLMENTS): the J3/J4 target.
    # Its due date, June 20 2026, is a SATURDAY under the frozen clock —
    # exercises the Saturday-due-date disclaimer in J3/J4.
    Card(
        card_id="card-sapphire-9013",
        name="Chase Sapphire Preferred",
        last_four="9013",
        current_balance=1240.50,
        statement_balance=875.20,
        remaining_statement_balance=875.20,
        minimum_due=40.00,
        due_date=date(2026, 6, 20),
    ),
    # The two cards below are both named "Freedom …": a name tie that forces
    # last-four disambiguation (invariant 5) and is D5's target. Neither has
    # AutoPay — the J2 enrollment targets and the J3/J4 scoping negatives.
    Card(
        card_id="card-freedom-unlimited-0767",
        name="Chase Freedom Unlimited",
        last_four="0767",
        current_balance=432.10,
        statement_balance=310.45,
        remaining_statement_balance=210.45,
        minimum_due=35.00,
        due_date=date(2026, 6, 25),
    ),
    Card(
        card_id="card-freedom-flex-4421",
        name="Chase Freedom Flex",
        last_four="4421",
        current_balance=89.99,
        statement_balance=89.99,
        remaining_statement_balance=89.99,
        minimum_due=25.00,
        due_date=date(2026, 6, 28),
    ),
)

FUNDING_ACCOUNTS: tuple[FundingAccount, ...] = (
    FundingAccount(
        account_id="acct-chase-checking-5678",
        name="Chase Total Checking",
        last_four="5678",
        kind="chase",
        balance=2500.00,
    ),
    # External non-Chase account: triggers the "we can't see that balance"
    # caveat (invariant 8) — D7 suppresses it.
    FundingAccount(
        account_id="acct-ally-savings-9999",
        name="Ally Savings",
        last_four="9999",
        kind="external",
        balance=None,
    ),
)

# Above this amount the mock's submission tools return a failure result
# (always — flag-independent). D3 only controls whether the mock's REPLY lies
# about that failure. Deliberately above every fixture balance so it is only
# reachable via an "Other amount" figure the customer names.
LARGE_PAYMENT_THRESHOLD = 5000.00


@dataclass(frozen=True)
class AutoPayEnrollment:
    """One card's active AutoPay setup, mirroring the Sierra store's
    repeating-payment model."""

    card_id: str
    payment_type: str  # "minimum_due" | "statement_balance" | "fixed"
    payment_type_label: str
    fixed_amount: float | None  # only for payment_type == "fixed"
    account_id: str
    repeating_model_id: str


# Exactly one card has AutoPay active (the Sapphire — the J3/J4 target with
# the Saturday due date). Both Freedom cards have none: they are the J2
# enrollment targets and prove J3/J4 list only AutoPay-active cards
# (invariant 11).
AUTOPAY_ENROLLMENTS: tuple[AutoPayEnrollment, ...] = (
    AutoPayEnrollment(
        card_id="card-sapphire-9013",
        payment_type="statement_balance",
        payment_type_label="Statement balance",
        fixed_amount=None,
        account_id="acct-chase-checking-5678",
        repeating_model_id="rpm-sapphire-0001",
    ),
)


@dataclass(frozen=True)
class ScheduledPayment:
    """One upcoming payment. ``kind`` separates customer-scheduled one-time
    payments (cancellable in J5) from AutoPay pending payments (explicitly
    OUT of J5's scope — D6 wrongly lists them)."""

    payment_id: str
    card_id: str
    account_id: str
    amount: float
    payment_date: date
    kind: str  # "one_time" | "autopay"


SCHEDULED_PAYMENTS: tuple[ScheduledPayment, ...] = (
    # The one cancellable one-time payment — J5's happy-path target, matching
    # the design's summary-string example ("$150.00 to Chase Sapphire
    # Preferred on June 20").
    ScheduledPayment(
        payment_id="pmt-onetime-0150",
        card_id="card-sapphire-9013",
        account_id="acct-chase-checking-5678",
        amount=150.00,
        payment_date=date(2026, 6, 20),
        kind="one_time",
    ),
    # The pending AutoPay payment (Sapphire's statement balance on its due
    # date). J5 must EXCLUDE it from the cancellable list; D6 includes it.
    # Same date as the one-time payment above, different amount — so the D6
    # scenario can reference it unambiguously by amount.
    ScheduledPayment(
        payment_id="pmt-autopay-0875",
        card_id="card-sapphire-9013",
        account_id="acct-chase-checking-5678",
        amount=875.20,
        payment_date=date(2026, 6, 20),
        kind="autopay",
    ),
)


def card_by_id(card_id: str) -> Card:
    for c in CARDS:
        if c.card_id == card_id:
            return c
    raise KeyError(card_id)


def account_by_id(account_id: str) -> FundingAccount:
    for a in FUNDING_ACCOUNTS:
        if a.account_id == account_id:
            return a
    raise KeyError(account_id)


def amount_options(card: Card) -> list[dict[str, object]]:
    """The amount options the options tool returns for one card — always
    fetched fresh for the currently selected card, never served from memory.
    "Remaining statement balance" is the special fetch the journey calls out.
    """
    return [
        {"optionId": "minimum_due", "label": "Minimum payment due", "amount": card.minimum_due},
        {
            "optionId": "statement_balance",
            "label": "Statement balance",
            "amount": card.statement_balance,
        },
        {
            "optionId": "remaining_statement_balance",
            "label": "Remaining statement balance",
            "amount": card.remaining_statement_balance,
        },
        {
            "optionId": "current_balance",
            "label": "Current balance",
            "amount": card.current_balance,
        },
        {"optionId": "other", "label": "Other amount", "amount": None},
    ]


def autopay_amount_options(card: Card) -> list[dict[str, object]]:
    """The AutoPay amount-type options (J2 setup and J3 update): unlike J1
    there is no free "other amount" — a fixed amount is a named type whose
    exact figure the customer must supply."""
    return [
        {"optionId": "minimum_due", "label": "Minimum payment due", "amount": card.minimum_due},
        {
            "optionId": "statement_balance",
            "label": "Statement balance",
            "amount": card.statement_balance,
        },
        {"optionId": "fixed", "label": "Fixed amount", "amount": None},
    ]


def autopay_for_card(card_id: str) -> AutoPayEnrollment | None:
    for e in AUTOPAY_ENROLLMENTS:
        if e.card_id == card_id:
            return e
    return None
