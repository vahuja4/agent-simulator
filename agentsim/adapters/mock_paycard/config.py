"""Per-defect toggles (design §6). All False = faithful agent."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MockConfig:
    """One boolean per planted defect. Each flag gates a single deviation
    inline in a journey module (marked with a ``# D<n>:`` comment); with all
    flags False the mock follows every journey invariant faithfully."""

    # D1 has two independently reproducible shapes. Keeping them as explicit
    # modes prevents the recall harness from depending on a particular
    # pressure phrase to select which defect behavior it is exercising.
    d1_same_turn_after_validation: bool = False
    d1_submit_on_reask: bool = False
    d2_stale_options_after_card_switch: bool = False
    d3_false_success_on_failed_submit: bool = False
    d4_no_warning_below_minimum_autopay: bool = False
    d5_silent_card_disambiguation: bool = False
    d6_autopay_listed_in_cancellable: bool = False
    d7_no_external_account_warning: bool = False
