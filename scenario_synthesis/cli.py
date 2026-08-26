"""Unified offline command surface for Phase 4.5 scenario synthesis."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .config import validate_all
from .planner import write_plan_report

COMMANDS = ("validate-contracts", "plan", "produce", "qualify", "report", "check-completion")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scenario_synthesis")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument(
        "--output-root",
        default="synthesized_scenarios/reports",
        help="report parent directory (plan only)",
    )
    parser.add_argument("--report-id", default="slice-2-first-plan")
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
    if args.command != "validate-contracts":
        parser.exit(2, f"{args.command}: not implemented\n")
    config, contracts, snapshot = validate_all()
    print(
        json.dumps(
            {
                "status": "valid",
                "config_hash": config.sha256,
                "contract_hashes": contracts.hashes,
                "snapshot_hash": snapshot.sha256,
            },
            sort_keys=True,
        )
    )
    return 0
