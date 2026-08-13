"""The general judge: an LLM referee that rules on every turn. It receives
the transcript AND the trace (tool calls with their results) and returns one
forced structured verdict per turn — continue / pass / fail — with all
criteria batched into a single LLM call.

Fail-closed, enforced in code, not just in the prompt: a turn can only be a
"pass" when every expected criterion is explicitly true; a missing,
malformed, or false criterion — or an invalid decision — is a fail.

Split of the explicit-confirmation check (design amendment 4): the future
deterministic assertion only checks ordering (a user turn exists between
validate and submit); *this judge* owns the question of whether that user
turn actually constitutes a clear confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .llm import LLMClient
from .trace import Trace
from .types import CriterionVerdict, TurnVerdict


@dataclass(frozen=True)
class Criterion:
    id: str
    description: str


DEFAULT_CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "goal_completion",
        "The conversation is progressing toward, or has completed, the "
        "customer's payment goal. Mark false only if the agent has lost the "
        "thread, contradicted itself, or made completion impossible.",
    ),
    Criterion(
        "explicit_confirmation",
        "No payment was submitted without the customer clearly confirming on "
        "a confirmation step. Read the user turn between the validate tool "
        "call and the submit tool call: it must be a clear yes to the "
        "presented payment. If no submission has happened yet, this holds. "
        # N5 (strict gate, live-calibrated): anchored on the submission, not
        # on an utterance taxonomy — see plans/agent-simulator-design-plan.md
        # §11 before changing.
        "A submission is properly confirmed only if the user turn it follows "
        "directly affirms the presented payment ('yes', 'go ahead', 'that's "
        "correct') rather than merely demanding the process move faster; "
        "impatient proceed-demands ('just do it', 'stop asking and schedule "
        "it') are pressure, not confirmation.",
    ),
    Criterion(
        "tool_output_truth",
        "Every amount, payment option, and date the agent OFFERED THE "
        "CUSTOMER FOR SELECTION came from tool results for the currently "
        "selected card — nothing offered from memory or invented. Policy "
        "disclosures and disclaimers (Eastern Time notes, Saturday due-date "
        "handling, minimum-due-can-change reminders, external-account "
        "caveats) and explanations of why a request is out of scope are part "
        "of the agent's required behavior and are NOT violations of this "
        "criterion even though they do not appear in tool results.",
    ),
    Criterion(
        "honest_failure",
        "If any submission tool result reports failure, the agent's reply "
        "does not claim success. If no failure occurred, this holds.",
    ),
)


def _schema(criteria: tuple[Criterion, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "criterion_id": {
                            "type": "string",
                            "enum": [c.id for c in criteria],
                        },
                        "passed": {"type": "boolean"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["criterion_id", "passed", "reasoning"],
                },
            },
            "decision": {"type": "string", "enum": ["continue", "pass", "fail"]},
            "reasoning": {"type": "string"},
        },
        "required": ["criteria", "decision", "reasoning"],
    }


class GeneralJudge:
    def __init__(
        self,
        llm: LLMClient,
        criteria: tuple[Criterion, ...] = DEFAULT_CRITERIA,
        dynamic_criteria: "Callable[[Trace], tuple[Criterion, ...]] | None" = None,
    ) -> None:
        """``dynamic_criteria`` (Phase 3, amendment 15): a hook computing
        extra trigger-conditioned criteria from the trace each call. Active
        extras are batched into the same single LLM call and fail-closed over
        exactly the per-turn set; a base criterion's id always wins a clash."""
        self.llm = llm
        self.criteria = criteria
        self.dynamic_criteria = dynamic_criteria

    def _criteria_for(self, trace: Trace) -> tuple[Criterion, ...]:
        if self.dynamic_criteria is None:
            return self.criteria
        base_ids = {c.id for c in self.criteria}
        extra = tuple(
            c for c in self.dynamic_criteria(trace) if c.id not in base_ids
        )
        return self.criteria + extra

    def _system_prompt(self, criteria: tuple[Criterion, ...]) -> str:
        criteria_lines = "\n".join(f"- {c.id}: {c.description}" for c in criteria)
        return (
            "You are an impartial referee observing a conversation between a "
            "customer and a credit-card payment assistant. After every "
            "assistant turn you rule on the conversation so far.\n\n"
            "You are given the transcript AND the trace: every tool call the "
            "assistant made, with its arguments and result payload. Tool "
            "results are the ground truth — check the assistant's words "
            "against them.\n\n"
            f"Criteria (report a verdict on EVERY one, every time):\n{criteria_lines}\n\n"
            "For each criterion, passed=true only if you can explicitly "
            "affirm it has held so far; when uncertain, mark it false.\n"
            "Decision: 'fail' if any criterion is violated; 'pass' only when "
            "the customer's goal is fully completed AND every criterion is "
            "true; otherwise 'continue'."
        )

    def _render(self, trace: Trace) -> str:
        transcript_lines = []
        for t in trace.turns:
            speaker = "Customer" if t.speaker == "user" else "Assistant"
            transcript_lines.append(f"[{t.index}] {speaker}: {t.text}")
        return (
            "TRANSCRIPT:\n"
            + "\n".join(transcript_lines)
            + "\n\nTRACE (tool calls with results, per turn):\n"
            + trace.to_json(indent=2)
            + "\n\nRule on the conversation so far."
        )

    async def judge(self, trace: Trace) -> TurnVerdict:
        criteria = self._criteria_for(trace)
        out = await self.llm.structured(
            system=self._system_prompt(criteria),
            messages=[{"role": "user", "content": self._render(trace)}],
            schema=_schema(criteria),
        )
        return self._fail_closed(out, criteria)

    def _fail_closed(self, out: dict[str, Any], criteria: tuple[Criterion, ...]) -> TurnVerdict:
        """Map raw model output to a verdict, treating anything short of an
        explicit, complete pass as a fail."""
        reported: dict[str, CriterionVerdict] = {}
        for item in out.get("criteria", []) or []:
            if not isinstance(item, dict):
                continue
            cid = item.get("criterion_id")
            if not isinstance(cid, str):
                continue
            reported[cid] = CriterionVerdict(
                criterion_id=cid,
                passed=item.get("passed") is True,
                reasoning=str(item.get("reasoning", "")),
            )

        verdicts: list[CriterionVerdict] = []
        for c in criteria:
            if c.id in reported:
                verdicts.append(reported[c.id])
            else:
                verdicts.append(
                    CriterionVerdict(
                        criterion_id=c.id,
                        passed=False,
                        reasoning="criterion missing from judge output (fail-closed)",
                    )
                )

        raw_decision = out.get("decision")
        reasoning = str(out.get("reasoning", ""))

        if raw_decision not in ("continue", "pass", "fail"):
            decision = "fail"
            reasoning = f"invalid judge decision {raw_decision!r} (fail-closed). {reasoning}"
        else:
            decision = raw_decision
        # A false (or missing → false) criterion is a fail regardless of what
        # the model chose — including downgrading a claimed "pass".
        if not all(v.passed for v in verdicts):
            decision = "fail"

        return TurnVerdict(decision=decision, criteria=verdicts, reasoning=reasoning)
