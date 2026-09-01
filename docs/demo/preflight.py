"""Verify pinned evidence and run the repository's offline suite."""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path


DEMO_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DEMO_ROOT.parents[1]
EXPECTED_PYTHON = (3, 12, 12)
EXPECTED_TESTS = 449


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _verify_python() -> None:
    if sys.version_info[:3] != EXPECTED_PYTHON:
        raise RuntimeError(
            f"expected Python 3.12.12, got {sys.version_info.major}."
            f"{sys.version_info.minor}.{sys.version_info.micro}"
        )
    expected = (REPO_ROOT / ".venv" / "bin" / "python").resolve()
    if Path(sys.executable).resolve() != expected:
        raise RuntimeError(f"pre-flight must use {expected}")
    importlib.import_module("readline")


def _verify_artifacts() -> int:
    manifest = json.loads((DEMO_ROOT / "manifest.json").read_text(encoding="utf-8"))
    evidence_commit = manifest["evidence_commit"]
    _git("cat-file", "-e", f"{evidence_commit}^{{commit}}")
    for record in manifest["artifacts"]:
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe artifact path: {relative}")
        path = REPO_ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"missing artifact: {relative}")
        working_bytes = path.read_bytes()
        committed_bytes = _git("show", f"{evidence_commit}:{relative.as_posix()}")
        expected_hash = record["sha256"]
        if _sha256(working_bytes) != expected_hash:
            raise RuntimeError(f"working-tree hash mismatch: {relative}")
        if _sha256(committed_bytes) != expected_hash:
            raise RuntimeError(f"committed hash mismatch: {relative}")
    return len(manifest["artifacts"])


def _run_offline_suite() -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "not live"],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    match = re.search(r"(\d+) passed", completed.stdout)
    if completed.returncode or match is None:
        raise RuntimeError("offline suite failed\n" + completed.stdout)
    passed = int(match.group(1))
    if passed != EXPECTED_TESTS:
        raise RuntimeError(
            f"offline suite count changed: expected {EXPECTED_TESTS}, got {passed}"
        )
    return f"{passed} passed"


def main() -> int:
    try:
        _verify_python()
        artifact_count = _verify_artifacts()
        test_result = _run_offline_suite()
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"PRE-FLIGHT FAIL: {exc}", file=sys.stderr)
        return 1
    print("PRE-FLIGHT PASS")
    print("python: 3.12.12 + readline")
    print(f"committed artifacts: {artifact_count}/{artifact_count} hashes verified")
    print(f"offline suite: {test_result}")
    print("live API calls: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
