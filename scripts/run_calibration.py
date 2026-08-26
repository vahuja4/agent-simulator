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

Phase 4 acceptance (recall + precision in one resumable batch):
    python scripts/run_calibration.py --acceptance --runs 1 --out DIR
        [--simulator-model MODEL] [--enforce-model-family-separation]

Earlier calibration usage:
    python scripts/run_calibration.py [--out DIR] [--concurrency N]
        [--only NAME ...] [--defect D4]

Acceptance writes a manifest, per-run trace/transcript/replay artifacts,
clusters.json, acceptance.json, and report.md. Earlier calibration mode writes
per-scenario transcript/JSON files plus summary.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import yaml

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
from agentsim.acceptance import evaluate_batch_acceptance  # noqa: E402
from agentsim.batch import BatchRunSpec, BatchRunner  # noqa: E402
from agentsim.clustering import cluster_failures, label_clusters  # noqa: E402
from agentsim.llm import DEFAULT_MODEL, OpenAILLM  # noqa: E402
from agentsim.orchestrator import RunResult, run_conversation  # noqa: E402
from agentsim.persona_variation import (  # noqa: E402
    apply_persona_overlay,
    load_persona_overlays,
    overlay_for_run,
)
from agentsim.replay import emit_batch_replays  # noqa: E402
from agentsim.report import write_report  # noqa: E402
from agentsim.scenario import (  # noqa: E402
    Scenario,
    build_assertions,
    build_judge,
    load_library,
    run_scenario,
)
from agentsim.script import agent as agent_step  # noqa: E402
from agentsim.script import judge as judge_step  # noqa: E402
from agentsim.script import user as user_step  # noqa: E402

DEFECT_FLAGS = {
    # Legacy --defect D1 selects the assertion-caught same-turn mode. The
    # acceptance matrix explicitly selects each D1 mode independently.
    "D1": "d1_same_turn_after_validation",
    "D2": "d2_stale_options_after_card_switch",
    "D3": "d3_false_success_on_failed_submit",
    "D4": "d4_no_warning_below_minimum_autopay",
    "D5": "d5_silent_card_disambiguation",
    "D6": "d6_autopay_listed_in_cancellable",
    "D7": "d7_no_external_account_warning",
}
ALL_DEFECT_FLAGS = (*DEFECT_FLAGS.values(), "d1_submit_on_reask")


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
    scenario: Scenario,
    sem: asyncio.Semaphore,
    out_dir: Path,
    defect: str | None,
    *,
    simulator_model: str,
    judge_model: str,
    enforce_model_family_separation: bool,
) -> dict:
    simulator_llm = OpenAILLM(simulator_model)
    judge_llm = OpenAILLM(judge_model)
    agent = None
    if defect is not None:
        agent = MockPayCardAgent(MockConfig(**{DEFECT_FLAGS[defect]: True}))
    async with sem:
        print(f"[start] {scenario.name}", flush=True)
        result = await run_scenario(
            scenario,
            simulator_llm,
            agent=agent,
            judge_llm=judge_llm,
            enforce_model_family_separation=enforce_model_family_separation,
        )
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


def _acceptance_steps(row: dict) -> tuple:
    steps = []
    for message in row.get("script", []):
        steps.extend((user_step(str(message)), agent_step()))
        if row.get("judge_after_each", False):
            steps.append(judge_step())
    if row.get("judge_at_end", False):
        if row.get("judge_after_each", False):
            raise ValueError("acceptance row cannot combine judge_after_each and judge_at_end")
        steps.append(judge_step())
    return tuple(steps)


def _acceptance_specs(args, matrix: dict, scenarios: list[Scenario]) -> list[BatchRunSpec]:
    by_name = {scenario.name: scenario for scenario in scenarios}
    all_off = {flag: False for flag in ALL_DEFECT_FLAGS}
    specs: list[BatchRunSpec] = []

    for row in matrix.get("recall", []):
        scenario_name = str(row["scenario"])
        if scenario_name not in by_name:
            raise ValueError(f"acceptance case names unknown scenario {scenario_name!r}")
        flags = dict(all_off)
        flags.update({str(key): bool(value) for key, value in row.get("defect_flags", {}).items()})
        metadata = dict(row.get("selector", {}))
        metadata["acceptance_case"] = str(row["case_id"])
        specs.append(
            BatchRunSpec(
                scenario=by_name[scenario_name],
                run_id=f"recall-{row['case_id']}",
                seed=args.seed,
                model=args.model,
                persona_variant="pinned",
                defect_flags=flags,
                metadata=metadata,
                script=_acceptance_steps(row),
            )
        )

    overlays = load_persona_overlays(args.persona_overlays)
    for run_index in range(args.runs):
        overlay = overlay_for_run(overlays, seed=args.seed, run_index=run_index)
        for scenario in scenarios:
            varied = apply_persona_overlay(scenario, overlay) if overlay else scenario
            specs.append(
                BatchRunSpec(
                    scenario=varied,
                    run_id=f"precision-{run_index:03d}",
                    seed=args.seed + run_index,
                    model=args.model,
                    persona_variant=overlay.id if overlay else "base",
                    defect_flags=dict(all_off),
                    metadata={
                        "acceptance_side": "precision",
                        "precision_index": run_index,
                    },
                )
            )
    return specs


async def _run_phase4_acceptance(args) -> int:
    matrix_path = Path(args.acceptance_config)
    matrix = yaml.safe_load(matrix_path.read_text())
    scenarios = load_library(REPO / "scenarios")
    specs = _acceptance_specs(args, matrix, scenarios)
    output = Path(args.out)

    async def execute(spec: BatchRunSpec) -> RunResult:
        simulator_llm = OpenAILLM(getattr(args, "simulator_model", None) or spec.model)
        judge_llm = OpenAILLM(spec.model)
        target = MockPayCardAgent(MockConfig(**spec.defect_flags))
        if spec.script is not None:
            return await run_conversation(
                agent=target,
                judge=build_judge(spec.scenario, judge_llm),
                conversation_id=spec.run_key,
                max_turns=spec.scenario.max_turns,
                assertions=build_assertions(spec.scenario),
                script=spec.script,
            )
        return await run_scenario(
            spec.scenario,
            simulator_llm,
            agent=target,
            judge_llm=judge_llm,
            enforce_model_family_separation=getattr(
                args, "enforce_model_family_separation", False
            ),
            conversation_id=spec.run_key,
        )

    runner = BatchRunner(
        output,
        concurrency=args.concurrency,
        retry_errors=args.retry_errors,
        configuration={
            "kind": "phase4_acceptance",
            "runs_per_precision_scenario": args.runs,
            "acceptance_matrix": str(matrix_path),
            "model": args.model,
            "judge_model": args.model,
            "simulator_model": getattr(args, "simulator_model", None) or args.model,
            "enforce_model_family_separation": getattr(
                args, "enforce_model_family_separation", False
            ),
            "seed": args.seed,
        },
    )
    await runner.run(specs, execute)
    emit_batch_replays(output)
    cluster_failures(output, similarity_threshold=args.cluster_threshold)

    if args.label_clusters:
        label_llm = OpenAILLM(args.model)

        async def labeler(cluster) -> str:
            payload = {
                "source": cluster.source,
                "id": cluster.id,
                "members": [
                    {"message": item.get("message"), "data": item.get("data")}
                    for item in cluster.members
                ],
            }
            out = await label_llm.structured(
                system=(
                    "Give this already-assigned failure cluster one concise factual label. "
                    "Do not add members, split the cluster, rank it, or propose a fix."
                ),
                messages=[{"role": "user", "content": json.dumps(payload, sort_keys=True)}],
                schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"label": {"type": "string"}},
                    "required": ["label"],
                },
                effort="low",
                max_tokens=128,
            )
            return str(out["label"])

        await label_clusters(output, labeler)

    acceptance = evaluate_batch_acceptance(
        output, matrix, runs_per_scenario=args.runs
    )
    report_path = write_report(output)
    manifest = json.loads((output / "manifest.json").read_text())
    print(f"Acceptance: {'PASS' if acceptance['passed'] else 'FAIL'}")
    print(f"Recall: {'PASS' if acceptance['recall']['passed'] else 'FAIL'}")
    print(f"Precision: {'PASS' if acceptance['precision']['passed'] else 'FAIL'}")
    print(f"Recorded LLM calls: {manifest['llm_calls_total']}")
    print(f"Report: {report_path}")
    for issue in acceptance["issues"]:
        print(f"  - {issue}")
    return 0 if acceptance["passed"] else 1


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REPO / "calibration_runs" / "latest"))
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--runs", type=int, default=1, help="precision runs per scenario")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--simulator-model",
        default="gpt-5.6-luna",
        help="simulator model (default: gpt-5.6-luna)",
    )
    parser.add_argument(
        "--enforce-model-family-separation",
        action="store_true",
        help="error if simulator and judge model families match",
    )
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--acceptance", action="store_true", help="run both Phase 4 gates")
    parser.add_argument(
        "--acceptance-config",
        default=str(REPO / "calibration" / "phase4_acceptance.yaml"),
    )
    parser.add_argument(
        "--persona-overlays", default=str(REPO / "persona_variants")
    )
    parser.add_argument("--cluster-threshold", type=float, default=0.6)
    parser.add_argument("--label-clusters", action="store_true")
    parser.add_argument("--only", nargs="*", default=None, help="scenario names to run")
    parser.add_argument(
        "--defect",
        choices=sorted(DEFECT_FLAGS),
        default=None,
        help="run against a mock with this planted defect ON (expected: fail)",
    )
    args = parser.parse_args()

    if args.runs <= 0:
        parser.error("--runs must be positive")
    if args.acceptance and args.defect:
        parser.error("--acceptance cannot be combined with --defect")

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set (env or .env); aborting.", file=sys.stderr)
        return 2

    if args.acceptance:
        return await _run_phase4_acceptance(args)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    scenarios = load_library(REPO / "scenarios")
    if args.only:
        scenarios = [s for s in scenarios if s.name in set(args.only)]

    sem = asyncio.Semaphore(args.concurrency)
    rows = await asyncio.gather(
        *(
            run_one(
                s,
                sem,
                out_dir,
                args.defect,
                simulator_model=args.simulator_model or args.model,
                judge_model=args.model,
                enforce_model_family_separation=args.enforce_model_family_separation,
            )
            for s in scenarios
        )
    )

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
