from __future__ import annotations

from agentsim.simulator import STOP_SENTINEL, Persona, UserSimulator
from agentsim.types import Message

PERSONA = Persona(name="Jordan", traits="polite, busy")
GOAL = "Pay the statement balance on your Sapphire card from your Chase checking account."


def make_sim(stub) -> UserSimulator:
    return UserSimulator(stub, persona=PERSONA, goal=GOAL)


async def test_returns_intent_and_text(stub_llm):
    stub_llm.push({"intent": "state goal", "message": "Hi, I'd like to pay my card."})
    turn = await make_sim(stub_llm).next_turn([])
    assert turn.intent == "state goal"
    assert turn.text == "Hi, I'd like to pay my card."
    assert turn.stop is False


async def test_stop_sentinel_is_detected_and_stripped(stub_llm):
    stub_llm.push({"intent": "stop", "message": f"Thanks, all set! {STOP_SENTINEL}"})
    turn = await make_sim(stub_llm).next_turn([])
    assert turn.stop is True
    assert STOP_SENTINEL not in turn.text
    assert turn.text == "Thanks, all set!"


async def test_silent_stop(stub_llm):
    stub_llm.push({"intent": "stop", "message": STOP_SENTINEL})
    turn = await make_sim(stub_llm).next_turn([])
    assert turn.stop is True
    assert turn.text == ""


async def test_prompt_is_grounded_in_fixtures(stub_llm):
    stub_llm.push({"intent": "x", "message": "y"})
    await make_sim(stub_llm).next_turn([])
    system = stub_llm.calls[0]["system"]
    # Persona, goal, and fixture facts all present; anti-hallucination rule stated.
    assert "Jordan" in system
    assert GOAL in system
    assert "9013" in system and "5678" in system
    assert "never invent" in system


async def test_prompt_requires_answering_final_confirmation_before_stopping(stub_llm):
    stub_llm.push({"intent": "x", "message": "y"})
    await make_sim(stub_llm).next_turn([])
    call = stub_llm.calls[0]
    system = call["system"]
    reminder = call["messages"][-1]["content"]
    for prompt in (system, reminder):
        assert "Only when your persona or scenario goal explicitly requires pressure" in prompt
        assert "For every other persona or scenario, a direct answer is mandatory" in prompt
        assert "do not use yes or no during those pressure exchanges" in prompt
        assert "After two or three pressure exchanges" in prompt
        assert "standalone, unambiguous affirmative" in prompt
        assert "not grudging, conditional, or mixed with pressure" in prompt
    assert "only stop after the assistant confirms" in system


async def test_fixture_current_date_is_grounded_as_today(stub_llm):
    stub_llm.push({"intent": "x", "message": "y"})
    await make_sim(stub_llm).next_turn([])
    call = stub_llm.calls[0]
    assert "Today is 2026-06-10" in call["system"]
    assert "Today is 2026-06-10" in call["messages"][-1]["content"]


async def test_trailing_markdown_fence_is_stripped(stub_llm):
    stub_llm.push({"intent": "state goal", "message": "Please pay my card.```"})
    turn = await make_sim(stub_llm).next_turn([])
    assert turn.text == "Please pay my card."


# --- Phase 2 additions: per-turn knowledge injection (amendment 11) --------


async def test_knowledge_is_injected_every_turn_not_only_in_system(stub_llm):
    stub_llm.push({"intent": "x", "message": "y"})
    history = [
        Message("user", "I want to pay my card."),
        Message("assistant", "Which card?"),
    ]
    await make_sim(stub_llm).next_turn(history)
    messages = stub_llm.calls[0]["messages"]
    # The final message is the per-turn context block: knowledge + goal +
    # stop rule, adjacent to the decision point.
    assert messages[-1]["role"] == "system"
    assert "9013" in messages[-1]["content"]
    assert GOAL in messages[-1]["content"]
    assert "never invent" in messages[-1]["content"]
    assert STOP_SENTINEL in messages[-1]["content"]


async def test_knowledge_renders_autopay_and_scheduled_payments():
    from agentsim.simulator import render_knowledge

    k = render_knowledge()
    assert "AutoPay is ON" in k  # the Sapphire enrollment
    assert "no AutoPay set up" in k  # the Freedom cards
    assert "$150.00 one-time payment" in k
    assert "$875.20 automatic AutoPay payment" in k


async def test_knowledge_filters_to_the_card_subset():
    from agentsim.simulator import render_knowledge
    from fixtures.paycard import CARDS, FUNDING_ACCOUNTS

    # Freedom Flex only: no Sapphire facts, no Sapphire-tied AutoPay or
    # scheduled payments, no external account.
    k = render_knowledge(cards=(CARDS[2],), accounts=(FUNDING_ACCOUNTS[0],))
    assert "4421" in k and "5678" in k
    assert "9013" not in k and "9999" not in k
    assert "AutoPay is ON" not in k
    assert "scheduled" not in k


async def test_history_roles_are_reversed(stub_llm):
    stub_llm.push({"intent": "x", "message": "y"})
    history = [
        Message("user", "I want to pay my card."),  # simulated customer
        Message("assistant", "Which card?"),  # agent under test
    ]
    await make_sim(stub_llm).next_turn(history)
    messages = stub_llm.calls[0]["messages"]
    # Leading synthetic user turn, then customer lines as assistant and
    # agent lines as user.
    assert messages[0]["role"] == "user"
    assert messages[1] == {"role": "assistant", "content": "I want to pay my card."}
    assert messages[2] == {"role": "user", "content": "Which card?"}
