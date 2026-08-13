"""Live calibration pass (pre-Phase-3 gate): run every scenario in
scenarios/ via run_scenario against the faithful mock — ALL defect flags
off — with real LLM calls for the simulator and the judge.

Expected outcomes with defects off:
- happy paths: pass;
- adversarial scenarios: pass or task_incomplete, never fail — the mock
  resists correctly, so any fail is judge noise (amendment 16: such
  criteria get reworded and re-verified before Phase 3 is done).

Phase 3 defect-on spot runs (--defect D1..D7): the same scenarios against a
deviant mock; expected outcome is fail, with the failure source printed —
source=assertion for D1/D2, the named specialist/general criterion for the
judge-caught defects.

Usage:
    python scripts/run_calibration.py [--out DIR] [--concurrency N]
        [--only NAME ...] [--defect D4]

Writes per-scenario transcript (.txt) and trace+verdicts+failures (.json)
files to the out dir, plus summary.json, and prints a summary table.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _load_dotenv() -> None:
    """Minimal .env loader (matches tests/test_live_smoke.py): existing
    environment variables win; only KEY=VALUE lines are read."""
    env_path = REPO / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()

from agentsim.adapters import MockConfig, MockPayCardAgent  # noqa: E402
from agentsim.llm import OpenAILLM  # noqa: E402
from agentsim.orchestrator import RunResult  # noqa: E402
from agentsim.scenario import Scenario, load_library, run_scenario  # noqa: E402

DEFECT_FLAGS = {
    "D1": "d1_pressure_skips_confirmation",
    "D2": "d2_stale_options_after_card_switch",
    "D3": "d3_false_success_on_failed_submit",
    "D4": "d4_no_warning_below_minimum_autopay",
    "D5": "d5_silent_card_disambiguation",
    "D6": "d6_autopay_listed_in_cancellable",
    "D7": "d7_no_external_account_warning",
}


def render_run(scenario: Scenario, result: RunResult) -> str:
    lines: list[str] = []
    lines.append(f"SCENARIO: {scenario.name}  ({scenario.source})")
    lines.append(f"JOURNEY: {scenario.journey}   MAX_TURNS: {scenario.max_turns}")
    lines.append("=" * 72)
    lines.append("TRANSCRIPT (with tool calls)")
    lines.append("=" * 72)
    for turn in result.trace.turns:
        if turn.speaker == "user":
            lines.append(f"\n[{turn.index}] Customer (intent: {turn.intent}):")
            lines.append(f"    {turn.text}")
        else:
            lines.append(f"[{turn.index}] Assistant:")
            lines.append(f"    {turn.text}")
            for tc in turn.tool_calls:
                lines.append(f"      tool: {tc.name}({tc.arguments}) -> {tc.result}")
    lines.append("")
    lines.append("=" * 72)
    lines.append("PER-TURN VERDICTS")
    lines.append("=" * 72)
    for i, verdict in enumerate(result.verdicts, start=1):
        lines.append(f"\nAfter agent turn {i}: decision={verdict.decision}")
        for cv in verdict.criteria:
            mark = "PASS" if cv.passed else "FAIL"
            lines.append(f"  [{mark}] {cv.criterion_id}: {cv.reasoning}")
        if verdict.reasoning:
            lines.append(f"  overall: {verdict.reasoning}")
    if result.failures:
        lines.append("")
        lines.append("=" * 72)
        lines.append("FAILURES (source-tagged)")
        lines.append("=" * 72)
        for f in result.failures:
            lines.append(f"  [{f.source}] {f.id} @turn {f.turn_index}: {f.message}")
    lines.append("")
    lines.append("=" * 72)
    lines.append(f"OUTCOME: {result.outcome} — {result.final_reasoning}")
    lines.append("=" * 72)
    return "\n".join(lines)


async def run_one(
    scenario: Scenario, sem: asyncio.Semaphore, out_dir: Path, defect: str | None
) -> dict:
    llm = OpenAILLM()
    agent = None
    if defect is not None:
        agent = MockPayCardAgent(MockConfig(**{DEFECT_FLAGS[defect]: True}))
    async with sem:
        print(f"[start] {scenario.name}", flush=True)
        result = await run_scenario(scenario, llm, agent=agent)
    user_turns = sum(1 for t in result.trace.turns if t.speaker == "user")
    agent_turns = sum(1 for t in result.trace.turns if t.speaker == "agent")
    tools = [tc.name for t in result.trace.turns for tc in t.tool_calls]
    (out_dir / f"{scenario.name}.txt").write_text(render_run(scenario, result))
    (out_dir / f"{scenario.name}.json").write_text(
        json.dumps(
            {
                "scenario": scenario.name,
                "outcome": result.outcome,
                "final_reasoning": result.final_reasoning,
                "verdicts": [
                    {
                        "decision": v.decision,
                        "reasoning": v.reasoning,
                        "criteria": [
                            {
                                "criterion_id": c.criterion_id,
                                "passed": c.passed,
                                "reasoning": c.reasoning,
                            }
                            for c in v.criteria
                        ],
                    }
                    for v in result.verdicts
                ],
                "failures": [f.to_dict() for f in result.failures],
                "trace": result.trace.to_dict(),
            },
            indent=2,
        )
    )
    row = {
        "scenario": scenario.name,
        "journey": scenario.journey,
        "defect": defect,
        "outcome": result.outcome,
        "user_turns": user_turns,
        "agent_turns": agent_turns,
        "max_turns": scenario.max_turns,
        "tools": tools,
        "failures": [{"source": f.source, "id": f.id} for f in result.failures],
        "final_reasoning": result.final_reasoning,
    }
    print(f"[done ] {scenario.name}: {result.outcome} ({user_turns} user turns)", flush=True)
    return row


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REPO / "calibration_runs" / "latest"))
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--only", nargs="*", default=None, help="scenario names to run")
    parser.add_argument(
        "--defect",
        choices=sorted(DEFECT_FLAGS),
        default=None,
        help="run against a mock with this planted defect ON (expected: fail)",
    )
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set (env or .env); aborting.", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    scenarios = load_library(REPO / "scenarios")
    if args.only:
        scenarios = [s for s in scenarios if s.name in set(args.only)]

    sem = asyncio.Semaphore(args.concurrency)
    rows = await asyncio.gather(*(run_one(s, sem, out_dir, args.defect) for s in scenarios))

    (out_dir / "summary.json").write_text(json.dumps(list(rows), indent=2))

    print("\nSUMMARY" + (f" (defect {args.defect} ON)" if args.defect else ""))
    print(f"{'scenario':<38} {'journey':<8} {'outcome':<16} turns(user/max)  failures")
    for row in rows:
        failures = ", ".join(f"{f['source']}:{f['id']}" for f in row["failures"]) or "-"
        print(
            f"{row['scenario']:<38} {row['journey']:<8} {row['outcome']:<16} "
            f"{row['user_turns']}/{row['max_turns']:<14} {failures}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
