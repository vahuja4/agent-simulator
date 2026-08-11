"""YAML scenario schema + loader (design amendment 9).

A scenario is one test case: journey, persona, goal, the slice of fixture
knowledge the simulated customer is allowed to know, the judge's
success criteria, max_turns, and a ``tool_assertions`` block.

The assertion ENGINE is Phase 3 — this module only carries and validates the
assertions (closed vocabulary, clear errors on load); nothing enforces them
at runtime yet.

``run_scenario`` wires a loaded scenario to the existing pieces: the
UserSimulator gets the persona/goal and the fixture-filtered knowledge; the
GeneralJudge gets one extra batched criterion holding the scenario's success
criteria (the per-invariant specialist criteria arrive in Phase 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from fixtures.paycard import CARDS, FUNDING_ACCOUNTS, Card, FundingAccount

from . import registry
from .judge import DEFAULT_CRITERIA, Criterion, GeneralJudge
from .llm import LLMClient
from .orchestrator import RunResult, run_conversation
from .simulator import Persona, UserSimulator, render_knowledge

JOURNEYS = ("J1", "J2", "J3", "J4", "J5")

# The closed assertion vocabulary (from design §3): type → (required extra
# fields, which of those fields must hold registry tool names).
_ASSERTION_TYPES: dict[str, tuple[set[str], set[str]]] = {
    # submit requires a prior successful validate + a user turn between them
    "validated_submit": ({"submit", "validate"}, {"submit", "validate"}),
    # every submitted amount came from the options fetched for the selected card
    "amount_in_options": (set(), set()),
    # after a card switch the options tool must be re-fetched before amounts
    "refetch_after_card_switch": (set(), set()),
    # the named tool must never be called in this scenario
    "must_not_call": ({"tool"}, {"tool"}),
}


class ScenarioError(Exception):
    """A scenario file failed validation. The message names the file and
    field so library authors can fix it without reading the loader."""


@dataclass(frozen=True)
class ToolAssertion:
    type: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class Scenario:
    name: str
    journey: str
    description: str
    persona: Persona
    goal: str
    knowledge_cards: tuple[Card, ...]
    knowledge_accounts: tuple[FundingAccount, ...]
    success_criteria: list[str]
    max_turns: int
    tool_assertions: list[ToolAssertion]
    source: str  # the file it was loaded from, for error/report context

    def render_knowledge(self) -> str:
        """The simulator's grounded knowledge, filtered to this scenario's
        card/account subset (AutoPay + scheduled payments follow the cards)."""
        return render_knowledge(cards=self.knowledge_cards, accounts=self.knowledge_accounts)


def _require(data: dict[str, Any], key: str, kind: type, where: str) -> Any:
    if key not in data:
        raise ScenarioError(f"{where}: missing required field '{key}'")
    value = data[key]
    if not isinstance(value, kind):
        raise ScenarioError(
            f"{where}: field '{key}' must be {kind.__name__}, got {type(value).__name__}"
        )
    return value


def _resolve_cards(fours: list[Any], where: str) -> tuple[Card, ...]:
    known = {c.last_four: c for c in CARDS}
    resolved = []
    for four in fours:
        if not isinstance(four, str) or four not in known:
            raise ScenarioError(
                f"{where}: knowledge.cards entry {four!r} is not a fixture card "
                f"last-four (known: {sorted(known)})"
            )
        resolved.append(known[four])
    return tuple(resolved)


def _resolve_accounts(fours: list[Any], where: str) -> tuple[FundingAccount, ...]:
    known = {a.last_four: a for a in FUNDING_ACCOUNTS}
    resolved = []
    for four in fours:
        if not isinstance(four, str) or four not in known:
            raise ScenarioError(
                f"{where}: knowledge.accounts entry {four!r} is not a fixture account "
                f"last-four (known: {sorted(known)})"
            )
        resolved.append(known[four])
    return tuple(resolved)


def _parse_assertions(raw: Any, where: str) -> list[ToolAssertion]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ScenarioError(f"{where}: tool_assertions must be a list")
    assertions: list[ToolAssertion] = []
    for i, item in enumerate(raw):
        spot = f"{where}: tool_assertions[{i}]"
        if not isinstance(item, dict):
            raise ScenarioError(f"{spot}: must be a mapping")
        a_type = item.get("type")
        if a_type not in _ASSERTION_TYPES:
            raise ScenarioError(
                f"{spot}: unknown type {a_type!r} (known: {sorted(_ASSERTION_TYPES)})"
            )
        required, tool_fields = _ASSERTION_TYPES[a_type]
        extra = {k: v for k, v in item.items() if k != "type"}
        missing = required - extra.keys()
        if missing:
            raise ScenarioError(f"{spot}: type '{a_type}' requires field(s) {sorted(missing)}")
        unknown = extra.keys() - required
        if unknown:
            raise ScenarioError(
                f"{spot}: unknown field(s) {sorted(unknown)} for type '{a_type}'"
            )
        for f_name in tool_fields:
            tool = extra[f_name]
            if tool not in registry.ALL_TOOLS:
                raise ScenarioError(
                    f"{spot}: '{f_name}' names unknown tool {tool!r} "
                    "(must be a registry tool name)"
                )
        assertions.append(ToolAssertion(type=a_type, fields={k: str(v) for k, v in extra.items()}))
    return assertions


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    where = path.name
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ScenarioError(f"{where}: invalid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise ScenarioError(f"{where}: top level must be a mapping")

    name = _require(raw, "name", str, where)
    journey = _require(raw, "journey", str, where)
    if journey not in JOURNEYS:
        raise ScenarioError(f"{where}: journey must be one of {JOURNEYS}, got {journey!r}")
    description = str(raw.get("description", "")).strip()

    persona_raw = _require(raw, "persona", dict, where)
    persona = Persona(
        name=_require(persona_raw, "name", str, f"{where}: persona"),
        traits=_require(persona_raw, "traits", str, f"{where}: persona"),
    )
    goal = _require(raw, "goal", str, where).strip()

    knowledge = _require(raw, "knowledge", dict, where)
    cards = _resolve_cards(_require(knowledge, "cards", list, f"{where}: knowledge"), where)
    if not cards:
        raise ScenarioError(f"{where}: knowledge.cards must not be empty")
    accounts = _resolve_accounts(
        _require(knowledge, "accounts", list, f"{where}: knowledge"), where
    )
    if not accounts:
        raise ScenarioError(f"{where}: knowledge.accounts must not be empty")

    success = _require(raw, "success_criteria", list, where)
    if not success or not all(isinstance(s, str) and s.strip() for s in success):
        raise ScenarioError(f"{where}: success_criteria must be a non-empty list of strings")

    max_turns = _require(raw, "max_turns", int, where)
    if isinstance(max_turns, bool) or max_turns <= 0:
        raise ScenarioError(f"{where}: max_turns must be a positive integer")

    assertions = _parse_assertions(raw.get("tool_assertions"), where)

    known_keys = {
        "name", "journey", "description", "persona", "goal", "knowledge",
        "success_criteria", "max_turns", "tool_assertions",
    }
    unknown = raw.keys() - known_keys
    if unknown:
        raise ScenarioError(f"{where}: unknown top-level field(s) {sorted(unknown)}")

    return Scenario(
        name=name,
        journey=journey,
        description=description,
        persona=persona,
        goal=goal,
        knowledge_cards=cards,
        knowledge_accounts=accounts,
        success_criteria=[s.strip() for s in success],
        max_turns=max_turns,
        tool_assertions=assertions,
        source=str(path),
    )


def load_library(directory: str | Path) -> list[Scenario]:
    """Every *.yaml in the directory, sorted by filename. Any invalid file
    raises ScenarioError naming that file."""
    directory = Path(directory)
    return [load_scenario(p) for p in sorted(directory.glob("*.yaml"))]


# ------------------------------------------------------------------ wiring


def build_simulator(scenario: Scenario, llm: LLMClient) -> UserSimulator:
    return UserSimulator(
        llm,
        persona=scenario.persona,
        goal=scenario.goal,
        knowledge=scenario.render_knowledge(),
    )


def build_judge(scenario: Scenario, llm: LLMClient) -> GeneralJudge:
    """The general judge plus ONE extra batched criterion carrying the
    scenario's success criteria. Per-invariant specialist criteria are
    Phase 3."""
    scenario_criterion = Criterion(
        "scenario_success",
        "Scenario-specific success criteria (ALL must hold): "
        + " ".join(f"({i + 1}) {s}" for i, s in enumerate(scenario.success_criteria)),
    )
    return GeneralJudge(llm, criteria=(*DEFAULT_CRITERIA, scenario_criterion))


async def run_scenario(
    scenario: Scenario,
    llm: LLMClient,
    agent=None,
    *,
    conversation_id: str | None = None,
) -> RunResult:
    """One conversation for one scenario against the given agent adapter
    (default: a fresh faithful MockPayCardAgent)."""
    if agent is None:
        from .adapters import MockPayCardAgent

        agent = MockPayCardAgent()
    return await run_conversation(
        simulator=build_simulator(scenario, llm),
        agent=agent,
        judge=build_judge(scenario, llm),
        conversation_id=conversation_id or scenario.name,
        max_turns=scenario.max_turns,
    )
