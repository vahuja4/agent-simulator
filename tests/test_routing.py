"""Journey-router precedence, pinned explicitly (Phase 2 review item 1b).
The router sees lowercased text, as the agent lowercases before parsing."""

from __future__ import annotations

import pytest

from agentsim.adapters.mock_paycard.parsing import route_journey


@pytest.mark.parametrize(
    ("text", "journey"),
    [
        # J2 — AutoPay mention alone
        ("i'd like to set up autopay on my freedom unlimited", "J2"),
        ("can i get automatic payments going?", "J2"),
        ("i want recurring payments", "J2"),
        # J3 — AutoPay + change/update wording
        ("i want to change my autopay amount", "J3"),
        ("update my automatic payments please", "J3"),
        ("edit autopay", "J3"),
        # J4 — AutoPay + cancel-ish wording (beats J3 wording if both appear)
        ("turn off autopay on my sapphire", "J4"),
        ("cancel my autopay", "J4"),
        ("i want to stop the automatic payments", "J4"),
        # J5 — cancel-ish + a payment referent, no AutoPay mention
        ("i need to cancel a scheduled payment", "J5"),
        ("cancel the $150 payment on june 20", "J5"),
        # J1 — pay intent
        ("hi, i'd like to pay my credit card", "J1"),
        ("i want to pay my freedom card", "J1"),
        # Unrouted — greet and wait
        ("hi", None),
        ("hello, quick question", None),
    ],
)
def test_routing_precedence(text: str, journey: str | None):
    assert route_journey(text) == journey


def test_cancel_autopay_payment_referent_routes_to_j4():
    # Pinned deliberately: "cancel my autopay payment on june 20" means a
    # specific pending payment (J5 territory, where the mock correctly
    # refuses AutoPay pendings), but the AutoPay mention wins and routes to
    # J4 (turn AutoPay off). Routing cancel + autopay + specific-payment
    # referent to J5 is a known candidate refinement, deferred with the
    # cross-journey mind-change work — see route_journey's docstring. The D6
    # scenario's opener must therefore avoid "autopay" phrasing
    # (scenarios/j5_cancel_autopay_pending.yaml).
    assert route_journey("cancel my autopay payment on june 20") == "J4"
