"""Shared strict-loader validation helpers."""

from __future__ import annotations

from typing import Any, Mapping


def _mapping(
    value: Any, where: str, *, error: type[Exception]
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise error(f"{where} must be a mapping")
    return value


def _strict(
    value: Mapping[str, Any],
    fields: set[str],
    where: str,
    *,
    error: type[Exception],
) -> None:
    missing = fields - set(value)
    unknown = set(value) - fields
    if missing:
        raise error(f"{where}: missing field(s) {sorted(missing)}")
    if unknown:
        raise error(f"{where}: unknown field(s) {sorted(unknown)}")


def _positive_int(value: Any, where: str, *, error: type[Exception]) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise error(f"{where} must be a positive integer")
    return value
