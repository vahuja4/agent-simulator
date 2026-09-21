"""Hand-built normalized Traces and Journey Scenarios for offline tests.

Raw → normalized is the adapter side's job; until it exists, tests state the
normalized facts directly. ``TraceBuilder.turn`` lays out one Turn the way the
agent service records it: the user message, the actions it caused, then the
agent reply those actions name as ``reply_message_id``.
"""

from __future__ import annotations

from typing import Any

from agentsim.journey import checks
from agentsim.journey.definition import load_journey_definition
from agentsim.journey.normalized_trace import (
    ActionError,
    Evidence,
    NormalizedTrace,
    TraceAction,
    TraceMessage,
)
from agentsim.journey.scenario import (
    FixtureBinding,
    JourneyPersona,
    JourneyScenario,
    JourneySynthesis,
    KnowledgeEvidence,
)

AVAILABLE = Evidence(messages="available", actions="available")
JOURNEY = load_journey_definition("journeys/appointment_rescheduling/journey.yaml")


def lookup(*appointment_ids: str, **overrides: Any) -> dict[str, Any]:
    return {
        "tool_name": checks.LOOKUP_APPOINTMENTS,
        "arguments": {"confirmation_code": "HSD-4821"},
        "result": {"appointments": [{"appointment_id": a} for a in appointment_ids]},
        **overrides,
    }


def find_slots(appointment_id: str, *slot_ids: str, **overrides: Any) -> dict[str, Any]:
    return {
        "tool_name": checks.FIND_AVAILABLE_SLOTS,
        "arguments": {"appointment_id": appointment_id},
        "result": {"slots": [{"slot_id": s} for s in slot_ids]},
        **overrides,
    }


def update(appointment_id: Any, slot_id: Any, *, failed: bool = False, **overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "tool_name": checks.UPDATE_APPOINTMENT,
        "arguments": {"appointment_id": appointment_id, "slot_id": slot_id},
        "result": {"appointment": {"appointment_id": appointment_id}},
    }
    if failed:
        spec.update(
            status="failed",
            result=None,
            error=ActionError("update_failed", "the appointment system rejected the update"),
        )
    return {**spec, **overrides}


class TraceBuilder:
    def __init__(self) -> None:
        self.messages: list[TraceMessage] = []
        self.actions: list[TraceAction] = []
        self._sequence = 0

    def _next(self) -> int:
        self._sequence += 1
        return self._sequence

    def turn(self, user_text: str, reply_text: str, *actions: dict[str, Any]) -> "TraceBuilder":
        user_id = f"m{len(self.messages) + 1}"
        reply_id = f"m{len(self.messages) + 2}"
        self.messages.append(TraceMessage(user_id, self._next(), "user", user_text))
        for spec in actions:
            fields = {
                "action_id": f"a{len(self.actions) + 1}",
                "sequence": self._next(),
                "result_available": True,
                "status": "succeeded",
                "error": None,
                "caused_by_message_id": user_id,
                "reply_message_id": reply_id,
                **spec,
            }
            self.actions.append(TraceAction(**fields))
        self.messages.append(TraceMessage(reply_id, self._next(), "agent", reply_text))
        return self

    def build(self, evidence: Evidence = AVAILABLE, tool_failures: tuple[str, ...] = ()) -> NormalizedTrace:
        return NormalizedTrace(
            conversation_id="conv-1",
            platform="journey-service",
            fixture_state_sha256="0" * 64,
            tool_failures=tool_failures,
            evidence=evidence,
            messages=tuple(self.messages),
            actions=tuple(self.actions),
        )


def journey_scenario(
    *,
    appointment_id: str = "A-1001",
    target_slot_ids: tuple[str, ...] = ("S-101",),
    tool_failures: tuple[str, ...] = (),
    expected_outcome: str = checks.OUTCOME_RESCHEDULED,
) -> JourneyScenario:
    return JourneyScenario(
        scenario_id="synth-appointment-rescheduling-0123456789ab",
        journey="appointment-rescheduling",
        description="A customer moves a dental cleaning.",
        persona=JourneyPersona("cooperative", "Maya Okafor", "polite and brief"),
        goal="Move my dental cleaning to a later day.",
        knowledge_level="medium",
        knowledge_evidence=KnowledgeEvidence(
            "relies_on_agent_for_rule", "same_service_only", None
        ),
        complication="none",
        fixture=FixtureBinding("C-100", appointment_id, target_slot_ids, tool_failures),
        grounded_facts=(),
        max_turns=12,
        expected_outcome=expected_outcome,
        assertion_ids=tuple(checks.ASSERTIONS),
        judge_criterion_ids=JOURNEY.judge_criterion_ids,
        synthesis=JourneySynthesis(
            set_id="set-1", spec_id="spec-001", journey_sha256="a" * 64,
            fixture_state_sha256="b" * 64, generation_config_sha256="c" * 64,
            generator_version="test", model="stub", generated_at="2026-09-21T00:00:00Z",
        ),
        source="hand-built",
    )


def confirmed_reschedule() -> TraceBuilder:
    """Identify, offer, confirm, update — one step per Turn."""
    return (
        TraceBuilder()
        .turn("I need to move my cleaning, code HSD-4821.",
              "I found your cleaning with Dr. Alvarez on 6 October. When suits you?",
              lookup("A-1001"))
        .turn("Later that week if possible.",
              "Dr. Alvarez has 9 October at 11:00. Shall I move it there?",
              find_slots("A-1001", "S-101", "S-102"))
        .turn("Yes, please move it.",
              "Done. Your cleaning is now on 9 October at 11:00 with Dr. Alvarez.",
              update("A-1001", "S-101"))
    )
