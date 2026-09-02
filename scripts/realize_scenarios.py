#!/usr/bin/env python3
"""LEGACY — replaced by Phase 4.5 scenario synthesis; delete at cutover. Do not add features here.

Explicit live entry point for Phase 3 scenario realization.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
from pathlib import Path

from agentsim.llm import OpenAILLM
from scenario_synthesis.blueprint import Blueprint
from scenario_synthesis.enumerate import enumerate_blueprints
from scenario_synthesis.realize import DEFAULT_MANIFEST, realize_catalog
from scenario_synthesis.sample import behavioral_class_key

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(env_path: str | Path = ROOT / ".env") -> None:
    """Load simple KEY=VALUE entries while preserving the existing environment."""
    path = Path(env_path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def load_manifest_sample(
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> tuple[Blueprint, ...]:
    """Load the deterministic Phase 2 sample recorded in the manifest."""
    manifest = json.loads(Path(manifest_path).read_text())
    seed = manifest.get("seed")
    sample_ids = manifest.get("sample_ids")
    expected_count = manifest.get("counts", {}).get("sample")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SystemExit("manifest seed must be an integer")
    if (
        not isinstance(sample_ids, list)
        or not sample_ids
        or not all(isinstance(item, str) and item for item in sample_ids)
        or len(set(sample_ids)) != len(sample_ids)
    ):
        raise SystemExit("manifest sample_ids must be a non-empty unique string list")
    if expected_count != len(sample_ids):
        raise SystemExit(
            "manifest sample count does not match the number of sample_ids"
        )

    blueprints_by_id = {
        blueprint.id: blueprint for blueprint in enumerate_blueprints(seed=seed)
    }
    missing = [
        blueprint_id
        for blueprint_id in sample_ids
        if blueprint_id not in blueprints_by_id
    ]
    if missing:
        raise SystemExit(
            "manifest sample_ids are absent from deterministic enumeration: "
            + ", ".join(missing)
        )
    selected = tuple(blueprints_by_id[blueprint_id] for blueprint_id in sample_ids)
    class_keys = {behavioral_class_key(blueprint) for blueprint in selected}
    if len(class_keys) != len(selected):
        raise SystemExit("manifest sample_ids contain duplicate behavioral classes")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-label", required=True)
    args = parser.parse_args()
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set (environment or .env)")
    blueprints = load_manifest_sample()
    asyncio.run(
        realize_catalog(
            blueprints,
            OpenAILLM(),
            batch_label=args.batch_label,
            report=print,
        )
    )


if __name__ == "__main__":
    main()
