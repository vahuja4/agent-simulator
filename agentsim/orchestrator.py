"""The turn loop: user simulator → agent adapter → trace append → judge,
until a verdict, a ###STOP###, or max_turns. Everything observable about the
run lands in the Trace; verdicts ride alongside in the RunResult.

Reaching max_turns (or the simulator stopping) without goal completion is a
distinct ``task_incomplete`` outcome — running out of turns is not a policy
failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LLMError
from .trace import Trace, TraceToolCall
from .types import AgentInput, Message, TurnVerdict


@dataclass
class RunResult:
    trace: Trace
    verdicts: list[TurnVerdict] = field(default_factory=list)
    outcome: str = "task_incomplete"  # pass | fail | task_incomplete | error
    final_reasoning: str = ""


async def run_conversation(
    *,
    simulator,
    agent,
    judge,
    conversation_id: str = "conv-1",
    max_turns: int = 12,
) -> RunResult:
    trace = Trace(conversation_id=conversation_id)
    history: list[Message] = []
    verdicts: list[TurnVerdict] = []
    outcome = "task_incomplete"
    reasoning = f"max_turns ({max_turns}) reached without goal completion"
    selected_card: str | None = None

    try:
        for _ in range(max_turns):
            sim_turn = await simulator.next_turn(history)
            if sim_turn.stop and not sim_turn.text.strip():
                reasoning = "user simulator stopped before goal completion"
                break

            history.append(Message("user", sim_turn.text))
            # selected_card on a user turn is the last agent-reported value.
            trace.add_user_turn(sim_turn.text, sim_turn.intent, selected_card)

            response = await agent.call(AgentInput(conversation_id, list(history)))
            history.append(Message("assistant", response.content))
            selected_card = response.selected_card
            trace.add_agent_turn(
                response.content,
                [TraceToolCall(t.name, t.arguments, t.result) for t in response.tool_calls],
                selected_card,
            )

            verdict = await judge.judge(trace)
            verdicts.append(verdict)
            if verdict.decision in ("pass", "fail"):
                outcome = verdict.decision
                reasoning = verdict.reasoning
                break
            if sim_turn.stop:
                reasoning = "user simulator stopped; judge had not reached a verdict"
                break
    except LLMError as e:
        outcome = "error"
        reasoning = f"harness LLM call failed: {e}"

    trace.outcome = outcome
    return RunResult(trace=trace, verdicts=verdicts, outcome=outcome, final_reasoning=reasoning)
