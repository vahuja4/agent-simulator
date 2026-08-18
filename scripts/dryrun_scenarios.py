#!/usr/bin/env python3
"""Explicit live entry point for Phase 4 generated-scenario dry-runs."""

from __future__ import annotations

import asyncio
import argparse
import json

from agentsim.llm import OpenAILLM
from agentsim.scenario import load_scenario
from scenario_synthesis.blueprint import load_blueprint
from scenario_synthesis.dryrun import (
    DEFAULT_MANIFEST,
    ROOT,
    DryRunCandidate,
    run_dryrun_batch,
)


async def _main(batch_label: str) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    entries = [
        entry
        for entry in manifest.get("realized_scenarios", [])
        if entry.get("batch_label") == batch_label
        and "scenario_id" in entry
        and "status" not in entry
    ]
    if not entries:
        raise SystemExit(
            f"manifest has no successful realizations for batch {batch_label!r}"
        )
    candidates = []
    for entry in entries:
        blueprint_id = entry["blueprint_id"]
        scenario_id = entry["scenario_id"]
        candidates.append(
            DryRunCandidate(
                load_blueprint(ROOT / "generated_scenarios" / "blueprints" / f"{blueprint_id}.yaml"),
                load_scenario(ROOT / "generated_scenarios" / "yaml" / f"{scenario_id}.yaml"),
            )
        )
    await run_dryrun_batch(
        candidates,
        lambda _blueprint, _configuration: OpenAILLM(),
        batch_label=batch_label,
        manifest_path=DEFAULT_MANIFEST,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-label", required=True)
    asyncio.run(_main(parser.parse_args().batch_label))
