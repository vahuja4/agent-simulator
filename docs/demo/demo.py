"""Read-only entrypoint for the committed offline evidence demo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


DEMO_ROOT = Path(__file__).resolve().parent
STEPS = tuple("ABCDEF")


def _captured_output(step: str) -> str:
    return (DEMO_ROOT / "expected" / f"{step}.txt").read_text(encoding="utf-8")


def _print_step(step: str) -> None:
    sys.stdout.write(_captured_output(step))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="./demo", description="Replay committed evidence without API calls."
    )
    parser.add_argument("command", choices=(*STEPS, "all", "steps", "preflight"))
    args = parser.parse_args(argv)

    if args.command == "preflight":
        from preflight import main as preflight_main

        return preflight_main()
    if args.command == "steps":
        for step in STEPS:
            first_line = _captured_output(step).splitlines()[0]
            print(f"{step}: {first_line.removeprefix(f'{step} — ')}")
        return 0
    if args.command == "all":
        for index, step in enumerate(STEPS):
            if index:
                print()
            _print_step(step)
        return 0
    _print_step(args.command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
