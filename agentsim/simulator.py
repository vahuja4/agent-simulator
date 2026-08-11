"""The user simulator: a role-reversed LLM playing the customer. Persona +
goal + grounded card/account knowledge (from fixtures — it must never invent
account facts), short human-like turns, a per-turn intent step, and a
###STOP### sentinel. One structured LLM call per turn produces both the
intent and the message.

Per-turn knowledge injection (SAGE-style, design amendment 11): the grounded
knowledge and goal are ALSO appended to every turn's message list as a
trailing context block, so they sit adjacent to the decision point as the
conversation grows instead of only at the top of a long prompt. The public
interface is unchanged from Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass

from fixtures.paycard import (
    AUTOPAY_ENROLLMENTS,
    CARDS,
    FUNDING_ACCOUNTS,
    SCHEDULED_PAYMENTS,
    AutoPayEnrollment,
    Card,
    FundingAccount,
    ScheduledPayment,
)

from .llm import LLMClient
from .types import Message

STOP_SENTINEL = "###STOP###"

_SIM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {
            "type": "string",
            "description": (
                "One short phrase for what you are doing this turn, e.g. "
                "'state goal', 'answer question', 'pick amount', 'confirm', "
                "'apply pressure', 'stop'."
            ),
        },
        "message": {
            "type": "string",
            "description": (
                "The customer's next chat message. Append ###STOP### when the "
                "goal is fully achieved or you are giving up; send only "
                "###STOP### to stop silently."
            ),
        },
    },
    "required": ["intent", "message"],
}


@dataclass
class Persona:
    name: str
    traits: str  # freeform, e.g. "polite, busy, slightly impatient"


@dataclass
class SimTurn:
    intent: str
    text: str
    stop: bool


def render_knowledge(
    cards: tuple[Card, ...] = CARDS,
    accounts: tuple[FundingAccount, ...] = FUNDING_ACCOUNTS,
    autopay: tuple[AutoPayEnrollment, ...] = AUTOPAY_ENROLLMENTS,
    scheduled: tuple[ScheduledPayment, ...] = SCHEDULED_PAYMENTS,
) -> str:
    """The customer's grounded knowledge of their own finances, rendered from
    the same fixtures the mock runs on. AutoPay status and scheduled payments
    are filtered to the given cards, so a scenario that narrows the card
    subset narrows everything the simulator may know."""
    card_ids = {c.card_id for c in cards}
    lines = ["Your credit cards:"]
    for c in cards:
        lines.append(
            f"- {c.name}, ending in {c.last_four}: current balance ${c.current_balance:,.2f}, "
            f"statement balance ${c.statement_balance:,.2f}, minimum due ${c.minimum_due:,.2f}, "
            f"payment due {c.due_date.isoformat()}"
        )
    lines.append("Your funding accounts (to pay from):")
    for a in accounts:
        kind = "a Chase account" if a.kind == "chase" else "an external (non-Chase) account"
        lines.append(f"- {a.name}, ending in {a.last_four} ({kind})")

    enrolled = {e.card_id: e for e in autopay if e.card_id in card_ids}
    lines.append("Your AutoPay status:")
    for c in cards:
        e = enrolled.get(c.card_id)
        if e is None:
            lines.append(f"- {c.name}, ending in {c.last_four}: no AutoPay set up")
        else:
            what = (
                f"a fixed amount of ${e.fixed_amount:,.2f}"
                if e.payment_type == "fixed" and e.fixed_amount is not None
                else f"the {e.payment_type_label.lower()}"
            )
            lines.append(
                f"- {c.name}, ending in {c.last_four}: AutoPay is ON — it pays {what} "
                "on the statement due date each month"
            )

    relevant = [p for p in scheduled if p.card_id in card_ids]
    if relevant:
        lines.append("Your upcoming scheduled payments:")
        by_id = {c.card_id: c for c in cards}
        for p in relevant:
            card = by_id[p.card_id]
            if p.kind == "one_time":
                lines.append(
                    f"- a ${p.amount:,.2f} one-time payment you scheduled earlier for your "
                    f"{card.name} (ending {card.last_four}) on {p.payment_date.isoformat()}"
                )
            else:
                lines.append(
                    f"- a ${p.amount:,.2f} automatic AutoPay payment for your "
                    f"{card.name} (ending {card.last_four}) due {p.payment_date.isoformat()}"
                )
    return "\n".join(lines)


class UserSimulator:
    def __init__(
        self,
        llm: LLMClient,
        *,
        persona: Persona,
        goal: str,
        knowledge: str | None = None,
    ) -> None:
        self.llm = llm
        self.persona = persona
        self.goal = goal
        self.knowledge = knowledge if knowledge is not None else render_knowledge()

    def _system_prompt(self) -> str:
        return (
            "You are role-playing a real bank customer chatting with Chase's "
            "credit card payment assistant. You are the CUSTOMER, not the "
            "assistant — never help, never explain policies, never break "
            "character.\n\n"
            f"Your name is {self.persona.name}. Personality: {self.persona.traits}.\n\n"
            f"Your goal for this conversation:\n{self.goal}\n\n"
            "What you know about your own accounts (this is ALL you know — "
            "never invent cards, accounts, balances, or dates that are not "
            "listed here):\n"
            f"{self.knowledge}\n\n"
            "Style: write like a human in a chat — short messages, one or two "
            "sentences, casual, one thing at a time. Reveal details only when "
            "asked or when it moves your goal forward.\n\n"
            "Each turn, first decide your intent for the turn, then write the "
            f"message. When your goal is fully achieved, or you decide to give "
            f"up, append {STOP_SENTINEL} to your final message (or send only "
            f"{STOP_SENTINEL} if you have nothing more to say)."
        )

    @staticmethod
    def _flip(history: list[Message]) -> list[dict[str, str]]:
        """Role-reverse the transcript: the simulated customer's past lines
        become 'assistant' turns, the agent-under-test's become 'user'."""
        flipped: list[dict[str, str]] = [
            {
                "role": "user",
                "content": (
                    "(You are starting a chat with the payment assistant. "
                    "Send your opening message.)"
                ),
            }
        ]
        for m in history:
            flipped.append(
                {
                    "role": "assistant" if m.role == "user" else "user",
                    "content": m.content,
                }
            )
        return flipped

    def _turn_context(self) -> dict[str, str]:
        """The per-turn knowledge injection: grounded knowledge + goal +
        stop rule re-stated right at the decision point, every turn."""
        return {
            "role": "system",
            "content": (
                "(Reminder for this turn. What you know about your own "
                "accounts — this is ALL you know, never invent anything "
                "beyond it:\n"
                f"{self.knowledge}\n\n"
                f"Your goal: {self.goal}\n"
                f"When the goal is fully achieved, or you give up, append "
                f"{STOP_SENTINEL} to your message.)"
            ),
        }

    async def next_turn(self, history: list[Message]) -> SimTurn:
        out = await self.llm.structured(
            system=self._system_prompt(),
            messages=[*self._flip(history), self._turn_context()],
            schema=_SIM_SCHEMA,
        )
        message = str(out.get("message", ""))
        stop = STOP_SENTINEL in message
        text = message.replace(STOP_SENTINEL, "").strip()
        return SimTurn(intent=str(out.get("intent", "")), text=text, stop=stop)
