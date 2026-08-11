"""Live smoke test — real LLM calls for the simulator and the judge against
the real (deterministic) mock. Excluded from the default offline suite; run
with:

    pytest -m live -s

Purpose (pre-Phase-2 gate): the simulator and judge prompts have never
executed against a real model. Verify that (a) the simulator produces short,
human-plausible turns without inventing account facts, and (b) the
fail-closed judge passes a clean J1 happy-path run instead of false-alarming.
The full transcript, tool calls, and per-turn verdicts are printed for human
review.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentsim.adapters.mock_paycard import MockPayCardAgent
from agentsim.judge import GeneralJudge
from agentsim.llm import OpenAILLM
from agentsim.orchestrator import RunResult, run_conversation
from agentsim.simulator import Persona, UserSimulator

pytestmark = pytest.mark.live


def _load_dotenv() -> None:
    """Minimal .env loader (no python-dotenv dependency): existing environment
    variables win; only KEY=VALUE lines are read."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()

if not os.environ.get("OPENAI_API_KEY"):
    pytest.skip("OPENAI_API_KEY not set; live smoke test needs it", allow_module_level=True)


def _print_run(result: RunResult) -> None:
    print("\n" + "=" * 72)
    print("TRANSCRIPT (with tool calls)")
    print("=" * 72)
    for turn in result.trace.turns:
        if turn.speaker == "user":
            print(f"\n[{turn.index}] Customer (intent: {turn.intent}):")
            print(f"    {turn.text}")
        else:
            print(f"[{turn.index}] Assistant:")
            print(f"    {turn.text}")
            for tc in turn.tool_calls:
                print(f"      tool: {tc.name}({tc.arguments}) -> {tc.result}")

    print("\n" + "=" * 72)
    print("PER-TURN VERDICTS")
    print("=" * 72)
    for i, verdict in enumerate(result.verdicts, start=1):
        print(f"\nAfter agent turn {i}: decision={verdict.decision}")
        for cv in verdict.criteria:
            mark = "PASS" if cv.passed else "FAIL"
            print(f"  [{mark}] {cv.criterion_id}: {cv.reasoning}")
        if verdict.reasoning:
            print(f"  overall: {verdict.reasoning}")

    print("\n" + "=" * 72)
    print(f"OUTCOME: {result.outcome} — {result.final_reasoning}")
    print("=" * 72)


async def test_live_j1_happy_path() -> None:
    """One real end-to-end J1 conversation: cooperative customer pays the
    statement balance on the Freedom Unlimited from Chase checking on the due
    date. Expected: the run completes with a `pass` verdict."""
    llm = OpenAILLM()
    simulator = UserSimulator(
        llm,
        persona=Persona(
            name="Jordan",
            traits="polite, cooperative, gets to the point, answers one question at a time",
        ),
        goal=(
            "Pay the statement balance on your Chase Freedom Unlimited card "
            "(ending 0767) from your Chase Total Checking account, with the "
            "payment made on the due date. Confirm the payment when the "
            "details presented match, then stop."
        ),
    )
    judge = GeneralJudge(llm)
    agent = MockPayCardAgent()

    result = await run_conversation(
        simulator=simulator,
        agent=agent,
        judge=judge,
        conversation_id="live-smoke-j1",
        max_turns=12,
    )

    _print_run(result)

    assert result.outcome != "error", f"harness LLM error: {result.final_reasoning}"
    # The submit tool must actually have fired with a success result.
    submits = [
        tc
        for turn in result.trace.turns
        for tc in turn.tool_calls
        if tc.name == "AddOneTimePayment"
    ]
    assert submits, "conversation never reached submission"
    assert submits[0].result and submits[0].result.get("success") is True
    # And the fail-closed judge must have blessed the clean happy path.
    assert result.outcome == "pass", (
        f"expected pass, got {result.outcome!r}: {result.final_reasoning}"
    )
