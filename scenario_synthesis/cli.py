"""Unified offline command surface for Phase 4.5 scenario synthesis."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .config import validate_all

COMMANDS = ("validate-contracts", "plan", "produce", "qualify", "report", "check-completion")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scenario_synthesis")
    parser.add_argument("command", choices=COMMANDS)
    args = parser.parse_args(argv)
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
