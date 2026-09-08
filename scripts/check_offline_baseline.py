"""Run the offline suite and hold it to the baseline recorded in ENVIRONMENT.md.

`make test` runs this instead of bare pytest so that a commit which changes the
pass count without updating `ENVIRONMENT.md` fails loudly, in the same session,
rather than being rediscovered by whoever runs the suite next. Any failing test
is drift by definition: the recorded baseline is a green suite.

Extra arguments are passed through to pytest (e.g. `-k lifecycle`), in which
case the pass-count comparison is skipped because the selection is partial.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_RE = re.compile(r"Expected offline baseline:\s*(\d+) passed")


def expected_passed() -> int:
    text = (ROOT / "ENVIRONMENT.md").read_text(encoding="utf-8")
    match = BASELINE_RE.search(text)
    if match is None:
        sys.exit("ENVIRONMENT.md has no 'Expected offline baseline: N passed' line")
    return int(match.group(1))


def count(summary: str, word: str) -> int:
    match = re.search(rf"(\d+) {word}", summary)
    return int(match.group(1)) if match else 0


def main(argv: list[str]) -> int:
    expected = expected_passed()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *argv],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    sys.stdout.write(proc.stdout)
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    summary = lines[-1] if lines else ""
    passed = count(summary, "passed")
    failed = count(summary, "failed") + count(summary, "error")
    if proc.returncode != 0 or failed:
        print(
            f"baseline check: FAIL — {passed} passed / {failed} failed or errored; "
            f"ENVIRONMENT.md records a green suite of {expected} passed",
            file=sys.stderr,
        )
        return 1
    if argv:
        print(f"baseline check: skipped pass-count comparison for a partial selection ({passed} passed)")
        return 0
    if passed != expected:
        print(
            f"baseline check: FAIL — {passed} passed but ENVIRONMENT.md expects {expected}; "
            "update the baseline in this commit",
            file=sys.stderr,
        )
        return 1
    print(f"baseline check: OK ({passed} passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
