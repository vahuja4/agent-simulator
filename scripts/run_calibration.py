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

Simulator-compliance landing gate (fixed first-pass denominator):
    python scripts/run_calibration.py --simulator-compliance-gate --runs 3 \
        --candidate-id CANDIDATE --simulator-model DISTINCT_FAMILY_MODEL \
        --model gpt-5.5 --out NEW_DIR

All modes require ``AGENTSIM_LIVE_CREDIT_FLOOR_USD`` and
``AGENTSIM_MAX_COST_PER_LLM_CALL_USD``. The first is an operator-verified lower
bound on current credit; the second is a conservative per-call cost ceiling.

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
from decimal import Decimal
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _load_dotenv() -> None:
    """Minimal .env loader: existing environment variables win; only
    KEY=VALUE lines are read."""
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
from agentsim.live_credit import LiveCreditError, live_credit_preflight  # noqa: E402
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
    load_synthesized_scenario,
    run_scenario,
)
from agentsim.script import agent as agent_step  # noqa: E402
from agentsim.script import judge as judge_step  # noqa: E402
from agentsim.script import user as user_step  # noqa: E402
from scenario_synthesis.candidate import load_candidate  # noqa: E402
from scenario_synthesis.simulator_compliance import (  # noqa: E402
    curated_simulator_compliance_criteria,
    judge_simulator_compliance,
    simulator_compliance_criteria,
)

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

CURATED_COMPLICATIONS = {
    "j1-ambiguous-freedom-card": "ambiguous-reference",
    "j1-card-switch-stale-options": "mid-conversation-correction",
    "j1-happy-path": "none",
    "j1-happy-path-minimal-opener": "underspecification",
    "j1-large-payment-false-success": "none",
    "j1-pressure-skips-confirmation": "none",
    "j2-external-funding-account": "none",
    "j2-happy-path": "none",
    "j3-below-minimum-fixed-autopay": "none",
    "j3-happy-path": "none",
    "j4-happy-path": "none",
    "j5-cancel-autopay-pending": "false-premise",
    "j5-happy-path": "none",
}

CURATED_COMPLICATION_EVIDENCE = {
    "j1-ambiguous-freedom-card": {
        "ambiguous_card_reference": "Freedom card",
    },
    "j1-card-switch-stale-options": {
        "correction": "switch from card 9013 to card 0767 while preserving the J1 Goal",
    },
    "j5-cancel-autopay-pending": {
        "false_premise": (
            "the real pending $875.20 AutoPay payment on June 20 is cancellable "
            "through the scheduled-payment cancellation Journey"
        ),
    },
}

STANDARD_TOKEN_PRICES_PER_MILLION_USD = {
    "gpt-4.1-mini": {
        "input": Decimal("0.40"),
        "cached_input": Decimal("0.10"),
        "output": Decimal("1.60"),
    },
    "o3": {
        "input": Decimal("2.00"),
        "cached_input": Decimal("0.50"),
        "output": Decimal("8.00"),
    },
    "gpt-5.5": {
        "input": Decimal("5.00"),
        "cached_input": Decimal("0.50"),
        "output": Decimal("30.00"),
    },
}
PRICING_VERIFIED_ON = "2026-09-01"
PRICING_SOURCE = "https://developers.openai.com/api/docs/pricing"
COMPLIANCE_GATE_EPISODE_TIMEOUT_SECONDS = 300


def _role_usage_summary(provider: OpenAILLM) -> dict:
    rates = STANDARD_TOKEN_PRICES_PER_MILLION_USD[provider.model]
    input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    for record in provider.usage_records:
        usage = record["usage"]
        input_tokens += int(usage.get("prompt_tokens") or 0)
        output_tokens += int(usage.get("completion_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached_input_tokens += int(details.get("cached_tokens") or 0)
    uncached_input_tokens = input_tokens - cached_input_tokens
    if uncached_input_tokens < 0:
        raise ValueError("cached input tokens exceed total input tokens")
    million = Decimal(1_000_000)
    actual_cost = (
        Decimal(uncached_input_tokens) * rates["input"]
        + Decimal(cached_input_tokens) * rates["cached_input"]
        + Decimal(output_tokens) * rates["output"]
    ) / million
    cache_hit_rate = (
        Decimal(cached_input_tokens) / Decimal(input_tokens)
        if input_tokens
        else Decimal(0)
    )
    return {
        "model": provider.model,
        "call_count": len(provider.usage_records),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "cache_hit_rate": f"{cache_hit_rate:.6f}",
        "actual_cost_usd": f"{actual_cost:.6f}",
        "calls": provider.usage_records,
    }


def _gate_usage_summary(simulator: OpenAILLM, judge: OpenAILLM) -> dict:
    simulator_summary = _role_usage_summary(simulator)
    judge_summary = _role_usage_summary(judge)
    total = Decimal(simulator_summary["actual_cost_usd"]) + Decimal(
        judge_summary["actual_cost_usd"]
    )
    return {
        "pricing": {
            "verified_on": PRICING_VERIFIED_ON,
            "source": PRICING_SOURCE,
            "basis": "standard short-context token rates per 1M tokens",
        },
        "simulator": simulator_summary,
        "judge": judge_summary,
        "total_actual_cost_usd": f"{total:.6f}",
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
    try:
        async with sem:
            print(f"[start] {scenario.name}", flush=True)
            result = await run_scenario(
                scenario,
                simulator_llm,
                agent=agent,
                judge_llm=judge_llm,
                enforce_model_family_separation=enforce_model_family_separation,
            )
    except BaseException as exc:
        status = (
            "infrastructure-interrupted"
            if isinstance(exc, asyncio.CancelledError)
            else "infrastructure-error"
        )
        error = f"{type(exc).__name__}: {exc}"
        record = {
            "scenario": scenario.name,
            "journey": scenario.journey,
            "defect": defect,
            "status": status,
            "outcome": "error",
            "error": error,
            "models": {"simulator": simulator_model, "judge": judge_model},
        }
        (out_dir / f"{scenario.name}.txt").write_text(
            f"SCENARIO: {scenario.name}\nSTATUS: {status}\nERROR: {error}\n"
        )
        (out_dir / f"{scenario.name}.json").write_text(json.dumps(record, indent=2))
        print(f"[error] {scenario.name}: {error}", flush=True)
        return record
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
        "status": "completed",
    }
    print(f"[done ] {scenario.name}: {result.outcome} ({user_turns} user turns)", flush=True)
    return row


async def judge_calibration_simulator_compliance(
    judge_llm,
    result: RunResult,
    *,
    scenario: Scenario,
    criteria,
    declared_complication: str,
    goal_facts: dict,
):
    """Calibration wrapper around the production compliance invocation."""
    return await judge_simulator_compliance(
        judge_llm,
        result.trace,
        scenario=scenario,
        criteria=criteria,
        declared_complication=declared_complication,
        goal_facts=goal_facts,
    )


def _curated_goal_facts(scenario: Scenario) -> dict:
    complication = CURATED_COMPLICATIONS[scenario.name]
    return {
        "curated_scenario_goal": scenario.goal,
        "declared_complication": complication,
        **CURATED_COMPLICATION_EVIDENCE.get(scenario.name, {}),
    }


async def _run_compliance_gate_episode(
    *,
    scenario: Scenario,
    repetition: int,
    kind: str,
    out_dir: Path,
    simulator_llm,
    judge_llm,
    criteria,
    declared_complication: str,
    goal_facts: dict,
    sem: asyncio.Semaphore,
    timeout_seconds: float = COMPLIANCE_GATE_EPISODE_TIMEOUT_SECONDS,
) -> dict:
    identity = {"kind": kind, "scenario": scenario.name, "repetition": repetition}
    path = out_dir / kind / f"repetition-{repetition}" / f"{scenario.name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with sem:
            async with asyncio.timeout(timeout_seconds):
                result = await run_scenario(
                    scenario,
                    simulator_llm,
                    agent=MockPayCardAgent(),
                    judge_llm=judge_llm,
                    enforce_model_family_separation=True,
                    conversation_id=(
                        f"simulator-compliance-gate-{kind}-{repetition}-{scenario.name}"
                    ),
                )
                compliance = await judge_calibration_simulator_compliance(
                    judge_llm,
                    result,
                    scenario=scenario,
                    criteria=criteria,
                    declared_complication=declared_complication,
                    goal_facts=goal_facts,
                )
    except BaseException as exc:
        status = (
            "infrastructure-interrupted"
            if isinstance(exc, asyncio.CancelledError)
            else "infrastructure-error"
        )
        record = {
            "schema_version": 1,
            **identity,
            "status": status,
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        return record

    rulings = [item.to_dict() for item in compliance.criteria]
    passed = result.outcome == "pass" and all(item["passed"] for item in rulings)
    record = {
        "schema_version": 1,
        **identity,
        "status": "completed",
        "passed": passed,
        "declared_complication": declared_complication,
        "goal_facts": goal_facts,
        "ordinary_outcome": result.outcome,
        "ordinary_failures": [failure.to_dict() for failure in result.failures],
        "simulator_compliance_passed": all(item["passed"] for item in rulings),
        "simulator_compliance_rulings": rulings,
        "trace": result.trace.to_dict(),
    }
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def _pressure_persona_fidelity(record: dict) -> tuple[bool, str]:
    if not record.get("passed"):
        return False, "spot-check Episode or compliance failed"
    turns = record["trace"]["turns"]
    validate_turns = [
        turn["index"]
        for turn in turns
        if any(call["name"] == "AddValidateOneTimePayment" for call in turn["tool_calls"])
    ]
    submit_turns = [
        turn["index"]
        for turn in turns
        if any(call["name"] == "AddOneTimePayment" for call in turn["tool_calls"])
    ]
    if not validate_turns or not submit_turns:
        return False, "pressure spot-check did not reach validation and submission"
    responses = [
        turn["text"].strip()
        for turn in turns
        if turn["speaker"] == "user"
        and validate_turns[-1] < turn["index"] < submit_turns[0]
    ]
    pressure_count = len(responses) - 1
    final = responses[-1].lower().strip(" .!") if responses else ""
    passed = pressure_count in (2, 3) and final in {
        "yes",
        "yes, please",
        "yes, schedule it",
        "please schedule it",
    }
    return passed, (
        f"observed {pressure_count} pressure exchanges followed by {responses[-1]!r}"
        if responses
        else "no customer response occurred between validation and submission"
    )


async def _run_simulator_compliance_gate(args) -> int:
    out_dir = Path(args.out)
    if out_dir.exists():
        raise SystemExit(
            f"refusing to reuse simulator-compliance gate output directory: {out_dir}"
        )
    out_dir.mkdir(parents=True)
    scenarios = load_library(REPO / "scenarios")
    if set(CURATED_COMPLICATIONS) != {scenario.name for scenario in scenarios}:
        raise SystemExit("curated Complication mapping does not match the Scenario library")
    candidate = load_candidate(args.candidate_output_root, args.candidate_id)
    if candidate.ordinal != 1:
        raise SystemExit("simulator-compliance gate requires the admitted ordinal-1 Candidate")
    terminal = json.loads((candidate.bundle / "terminal.json").read_text())
    if terminal.get("status") != "admitted":
        raise SystemExit("simulator-compliance gate Candidate is not admitted")
    synthesized = load_synthesized_scenario(candidate.scenario_path)
    simulator_llm = OpenAILLM(
        args.simulator_model,
        usage_path=out_dir / "usage" / "simulator.jsonl",
    )
    judge_llm = OpenAILLM(
        args.model,
        usage_path=out_dir / "usage" / "judge.jsonl",
    )
    sem = asyncio.Semaphore(args.concurrency)

    pressure = next(
        scenario for scenario in scenarios if scenario.name == "j1-pressure-skips-confirmation"
    )
    pressure_facts = _curated_goal_facts(pressure)
    spot = await _run_compliance_gate_episode(
        scenario=pressure,
        repetition=0,
        kind="persona-fidelity-spot-check",
        out_dir=out_dir,
        simulator_llm=simulator_llm,
        judge_llm=judge_llm,
        criteria=curated_simulator_compliance_criteria("none", pressure_facts),
        declared_complication="none",
        goal_facts=pressure_facts,
        sem=sem,
    )
    fidelity_passed, fidelity_reason = _pressure_persona_fidelity(spot)
    spot_summary = {
        "schema_version": 1,
        "model": args.simulator_model,
        "passed": fidelity_passed,
        "reason": fidelity_reason,
    }
    (out_dir / "persona-fidelity-spot-check.json").write_text(
        json.dumps(spot_summary, indent=2, sort_keys=True) + "\n"
    )
    if not fidelity_passed:
        blocked = {
            "schema_version": 1,
            "first_pass_started": False,
            "models": {"simulator": args.simulator_model, "judge": args.model},
            "model_family_separation_enforced": True,
            "persona_fidelity_spot_check": spot_summary,
            "usage": _gate_usage_summary(simulator_llm, judge_llm),
            "failures": [
                {
                    "kind": "persona-fidelity-spot-check",
                    "scenario": pressure.name,
                    "repetition": 0,
                    "status": spot.get("status"),
                    "error": spot.get("error"),
                    "reason": fidelity_reason,
                }
            ],
        }
        (out_dir / "summary.json").write_text(
            json.dumps(blocked, indent=2, sort_keys=True) + "\n"
        )
        (out_dir / "REPORT.md").write_text(
            "# Simulator Complication compliance calibration gate\n\n"
            "The denominator did not start because the required new-family "
            f"simulator Persona-fidelity spot-check failed: {fidelity_reason}.\n"
        )
        return 1

    tasks = []
    for repetition in range(3):
        for scenario in scenarios:
            complication = CURATED_COMPLICATIONS[scenario.name]
            goal_facts = _curated_goal_facts(scenario)
            tasks.append(
                _run_compliance_gate_episode(
                    scenario=scenario,
                    repetition=repetition,
                    kind="curated",
                    out_dir=out_dir,
                    simulator_llm=simulator_llm,
                    judge_llm=judge_llm,
                    criteria=curated_simulator_compliance_criteria(
                        complication, goal_facts
                    ),
                    declared_complication=complication,
                    goal_facts=goal_facts,
                    sem=sem,
                )
            )
        tasks.append(
            _run_compliance_gate_episode(
                scenario=synthesized,
                repetition=repetition,
                kind="admitted-cell",
                out_dir=out_dir,
                simulator_llm=simulator_llm,
                judge_llm=judge_llm,
                criteria=simulator_compliance_criteria(
                    candidate.blueprint.knowledge_level,
                    candidate.blueprint.goal_facts["knowledge_evidence"],
                    candidate.blueprint.complication,
                    candidate.blueprint.goal_facts,
                ),
                declared_complication=candidate.blueprint.complication,
                goal_facts=dict(candidate.blueprint.goal_facts),
                sem=sem,
            )
        )
    records = await asyncio.gather(*tasks)
    curated = [record for record in records if record["kind"] == "curated"]
    admitted = [record for record in records if record["kind"] == "admitted-cell"]
    failures = [
        {
            "kind": record["kind"],
            "scenario": record["scenario"],
            "repetition": record["repetition"],
            "status": record["status"],
            "error": record.get("error"),
            "ordinary_outcome": record.get("ordinary_outcome"),
            "failed_compliance_criteria": [
                ruling["criterion_id"]
                for ruling in record.get("simulator_compliance_rulings", [])
                if not ruling["passed"]
            ],
        }
        for record in records
        if not record["passed"]
    ]
    summary = {
        "schema_version": 1,
        "first_pass_only": True,
        "models": {"simulator": args.simulator_model, "judge": args.model},
        "model_family_separation_enforced": True,
        "persona_fidelity_spot_check": spot_summary,
        "usage": _gate_usage_summary(simulator_llm, judge_llm),
        "curated": {
            "scenario_count": 13,
            "repetitions": 3,
            "total": 39,
            "passed": sum(record["passed"] for record in curated),
            "applicable_simulator_compliance_criteria": 4,
        },
        "admitted_cell": {
            "candidate_id": candidate.candidate_id,
            "repetitions": 3,
            "total": 3,
            "passed": sum(record["passed"] for record in admitted),
            "simulator_compliance_criteria": 5,
        },
        "failures": failures,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    clean = summary["curated"]["passed"] == 39 and summary["admitted_cell"]["passed"] == 3
    report = (
        "# Simulator Complication compliance calibration gate\n\n"
        f"Simulator: `{args.simulator_model}`  \nJudge: `{args.model}`  \n"
        "Configuration: defects off; model-family separation enforced\n\n"
        "## Honest first-pass result\n\n"
        f"Curated: **{summary['curated']['passed']}/39**.  \n"
        f"Admitted ordinal-1 cell: **{summary['admitted_cell']['passed']}/3**.\n\n"
        "The curated Scenarios were judged on the four applicable criteria; the "
        "Knowledge-level criterion is not applicable because curated Scenarios do "
        "not declare a Knowledge level. The synthesized cell was judged on all five.\n\n"
        "No rejudging or replacement Episodes entered either denominator.\n"
        "\n## Usage and actual cost\n\n"
        f"Simulator: **${summary['usage']['simulator']['actual_cost_usd']}** "
        f"across {summary['usage']['simulator']['call_count']} calls.  \n"
        f"Judge: **${summary['usage']['judge']['actual_cost_usd']}** across "
        f"{summary['usage']['judge']['call_count']} calls; cached-input token "
        f"rate **{summary['usage']['judge']['cache_hit_rate']}**.  \n"
        f"Total: **${summary['usage']['total_actual_cost_usd']}**.\n"
    )
    if failures:
        report += "\n## Failure attribution\n\n" + "\n".join(
            f"- `{item['kind']}/{item['repetition']}/{item['scenario']}`: "
            f"{item['status']}; error={item['error']!r}; "
            f"ordinary={item['ordinary_outcome']!r}; "
            f"compliance={item['failed_compliance_criteria']}"
            for item in failures
        ) + "\n"
    (out_dir / "REPORT.md").write_text(report)
    return 0 if clean else 1


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
        "--simulator-compliance-gate",
        action="store_true",
        help="run the fixed curated N=3 plus admitted ordinal-1 compliance gate",
    )
    parser.add_argument("--candidate-id")
    parser.add_argument("--candidate-output-root", default=str(REPO / "synthesized_scenarios"))
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
    if args.simulator_compliance_gate:
        if args.acceptance or args.defect or args.only:
            parser.error(
                "--simulator-compliance-gate cannot be combined with --acceptance, "
                "--defect, or --only"
            )
        if args.runs != 3:
            parser.error("--simulator-compliance-gate requires --runs 3")
        if not args.candidate_id:
            parser.error("--simulator-compliance-gate requires --candidate-id")
        from agentsim.scenario import check_model_family_separation

        check_model_family_separation(
            args.simulator_model,
            args.model,
            enforce=True,
        )

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set (env or .env); aborting.", file=sys.stderr)
        return 2

    scenarios_for_ceiling = load_library(REPO / "scenarios")
    if args.simulator_compliance_gate:
        candidate_for_ceiling = load_candidate(
            args.candidate_output_root, args.candidate_id
        )
        synthesized_for_ceiling = load_synthesized_scenario(
            candidate_for_ceiling.scenario_path
        )
        pressure_for_ceiling = next(
            scenario
            for scenario in scenarios_for_ceiling
            if scenario.name == "j1-pressure-skips-confirmation"
        )
        maximum_planned_llm_calls = (
            sum((scenario.max_turns * 2 + 1) * 3 for scenario in scenarios_for_ceiling)
            + (synthesized_for_ceiling.max_turns * 2 + 1) * 3
            + pressure_for_ceiling.max_turns * 2
            + 1
        )
    elif args.acceptance:
        matrix = yaml.safe_load(Path(args.acceptance_config).read_text())
        specs_for_ceiling = _acceptance_specs(args, matrix, scenarios_for_ceiling)
        maximum_planned_llm_calls = sum(
            spec.scenario.max_turns * 2 for spec in specs_for_ceiling
        ) + (len(specs_for_ceiling) if args.label_clusters else 0)
    else:
        if args.only:
            scenarios_for_ceiling = [
                scenario
                for scenario in scenarios_for_ceiling
                if scenario.name in set(args.only)
            ]
        maximum_planned_llm_calls = sum(
            scenario.max_turns * 2 for scenario in scenarios_for_ceiling
        )
    try:
        credit_floor, per_call_ceiling, cost_ceiling = live_credit_preflight(
            maximum_planned_llm_calls
        )
    except LiveCreditError as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "status": "live-cost-ceiling",
                "maximum_planned_llm_calls": maximum_planned_llm_calls,
                "maximum_cost_per_llm_call_usd": str(per_call_ceiling),
                "maximum_planned_cost_usd": str(cost_ceiling),
                "configured_credit_floor_usd": str(credit_floor),
            },
            sort_keys=True,
        ),
        flush=True,
    )

    if args.simulator_compliance_gate:
        return await _run_simulator_compliance_gate(args)

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
