#!/usr/bin/env python3
"""LEGACY — replaced by Phase 4.5 scenario synthesis; delete at cutover. Do not add features here.

Explicit live entry point for Phase 4 generated-scenario dry-runs.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os

from agentsim.llm import OpenAILLM
from agentsim.scenario import load_scenario
from scenario_synthesis.compatibility import load_legacy_blueprint
from scenario_synthesis.dryrun import (
    DEFAULT_MANIFEST,
    ROOT,
    DryRunCandidate,
    run_dryrun_batch,
    select_successful_realizations,
)


async def _main(batch_label: str) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    entries = select_successful_realizations(
        manifest.get("realized_scenarios", []), batch_label
    )
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
                load_legacy_blueprint(ROOT / "generated_scenarios" / "blueprints" / f"{blueprint_id}.yaml"),
                load_scenario(ROOT / "generated_scenarios" / "yaml" / f"{scenario_id}.yaml"),
            )
        )
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set (environment or .env)")
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
