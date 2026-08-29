"""One process-local event loop for synchronous synthesis command providers."""

from __future__ import annotations

import asyncio
import atexit
from collections.abc import Coroutine
from typing import Any, TypeVar


T = TypeVar("T")
_runner: asyncio.Runner | None = None


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    """Run provider work without rebinding shared async clients to new loops."""
    global _runner
    if _runner is None:
        _runner = asyncio.Runner()
        atexit.register(_close)
    return _runner.run(coroutine)


def _close() -> None:
    global _runner
    if _runner is not None:
        _runner.close()
        _runner = None
