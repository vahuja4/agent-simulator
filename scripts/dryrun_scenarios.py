#!/usr/bin/env python3
"""Explicit live entry point for Phase 4 generated-scenario dry-runs."""

from __future__ import annotations

import asyncio
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


async def _main() -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    entries = manifest.get("realized_scenarios", [])
    if not entries:
        raise SystemExit("manifest has no realized scenarios; run realization explicitly first")
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
        manifest_path=DEFAULT_MANIFEST,
    )


if __name__ == "__main__":
    asyncio.run(_main())
