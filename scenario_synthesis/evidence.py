"""Canonical, hash-addressed evidence helpers for synthesis artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class EvidenceReferenceError(ValueError):
    """An evidence reference is malformed, escaping, missing, or mismatched."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def atomic_text(path: str | Path, value: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False
    )
    try:
        with handle:
            handle.write(value)
        os.replace(handle.name, target)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)


def atomic_json(path: str | Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def evidence_reference(path: str | Path, *, root: str | Path) -> dict[str, str]:
    target = Path(path)
    return {
        "path": str(target.relative_to(Path(root))),
        "sha256": sha256_file(target),
    }


def validate_evidence_reference(
    reference: Any, *, root: str | Path
) -> Path:
    """Validate a relative, root-contained, hash-bound evidence reference."""
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise EvidenceReferenceError("evidence reference schema is invalid")
    raw_path = reference["path"]
    if not isinstance(raw_path, str) or not raw_path:
        raise EvidenceReferenceError("evidence path must be a non-empty string")
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise EvidenceReferenceError(
            "evidence path must be relative and contained by the evidence root"
        )
    evidence_root = Path(root).resolve()
    target = (evidence_root / relative).resolve()
    try:
        target.relative_to(evidence_root)
    except ValueError as exc:
        raise EvidenceReferenceError(
            "evidence path must be relative and contained by the evidence root"
        ) from exc
    if not target.is_file() or sha256_file(target) != reference["sha256"]:
        raise EvidenceReferenceError("evidence hash mismatch")
    return target
