"""Strict-loader helpers for the Journey input files.

Same shape as ``scenario_synthesis/_strict.py``, which cannot be imported from
here: its package ``__init__`` pulls in ``fixtures.paycard``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


def _load_yaml(path: Path, *, error: type[Exception]) -> Mapping[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise error(f"{path.name}: cannot read file: {exc}") from exc
    except yaml.YAMLError as exc:
        raise error(f"{path.name}: invalid YAML: {exc}") from exc
    return _mapping(raw, path.name, error=error)


def _mapping(value: Any, where: str, *, error: type[Exception]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise error(f"{where} must be a mapping")
    return value


def _strict(
    value: Mapping[str, Any],
    fields: set[str],
    where: str,
    *,
    error: type[Exception],
    optional: frozenset[str] = frozenset(),
) -> None:
    missing = fields - set(value)
    unknown = set(value) - fields - optional
    if missing:
        raise error(f"{where}: missing field(s) {sorted(missing)}")
    if unknown:
        raise error(f"{where}: unknown field(s) {sorted(unknown)}")


def _string(value: Any, where: str, *, error: type[Exception]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error(f"{where} must be a non-empty string")
    return value.strip()


def _list(value: Any, where: str, *, error: type[Exception]) -> list[Any]:
    if not isinstance(value, list):
        raise error(f"{where} must be a list")
    return value


def _unique_strings(
    value: Any, where: str, *, error: type[Exception], allow_empty: bool = False
) -> tuple[str, ...]:
    items = tuple(
        _string(item, f"{where}[{i}]", error=error)
        for i, item in enumerate(_list(value, where, error=error))
    )
    if not items and not allow_empty:
        raise error(f"{where} must not be empty")
    duplicates = sorted({item for item in items if items.count(item) > 1})
    if duplicates:
        raise error(f"{where}: duplicate value(s) {duplicates}")
    return items


def _positive_int(value: Any, where: str, *, error: type[Exception]) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise error(f"{where} must be a positive integer")
    return value


def _schema_version(value: Any, where: str, *, error: type[Exception]) -> int:
    if isinstance(value, bool) or value != 1:
        raise error(f"{where}: schema_version must be 1, got {value!r}")
    return 1
