"""Scripting DSL (design §7, amendment 17): user() / agent() / judge() /
proceed(). Scripted steps and autonomous simulation share the orchestrator
machinery and produce the same Trace — ``run_conversation(script=...)``
interprets these steps inside its one turn loop.

Steps are plain serializable dataclasses, not closures, so a scripted opening
can later be generated mechanically from a recorded trace's turn list
(user(text) per user turn, agent() per agent turn — the Phase 4 replay
emitter is a trivial map, designed for here but not built).

Semantics in the orchestrator:
- user("...")  injects that user message (trace intent "scripted");
  user() with no text delegates the turn to the user simulator.
- agent()      the agent-under-test replies; assertions run as always.
- judge()      an explicit checkpoint — while scripted, the judge rules ONLY
  here (pinned openings don't spend LLM calls being refereed turn-by-turn).
- proceed(n)   hands control to the autonomous loop (simulator + per-turn
  judge) for n user turns, or until max_turns/verdict if n is omitted.
  Must be the final step.

A script with zero judge() checkpoints and no proceed() can therefore never
pass: a pass is judge-earned only (adjustment 1) — assertions can force
fail, and a script that just ends yields task_incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


class ScriptError(Exception):
    """A script failed validation; the message names the step position."""


@dataclass(frozen=True)
class UserStep:
    text: str | None = None  # None → the user simulator produces this turn

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "user", "text": self.text}


@dataclass(frozen=True)
class AgentStep:
    def to_dict(self) -> dict[str, Any]:
        return {"kind": "agent"}


@dataclass(frozen=True)
class JudgeStep:
    def to_dict(self) -> dict[str, Any]:
        return {"kind": "judge"}


@dataclass(frozen=True)
class ProceedStep:
    turns: int | None = None  # None → whatever max_turns still allows

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "proceed", "turns": self.turns}


Step = UserStep | AgentStep | JudgeStep | ProceedStep


def user(text: str | None = None) -> UserStep:
    return UserStep(text=text)


def agent() -> AgentStep:
    return AgentStep()


def judge() -> JudgeStep:
    return JudgeStep()


def proceed(turns: int | None = None) -> ProceedStep:
    return ProceedStep(turns=turns)


def step_from_dict(d: dict[str, Any]) -> Step:
    kind = d.get("kind")
    if kind == "user":
        return UserStep(text=d.get("text"))
    if kind == "agent":
        return AgentStep()
    if kind == "judge":
        return JudgeStep()
    if kind == "proceed":
        return ProceedStep(turns=d.get("turns"))
    raise ScriptError(f"unknown step kind {kind!r}")


def script_to_dicts(steps: Sequence[Step]) -> list[dict[str, Any]]:
    return [s.to_dict() for s in steps]


def script_from_dicts(dicts: Sequence[dict[str, Any]]) -> list[Step]:
    return [step_from_dict(d) for d in dicts]


def validate_script(steps: Sequence[Step]) -> None:
    """Reject malformed sequences with the step position named: user turns
    and agent turns must alternate (that is the Trace's shape), judge() only
    after a completed exchange, proceed() only as the final step."""
    if not steps:
        raise ScriptError("script is empty")
    pending_user = False
    agent_has_spoken = False
    for i, step in enumerate(steps):
        where = f"script step {i}"
        if isinstance(step, UserStep):
            if pending_user:
                raise ScriptError(f"{where}: user() follows user() without agent()")
            pending_user = True
        elif isinstance(step, AgentStep):
            if not pending_user:
                raise ScriptError(f"{where}: agent() without a preceding user()")
            pending_user = False
            agent_has_spoken = True
        elif isinstance(step, JudgeStep):
            if pending_user:
                raise ScriptError(f"{where}: judge() between user() and agent()")
            if not agent_has_spoken:
                raise ScriptError(f"{where}: judge() before any agent turn")
        elif isinstance(step, ProceedStep):
            if pending_user:
                raise ScriptError(f"{where}: proceed() between user() and agent()")
            if i != len(steps) - 1:
                raise ScriptError(f"{where}: proceed() must be the final step")
            if step.turns is not None and step.turns <= 0:
                raise ScriptError(f"{where}: proceed(turns=) must be positive")
        else:
            raise ScriptError(f"{where}: not a script step: {step!r}")
    if pending_user:
        raise ScriptError("script ends with a user() awaiting its agent() turn")
