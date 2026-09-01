"""Unified offline command surface for Phase 4.5 scenario synthesis."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agentsim.live_credit import LiveCreditError, live_credit_preflight

from .candidate import load_candidate, produce_candidate
from .completion import check_completion
from .config import validate_all
from .generator import generate_blueprints
from .planner import write_plan_report
from .qualification import (
    LiveQualificationRunner,
    StubQualificationRunner,
    invalidate_admission,
    qualify_candidate,
)
from .realization_provider import (
    LiveRealizationProvider,
    StubRealizationProvider,
)
from .reporting import generate_coverage_report

COMMANDS = (
    "validate-contracts", "plan", "produce", "qualify", "invalidate-admission",
    "report", "check-completion",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scenario_synthesis")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-contracts")
    plan = subparsers.add_parser("plan")
    plan.add_argument("--output-root", default="synthesized_scenarios/reports")
    plan.add_argument("--report-id", default="slice-2-first-plan")
    produce = subparsers.add_parser("produce")
    _offline_arguments(produce)
    produce.add_argument("--cell-id")
    produce.add_argument("--stub-failure", action="append", default=[], metavar="ATTEMPT:MODE")
    qualify = subparsers.add_parser("qualify")
    _offline_arguments(qualify)
    qualify.add_argument("--candidate-id", required=True)
    qualify.add_argument("--stub-outcome", action="append", default=[], metavar="SIDE:REPETITION:KIND")
    invalidate = subparsers.add_parser("invalidate-admission")
    invalidate.add_argument("--output-root", default="synthesized_scenarios")
    invalidate.add_argument("--candidate-id", required=True)
    invalidate.add_argument("--detail", required=True)
    report = subparsers.add_parser("report")
    report.add_argument("--output-root", default="synthesized_scenarios")
    report.add_argument("--report-id", default="slice-4-current")
    completion = subparsers.add_parser("check-completion")
    completion.add_argument("--output-root", default="synthesized_scenarios")
    completion.add_argument("--report-id", default="slice-4-current")
    args = parser.parse_args(argv)
    if args.command == "plan":
        bundle = write_plan_report(
            Path(args.output_root), report_id=args.report_id
        )
        coverage = json.loads((bundle / "coverage.json").read_text())
        print(
            json.dumps(
                {
                    "status": "planned",
                    "report_bundle": str(bundle),
                    "eligible_cell_count": coverage["eligible_cell_count"],
                    "snapshot_hash": coverage["snapshot_hash"],
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "validate-contracts":
        config, contracts, snapshot = validate_all()
        _print(
            status="valid",
            config_hash=config.sha256,
            contract_hashes=contracts.hashes,
            snapshot_hash=snapshot.sha256,
        )
        return 0
    if args.command == "produce":
        _require_execution_mode(parser, args)
        blueprints = generate_blueprints()
        if args.cell_id:
            blueprints = tuple(item for item in blueprints if item.cell_id == args.cell_id)
        if not blueprints:
            parser.error("no realizable blueprint matches --cell-id")
        if args.live and not args.cell_id:
            parser.error("produce --live requires an explicit --cell-id")
        failures = {}
        if args.live and args.stub_failure:
            parser.error("--stub-failure is available only with --stub")
        for value in args.stub_failure:
            try:
                attempt, mode = value.split(":", 1)
                failures[(0, int(attempt))] = mode
            except ValueError:
                parser.error("--stub-failure must be ATTEMPT:MODE")
        if args.live:
            config, _contracts, snapshot = validate_all()
            planned_llm_calls = int(config.content["limits"]["realization_retry_bound"]) + 1
            _print_live_cost_ceiling(
                parser=parser,
                command="produce",
                snapshot_hash=snapshot.sha256,
                realization_calls=int(config.content["limits"]["realization_retry_bound"]) + 1,
                episodes=0,
                llm_calls=planned_llm_calls,
            )
            provider = LiveRealizationProvider.from_config()
        else:
            provider = StubRealizationProvider(failure_modes=failures)
        candidate = produce_candidate(
            blueprints[0],
            output_root=args.output_root,
            provider=provider,
        )
        if candidate is None:
            _print(status="production-failed", cell_id=blueprints[0].cell_id)
            return 1
        _print(
            status="candidate-produced",
            candidate_id=candidate.candidate_id,
            cell_id=candidate.cell_id,
            candidate_ordinal=candidate.ordinal,
            candidate_bundle=str(candidate.bundle),
        )
        return 0
    if args.command == "qualify":
        _require_execution_mode(parser, args)
        outcomes = {}
        if args.live and args.stub_outcome:
            parser.error("--stub-outcome is available only with --stub")
        for value in args.stub_outcome:
            try:
                side, repetition, kind = value.split(":", 2)
                outcomes[(side, int(repetition))] = kind
            except ValueError:
                parser.error("--stub-outcome must be SIDE:REPETITION:KIND")
        if args.live:
            candidate = load_candidate(args.output_root, args.candidate_id)
            config, _contracts, snapshot = validate_all()
            repetitions = int(config.content["limits"]["admission_repetitions"])
            sides = 1 if candidate.blueprint.fitness_target_id is None else 2
            replacement_calls = (
                int(config.content["limits"]["realization_retry_bound"]) + 1
                if candidate.ordinal < int(config.content["limits"]["replacement_bound"])
                else 0
            )
            planned_llm_calls = (
                replacement_calls
                + repetitions * sides * (candidate.blueprint.max_turns * 2 + 1)
            )
            _print_live_cost_ceiling(
                parser=parser,
                command="qualify",
                snapshot_hash=snapshot.sha256,
                realization_calls=replacement_calls,
                episodes=repetitions * sides,
                llm_calls=planned_llm_calls,
            )
            runner = LiveQualificationRunner.from_config()
            replacement_provider = LiveRealizationProvider.from_config()
        else:
            runner = StubQualificationRunner(outcomes=outcomes)
            replacement_provider = StubRealizationProvider()
        result = qualify_candidate(
            args.candidate_id,
            output_root=args.output_root,
            runner=runner,
            replacement_provider=replacement_provider,
        )
        _print(
            status=result.decision.status,
            qualification_id=result.qualification_id,
            candidate_id=result.candidate.candidate_id,
            detection_unproven=result.decision.detection_unproven,
            library_path=None if result.library_path is None else str(result.library_path),
            replacement_candidate_id=(
                None if result.replacement is None else result.replacement.candidate_id
            ),
        )
        return 0 if result.decision.admitted else 1
    if args.command == "report":
        bundle = generate_coverage_report(
            args.output_root, report_id=args.report_id
        )
        coverage = json.loads((bundle / "coverage.json").read_text())
        _print(
            status="reported",
            report_bundle=str(bundle),
            report_status=coverage["report_status"],
            eligible_pair_count=coverage["denominators"]["eligible_pair"],
            eligible_cell_count=coverage["denominators"]["eligible_cell"],
        )
        return 0
    if args.command == "invalidate-admission":
        record, archive_path = invalidate_admission(
            args.candidate_id,
            output_root=args.output_root,
            detail=args.detail,
        )
        _print(
            status="admission-invalidated",
            candidate_id=args.candidate_id,
            qualification_id=record["subject_id"],
            reason_code=record["reason_code"],
            regeneration_budget_consumed=False,
            invalidated_library_path=str(archive_path),
        )
        return 0
    if args.command == "check-completion":
        bundle, result = check_completion(
            args.output_root, report_id=args.report_id
        )
        _print(
            status="pass" if result["passed"] else "fail",
            report_bundle=str(bundle),
            clauses=result["clauses"],
            gaps=result["gaps"],
        )
        return 0 if result["passed"] else 1
    parser.exit(2, f"{args.command}: not implemented\n")


def _offline_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-root", default="synthesized_scenarios")
    parser.add_argument("--stub", action="store_true")
    parser.add_argument("--live", action="store_true")


def _require_execution_mode(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    if args.stub and args.live:
        parser.error("choose exactly one execution mode: --stub or --live")
    if not args.stub and not args.live:
        parser.exit(
            2,
            f"{args.command}: choose --stub for offline development or "
            "explicit --live execution\n",
        )


def _print(**value: object) -> None:
    print(json.dumps(value, sort_keys=True))


def _print_live_cost_ceiling(
    *,
    parser: argparse.ArgumentParser,
    command: str,
    snapshot_hash: str,
    realization_calls: int,
    episodes: int,
    llm_calls: int,
) -> None:
    try:
        credit_floor, per_call_ceiling, cost_ceiling = live_credit_preflight(llm_calls)
    except LiveCreditError as exc:
        parser.error(str(exc))
    _print(
        status="live-cost-ceiling",
        command=command,
        snapshot_hash=snapshot_hash,
        maximum_planned_realization_calls=realization_calls,
        maximum_planned_episodes=episodes,
        maximum_planned_llm_calls=llm_calls,
        maximum_cost_per_llm_call_usd=str(per_call_ceiling),
        maximum_planned_cost_usd=str(cost_ceiling),
        configured_credit_floor_usd=str(credit_floor),
    )
    sys.stdout.flush()
