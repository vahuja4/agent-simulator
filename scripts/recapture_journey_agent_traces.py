#!/usr/bin/env python3
"""Re-capture the two raw Traces pinned in ``tests/fixtures/journey_agent_raw_traces/``
from a running AGENT **stub** service, through the harness adapter, and compare
them with the committed samples.

The pinned samples catch drift on the harness side only: if AGENT's raw Trace
format changes, nothing in this repository fails. Run this whenever AGENT's
service changes (session 09 contract re-check):

    # in AGENT:  .venv/bin/python -m journey_agent.service --port 8765 --agent stub
    .venv/bin/python scripts/recapture_journey_agent_traces.py \
        --fixture-state ../journey_agent/tests/fixtures/fixture_state.json \
        --service-url http://127.0.0.1:8765 --output-dir <dir>

The conversation is the one session 05a captured — the same three customer
messages, once without and once with the controlled ``update_appointment``
failure — against AGENT's own test Fixture state, which is what the samples'
``fixture_state_sha256`` names. Only ``conversation_id`` may differ; the raw
Trace holds no timestamp. Exit 0 when both structures match, 1 when either
differs (then stop and report; do not update either side to make them agree),
2 for an unusable request.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agentsim.adapters.conversation import AdapterError  # noqa: E402
from agentsim.adapters.journey_service import JourneyServiceAdapter  # noqa: E402
from agentsim.journey.definition import FixtureState  # noqa: E402

SAMPLES = REPO / "tests" / "fixtures" / "journey_agent_raw_traces"
MESSAGES = ("My confirmation code is DC-4821.", "S-2 please", "yes")
CAPTURES = {"successful": (), "tool_failure": ("update_appointment",)}


def capture(adapter: JourneyServiceAdapter, fixture_state: FixtureState,
            tool_failures: tuple[str, ...]) -> dict[str, Any]:
    handle = adapter.start_conversation(fixture_state=fixture_state, tool_failures=tool_failures)
    try:
        for text in MESSAGES:
            adapter.send_message(handle, text)
        retrieved = adapter.retrieve_trace(handle)
    finally:
        adapter.release(handle)
    if retrieved.error or retrieved.raw is None:
        raise AdapterError("protocol", f"retrieval failed: {retrieved.error}")
    return retrieved.raw


def without_ids(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in raw.items() if key != "conversation_id"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fixture-state", required=True, metavar="JSON",
                        help="AGENT's tests/fixtures/fixture_state.json")
    parser.add_argument("--service-url", default="http://127.0.0.1:8765")
    parser.add_argument("--output-dir", required=True, metavar="DIR",
                        help="where the re-captured Traces are written")
    args = parser.parse_args(argv)

    try:
        data = json.loads(Path(args.fixture_state).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"recapture: {error}", file=sys.stderr)
        return 2
    fixture_state = FixtureState(data=data, source=args.fixture_state)
    adapter = JourneyServiceAdapter(args.service_url)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    differing = []
    for name, tool_failures in CAPTURES.items():
        try:
            raw = capture(adapter, fixture_state, tool_failures)
        except AdapterError as error:
            print(f"recapture: {name}: {error}", file=sys.stderr)
            return 2
        (output_dir / f"{name}.json").write_text(
            json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        pinned = json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))
        if raw.get("agent") != "stub":
            print(f"{name}: answered by {raw.get('agent')!r}, not the stub; use --agent stub")
            return 2
        same = without_ids(raw) == without_ids(pinned)
        print(f"{name}: {'same as' if same else 'DIFFERS from'} {SAMPLES / f'{name}.json'}")
        if not same:
            differing.append(name)
    if differing:
        print(f"re-captured Traces are in {output_dir}; compare before changing either side")
        return 1
    print("contract re-check: AGENT's raw Trace format matches the pinned samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
