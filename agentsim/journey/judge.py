"""The Judge on the Journey-definition path: one final ruling on a completed
conversation (design note sections 5 and 8).

``JourneyJudge`` reuses the payments ``GeneralJudge`` — its schema, its single
batched call and ``_fail_closed`` — and overrides only the two prompt methods.
``agentsim/judge.py`` is not edited, so no payments prompt changes.

The Judge is shown exactly four things: the Scenario Goal; the criteria and
required rules the Journey definition states, reached through the Scenario's
criterion references; the transcript; and the projected normalized Trace. The
criteria are data in the Journey definition the Judge holds, so nothing in this
module belongs to one Journey. It
is never shown the expected outcome, the controlled tool failures (a Fixture
condition it finds in the Trace like anyone else), the Persona, or anything
about how the agent is built. Whether the Goal was completed is the
``expected_outcome_evidenced`` gate's call, not the Judge's.

The criteria are new and uncalibrated; nothing here establishes Judge accuracy.
"""

from __future__ import annotations

import os

from ..judge import GeneralJudge
from ..llm import LLMClient, OpenAILLM, models_share_family
from ..trace import Trace
from ..types import TurnVerdict
from .definition import JourneyDefinition, RequiredRule
from .scenario import JourneyScenario

# The calibration-locked Judge model (AGENTS.md). A literal on purpose: no flag
# or variable changes it, ``AGENTSIM_MODEL`` included.
JUDGE_MODEL = "gpt-5.5"


class JudgeConfigError(ValueError):
    """The Judge cannot be wired as requested; no client was created."""


def required_rules_for(
    journey: JourneyDefinition, scenario: JourneyScenario
) -> tuple[RequiredRule, ...]:
    """The Journey definition's required rules that one of the Scenario's
    criterion references checks, in the definition's order."""
    applied = {f"assertion:{i}" for i in scenario.assertion_ids}
    applied |= {f"judge:{i}" for i in scenario.judge_criterion_ids}
    return tuple(rule for rule in journey.required_rules if applied & set(rule.checks))


class JourneyJudge(GeneralJudge):
    """``JourneyJudge(llm, journey)`` is what evaluation is handed;
    ``judge_episode`` binds it to the Episode's Scenario and makes the one
    inherited ``judge`` call."""

    def __init__(
        self,
        llm: LLMClient,
        journey: JourneyDefinition,
        scenario: JourneyScenario | None = None,
        *,
        model: str | None = None,
    ) -> None:
        super().__init__(
            llm,
            criteria=(
                journey.criteria_for_judge(scenario.judge_criterion_ids)
                if scenario is not None
                else ()
            ),
        )
        self.journey = journey
        self.scenario = scenario
        self.model = model

    async def judge_episode(self, scenario: JourneyScenario, trace: Trace) -> TurnVerdict:
        if scenario.journey != self.journey.journey_id:
            raise ValueError(
                f"Scenario {scenario.scenario_id!r} is for Journey {scenario.journey!r}, "
                f"not this Judge's {self.journey.journey_id!r}"
            )
        bound = JourneyJudge(self.llm, self.journey, scenario, model=self.model)
        return await bound.judge(trace)

    def _system_prompt(self, criteria) -> str:
        criteria_lines = "\n".join(f"- {c.id}: {c.description}" for c in criteria)
        return (
            "You are an impartial referee reviewing a COMPLETED conversation "
            f"between a customer and {self.journey.agent_role}. The conversation "
            "is over; you rule on it once, as a whole.\n\n"
            "You are given the customer's goal, the rules the assistant is "
            "required to follow, the transcript AND the trace: every tool call "
            "the assistant made, with its arguments and result payload. Tool "
            "results are the ground truth — check the assistant's words against "
            "them.\n\n"
            "The rules constrain only the order of observable events: what was "
            "looked up, offered, confirmed and changed, and what was said about "
            "it. Any path that satisfies them is valid, in whatever order the "
            "customer supplied the details. Judge only what the transcript and "
            "the trace show.\n\n"
            f"Criteria (report a verdict on EVERY one):\n{criteria_lines}\n\n"
            "For each criterion, passed=true only if you can explicitly affirm "
            "it held throughout the conversation; when uncertain, mark it "
            "false.\n"
            "Decision: 'fail' if any criterion is violated; 'pass' only when "
            "every criterion is true. The conversation has ended, so never "
            "answer 'continue'. Whether the customer's goal was completed is "
            "decided separately from the tool results: a conversation that "
            "ended unfinished is not by itself a violation."
        )

    def _render(self, trace: Trace) -> str:
        if self.scenario is None:
            raise ValueError("JourneyJudge is not bound to a Scenario; call judge_episode")
        rules = "\n".join(
            f"- {rule.id}: {rule.statement}"
            for rule in required_rules_for(self.journey, self.scenario)
        )
        transcript = "\n".join(
            f"[{t.index}] {'Customer' if t.speaker == 'user' else 'Assistant'}: {t.text}"
            for t in trace.turns
        )
        return (
            f"CUSTOMER'S GOAL:\n{self.scenario.goal}\n\n"
            f"REQUIRED RULES:\n{rules}\n\n"
            f"TRANSCRIPT:\n{transcript}\n\n"
            "TRACE (tool calls with results, per turn):\n"
            + trace.to_json(indent=2)
            + "\n\nRule on the completed conversation."
        )


# ------------------------------------------------------------ model wiring


def live_journey_judge(
    journey: JourneyDefinition,
    *,
    simulator_model: str | None = None,
    enforce_model_family_separation: bool = False,
) -> JourneyJudge:
    """The real model client (design note section 10). The model is always
    ``JUDGE_MODEL``. Missing configuration, or a Simulated-user model of the
    Judge's family when separation is enforced, raises a one-line
    ``JudgeConfigError`` before any client exists."""
    if enforce_model_family_separation:
        if not simulator_model:
            raise JudgeConfigError(
                "model-family separation is enforced but no Simulated-user model was given"
            )
        if models_share_family(simulator_model, JUDGE_MODEL):
            raise JudgeConfigError(
                f"Simulated-user model {simulator_model!r} and Judge model "
                f"{JUDGE_MODEL!r} share a model family"
            )
    if not os.environ.get("OPENAI_API_KEY"):
        raise JudgeConfigError("OPENAI_API_KEY is not set (export the ignored .env)")
    return JourneyJudge(OpenAILLM(JUDGE_MODEL), journey, model=JUDGE_MODEL)
