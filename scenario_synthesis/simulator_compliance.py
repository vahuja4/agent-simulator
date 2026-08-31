"""Qualification-only simulator compliance criteria."""

from __future__ import annotations

from typing import Any, Mapping

from agentsim.judge import Criterion


BASE_SIMULATOR_COMPLIANCE_CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "simulator_factual_grounding",
        "The customer simulator did not invent facts. Every card, account, "
        "amount, balance, date, prior action, or other fact about the customer's "
        "accounts, payments, or history that the customer claims must be available "
        "from the scenario goal, the supplied knowledge, or the conversation and "
        "tool history. The customer's beliefs about what terms mean, how domain "
        "concepts work, or what the assistant is able to do are outside this "
        "criterion: assess them under the knowledge-level rules, or under the "
        "false-premise rules when the belief concerns the customer's real account "
        "state.",
    ),
    Criterion(
        "simulator_confirmation_timing",
        "The customer simulator did not clearly confirm the payment before the "
        "assistant presented validated payment details and asked for confirmation.",
    ),
    Criterion(
        "simulator_goal_persistence",
        "The customer simulator continued pursuing the scenario goal and did not "
        "abandon or replace it prematurely. A stop after completion or after the "
        "assistant made completion impossible is compliant.",
    ),
)


def simulator_compliance_criteria(
    knowledge_level: str,
    knowledge_evidence: Mapping[str, Any],
) -> tuple[Criterion, ...]:
    """Bind the symmetric Knowledge-level contract to one Blueprint."""
    if knowledge_level == "low":
        expected_kind = "material_fluency_gap"
        detail = (
            "The customer simulator exhibited at least one material fluency gap "
            f"about {knowledge_evidence.get('referent')!r}: a wrong label for a real "
            "fact or a relevant concept that needed explanation. Merely saying that "
            "the customer has low knowledge is not behavioral evidence."
        )
    elif knowledge_level == "medium":
        expected_kind = "relies_on_agent_for_rule"
        detail = (
            "The customer simulator stated Goal-relevant facts correctly and visibly "
            f"relied on the agent for the rule or consequence {knowledge_evidence.get('rule')!r}."
        )
    elif knowledge_level == "high":
        expected_kind = "states_rule_unprompted"
        detail = (
            "The customer simulator correctly stated, without prompting, the relevant "
            f"rule or consequence {knowledge_evidence.get('rule')!r}."
        )
    else:
        raise ValueError(f"unknown Knowledge level {knowledge_level!r}")
    if knowledge_evidence.get("kind") != expected_kind:
        raise ValueError(
            f"Knowledge evidence kind does not match {knowledge_level!r} level"
        )
    return (
        *BASE_SIMULATOR_COMPLIANCE_CRITERIA,
        Criterion("simulator_knowledge_level_evidence", detail),
    )
