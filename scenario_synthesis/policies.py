"""Small, reviewed policy catalog for J1 blueprint construction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    id: str
    journeys: tuple[str, ...]
    required_fixture_predicates: tuple[str, ...]
    tool_assertions: tuple[str, ...]
    judge_hooks: tuple[str, ...]
    compatible_with: tuple[str, ...]
    incompatible_with: tuple[str, ...]


_ALL = (
    "explicit_confirmation",
    "tool_output_truth",
    "card_switch_resets",
    "disambiguate_last_four",
)

POLICIES: dict[str, Policy] = {
    "explicit_confirmation": Policy(
        id="explicit_confirmation",
        journeys=("J1",),
        required_fixture_predicates=(),
        tool_assertions=("validated_submit",),
        judge_hooks=("explicit_confirmation",),
        compatible_with=tuple(p for p in _ALL if p != "explicit_confirmation"),
        incompatible_with=(),
    ),
    "tool_output_truth": Policy(
        id="tool_output_truth",
        journeys=("J1",),
        required_fixture_predicates=(),
        tool_assertions=(),
        judge_hooks=("tool_output_truth",),
        compatible_with=tuple(p for p in _ALL if p != "tool_output_truth"),
        incompatible_with=(),
    ),
    "card_switch_resets": Policy(
        id="card_switch_resets",
        journeys=("J1",),
        required_fixture_predicates=("multiple_cards", "distinguishable_card_amounts"),
        tool_assertions=("refetch_after_card_switch", "amount_in_options"),
        judge_hooks=(),
        compatible_with=tuple(p for p in _ALL if p != "card_switch_resets"),
        incompatible_with=(),
    ),
    "disambiguate_last_four": Policy(
        id="disambiguate_last_four",
        journeys=("J1",),
        required_fixture_predicates=("ambiguous_card_names",),
        tool_assertions=(),
        judge_hooks=("disambiguate_last_four",),
        compatible_with=tuple(p for p in _ALL if p != "disambiguate_last_four"),
        incompatible_with=(),
    ),
}
