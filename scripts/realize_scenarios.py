#!/usr/bin/env python3
"""Explicit live entry point for Phase 3 scenario realization."""

from __future__ import annotations

import asyncio

from agentsim.llm import OpenAILLM
from scenario_synthesis.enumerate import enumerate_blueprints
from scenario_synthesis.realize import realize_catalog


def main() -> None:
    asyncio.run(realize_catalog(enumerate_blueprints(), OpenAILLM()))


if __name__ == "__main__":
    main()
