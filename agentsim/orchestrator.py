"""The turn loop: user simulator → agent adapter → trace append → assertions
→ judge, until a verdict, a ###STOP###, or max_turns. Everything observable
about the run lands in the Trace; verdicts and merged failures ride alongside
in the RunResult.

Scripted steps (script.py, amendment 17) run through this same loop: a
script's user()/agent() steps produce the same Trace shape as autonomous
turns, assertions run after every agent turn either way, the judge rules only
at explicit judge() checkpoints while scripted, and proceed() hands over to
the autonomous simulator loop under the shared max_turns budget.

Outcome derivation (amendment 14 + adjustment 1): a deterministic assertion
failure fails the run immediately — before that turn's judge call, so the
hard gate is structural (the judge never rules on a turn an assertion already
failed). A "pass" is judge-earned only: assertions can force fail, never
produce pass; a script that ends with no judge ruling is task_incomplete.
Reaching max_turns (or the simulator stopping) without goal completion is
likewise ``task_incomplete`` — running out of turns is not a policy failure.

The stop-on-assertion-failure decision lives HERE, in the outcome
derivation, not inside AssertionEngine (adjustment 3) — a future collect
mode (continue past failures on expensive real-agent runs) is a parameter
in this loop, not an engine refactor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Sequence

from .assertions import AssertionEngine
from .llm import LLMError
from .script import AgentStep, JudgeStep, ProceedStep, Step, UserStep, validate_script
from .trace import Trace
from .types import AgentInput, FailureRecord, Message, TurnVerdict


@dataclass
class RunResult:
    trace: Trace
    verdicts: list[TurnVerdict] = field(default_factory=list)
    outcome: str = "task_incomplete"  # pass | fail | task_incomplete | error
    final_reasoning: str = ""
    # Every failure with its source — assertion vs judge, and which
    # criterion/assertion — as structured data (amendment 14).
    failures: list[FailureRecord] = field(default_factory=list)
    # Structured visibility for checks that could not fully evaluate. The
    # assertion report remains reporting-only; degradation never changes the
    # run outcome here.
    degraded_checks: list[dict] = field(default_factory=list)
    # Harness-side LLM calls attempted by the simulator and judge. Calls made
    # internally by the black-box agent adapter are outside this counter.
    llm_calls: int = 0


def _judge_failures(verdict: TurnVerdict, turn_index: int) -> list[FailureRecord]:
    return [
        FailureRecord(
            source="judge",
            id=cv.criterion_id,
            turn_index=turn_index,
            message=cv.reasoning,
        )
        for cv in verdict.criteria
        if not cv.passed
    ]


async def run_conversation(
    *,
    simulator=None,
    agent,
    judge=None,
    conversation_id: str = "conv-1",
    max_turns: int = 12,
    assertions: AssertionEngine | None = None,
    script: Sequence[Step] | None = None,
) -> RunResult:
    steps = list(script) if script is not None else []
    if steps:
        validate_script(steps)
        if simulator is None and any(
            isinstance(s, ProceedStep) or (isinstance(s, UserStep) and s.text is None)
            for s in steps
        ):
            raise ValueError("script delegates turns to the simulator but simulator is None")
        if judge is None and any(isinstance(s, (JudgeStep, ProceedStep)) for s in steps):
            raise ValueError("script requires a judge (judge()/proceed()) but judge is None")
    else:
        if simulator is None or judge is None:
            raise ValueError("autonomous runs require both a simulator and a judge")

    trace = Trace(conversation_id=conversation_id)
    history: list[Message] = []
    verdicts: list[TurnVerdict] = []
    failures: list[FailureRecord] = []
    degraded_checks: list[dict] = []
    selected_card: str | None = None
    turns_used = 0
    llm_calls = 0

    def add_user_turn(text: str, intent: str | None) -> None:
        nonlocal turns_used
        history.append(Message("user", text))
        # selected_card on a user turn is the last agent-reported value.
        trace.add_user_turn(text, intent, selected_card)
        turns_used += 1

    async def run_agent_turn() -> tuple[str, str] | None:
        """Agent reply + trace append + the assertion hard gate."""
        nonlocal selected_card, degraded_checks
        response = await agent.call(AgentInput(conversation_id, list(history)))
        history.append(Message("assistant", response.content))
        selected_card = response.selected_card
        trace.add_agent_turn(
            response.content,
            response.tool_calls,
            selected_card,
        )
        if assertions is not None:
            report = assertions.check(trace)
            # The engine is prefix-safe and its latest report describes the
            # entire trace-so-far. Deduplicate structurally for stable
            # artifacts without changing any assertion semantics.
            seen: set[str] = set()
            degraded_checks = []
            for item in report.degraded:
                key = json.dumps(item, sort_keys=True, default=str)
                if key not in seen:
                    seen.add(key)
                    degraded_checks.append(dict(item))
            if report.failures:
                failures.extend(report.failures)
                return (
                    "fail",
                    "deterministic assertion failure: "
                    + "; ".join(f.message for f in report.failures),
                )
        return None

    async def run_judge() -> tuple[str, str] | None:
        nonlocal llm_calls
        llm_calls += 1
        verdict = await judge.judge(trace)
        verdicts.append(verdict)
        if verdict.decision in ("pass", "fail"):
            if verdict.decision == "fail":
                failures.extend(_judge_failures(verdict, trace.turns[-1].index))
            return (verdict.decision, verdict.reasoning)
        return None

    async def autonomous(budget: int, exhausted_reason: str) -> tuple[str, str]:
        nonlocal llm_calls
        for _ in range(budget):
            llm_calls += 1
            sim_turn = await simulator.next_turn(history)
            if sim_turn.stop and not sim_turn.text.strip():
                return ("task_incomplete", "user simulator stopped before goal completion")
            add_user_turn(sim_turn.text, sim_turn.intent)
            ended = await run_agent_turn()
            if ended:
                return ended
            ended = await run_judge()
            if ended:
                return ended
            if sim_turn.stop:
                return (
                    "task_incomplete",
                    "user simulator stopped; judge had not reached a verdict",
                )
        return ("task_incomplete", exhausted_reason)

    max_turns_reason = f"max_turns ({max_turns}) reached without goal completion"

    async def scripted() -> tuple[str, str]:
        nonlocal llm_calls
        sim_requested_stop = False
        for step in steps:
            if isinstance(step, UserStep):
                if turns_used >= max_turns:
                    return ("task_incomplete", max_turns_reason)
                if step.text is None:
                    llm_calls += 1
                    sim_turn = await simulator.next_turn(history)
                    if sim_turn.stop and not sim_turn.text.strip():
                        return (
                            "task_incomplete",
                            "user simulator stopped before goal completion",
                        )
                    sim_requested_stop = sim_turn.stop
                    add_user_turn(sim_turn.text, sim_turn.intent)
                else:
                    sim_requested_stop = False
                    add_user_turn(step.text, "scripted")
            elif isinstance(step, AgentStep):
                ended = await run_agent_turn()
                if ended:
                    return ended
            elif isinstance(step, JudgeStep):
                ended = await run_judge()
                if ended:
                    return ended
                if sim_requested_stop:
                    return (
                        "task_incomplete",
                        "user simulator stopped; judge had not reached a verdict",
                    )
            elif isinstance(step, ProceedStep):
                budget = max_turns - turns_used
                reason = max_turns_reason
                if step.turns is not None and step.turns < budget:
                    budget = step.turns
                    reason = f"proceed(turns={step.turns}) exhausted without a verdict"
                return await autonomous(budget, reason)
        # Adjustment 1: assertions alone can force fail, never produce pass —
        # a script that ends with no judge ruling is task_incomplete.
        return ("task_incomplete", "script ended without a judge ruling")

    try:
        if steps:
            outcome, reasoning = await scripted()
        else:
            outcome, reasoning = await autonomous(max_turns, max_turns_reason)
    except LLMError as e:
        outcome, reasoning = "error", f"harness LLM call failed: {e}"

    trace.outcome = outcome
    return RunResult(
        trace=trace,
        verdicts=verdicts,
        outcome=outcome,
        final_reasoning=reasoning,
        failures=failures,
        degraded_checks=degraded_checks,
        llm_calls=llm_calls,
    )
