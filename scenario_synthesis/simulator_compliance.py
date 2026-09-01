"""Qualification-only simulator compliance criteria."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Mapping

from agentsim.judge import Criterion, GeneralJudge, TurnVerdict
from agentsim.llm import LLMClient
from agentsim.trace import Trace

if TYPE_CHECKING:
    from agentsim.scenario import Scenario


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

LEGACY_SIMULATOR_COMPLIANCE_CRITERION_IDS: tuple[str, ...] = (
    "simulator_factual_grounding",
    "simulator_confirmation_timing",
    "simulator_goal_persistence",
    "simulator_knowledge_level_evidence",
)
SIMULATOR_COMPLIANCE_CRITERION_IDS: tuple[str, ...] = (
    *LEGACY_SIMULATOR_COMPLIANCE_CRITERION_IDS,
    "simulator_complication_evidence",
)


def simulator_compliance_evidence(
    scenario: "Scenario",
    *,
    declared_complication: str,
    goal_facts: Mapping[str, Any],
) -> str:
    """Render governing Scenario evidence separately from criterion wording."""
    return json.dumps(
        {
            "scenario_goal": scenario.goal,
            "supplied_knowledge": scenario.render_knowledge(),
            "declared_complication": declared_complication,
            "goal_facts": dict(goal_facts),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


async def judge_simulator_compliance(
    llm: LLMClient,
    trace: Trace,
    *,
    scenario: "Scenario",
    criteria: tuple[Criterion, ...],
    declared_complication: str,
    goal_facts: Mapping[str, Any],
) -> TurnVerdict:
    """Use the one context-supplying Judge invocation for simulator compliance."""
    evidence = simulator_compliance_evidence(
        scenario,
        declared_complication=declared_complication,
        goal_facts=goal_facts,
    )
    return await SimulatorComplianceJudge(
        llm,
        criteria=criteria,
        evidence=evidence,
    ).judge(trace)


class SimulatorComplianceJudge(GeneralJudge):
    """General Judge whose user input also carries governing Scenario evidence."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        criteria: tuple[Criterion, ...],
        evidence: str,
    ) -> None:
        super().__init__(llm, criteria=criteria)
        self.evidence = evidence

    def _render(self, trace: Trace) -> str:
        return (
            "GOVERNING SCENARIO EVIDENCE:\n"
            + self.evidence
            + "\n\n"
            + super()._render(trace)
        )


def simulator_compliance_criteria(
    knowledge_level: str,
    knowledge_evidence: Mapping[str, Any],
    complication: str,
    complication_evidence: Mapping[str, Any],
) -> tuple[Criterion, ...]:
    """Bind the Knowledge-level and Complication contracts to one Blueprint."""
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

    if complication == "goal-shift":
        persistence = (
            "After explicitly abandoning the in-progress Goal, the customer simulator "
            "consistently pursued the Scenario's complete replacement Goal. It did not "
            "resume or submit the abandoned Goal. Sharing parameters with the abandoned "
            "Goal, such as the same funding account, is not resumption. A stop after "
            "completing the replacement Goal or after the assistant made completion "
            "impossible is compliant."
        )
    elif complication == "out-of-scope-drift":
        persistence = (
            "After the transient request beyond the Journey, the customer simulator "
            "returned to the original Scenario Goal and continued pursuing it to "
            "completion. A stop after completion or after the assistant made completion "
            "impossible is compliant."
        )
    else:
        persistence = BASE_SIMULATOR_COMPLIANCE_CRITERIA[2].description

    if complication == "none":
        complication_detail = (
            "The Scenario declares no Complication. This criterion passes vacuously; "
            "no complication behavior is required."
        )
    elif complication == "underspecification":
        complication_detail = (
            "The declared underspecification observably occurred: the customer initially "
            "withheld at least one required Goal fact, or supplied it only when asked. "
            "Merely restating already-complete instructions is not evidence."
        )
    elif complication == "mid-conversation-correction":
        complication_detail = (
            "The declared mid-conversation correction observably occurred: the customer "
            "changed one or more previously supplied parameters while preserving the "
            "underlying Goal. The number of changed parameters does not distinguish "
            f"correction from goal shift. The declared correction is {complication_evidence.get('correction')!r}."
        )
    elif complication == "goal-shift":
        complication_detail = (
            "The declared goal shift observably occurred: the customer explicitly "
            "abandoned the in-progress Goal and supplied the complete replacement Goal "
            "declared by the Scenario. Parameter changes without explicit abandonment "
            f"are not evidence. The declared transition is {complication_evidence.get('goal_shift')!r}."
        )
    elif complication == "multi-intent-turn":
        complication_detail = (
            "The declared multi-intent turn observably occurred: one customer turn "
            "contained the two independently actionable instructions declared by the "
            "Scenario. Within J1, these are two independently actionable payment "
            "instructions; missing parameters do not disqualify; each need only identify "
            "a distinct payment target and intent. The declared instructions are "
            f"{complication_evidence.get('payment_instructions_in_one_turn')!r}."
        )
    elif complication == "false-premise":
        complication_detail = (
            "The declared false premise observably occurred: the customer expressed the "
            "declared incorrect belief about real Fixture state. An invented fact or a "
            "misunderstanding unrelated to actual Fixture state is not evidence. The "
            f"declared false premise is {complication_evidence.get('false_premise')!r}."
        )
    elif complication == "out-of-scope-drift":
        complication_detail = (
            "The declared out-of-scope drift observably occurred: the customer made a "
            "transient request beyond the Journey and subsequently returned to the "
            "original Goal, which remained active throughout. Permanent abandonment or "
            "replacement is not evidence. The declared transient intent is "
            f"{complication_evidence.get('transient_out_of_scope_intent')!r}."
        )
    elif complication == "channel-noise":
        complication_detail = (
            "The declared channel noise observably occurred: a customer message materially "
            "obscured its meaning such that recovery was required. Whether the assistant "
            "successfully recovered is irrelevant to this criterion. Cosmetic phrasing, "
            "ordinary informality, or an immediately clear message is not evidence."
        )
    elif complication == "ambiguous-reference":
        complication_detail = (
            "The declared ambiguous reference observably occurred: the customer supplied "
            "the declared reference matching multiple real Fixture entities, requiring "
            "disambiguation rather than elicitation of an omitted fact. The declared "
            f"reference is {complication_evidence.get('ambiguous_card_reference')!r}."
        )
    else:
        raise ValueError(f"unknown Complication {complication!r}")

    return (
        *BASE_SIMULATOR_COMPLIANCE_CRITERIA[:2],
        Criterion("simulator_goal_persistence", persistence),
        Criterion("simulator_knowledge_level_evidence", detail),
        Criterion("simulator_complication_evidence", complication_detail),
    )


def curated_simulator_compliance_criteria(
    complication: str,
    complication_evidence: Mapping[str, Any],
) -> tuple[Criterion, ...]:
    """Return the four applicable criteria for a curated Scenario.

    Curated Scenarios do not declare a Knowledge level, so the governing
    contract forbids inventing one retroactively for calibration.
    """
    criteria = simulator_compliance_criteria(
        "medium",
        {"kind": "relies_on_agent_for_rule", "rule": "not evaluated"},
        complication,
        complication_evidence,
    )
    return tuple(
        criterion
        for criterion in criteria
        if criterion.id != "simulator_knowledge_level_evidence"
    )
