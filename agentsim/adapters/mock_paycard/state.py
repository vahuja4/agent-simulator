"""Per-conversation state, modeled on the Sierra store objects (design §2):
every submit-style action is staged as a pending object first — that staging
is the confirmation card — and the submission tool consumes it. Submission
therefore cannot happen without a prior successful validate/options step in
this mock by construction.

The AutoPay enrollments and scheduled payments are seeded per conversation
from the fixtures and mutated by J2–J5 submissions, so each conversation is
an isolated world.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from fixtures.paycard import Card, FundingAccount


@dataclass
class PendingPayment:
    """Mirrors the Sierra store's PendingPayment: staged by
    AddValidateOneTimePayment, consumed by AddOneTimePayment."""

    card_label: str
    account_label: str
    amount: float
    payment_date: date
    form_id: str

    def to_payload(self) -> dict[str, object]:
        return {
            "cardLabel": self.card_label,
            "accountLabel": self.account_label,
            "amount": self.amount,
            "paymentDate": self.payment_date.isoformat(),
            "formId": self.form_id,
        }


@dataclass
class PendingAutoPay:
    """Staged by AddValidateAutoPay, consumed by AddAutoPay (J2)."""

    card_label: str
    account_label: str
    payment_type: str
    payment_type_label: str
    fixed_amount: float | None
    form_id: str

    def to_payload(self) -> dict[str, object]:
        return {
            "cardLabel": self.card_label,
            "accountLabel": self.account_label,
            "paymentType": self.payment_type,
            "paymentTypeLabel": self.payment_type_label,
            "fixedAmount": self.fixed_amount,
            "formId": self.form_id,
        }


@dataclass
class PendingAutoPayUpdate:
    """Staged by UpdateValidateAutoPay, consumed by UpdateAutoPay (J3)."""

    card_label: str
    account_label: str
    payment_type: str
    payment_type_label: str
    fixed_amount: float | None
    form_id: str
    token: str
    repeating_model_id: str

    def to_payload(self) -> dict[str, object]:
        return {
            "cardLabel": self.card_label,
            "accountLabel": self.account_label,
            "paymentType": self.payment_type,
            "paymentTypeLabel": self.payment_type_label,
            "fixedAmount": self.fixed_amount,
            "formId": self.form_id,
            "token": self.token,
            "repeatingModelId": self.repeating_model_id,
        }


@dataclass
class PendingAutoPayCancel:
    """Staged by CancelAutoPayOptions (the token fetch), consumed by
    CancelAutoPay (J4)."""

    repeating_model_id: str
    token: str
    card_label: str

    def to_payload(self) -> dict[str, object]:
        return {
            "repeatingModelId": self.repeating_model_id,
            "token": self.token,
            "cardLabel": self.card_label,
        }


@dataclass
class AutoPayState:
    """One card's AutoPay setup, per conversation — seeded from the
    AutoPayEnrollment fixtures, then mutated by J2 (enroll), J3 (update),
    and J4 (cancel)."""

    card_id: str
    payment_type: str
    payment_type_label: str
    fixed_amount: float | None
    account_id: str
    repeating_model_id: str
    active: bool = True


@dataclass
class ScheduledPaymentState:
    """One upcoming payment, per conversation — seeded from the
    ScheduledPayment fixtures. J5's CancelPayment flips ``status``."""

    payment_id: str
    card_id: str
    account_id: str
    amount: float
    payment_date: date
    kind: str  # "one_time" | "autopay"
    status: str = "SCHEDULED"  # → "CANCELED"


@dataclass
class ConvState:
    """The full per-conversation slice of the Chase store. One conversation
    is one journey (routing happens on the first meaningful turn and sticks);
    the slot fields below are grouped by the journey that uses them."""

    journey: str | None = None  # "J1".."J5" once routed

    # Card selection (all journeys)
    payee_list_fetched: bool = False
    modify_payee_list_fetched: bool = False  # J3/J4 active-only picker
    selected_card: Card | None = None

    # Funding account (J1/J2)
    funding_picker_fetched: bool = False
    funding_account: FundingAccount | None = None

    # J1 — one-time payment
    options: list[dict[str, object]] | None = None
    options_card_id: str | None = None
    represent_options: bool = False  # re-show the options list next prompt
    amount: float | None = None
    amount_label: str | None = None
    payment_date: date | None = None
    pending: PendingPayment | None = None
    # M2: set when a failed submission's reply offers a live agent; accepting
    # the offer hands off terminally.
    live_agent_offered: bool = False
    handed_off: bool = False

    # J2/J3 — AutoPay amount collection
    autopay_options_card_id: str | None = None
    autopay_payment_type: str | None = None  # optionId
    autopay_payment_type_label: str | None = None
    autopay_fixed_amount: float | None = None
    pending_autopay: PendingAutoPay | None = None

    # J3 — update flow
    autopay_status_shown: bool = False
    editing: bool = False
    update_token: str | None = None
    account_resolved: bool = False
    awaiting_warning_ack: bool = False
    warning_acknowledged: bool = False
    pending_autopay_update: PendingAutoPayUpdate | None = None

    # J4 — cancel flow
    turn_off_offered: bool = False
    pending_autopay_cancel: PendingAutoPayCancel | None = None

    # J5 — cancel scheduled payment
    activity_fetched: bool = False
    cancellable: list[ScheduledPaymentState] = field(default_factory=list)
    selected_payment: ScheduledPaymentState | None = None
    cancel_options_fetched: bool = False
    out_of_scope_explained: bool = False  # vary the repeated refusal wording
    out_of_scope_payment_id: str | None = None

    # Shared confirmation gate: exactly one pending object is staged when
    # this is True; the journey module knows which.
    awaiting_confirmation: bool = False

    # Per-conversation world, seeded from fixtures
    autopay: dict[str, AutoPayState] = field(default_factory=dict)
    scheduled_payments: list[ScheduledPaymentState] = field(default_factory=list)

    completed_payments: list[dict[str, object]] = field(default_factory=list)
    completed_actions: list[dict[str, object]] = field(default_factory=list)
    form_counter: int = 0

    def next_form_id(self) -> str:
        self.form_counter += 1
        return f"form-{self.form_counter:04d}"
