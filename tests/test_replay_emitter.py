import pytest

from agentsim.adapters import MockConfig, MockPayCardAgent
from agentsim.orchestrator import run_conversation
from agentsim.replay import emit_replay, load_replay
from test_assertions_defects import trace_for


CASES = {
    "D1": (
        {"d1_same_turn_after_validation": True},
        [
            "Just pay my Sapphire card right now, skip the questions.",
            "From my checking, hurry up.",
            "The minimum due.",
            "Today.",
        ],
    ),
    "D2": (
        {"d2_stale_options_after_card_switch": True},
        [
            "Pay my Sapphire card from my checking account.",
            "Actually, let's pay my Freedom Unlimited instead.",
            "The statement balance.",
            "Today.",
        ],
    ),
    "D3": (
        {"d3_false_success_on_failed_submit": True},
        [
            "Pay my Sapphire card.",
            "From my checking account.",
            "$6,000",
            "Today.",
            "Yes, go ahead.",
        ],
    ),
    "D4": (
        {"d4_no_warning_below_minimum_autopay": True},
        [
            "I want to change my autopay.",
            "Edit it please.",
            "A fixed amount of $25.",
            "Keep the same account.",
            "Yes, confirm the update.",
        ],
    ),
    "D5": (
        {"d5_silent_card_disambiguation": True},
        ["I want to pay my Freedom card."],
    ),
    "D6": (
        {"d6_autopay_listed_in_cancellable": True},
        [
            "I need to cancel a scheduled payment.",
            "The $875.20 one.",
            "Cancel it.",
        ],
    ),
    "D7": (
        {"d7_no_external_account_warning": True},
        [
            "Set up autopay on my Freedom Flex ending 4421.",
            "The minimum due.",
            "From my Ally Savings account.",
            "Yes, go ahead.",
        ],
    ),
}


@pytest.mark.parametrize("defect", sorted(CASES))
async def test_emitted_replay_reproduces_acceptance_defect_tool_sequence(defect, tmp_path):
    flags, user_lines = CASES[defect]
    trace = await trace_for(user_lines, **flags)
    trace.outcome = "fail"  # the semantic judge supplies this in acceptance runs
    path = emit_replay(trace, tmp_path / f"{defect}.json")
    steps = load_replay(path)

    replayed = await run_conversation(
        agent=MockPayCardAgent(MockConfig(**flags)),
        script=steps,
        max_turns=len(user_lines),
    )
    assert replayed.trace.tool_call_names() == trace.tool_call_names()
    assert [turn.text for turn in replayed.trace.turns] == [turn.text for turn in trace.turns]
