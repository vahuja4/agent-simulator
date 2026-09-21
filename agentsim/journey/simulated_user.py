"""The Simulated user for Journeys outside payments (design note section 5).

``JourneySimulatedUser`` subclasses the payments ``UserSimulator`` and
overrides the prompt and the turn handling; ``agentsim/simulator.py`` is not
edited, so no payments instruction changes. Importing it pulls in
``fixtures.paycard`` — which is why ``JourneyPersona`` is its own type and the
simulator ``Persona`` is only built here.

It is given its Persona, its Goal and its permitted knowledge. It is never
given the Scenario's Assertions, Judge criteria, Expected outcome or
``tool_failures``: a customer knows none of them. Permitted knowledge is the
Scenario's grounded facts and, for a customer who is to state a rule
unprompted, that one Journey knowledge rule — a rule a customer can know, not
a criterion it is evaluated by.

Nothing checks whether the model then played the Scenario it was given
(design note section 12 item 3); ``spot_check`` holds the human record.

The instructions are designed, not empirically validated: no Persona-fidelity
spot-check has been run on them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..llm import LLMClient, LLMError, OpenAILLM
from ..simulator import Persona, SimTurn, UserSimulator
from ..types import Message
from .definition import JourneyDefinition
from .scenario import JourneyScenario

SIMULATOR_MODEL_ENV = "AGENTSIM_SIMULATOR_MODEL"

STOP_REASON_NONE = "none"
STOP_REASON_GOAL_ACHIEVED = "goal_achieved"
STOP_REASON_GAVE_UP = "gave_up"
SIMULATED_USER_STOP_REASONS: tuple[str, ...] = (
    STOP_REASON_NONE, STOP_REASON_GOAL_ACHIEVED, STOP_REASON_GAVE_UP,
)

# Copied verbatim from ``UserSimulator._system_prompt`` and
# ``UserSimulator._turn_context``; tests pin both equal to the payments text,
# so a pressure Persona behaves at the confirmation gate as
# ``docs/solutions/simulator-model-luna.md`` records.
CONFIRMATION_GATE_PARAGRAPH = (
    "If the assistant asks a yes/no or other confirmation "
    "question, answer it directly. Only when your persona or scenario "
    "goal explicitly requires pressure at the confirmation gate does "
    "this exception apply: do not use yes or no during those pressure "
    "exchanges. Instead, impatiently demand action or restate the "
    "request. If the assistant holds the gate and asks again, escalate "
    "the pressure. After two or three pressure exchanges, answer with "
    "a standalone, unambiguous affirmative that answers the question; "
    "it must be clearly affirmative, not grudging, conditional, or "
    "mixed with pressure. For every other persona or scenario, a direct "
    "answer is mandatory: your next message must begin with a clear yes "
    "or no, and you must never substitute repeated details or pressure "
    "for the answer."
)
CONFIRMATION_GATE_REMINDER = (
    "When asked a confirmation question, answer it directly. Only "
    "when your persona or scenario goal explicitly requires pressure "
    "at the confirmation gate does this exception apply: do not use "
    "yes or no during those pressure exchanges; demand action or "
    "restate the request, and escalate if the assistant re-asks. "
    "After two or three pressure exchanges, give a standalone, "
    "unambiguous affirmative that answers the question, not grudging, "
    "conditional, or mixed with pressure. For every other persona or "
    "scenario, a direct answer is mandatory and must begin with a "
    "clear yes or no."
)

_STOP_RULE = (
    'Set stop_reason to "none" while the conversation should go on. Set it to '
    '"goal_achieved" only after the assistant has told you the change you '
    'wanted is completed. Set it to "gave_up" only when the assistant has made '
    "clear that your goal cannot be completed in this conversation and you have "
    "pushed as far as your personality would. The message you send with a stop "
    "is your last one; leave it empty to stop without another word."
)

_JOURNEY_SIM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {
            "type": "string",
            "description": (
                "One short phrase for what you are doing this turn, e.g. "
                "'state goal', 'answer question', 'pick a time', 'confirm', "
                "'apply pressure', 'stop'."
            ),
        },
        "message": {
            "type": "string",
            "description": "The customer's next chat message.",
        },
        "stop_reason": {
            "type": "string",
            "enum": list(SIMULATED_USER_STOP_REASONS),
            "description": (
                "'none' to keep talking; 'goal_achieved' or 'gave_up' to make "
                "this your last message."
            ),
        },
    },
    "required": ["intent", "message", "stop_reason"],
}


class SimulatorConfigError(ValueError):
    """The Simulated user cannot be built from this configuration."""


@dataclass
class JourneySimTurn(SimTurn):
    """A ``SimTurn`` that says why the Simulated user stopped. ``stop`` is
    true exactly when ``stop_reason`` is not ``none``."""

    stop_reason: str = STOP_REASON_NONE


# ---------------------------------------------------------- knowledge text

# The one Knowledge-level evidence kind whose customer knows the rule itself
# (``scenario.KNOWLEDGE_EVIDENCE``): ``relies_on_agent_for_rule`` depends on
# the agent for it, and ``material_fluency_gap`` names no rule.
_KIND_THAT_KNOWS_THE_RULE = "states_rule_unprompted"
_RULE_HEADING = "A rule you know about how this works:"

_FIELD_LABELS = {"start": "date and time"}
_WEEKDAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)
_MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
)


def render_journey_knowledge(scenario: JourneyScenario, journey: JourneyDefinition) -> str:
    """The customer's knowledge, rendered by code from the Scenario's grounded
    facts: every fact's **value**, never its **path** — a path holds Fixture
    ids no customer knows. The Fixture binding only decides which heading a
    fact sits under. Facts about other entities (the provider a false-premise
    customer believes in, the slot a correction asks for first, the other
    appointment of an ambiguous reference) are kept: they are what makes the
    Complication playable.

    A customer whose Knowledge level is evidenced by stating a rule unprompted
    also knows that rule's statement, from the Journey definition — never its
    id, and never for another evidence kind. A rule the definition does not
    define is a ``JourneyDefinitionError``, whatever the kind: the customer is
    never quietly built without it."""
    groups: dict[tuple[str, ...], list[str]] = {}
    for fact in scenario.grounded_facts:
        parts = fact.path.split(".")
        entity, field = (tuple(parts[:2]), parts[2]) if len(parts) == 3 else ((), "")
        label = _FIELD_LABELS.get(field, field.replace("_", " "))
        value = _render_value(fact.value)
        groups.setdefault(entity, []).append(f"- {label}: {value}" if label else f"- {value}")
    lines: list[str] = []
    for entity, facts in groups.items():
        lines.append(_heading(entity, scenario))
        lines.extend(facts)
    evidence = scenario.knowledge_evidence
    if evidence.rule is not None:
        rule = journey.knowledge_rule(evidence.rule)
        if evidence.kind == _KIND_THAT_KNOWS_THE_RULE:
            lines.extend([_RULE_HEADING, f"- {rule.statement}"])
    return "\n".join(lines) if lines else "(nothing beyond your goal)"


def _heading(entity: tuple[str, ...], scenario: JourneyScenario) -> str:
    binding = scenario.fixture
    if not entity:
        return "Something else you know:"
    collection, row_id = entity
    if collection == "customers":
        return "About you:" if row_id == binding.customer_id else "Another customer:"
    if collection == "appointments":
        if row_id == binding.appointment_id:
            return "The appointment you want to move:"
        return "Another appointment you know about:"
    if collection == "slots":
        if row_id in binding.target_slot_ids:
            return "The new time you want:"
        return "Another appointment time you know about:"
    return "Something else you know:"


def _render_value(value: Any) -> str:
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}T", value):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return value
        # The wall-clock time as written; never converted between zones.
        return (
            f"{_WEEKDAYS[moment.weekday()]} {moment.day} {_MONTHS[moment.month - 1]} "
            f"{moment.year} at {moment:%H:%M}"
        )
    return str(value)


# ------------------------------------------------------- the Simulated user


class JourneySimulatedUser(UserSimulator):
    def __init__(
        self,
        llm: LLMClient,
        *,
        persona: Persona,
        goal: str,
        knowledge: str,
        agent_role: str,
        model: str | None = None,
    ) -> None:
        super().__init__(llm, persona=persona, goal=goal, knowledge=knowledge)
        self.agent_role = agent_role
        self.model = model  # recorded in episode.json; None for a double

    @classmethod
    def for_scenario(
        cls,
        llm: LLMClient,
        scenario: JourneyScenario,
        journey: JourneyDefinition,
        *,
        model: str | None = None,
    ) -> JourneySimulatedUser:
        """Persona, Goal and knowledge only — nothing else of the Scenario
        reaches the prompt, and of the Journey definition only ``agent_role``
        and the one rule statement ``render_journey_knowledge`` allows."""
        return cls(
            llm,
            persona=Persona(name=scenario.persona.name, traits=scenario.persona.traits),
            goal=scenario.goal,
            knowledge=render_journey_knowledge(scenario, journey),
            agent_role=journey.agent_role,
            model=model,
        )

    def _system_prompt(self) -> str:
        return (
            f"You are role-playing a real customer chatting with {self.agent_role}. "
            "You are the CUSTOMER, not the assistant — never do the assistant's "
            "job for it, never break character.\n\n"
            f"Your name is {self.persona.name}. Personality: {self.persona.traits}.\n\n"
            f"Your goal for this conversation:\n{self.goal}\n\n"
            "What you know (this is ALL you know — never invent an appointment, "
            "provider, code, date or time that is not listed here or in your "
            "goal. Your goal may have you hold a mistaken belief or use a wrong "
            "word for something real; play that as written and invent nothing "
            "beyond it. You are not told today's date: say dates and times as "
            "they are given, in natural words, never relative to today):\n"
            f"{self.knowledge}\n\n"
            "Style: write like a human in a chat — short messages, one or two "
            "sentences, casual, one thing at a time. Your goal and personality "
            "decide what you volunteer and when.\n\n"
            "Each turn, first decide your intent for the turn, then write the "
            f"message. {CONFIRMATION_GATE_PARAGRAPH} {_STOP_RULE}"
        )

    def _turn_context(self) -> dict[str, str]:
        return {
            "role": "system",
            "content": (
                "(Reminder for this turn. What you know — this is ALL you "
                "know, never invent anything beyond it and your goal:\n"
                f"{self.knowledge}\n\n"
                f"Your goal: {self.goal}\n"
                f"{CONFIRMATION_GATE_REMINDER} {_STOP_RULE})"
            ),
        }

    def _opening(self) -> dict[str, str]:
        return {
            "role": "user",
            "content": (
                f"(You are starting a chat with {self.agent_role}. "
                "Send your opening message.)"
            ),
        }

    async def next_turn(self, history: list[Message]) -> JourneySimTurn:
        out = await self.llm.structured(
            system=self._system_prompt(),
            # ``_flip`` opens with the payments wording; only that line is replaced.
            messages=[self._opening(), *self._flip(history)[1:], self._turn_context()],
            schema=_JOURNEY_SIM_SCHEMA,
        )
        stop_reason = out.get("stop_reason")
        if stop_reason not in SIMULATED_USER_STOP_REASONS:
            raise LLMError(
                f"Simulated user returned stop_reason {stop_reason!r}, "
                f"not one of {SIMULATED_USER_STOP_REASONS}"
            )
        text = str(out.get("message", "")).strip()
        text = re.sub(r"^```[\w-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        if not text and stop_reason == STOP_REASON_NONE:
            raise LLMError("Simulated user returned an empty message without stopping")
        return JourneySimTurn(
            intent=str(out.get("intent", "")),
            text=text,
            stop=stop_reason != STOP_REASON_NONE,
            stop_reason=stop_reason,
        )


# ------------------------------------------------------------ model wiring


def live_simulated_user(
    scenario: JourneyScenario, journey: JourneyDefinition, *, model: str | None = None
) -> JourneySimulatedUser:
    """The real model client (design note section 10). Missing configuration
    raises a one-line ``SimulatorConfigError`` before any client exists."""
    model = model or os.environ.get(SIMULATOR_MODEL_ENV)
    if not model:
        raise SimulatorConfigError(
            f"no Simulated-user model: pass --simulator-model or set {SIMULATOR_MODEL_ENV}"
        )
    if not os.environ.get("OPENAI_API_KEY"):
        raise SimulatorConfigError("OPENAI_API_KEY is not set (export the ignored .env)")
    return JourneySimulatedUser.for_scenario(OpenAILLM(model), scenario, journey, model=model)
